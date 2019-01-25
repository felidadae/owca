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
from unittest.mock import patch, mock_open, call, Mock

import pytest

from owca.allocations import create_default_registry, AllocationsDict
from owca.allocators import AllocationConfiguration
from owca.cgroups import Cgroup
from owca.resctrl import ResGroup, RDTAllocation, RDTAllocationValue
from owca.testing import create_open_mock, allocation_metric


@patch('os.path.isdir', return_value=True)
@patch('os.rmdir')
@patch('owca.resctrl.SetEffectiveRootUid')
def test_resgroup_move_tasks_to_root(isdir_mock, rmdir_mock, *args):
    root_tasks_mock = mock_open()
    open_mock = create_open_mock({
        "/sys/fs/resctrl": "0",
        "/sys/fs/resctrl/tasks": root_tasks_mock,
        "/sys/fs/resctrl/best_efforts/mon_groups/task_id/tasks": "123\n124\n",
    })
    with patch('owca.resctrl.open', open_mock):
        resgroup = ResGroup("best_efforts")
        resgroup.move_tasks_to_root('task_id')
        rmdir_mock.assert_called_once_with('/sys/fs/resctrl/best_efforts/mon_groups/task_id')
        # Assure that only two pids were written to the root group.
        root_tasks_mock().assert_has_calls([
            call.write('123'),
            call.flush(),
            call.write('124'),
            call.flush()])


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
        (None, RDTAllocation(),
         RDTAllocation(), RDTAllocation()),
        (RDTAllocation(name=''), RDTAllocation(),  # empty group overrides existing
         RDTAllocation(), RDTAllocation()),
        (RDTAllocation(), RDTAllocation(l3='x'),
         RDTAllocation(l3='x'), RDTAllocation(l3='x')),
        (RDTAllocation(l3='x'), RDTAllocation(mb='y'),
         RDTAllocation(l3='x', mb='y'), RDTAllocation(mb='y')),
        (RDTAllocation(l3='x'), RDTAllocation(l3='x', mb='y'),
         RDTAllocation(l3='x', mb='y'), RDTAllocation(mb='y')),
        (RDTAllocation(l3='x', mb='y'), RDTAllocation(name='new', l3='x', mb='y'),
         RDTAllocation(name='new', l3='x', mb='y'), RDTAllocation(name='new', l3='x', mb='y')),
        (RDTAllocation(l3='x'), RDTAllocation(name='', l3='x'),
         RDTAllocation(name='', l3='x'), RDTAllocation(name='', l3='x'))
    )
)
def test_merge_rdt_allocations(
        current, new,
        expected_target, expected_changeset):

    cgroup = Cgroup(cgroup_path='/test', platform_cpus=2,
                    allocation_configuration=AllocationConfiguration())
    resgroup = ResGroup(name='')

    container_name = 'some_container-xx2'

    def convert(rdt_allocation):
        if rdt_allocation is not None:
            return RDTAllocationValue(container_name,
                                      rdt_allocation, resgroup, cgroup,
                                      platform_sockets=1,
                                      rdt_mb_control_enabled=False,
                                      rdt_cbm_mask='fffff',
                                      rdt_min_cbm_bits='1'
                                      )
        else:
            return None

    current_rdt_allocation_value = convert(current)
    new_rdt_allocation_value = convert(new)

    got_target_rdt_allocation_value, got_rdt_alloction_changeset_value = \
        new_rdt_allocation_value.calculate_changeset(current_rdt_allocation_value)

    assert got_target_rdt_allocation_value.unwrap() == expected_target
    assert got_rdt_alloction_changeset_value.unwrap() == expected_changeset


