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
from typing import Dict, List
from unittest.mock import patch, mock_open, call, Mock, MagicMock

import pytest

from owca.allocations import InvalidAllocations
from owca.allocators import RDTAllocation
from owca.resctrl import ResGroup
from owca.resctrl_allocations import RDTAllocationValue, RDTGroups, _parse_schemata_file_row, \
    _count_enabled_bits, check_cbm_bits
from owca.testing import create_open_mock, allocation_metric


@patch('os.path.isdir', return_value=True)
@patch('os.rmdir')
@patch('owca.resctrl.SetEffectiveRootUid')
@patch('os.listdir', side_effects=lambda path: {
    '/sys/fs/resctrl/best_efforts/mon_groups/some_container': [],
})
def test_resgroup_remove(listdir_mock, SetEffectiveRootUid_mock, rmdir_mock, isdir_mock):
    open_mock = create_open_mock({
        "/sys/fs/resctrl": "0",
        "/sys/fs/resctrl/best_efforts/mon_groups/some_container/tasks": "123\n124\n",
    })
    with patch('owca.resctrl.open', open_mock):
        resgroup = ResGroup("best_efforts")
        resgroup.remove('some-container')
        rmdir_mock.assert_called_once_with('/sys/fs/resctrl/best_efforts/mon_groups/some-container')


@pytest.mark.parametrize(
    'resgroup_args, write_schemata_args, expected_writes', [
        (dict(name=''), dict(l3='ble'),
         {'/sys/fs/resctrl/schemata': [b'ble\n']}),
        (dict(name='be', rdt_mb_control_enabled=False), dict(l3='l3write', mb='mbwrite'),
         {'/sys/fs/resctrl/be/schemata': [b'l3write\n']}),
        (dict(name='be', rdt_mb_control_enabled=True), dict(l3='l3write', mb='mbwrite'),
         {'/sys/fs/resctrl/be/schemata': [b'l3write\n', b'mbwrite\n']}),
    ]
)
def test_resgroup_write_schemata(resgroup_args, write_schemata_args,
                                 expected_writes: Dict[str, List[str]]):
    write_mocks = {filename: mock_open() for filename in expected_writes}
    resgroup = ResGroup(**resgroup_args)

    with patch('builtins.open', new=create_open_mock(write_mocks)):
        resgroup.write_schemata(**write_schemata_args)

    for filename, write_mock in write_mocks.items():
        expected_filename_writes = expected_writes[filename]
        expected_write_calls = [call().write(write_body) for write_body in expected_filename_writes]
        assert expected_filename_writes
        write_mock.assert_has_calls(expected_write_calls, any_order=True)


@patch('owca.resctrl.SetEffectiveRootUid')
@patch('os.makedirs')
@pytest.mark.parametrize(
    'resgroup_name, pids, mongroup_name, '
    'expected_writes, expected_setuid_calls_count, expected_makedirs', [
        # root groups
        ('', ['123'], 'c1',
         {'/sys/fs/resctrl/tasks': ['123'],
          '/sys/fs/resctrl/mon_groups/c1/tasks': ['123']
          }, 2, [call('/sys/fs/resctrl/mon_groups/c1', exist_ok=True)]),
        ('', ['123', '456'], 'c1',  # two pids
         {'/sys/fs/resctrl/tasks': ['123', '456'],
          '/sys/fs/resctrl/mon_groups/c1/tasks': ['123'],
          }, 2, [call('/sys/fs/resctrl/mon_groups/c1', exist_ok=True)]),
        # non-root groups
        ('be', ['123'], 'c1',  # no pids at all
         {'/sys/fs/resctrl/be/tasks': ['123'],
          '/sys/fs/resctrl/be/mon_groups/c1/tasks': ['123'],
          }, 2, [call('/sys/fs/resctrl/be/mon_groups/c1', exist_ok=True)]),
    ])
def test_resgroup_add_pids(makedirs_mock, SetEffectiveRootId_mock, resgroup_name, pids,
                           mongroup_name, expected_writes, expected_setuid_calls_count,
                           expected_makedirs):
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
    SetEffectiveRootId_mock.assert_has_calls(expected_setuid_calls, any_order=True)


@patch('owca.resctrl.SetEffectiveRootUid')
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
def test_resgroup_add_pids_invalid(makedirs_mock, SetEffectiveRootId_mock,
                                   side_effect, log_call):
    resgroup = ResGroup(name='')
    writes_mock = {
        '/sys/fs/resctrl/tasks': Mock(return_value=Mock(write=Mock(side_effect=side_effect))),
        '/sys/fs/resctrl/mon_groups/c1/tasks': MagicMock()
    }
    with patch('builtins.open', new=create_open_mock(writes_mock)), patch(
            'owca.resctrl.log') as log_mock:
        resgroup.add_pids(['123'], 'c1')
        log_mock.assert_has_calls([log_call])


