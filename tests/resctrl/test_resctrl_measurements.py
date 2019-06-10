# Copyright (c) 2018 Intel Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


import errno
from unittest.mock import patch, mock_open, call, Mock, MagicMock

from wca.resctrl import ResGroup
from wca.resctrl import RESCTRL_ROOT_NAME
from tests.testing import create_open_mock

import pytest


@patch('os.path.isdir', return_value=True)
@patch('os.rmdir')
@patch('wca.resctrl.SetEffectiveRootUid')
@patch('os.listdir', side_effects=lambda path: {
    '/sys/fs/resctrl/best_efforts/mon_groups/some_container': [],
})
def test_resgroup_remove(listdir_mock, set_effective_root_uid_mock, rmdir_mock, isdir_mock):
    open_mock = create_open_mock({
        "/sys/fs/resctrl": "0",
        "/sys/fs/resctrl/best_efforts/mon_groups/some_container/tasks": "123\n124\n",
    })
    with patch('wca.resctrl.open', open_mock):
        resgroup = ResGroup("best_efforts")
        resgroup.remove('some-container')
        rmdir_mock.assert_called_once_with('/sys/fs/resctrl/best_efforts/mon_groups/some-container')


@patch('wca.resctrl.log.warning')
@patch('os.path.exists', return_value=True)
@patch('os.makedirs', side_effect=OSError(errno.ENOSPC, "mock"))
@patch('builtins.open', new=create_open_mock({
    "/sys/fs/cgroup/cpu/ddd/tasks": "123",
}))
def test_resgroup_sync_no_space_left_on_device(makedirs_mock, exists_mock, log_warning_mock):
    with pytest.raises(Exception, match='Limit of workloads reached'):
        ResGroup("best_efforts")._create_controlgroup_directory()


@patch('builtins.open', new=create_open_mock({
    "/sys/fs/resctrl/mon_groups/best_efforts/mon_data/1/mbm_total_bytes": "1",
    "/sys/fs/resctrl/mon_groups/best_efforts/mon_data/2/mbm_total_bytes": "1",
    "/sys/fs/resctrl/mon_groups/best_efforts/mon_data/1/llc_occupancy": "1",
    "/sys/fs/resctrl/mon_groups/best_efforts/mon_data/2/llc_occupancy": "1",
    "/sys/fs/cgroup/cpu/best_efforts/cpuacct.usage": "4",
}))
@patch('os.listdir', return_value=['1', '2'])
def test_get_measurements(*mock):
    resgroup = ResGroup(name=RESCTRL_ROOT_NAME)
    assert {'memory_bandwidth': 2, 'llc_occupancy': 2} == \
        resgroup.get_measurements('best_efforts', True, True)


@patch('wca.resctrl.SetEffectiveRootUid')
@patch('os.makedirs')
@pytest.mark.parametrize(
    'resgroup_name, pids, mongroup_name, '
    'expected_writes, expected_setuid_calls_count, expected_makedirs', [
        # 1) Write to root cgroup with one pid.
        ('', ['123'], 'c1',
         {'/sys/fs/resctrl/tasks': ['123'],
          '/sys/fs/resctrl/mon_groups/c1/tasks': ['123']
          }, 2, [call('/sys/fs/resctrl/mon_groups/c1', exist_ok=True)]),
        # 2) Write to root cgroup with two pids.
        ('', ['123', '456'], 'c1',  # two pids
         {'/sys/fs/resctrl/tasks': ['123', '456'],
          '/sys/fs/resctrl/mon_groups/c1/tasks': ['123'],
          }, 2, [call('/sys/fs/resctrl/mon_groups/c1', exist_ok=True)]),
        # 3) Write to non-root cgroup with two pids.
        ('be', ['123'], 'c1',
         {'/sys/fs/resctrl/be/tasks': ['123'],
          '/sys/fs/resctrl/be/mon_groups/c1/tasks': ['123'],
          }, 2, [call('/sys/fs/resctrl/be/mon_groups/c1', exist_ok=True)]),
    ])
def test_resgroup_add_pids(makedirs_mock, set_effective_root_uid_mock,
                           resgroup_name, pids, mongroup_name,
                           expected_writes, expected_setuid_calls_count, expected_makedirs):
    """Test that for ResGroup created with resgroup_name, when add_pids() is called with
    pids and given mongroup_name, expected writes (filenames with expected bytes writes)
    will happen together with number of setuid calls and makedirs calls.
    """
    write_mocks = {filename: mock_open() for filename in expected_writes}
    resgroup = ResGroup(name=resgroup_name)

    # if expected_log:
    with patch('builtins.open', new=create_open_mock(write_mocks)):
        resgroup.add_pids(pids, mongroup_name)

    for filename, write_mock in write_mocks.items():
        expected_filename_writes = expected_writes[filename]
        expected_write_calls = [call().write(write_body) for write_body in expected_filename_writes]
        write_mock.assert_has_calls(expected_write_calls, any_order=True)

    # makedirs used
    makedirs_mock.assert_has_calls(expected_makedirs)

    # setuid used (at least number of times)
    expected_setuid_calls = [call.__enter__()] * expected_setuid_calls_count
    set_effective_root_uid_mock.assert_has_calls(expected_setuid_calls, any_order=True)


@patch('wca.resctrl.SetEffectiveRootUid')
@patch('os.makedirs')
@pytest.mark.parametrize('side_effect, log_call', [
    (OSError(errno.E2BIG, 'other'),
     call.error('Could not write pid to resctrl (%r): Unexpected errno %r.',
                '/sys/fs/resctrl/tasks', 7)),
    (OSError(errno.ESRCH, 'no such proc'),
     call.warning('Could not write pid to resctrl (%r): Process probably does not exist. ',
                  '/sys/fs/resctrl/tasks')),
    (OSError(errno.EINVAL, 'no such proc'),
     call.error('Could not write pid to resctrl (%r): Invalid argument %r.',
                '/sys/fs/resctrl/tasks')),
])
def test_resgroup_add_pids_invalid(makedirs_mock, set_effective_root_uid_mock,
                                   side_effect, log_call):
    resgroup = ResGroup(name='')
    writes_mock = {
        '/sys/fs/resctrl/tasks': Mock(return_value=Mock(write=Mock(side_effect=side_effect))),
        '/sys/fs/resctrl/mon_groups/c1/tasks': MagicMock()
    }
    with patch('builtins.open', new=create_open_mock(writes_mock)), patch(
            'wca.resctrl.log') as log_mock:
        resgroup.add_pids(['123'], 'c1')
        log_mock.assert_has_calls([log_call])