@pytest.mark.parametrize('rdt_allocation, expected_metrics', (
    (RDTAllocation(), []),
    (RDTAllocation(mb='mb:0=20'), [
        allocation_metric('rdt_mb', 20, group_name='', domain_id='0')
    ]),
    (RDTAllocation(mb='mb:0=20;1=30'), [
        allocation_metric('rdt_mb', 20, group_name='', domain_id='0'),
        allocation_metric('rdt_mb', 30, group_name='', domain_id='1'),
    ]),
    (RDTAllocation(l3='l3:0=ff'), [
        allocation_metric('rdt_l3_cache_ways', 8, group_name='', domain_id='0'),
        allocation_metric('rdt_l3_mask', 255, group_name='', domain_id='0'),
    ]),
    (RDTAllocation(name='be', l3='l3:0=ff', mb='mb:0=20;1=30'), [
        allocation_metric('rdt_l3_cache_ways', 8, group_name='be', domain_id='0'),
        allocation_metric('rdt_l3_mask', 255, group_name='be', domain_id='0'),
        allocation_metric('rdt_mb', 20, group_name='be', domain_id='0'),
        allocation_metric('rdt_mb', 30, group_name='be', domain_id='1'),
    ]),
))
def test_rdt_allocation_generate_metrics(rdt_allocation: RDTAllocation, expected_metrics):
    with patch('owca.resctrl.ResGroup._create_controlgroup_directory'):
        rdt_allocation_value = RDTAllocationValue(
            rdt_allocation, cgroup=Cgroup('/', platform_cpus=1),
            resgroup=ResGroup(name=rdt_allocation.name or ''),
            platform_sockets=1, rdt_mb_control_enabled=False,
            rdt_cbm_mask='fff', rdt_min_cbm_bits='1',
        )
        got_metrics = rdt_allocation_value.generate_metrics()
    assert got_metrics == expected_metrics


@pytest.mark.parametrize(
  'current, new, expected_target, expected_changeset', [
    ({}, {"rdt": RDTAllocation(name='', l3='ff')},
     {"rdt": RDTAllocation(name='', l3='ff')}, {"rdt": RDTAllocation(name='', l3='ff')}),
    ({"rdt": RDTAllocation(name='', l3='ff')}, {},
     {"rdt": RDTAllocation(name='', l3='ff')}, None),
    ({"rdt": RDTAllocation(name='', l3='ff')}, {"rdt": RDTAllocation(name='x', l3='ff')},
     {"rdt": RDTAllocation(name='x', l3='ff')}, {"rdt": RDTAllocation(name='x', l3='ff')}),
    ({"rdt": RDTAllocation(name='x', l3='ff')}, {"rdt": RDTAllocation(name='x', l3='dd')},
     {"rdt": RDTAllocation(name='x', l3='dd')}, {"rdt": RDTAllocation(name='x', l3='dd')}),
    ({"rdt": RDTAllocation(name='x', l3='dd', mb='ff')}, {"rdt": RDTAllocation(name='x', mb='ff')},
     {"rdt": RDTAllocation(name='x', l3='dd', mb='ff')}, None),
  ]
)
def test_allocations_dict_merging(current, new,
                                  expected_target, expected_changeset):

    # Extra mapping
    from owca.resctrl import RDTAllocationValue

    CgroupMock = Mock(spec=Cgroup)
    ResGroupMock = Mock(spec=ResGroup)

    def rdt_allocation_value_constructor(value, ctx, registry):
        return RDTAllocationValue(value, CgroupMock(), ResGroupMock(),
                                  platform_sockets=1, rdt_mb_control_enabled=False,
                                  rdt_cbm_mask='fff', rdt_min_cbm_bits='1',
                                  )

    registry = create_default_registry()
    registry.register_automapping_type(('rdt', RDTAllocation), rdt_allocation_value_constructor)

    def convert_dict(d):
        return AllocationsDict(d, None, registry)

    # Conversion
    current_dict = convert_dict(current)
    new_dict = convert_dict(new)

    # Merge
    got_target_dict, got_changeset_dict = new_dict.calculate_changeset(current_dict)

    assert got_target_dict.unwrap() == expected_target
    got_changeset = got_changeset_dict.unwrap() if got_changeset_dict is not None else None
    assert got_changeset == expected_changeset