@pytest.mark.parametrize(
    'current, new,'
    'expected_target,expected_changeset', (
            # within the same group
            (RDTAllocation(), RDTAllocation(l3='x'),
             RDTAllocation(l3='x'), RDTAllocation(l3='x')),
            (RDTAllocation(l3='x'), RDTAllocation(mb='y'),
             RDTAllocation(l3='x', mb='y'), RDTAllocation(mb='y')),
            (RDTAllocation(l3='x'), RDTAllocation(l3='x', mb='y'),
             RDTAllocation(l3='x', mb='y'), RDTAllocation(mb='y')),
            (RDTAllocation(l3='x'), RDTAllocation(name='', l3='x'),
             RDTAllocation(name='', l3='x'), RDTAllocation(name='', l3='x')),
            # moving between groups
            (None, RDTAllocation(),  # initial put into auto-group
             RDTAllocation(), RDTAllocation()),
            (RDTAllocation(name=''), RDTAllocation(),  # moving to auto-group from root
             RDTAllocation(), RDTAllocation()),
            (RDTAllocation(), RDTAllocation(name='be'),  # moving to named group from auto-group
             RDTAllocation(name='be'), RDTAllocation(name='be')),
            (RDTAllocation(l3='x'), RDTAllocation(name='be'),
             # moving to named group ignoring values
             RDTAllocation(name='be'), RDTAllocation(name='be')),
            (RDTAllocation(l3='x'), RDTAllocation(name=''),  # moving to root group ignoring values
             RDTAllocation(name=''), RDTAllocation(name='')),
            (RDTAllocation(l3='x', mb='y'), RDTAllocation(name='new', l3='x', mb='y'),
             RDTAllocation(name='new', l3='x', mb='y'), RDTAllocation(name='new', l3='x', mb='y')),
    )
)
def test_rdt_allocations_changeset(
        current, new,
        expected_target, expected_changeset):
    container_name = 'some_container-xx2'
    resgroup = ResGroup(name=container_name)
    rdt_groups = RDTGroups(16)

    def convert(rdt_allocation):
        if rdt_allocation is not None:
            return RDTAllocationValue(container_name,
                                      rdt_allocation,
                                      resgroup,
                                      lambda: ['1'],
                                      platform_sockets=1,
                                      rdt_mb_control_enabled=False,
                                      rdt_cbm_mask='fffff',
                                      rdt_min_cbm_bits='1',
                                      rdt_groups=rdt_groups,
                                      common_labels={},
                                      )
        else:
            return None

    current_value = convert(current)
    new_value = convert(new)

    got_target, got_changeset = \
        new_value.calculate_changeset(current_value)

    assert got_target == convert(expected_target)
    assert got_changeset == convert(expected_changeset)


@pytest.mark.parametrize('rdt_allocation, extra_labels, expected_metrics', (
        (RDTAllocation(), {}, []),
        (RDTAllocation(mb='mb:0=20'), {}, [
            allocation_metric('rdt_mb', 20, group_name='c1', domain_id='0', container_name='c1')
        ]),
        (RDTAllocation(mb='mb:0=20'), {'foo': 'bar'}, [
            allocation_metric('rdt_mb', 20, group_name='c1', domain_id='0',
                              container_name='c1', foo='bar')
        ]),
        (RDTAllocation(mb='mb:0=20'), {}, [
            allocation_metric('rdt_mb', 20, group_name='c1', domain_id='0', container_name='c1')
        ]),
        (RDTAllocation(mb='mb:0=20;1=30'), {}, [
            allocation_metric('rdt_mb', 20, group_name='c1', domain_id='0', container_name='c1'),
            allocation_metric('rdt_mb', 30, group_name='c1', domain_id='1', container_name='c1'),
        ]),
        (RDTAllocation(l3='l3:0=ff'), {}, [
            allocation_metric('rdt_l3_cache_ways', 8, group_name='c1', domain_id='0',
                              container_name='c1'),
            allocation_metric('rdt_l3_mask', 255, group_name='c1', domain_id='0',
                              container_name='c1'),
        ]),
        (RDTAllocation(name='be', l3='l3:0=ff', mb='mb:0=20;1=30'), {}, [
            allocation_metric('rdt_l3_cache_ways', 8, group_name='be', domain_id='0',
                              container_name='c1'),
            allocation_metric('rdt_l3_mask', 255, group_name='be', domain_id='0',
                              container_name='c1'),
            allocation_metric('rdt_mb', 20, group_name='be', domain_id='0', container_name='c1'),
            allocation_metric('rdt_mb', 30, group_name='be', domain_id='1', container_name='c1'),
        ]),
))
def test_rdt_allocation_generate_metrics(rdt_allocation: RDTAllocation, extra_labels,
                                         expected_metrics):
    rdt_allocation_value = RDTAllocationValue(
        'c1',
        rdt_allocation, get_pids=lambda: [],
        resgroup=ResGroup(name=rdt_allocation.name or ''),
        platform_sockets=1, rdt_mb_control_enabled=False,
        rdt_cbm_mask='fff', rdt_min_cbm_bits='1',
        common_labels=extra_labels,
        rdt_groups=RDTGroups(10),
    )
    got_metrics = rdt_allocation_value.generate_metrics()
    assert got_metrics == expected_metrics


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


@pytest.mark.parametrize(
    'mask, cbm_mask, min_cbm_bits, expected_error_message', (
            ('f0f', 'ffff', '1', 'without a gap'),
            ('0', 'ffff', '1', 'minimum'),
            ('ffffff', 'ffff', 'bigger', ''),
    )
)
def test_check_cbm_bits_gap(mask: str, cbm_mask: str, min_cbm_bits: str,
                            expected_error_message: str):
    with pytest.raises(InvalidAllocations, match=expected_error_message):
        check_cbm_bits(mask, cbm_mask, min_cbm_bits)
