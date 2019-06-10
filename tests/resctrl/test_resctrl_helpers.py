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

from unittest.mock import patch, mock_open, call

import pytest

from wca.resctrl import check_resctrl, get_max_rdt_values, read_mon_groups_relation, \
    clean_taskless_groups
from wca.resctrl_allocations import check_cbm_mask
from tests.testing import create_open_mock


@patch('builtins.open', new=create_open_mock({
    "/sys/fs/resctrl": "0",
    "/sys/fs/resctrl/tasks": "0",
    "/sys/fs/resctrl/mon_data/mon_L3_00/mbm_total_bytes": "0",
}))
def test_check_resctrl(*mock):
    assert check_resctrl()


@patch('os.listdir', return_value=['mesos-1', 'mesos-2', 'mesos-3'])
@patch('os.rmdir')
@patch('os.path.isdir', return_value=True)
@patch('os.path.exists', return_value=True)
def test_clean_resctrl(exists_mock, isdir_mock, rmdir_mock, listdir_mock):
    from wca.resctrl import cleanup_resctrl

    schemata_mock = mock_open()

    with patch('builtins.open', new=create_open_mock(
            {"/sys/fs/resctrl/mesos-1/tasks": "1\n2\n",
             # resctrl group to recycle - expected to be removed.
             "/sys/fs/resctrl/mesos-2/tasks": "",
             "/sys/fs/resctrl/mesos-3/tasks": "2",
             "/sys/fs/resctrl/mon_groups/mesos-1/tasks": "1\n2\n",
             # resctrl group to recycle - should be removed.
             "/sys/fs/resctrl/mon_groups/mesos-2/tasks": "",
             "/sys/fs/resctrl/mon_groups/mesos-3/tasks": "2",
             # default values expected to be written
             "/sys/fs/resctrl/schemata": schemata_mock})):
        cleanup_resctrl(root_rdt_l3='L3:0=ff', root_rdt_mb='MB:0=100', reset_resctrl=True)

    listdir_mock.assert_has_calls([
        call('/sys/fs/resctrl/mon_groups'),
        call('/sys/fs/resctrl/')
    ])
    isdir_mock.assert_has_calls([
        call('/sys/fs/resctrl/mon_groups/mesos-1'),
        call('/sys/fs/resctrl/mon_groups/mesos-2'),
        call('/sys/fs/resctrl/mon_groups/mesos-3'),
        call('/sys/fs/resctrl/mesos-1'),
        call('/sys/fs/resctrl/mesos-2'),
        call('/sys/fs/resctrl/mesos-3'),
    ])
    exists_mock.assert_has_calls([
        call('/sys/fs/resctrl/mon_groups/mesos-1/tasks'),
        call('/sys/fs/resctrl/mon_groups/mesos-2/tasks'),
        call('/sys/fs/resctrl/mon_groups/mesos-3/tasks'),
        call('/sys/fs/resctrl/mesos-1/tasks'),
        call('/sys/fs/resctrl/mesos-2/tasks'),
        call('/sys/fs/resctrl/mesos-3/tasks')
    ])

    rmdir_mock.assert_has_calls([
        call('/sys/fs/resctrl/mon_groups/mesos-1'),
        call('/sys/fs/resctrl/mon_groups/mesos-2'),
        call('/sys/fs/resctrl/mon_groups/mesos-3'),
        call('/sys/fs/resctrl/mesos-1'),
        call('/sys/fs/resctrl/mesos-2'),
        call('/sys/fs/resctrl/mesos-3')
    ])

    schemata_mock.assert_has_calls([
        call().write(b'L3:0=ff\n'),
        call().write(b'MB:0=100\n'),
    ], any_order=True)


@pytest.mark.parametrize(
    'cbm_mask, platform_sockets, expected_max_rdt_l3, expected_max_rdt_mb', (
            ('ff', 0, 'L3:', 'MB:'),
            ('ff', 1, 'L3:0=ff', 'MB:0=100'),
            ('ffff', 2, 'L3:0=ffff;1=ffff', 'MB:0=100;1=100'),
    )
)
def test_get_max_rdt_values(cbm_mask, platform_sockets, expected_max_rdt_l3, expected_max_rdt_mb):
    got_max_rdt_l3, got_max_rdt_mb = get_max_rdt_values(cbm_mask, platform_sockets, True, True)
    assert got_max_rdt_l3 == expected_max_rdt_l3
    assert got_max_rdt_mb == expected_max_rdt_mb


def test_check_cbm_mask_valid():
    check_cbm_mask('ff00', 'ffff', '1')


@patch('os.path.isdir', side_effect=lambda path: path in {
    '/sys/fs/resctrl/mon_groups',
    '/sys/fs/resctrl/mon_groups/foo',
    '/sys/fs/resctrl/ctrl1',
    '/sys/fs/resctrl/ctrl1/mon_groups',
    '/sys/fs/resctrl/ctrl1/mon_groups/bar',
})
@patch('os.listdir', side_effect=lambda path: {
    '/sys/fs/resctrl': ['tasks', 'ctrl1', 'mon_groups'],
    '/sys/fs/resctrl/mon_groups': ['foo'],
    '/sys/fs/resctrl/ctrl1/mon_groups': ['bar']
}[path])
def test_read_mon_groups_relation(listdir_mock, isdir_mock):
    relation = read_mon_groups_relation()
    assert relation == {'': ['foo'], 'ctrl1': ['bar']}


@patch('os.rmdir')
def test_clean_tasksless_resctrl_groups(rmdir_mock):
    with patch('wca.resctrl.open', create_open_mock({
        '/sys/fs/resctrl/mon_groups/c1/tasks': '',  # empty
        '/sys/fs/resctrl/mon_groups/c2/tasks': '1234',
        '/sys/fs/resctrl/empty/mon_groups/c3/tasks': '',
        '/sys/fs/resctrl/half_empty/mon_groups/c5/tasks': '1234',
        '/sys/fs/resctrl/half_empty/mon_groups/c6/tasks': '',
    })):
        mon_groups_relation = {'': ['c1', 'c2'],
                               'empty': ['c3'],
                               'half_empty': ['c5', 'c6'],
                               }
        clean_taskless_groups(mon_groups_relation)

    rmdir_mock.assert_has_calls([
        call('/sys/fs/resctrl/mon_groups/c1'),
        call('/sys/fs/resctrl/empty'),
        call('/sys/fs/resctrl/half_empty/mon_groups/c6')
    ])
