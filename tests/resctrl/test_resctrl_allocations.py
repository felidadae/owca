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

from typing import Dict, List
from unittest.mock import patch, mock_open, call

import pytest

from wca.allocations import InvalidAllocations
from wca.allocators import RDTAllocation
from wca.platforms import RDTInformation
from wca.resctrl import ResGroup
from wca.resctrl_allocations import RDTAllocationValue, RDTGroups, _parse_schemata_file_row, \
    _count_enabled_bits, check_cbm_mask, _is_rdt_suballocation_changed, _validate_domains
from tests.testing import create_open_mock, allocation_metric


@pytest.mark.parametrize(
    'resgroup_name, write_schemata_lines, expected_writes', [
        ('', ['any-string'],
         {'/sys/fs/resctrl/schemata': [b'any-string\n']}),
        ('be', ['l3write', 'mbwrite'],
         {'/sys/fs/resctrl/be/schemata': [b'l3write\n']}),
        ('be', ['l3write', 'mbwrite'],
         {'/sys/fs/resctrl/be/schemata': [b'l3write\n', b'mbwrite\n']}),
    ]
)
def test_resgroup_write_schemata(resgroup_name, write_schemata_lines,
                                 expected_writes: Dict[str, List[str]]):
    write_mocks = {filename: mock_open() for filename in expected_writes}
    resgroup = ResGroup(resgroup_name)

    with patch('builtins.open', new=create_open_mock(write_mocks)):
        resgroup.write_schemata(write_schemata_lines)

    for filename, write_mock in write_mocks.items():
        expected_filename_writes = expected_writes[filename]
        expected_write_calls = [call().write(write_body) for write_body in expected_filename_writes]
        assert expected_filename_writes
        write_mock.assert_has_calls(expected_write_calls, any_order=True)


@pytest.mark.parametrize(
    'current, new,'
    'expected_target,expected_changeset', (
            # --- Test cases withing the same group.
            # Set l3 within the same auto group.
            (RDTAllocation(l3='L3:0=0ff'), RDTAllocation(l3='L3:0=0f'),
             RDTAllocation(l3='L3:0=0f'), RDTAllocation(l3='L3:0=0f')),
            # Set mb within the same auto group to existing l3.
            (RDTAllocation(l3='L3:0=0f', mb='MB:0=x'), RDTAllocation(mb='MB:0=y'),
             RDTAllocation(l3='L3:0=0f', mb='MB:0=y'), RDTAllocation(mb='MB:0=y')),
            # Set l3 within the same auto group to existing l3 and mb.
            (RDTAllocation(l3='L3:0=0f', mb='MB:0=x'), RDTAllocation(l3='L3:0=0f', mb='MB:0=y'),
             RDTAllocation(l3='L3:0=0f', mb='MB:0=y'), RDTAllocation(mb='MB:0=y')),
            # Set l3 within the same auto group to existing l3 and mb.
            (RDTAllocation(l3='L3:0=0f'), RDTAllocation(name='', l3='L3:0=0f'),
             RDTAllocation(name='', l3='L3:0=0f'), RDTAllocation(name='', l3='L3:0=0f')),
            # --- Move moving between groups.
            # Initial put into auto-group.
            (None, RDTAllocation(),
             RDTAllocation(), RDTAllocation()),
            # Move to auto-group from root group.
            (RDTAllocation(name=''), RDTAllocation(),
             RDTAllocation(), RDTAllocation()),
            # Move to explicit named group from auto-group.
            (RDTAllocation(), RDTAllocation(name='be'),
             RDTAllocation(name='be'), RDTAllocation(name='be')),
            # Move to named group values are ignored.
            (RDTAllocation(l3='L3:0=0f'), RDTAllocation(name='be'),
             RDTAllocation(name='be'), RDTAllocation(name='be')),
            # Move to root group values are ignored.
            (RDTAllocation(l3='L3:0=0f'), RDTAllocation(name=''),
             RDTAllocation(name=''), RDTAllocation(name='')),
            # Move to 'new' group with new values.
            (RDTAllocation(l3='L3:0=0f', mb='MB:0=y'),
             RDTAllocation(name='new', l3='L3:0=0f', mb='MB:0=y'),
             RDTAllocation(name='new', l3='L3:0=0f', mb='MB:0=y'),
             RDTAllocation(name='new', l3='L3:0=0f', mb='MB:0=y')),
    )
)
def test_rdt_allocations_changeset(
        current, new,
        expected_target, expected_changeset):
    container_name = 'some_container-xx2'
    resgroup = ResGroup(name=container_name)
    rdt_groups = RDTGroups(16)

    def convert(rdt_allocation):
        rdt_information = RDTInformation(False, False, False, False, 'fffff', '1', 0, 0, 0)
        if rdt_allocation is not None:
            return RDTAllocationValue(container_name,
                                      rdt_allocation,
                                      resgroup,
                                      lambda: ['1'],
                                      platform_sockets=1,
                                      rdt_information=rdt_information,
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
def test_rdt_allocation_generate_metrics(rdt_allocation: RDTAllocation,
                                         extra_labels, expected_metrics):
    rdt_information = RDTInformation(True, True, True, True, 'fff', '1', 0, 0, 0)
    rdt_allocation_value = RDTAllocationValue(
        'c1',
        rdt_allocation, get_pids=lambda: [],
        resgroup=ResGroup(name=rdt_allocation.name or ''),
        platform_sockets=1, rdt_information=rdt_information,
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
        ('l3:0=20', {'0': '20'}),
))
def test_parse_schemata_file_row(line, expected_domains):
    got_domains = _parse_schemata_file_row(line)
    assert got_domains == expected_domains


@pytest.mark.parametrize('inputs,expected_result', (
        # Trivial.
        (('L3:0=00f;1=00f', 'L3:0=00f;1=00f'), False),
        # Differing with leading 0.
        (('L3:0=00f;1=00f', 'L3:0=0000f;1=0000f'), False),
        # Differing that second does not contain second socket allocation,
        #   but still expected_result is False.
        (('L3:0=00f;1=00f', 'L3:0=00f'), False),
        (('L3:0=00f;1=00ff', 'L3:0=0000f'), False),
        # No change for left filled with spaces as well.
        (('L3:0= 00f;1=00ff', 'L3:0=  0000f'), False),
        # Differencing with ending 0, should return True.
        (('L3:0=00f;1=00f', 'L3:0=00f0;1=00f0'), True),
        # The new allocation is not provided (None).
        (('L3:0=00f0;1=00f0', None), False),
))
def test_compare_rdt_allocation_l3(inputs, expected_result):
    assert _is_rdt_suballocation_changed(inputs[0], inputs[1]) == expected_result


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
        check_cbm_mask(mask, cbm_mask, min_cbm_bits)


@pytest.mark.parametrize(
    'domains, platform_sockets', [
        ([], 0),
        ([], 5),
        (['3'], 4),
        (['0', '1', '2', '3'], 4),
    ]
)
def test_validate_domain_ok(domains, platform_sockets):
    _validate_domains(domains, platform_sockets)


@pytest.mark.parametrize(
    'domains, platform_sockets, exception_match', [
        (['3'], 0, 'range'),
        (['1', '6'], 5, 'range'),
        (['xx'], 4, 'numeric'),
    ]
)
def test_validate_domain_invalid(domains, platform_sockets, exception_match):
    with pytest.raises(InvalidAllocations, match=exception_match):
        _validate_domains(domains, platform_sockets)
