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
from unittest.mock import Mock
from unittest.mock import patch

import pytest

from owca import platforms
from owca.allocations import InvalidAllocations
from owca.allocators import AllocationType, RDTAllocation
from owca.cgroups import Cgroup
from owca.containers import Container
from owca.resctrl import ResGroup
from owca.resctrl_allocations import RDTGroups, RDTAllocationValue
from owca.runners.allocation import TasksAllocationsValues, TaskAllocationsValues
from owca.testing import allocation_metric, task, container

platform_mock = Mock(
    spec=platforms.Platform, sockets=1,
    rdt_cbm_mask='fffff', rdt_min_cbm_bits=1, rdt_mb_control_enabled=False, rdt_num_closids=2)


@pytest.mark.parametrize('tasks_allocations,expected_metrics', (
        ({}, []),
        ({'task_id-t1': {AllocationType.SHARES: 0.5}}, [
            allocation_metric('cpu_shares', value=0.5,
                              container_name='t1', task='task_id-t1')
        ]),
        ({'task_id-t1': {AllocationType.RDT: RDTAllocation(mb='mb:0=20')}}, [
            allocation_metric('rdt_mb', 20, group_name='t1', domain_id='0', container_name='t1',
                              task='task_id-t1')
        ]),
        ({'task_id-t1': {AllocationType.SHARES: 0.5,
                         AllocationType.RDT: RDTAllocation(mb='mb:0=20')}}, [
             allocation_metric('cpu_shares', value=0.5, container_name='t1', task='task_id-t1'),
             allocation_metric('rdt_mb', 20, group_name='t1', domain_id='0', container_name='t1',
                               task='task_id-t1')
         ]),
        ({'task_id-t1': {
            AllocationType.SHARES: 0.5, AllocationType.RDT: RDTAllocation(mb='mb:0=30')
        },
             'task_id-t2': {
                 AllocationType.QUOTA: 0.6,
                 AllocationType.RDT: RDTAllocation(name='b', l3='L3:0=f'),
             }
         }, [
             allocation_metric('cpu_shares', value=0.5, container_name='t1', task='task_id-t1'),
             allocation_metric('rdt_mb', 30, group_name='t1', domain_id='0', container_name='t1',
                               task='task_id-t1'),
             allocation_metric('cpu_quota', value=0.6, container_name='t2', task='task_id-t2'),
             allocation_metric('rdt_l3_cache_ways', 4, group_name='b',
                               domain_id='0', container_name='t2', task='task_id-t2'),
             allocation_metric('rdt_l3_mask', 15, group_name='b',
                               domain_id='0', container_name='t2', task='task_id-t2'),
         ]),
))
def test_convert_task_allocations_to_metrics(tasks_allocations, expected_metrics):
    containers = {task('/t1'): container('/t1'),
                  task('/t2'): container('/t2'),
                  }
    allocations = TasksAllocationsValues.create(
        tasks_allocations, containers, platform_mock)
    allocations.validate()
    metrics_got = allocations.generate_metrics()
    assert metrics_got == expected_metrics


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
        ({"rdt": RDTAllocation(name='x', l3='dd', mb='ff')},
         {"rdt": RDTAllocation(name='x', mb='ff')},
         {"rdt": RDTAllocation(name='x', l3='dd', mb='ff')}, None),
    ]
)
def test_rdt_allocations_dict_changeset(current, new, expected_target, expected_changeset):
    # Extra mapping

    CgroupMock = Mock(spec=Cgroup)
    ResGroupMock = Mock(spec=ResGroup)
    ContainerMock = Mock(spec=Container)
    rdt_groups = RDTGroups(20)

    def rdt_allocation_value_constructor(allocation_value, container, common_labels):
        return RDTAllocationValue('c1', allocation_value, CgroupMock(), ResGroupMock(),
                                  platform_sockets=1, rdt_mb_control_enabled=False,
                                  rdt_cbm_mask='fff', rdt_min_cbm_bits='1',
                                  rdt_groups=rdt_groups,
                                  common_labels=common_labels,
                                  )

    def convert_dict(simple_dict):
        if simple_dict is not None:
            return TaskAllocationsValues.create(
                simple_dict,
                container=ContainerMock(),
                registry={AllocationType.RDT: rdt_allocation_value_constructor},
                common_labels={})
        else:
            return None

    # Conversion
    current_dict = convert_dict(current)
    new_dict = convert_dict(new)

    # Merge
    got_target_dict, got_changeset_dict = new_dict.calculate_changeset(current_dict)

    assert got_changeset_dict == convert_dict(expected_changeset)


