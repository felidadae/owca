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

from owca.allocators import RDTAllocation
from owca.resctrl import ResGroup
from owca.resctrl_allocations import RDTAllocationValue, RDTGroups
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
def test_resgroup_perform_allocations(resgroup_args, write_schemata_args,
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
