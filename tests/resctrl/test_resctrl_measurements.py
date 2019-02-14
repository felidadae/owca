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
from unittest.mock import call, MagicMock, patch

import pytest

from owca.resctrl import ResGroup, RESCTRL_ROOT_NAME
from owca.testing import create_open_mock


@patch('owca.resctrl.log.warning')
@patch('os.path.exists', return_value=True)
@patch('os.makedirs')
@patch('owca.resctrl.SetEffectiveRootUid')
def test_resgroup_add_tasks(*args):
    root_tasks_mock = MagicMock()
    tasks_mock = MagicMock()
    mongroup_tasks_mock = MagicMock()
    open_mock = create_open_mock({
        "/sys/fs/resctrl": "0",
        "/sys/fs/resctrl/tasks": root_tasks_mock,
        # for best_efforts resctrl group
        "/sys/fs/resctrl/best_efforts/tasks": tasks_mock,
        "/sys/fs/resctrl/best_efforts/mon_groups/task_id/tasks": mongroup_tasks_mock,
    })
    with patch('builtins.open', open_mock):
        resgroup = ResGroup("best_efforts")
        resgroup.add_pids(['123', '124'], 'task_id')

        tasks_mock.assert_called_once_with(
            '/sys/fs/resctrl/best_efforts/tasks', 'w')
        tasks_mock.assert_has_calls([call().write('123')])
        tasks_mock.assert_has_calls([call().write('124')])

        mongroup_tasks_mock.assert_called_once_with(
            '/sys/fs/resctrl/best_efforts/mon_groups/task_id/tasks', 'w')
        mongroup_tasks_mock.assert_has_calls([call().write('123')])
        mongroup_tasks_mock.assert_has_calls([call().write('124')])


@patch('owca.resctrl.log.warning')
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
    assert {'memory_bandwidth': 2, 'llc_occupancy': 2} == resgroup.get_measurements('best_efforts')
