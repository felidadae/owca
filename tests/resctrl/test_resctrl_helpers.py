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

import sys
from unittest.mock import patch, mock_open, call, Mock

import pytest

from owca.resctrl import check_resctrl, get_max_rdt_values, check_cbm_bits, \
    _parse_schemata_file_row, read_mon_groups_relation, clean_taskless_groups, _count_enabled_bits
from owca.testing import create_open_mock


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
    from owca.resctrl import cleanup_resctrl

    schemata_mock = mock_open()

    with patch('builtins.open', new=create_open_mock({
            "/sys/fs/resctrl/mesos-1/tasks": "1\n2\n",
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
    got_max_rdt_l3, got_max_rdt_mb = get_max_rdt_values(cbm_mask, platform_sockets)
    assert got_max_rdt_l3 == expected_max_rdt_l3
    assert got_max_rdt_mb == expected_max_rdt_mb


@pytest.mark.parametrize(
    'mask, cbm_mask, min_cbm_bits, expected_error_message', (
            ('f0f', 'ffff', '1', 'without a gap'),
            ('0', 'ffff', '1', 'minimum'),
            ('ffffff', 'ffff', 'bigger', ''),
    )
)
def test_check_cbm_bits_gap(mask: str, cbm_mask: str, min_cbm_bits: str,
                            expected_error_message: str):
    with pytest.raises(ValueError, match=expected_error_message):
        check_cbm_bits(mask, cbm_mask, min_cbm_bits)


def test_check_cbm_bits_valid():
    check_cbm_bits('ff00', 'ffff', '1')


@pytest.mark.parametrize('line,expected_domains', (
        ('', {}),
        ('x=2', {'x': '2'}),
        ('x=2;y=3', {'x': '2', 'y': '3'}),
        ('foo=bar', {'foo': 'bar'}),
        ('mb:1=20;2=50', {'1': '20', '2': '50'}),
        ('mb:xxx=20mbs;2=50b', {'xxx': '20mbs', '2': '50b'}),
        ('l3:0=20;1=30', {'1': '30', '0': '20'}),
))
def test_parse_schemata_file_row(line, expected_domains):
    got_domains = _parse_schemata_file_row(line)
    assert got_domains == expected_domains


@pytest.mark.parametrize('invalid_line,expected_message', (
        ('x=', 'value cannot be empty'),
        ('x=2;x=3', 'Conflicting domain id found!'),
        ('=2', 'domain_id cannot be empty!'),
        ('2', 'Value separator is missing "="!'),
        (';', 'domain cannot be empty'),
        ('xxx', 'Value separator is missing "="!'),
))
def test_parse_invalid_schemata_file_domains(invalid_line, expected_message):
    with pytest.raises(ValueError, match=expected_message):
        _parse_schemata_file_row(invalid_line)


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

    with patch('owca.resctrl.open', create_open_mock({
                   '/sys/fs/resctrl/mon_groups/c1/tasks': '',  # empty
                   '/sys/fs/resctrl/mon_groups/c2/tasks': '1234',
                   '/sys/fs/resctrl/empty/mon_groups/c3/tasks': '',
                   '/sys/fs/resctrl/half_empty/mon_groups/c5/tasks': '1234',
                   '/sys/fs/resctrl/half_empty/mon_groups/c6/tasks': '',
            })) as mocks:
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


@pytest.mark.parametrize('hexstr,expected_bits_count', (
        ('', 0),
        ('1', 1),
        ('2', 1),
        ('3', 2),
        ('f', 4),
        ('f0', 4),
        ('0f0', 4),
        ('ff0', 8),
        ('f1f', 9),
        ('fffff', 20),
))
def test_count_enabled_bits(hexstr, expected_bits_count):
    got_bits_count = _count_enabled_bits(hexstr)
    assert got_bits_count == expected_bits_count