@pytest.mark.parametrize('tasks_allocations,expected_error', [
    ({'tx': {'cpu_shares': 3}}, 'invalid task id'),
    ({'task_id-t1': {'wrong_type': 5}}, 'unknown allocation type'),
    ({'task_id-t1': {'rdt': RDTAllocation()},
      'task_id-t2': {'rdt': RDTAllocation()},
      'task_id-t3': {'rdt': RDTAllocation()}},
     'too many resource groups for available CLOSids'),
])
def test_convert_invalid_task_allocations(tasks_allocations, expected_error):
    containers = {task('/t1'): container('/t1'),
                  task('/t2'): container('/t2'),
                  task('/t3'): container('/t3'),
                  }
    with pytest.raises(InvalidAllocations, match=expected_error):
        got_allocations_values = TasksAllocationsValues.create(
            tasks_allocations, containers, platform_mock)
        got_allocations_values.validate()


@pytest.mark.parametrize(
    'tasks_allocations,expected_resgroup_reallocation_count',
    (
            # No RDT allocations.
            (
                    {
                        'task_id-t1': {AllocationType.QUOTA: 0.6},
                    },
                    0
            ),
            # The both task in the same resctrl group.
            (
                    {
                        'task_id-t1': {'rdt': RDTAllocation(name='be', l3='L3:0=ff')},
                        'task_id-t2': {'rdt': RDTAllocation(name='be', l3='L3:0=ff')}
                    },
                    1
            ),
            # The tasks in seperate resctrl group.
            (
                    {
                        'task_id-t1': {'rdt': RDTAllocation(name='be', l3='L3:0=ff')},
                        'task_id-t2': {'rdt': RDTAllocation(name='le', l3='L3:0=ff')}
                    },
                    2
            ),
            # The tasks in root group (even with diffrent l3 values)
            (
                    {
                        'task_id-t1': {'rdt': RDTAllocation(name='', l3='L3:0=ff')},
                        'task_id-t2': {'rdt': RDTAllocation(name='', l3='L3:0=ff')}
                    },
                    1
            ),
            # The tasks are in autonamed groups (force execution always)
            (
                    {
                        'task_id-t1': {'rdt': RDTAllocation(l3='L3:0=ff')},
                        'task_id-t2': {'rdt': RDTAllocation(l3='L3:0=ff')}
                    },
                    2
            ),
    )
)
def test_unique_rdt_allocations(tasks_allocations, expected_resgroup_reallocation_count):
    """Checks if allocation of resctrl group is performed only once if more than one
       task_allocations has RDTAllocation with the same name. In other words,
       check if unnecessary reallocation of resctrl group does not take place.

       The goal is achieved by checking how many times
       Container.write_schemata is called with allocate_rdt=True."""
    containers = {task('/t1'): container('/t1', resgroup_name='', with_config=True),
                  task('/t2'): container('/t2', resgroup_name='', with_config=True)}
    allocations = TasksAllocationsValues.create(
        tasks_allocations, containers, platform_mock)
    allocations.validate()
    with patch('owca.resctrl.ResGroup.write_schemata') as mock, \
            patch('owca.cgroups.Cgroup._write'), patch('owca.cgroups.Cgroup._read'):
        allocations.perform_allocations()
        assert mock.call_count == expected_resgroup_reallocation_count
