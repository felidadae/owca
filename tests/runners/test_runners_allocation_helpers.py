# Copyright (c) 2019 Intel Corporation
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

from tests.testing import allocation_metric, task, task_data, container, platform_mock
from wca.allocations import InvalidAllocations
from wca.allocators import (AllocationType, RDTAllocation,
                            AllocationConfiguration, Allocator)
from wca.cgroups import Cgroup
from wca.containers import Container
from wca.nodes import Node
from wca.platforms import RDTInformation
from wca.resctrl import ResGroup
from wca.resctrl_allocations import RDTGroups, RDTAllocationValue
from wca.runners.allocation import (TasksAllocationsValues,
                                    TaskAllocationsValues,
                                    AllocationRunner,
                                    validate_shares_allocation_for_kubernetes,
                                    _get_tasks_allocations,
                                    _update_tasks_data_with_allocations)
from wca.runners.measurement import MeasurementRunner
from wca.storage import Storage


@pytest.mark.parametrize('tasks_allocations, expected_metrics', (
        ({}, []),
        ({'t1_task_id': {AllocationType.SHARES: 0.5}}, [
            allocation_metric('cpu_shares', value=0.5,
                              container_name='t1', task='t1_task_id')
        ]),
        ({'t1_task_id': {AllocationType.RDT: RDTAllocation(mb='MB:0=20')}}, [
            allocation_metric('rdt_mb', 20, group_name='t1', domain_id='0', container_name='t1',
                              task='t1_task_id')
        ]),
        ({'t1_task_id': {AllocationType.SHARES: 0.5,
                         AllocationType.RDT: RDTAllocation(mb='MB:0=20')}}, [
             allocation_metric('cpu_shares', value=0.5, container_name='t1', task='t1_task_id'),
             allocation_metric('rdt_mb', 20, group_name='t1', domain_id='0', container_name='t1',
                               task='t1_task_id')
         ]),
        ({'t1_task_id': {
            AllocationType.SHARES: 0.5, AllocationType.RDT: RDTAllocation(
                mb='MB:0=30', l3='L3:0=f')
        },
             't2_task_id': {
                 AllocationType.QUOTA: 0.6,
                 AllocationType.RDT: RDTAllocation(name='b', l3='L3:0=f'),
             }
         }, [allocation_metric('cpu_shares', value=0.5, container_name='t1', task='t1_task_id'),
             allocation_metric('rdt_l3_cache_ways', 4, group_name='t1',
                               domain_id='0', container_name='t1',
                               task='t1_task_id'),
             allocation_metric('rdt_l3_mask', 15, group_name='t1',
                               domain_id='0', container_name='t1', task='t1_task_id'),
             allocation_metric('rdt_mb', 30, group_name='t1', domain_id='0', container_name='t1',
                               task='t1_task_id'),
             allocation_metric('cpu_quota', value=0.6, container_name='t2',
                               task='t2_task_id'),
             allocation_metric('rdt_l3_cache_ways', 4, group_name='b',
                               domain_id='0', container_name='t2',
                               task='t2_task_id'),
             allocation_metric('rdt_l3_mask', 15, group_name='b',
                               domain_id='0', container_name='t2', task='t2_task_id')
             ]),
))
def test_allocations_generate_metrics(tasks_allocations, expected_metrics):
    """Check that proper allocations metrics are generated. """
    containers = {task('/t1'): container('/t1'),
                  task('/t2'): container('/t2'),
                  }
    platform_mock.rdt_information.rdt_mb_control_enabled = True
    allocations_values = TasksAllocationsValues.create(
        True, tasks_allocations, containers, platform_mock)
    allocations_values.validate()
    metrics_got = allocations_values.generate_metrics()
    assert metrics_got == expected_metrics


rdta = RDTAllocation


@pytest.mark.parametrize(
    'current, new, expected_target, expected_changeset', [
        ({}, {"rdt": rdta(name='', l3='L3:0=ff')},
         {"rdt": rdta(name='', l3='L3:0=ff')}, {"rdt": rdta(name='', l3='L3:0=ff')}),
        ({"rdt": rdta(name='', l3='L3:0=ff')}, {},
         {"rdt": rdta(name='', l3='L3:0=ff')}, None),
        ({"rdt": rdta(name='', l3='L3:0=ff')}, {"rdt": rdta(name='x', l3='L3:0=ff')},
         {"rdt": rdta(name='x', l3='L3:0=ff')}, {"rdt": rdta(name='x', l3='L3:0=ff')}),
        ({"rdt": rdta(name='x', l3='L3:0=ff')}, {"rdt": rdta(name='x', l3='L3:0=dd')},
         {"rdt": rdta(name='x', l3='L3:0=dd')}, {"rdt": rdta(name='x', l3='L3:0=dd')}),
        ({"rdt": rdta(name='x', l3='L3:0=dd', mb='MB:0=ff')},
         {"rdt": rdta(name='x', mb='MB:0=ff')},
         {"rdt": rdta(name='x', l3='L3:0=dd', mb='MB:0=ff')}, None),
    ]
)
def test_rdt_allocations_dict_changeset(current, new, expected_target, expected_changeset):
    """Check that changeset is properly calculated."""

    # We need have to convert simple objects to wrapped using mocks, so
    # prepare class mocks (constructors).
    CgroupMock = Mock(spec=Cgroup)
    ResGroupMock = Mock(spec=ResGroup)
    ContainerMock = Mock(spec=Container)

    # Limiter for rdtgroups - 20 is enough to be not limited by number of rdtgroups.
    rdt_groups = RDTGroups(20)

    def rdt_allocation_value_constructor(allocation_value, container, common_labels):
        rdt_information = RDTInformation(
            False, False, False, False, 'fff', '1', 0, 0, 0)
        return RDTAllocationValue('c1', allocation_value, CgroupMock(), ResGroupMock(),
                                  platform_sockets=1,
                                  rdt_information=rdt_information,
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

    # Convert both current and new value.
    current_values = convert_dict(current)
    new_values = convert_dict(new)
    expected_changeset_values = convert_dict(expected_changeset)
    expected_target_values = convert_dict(expected_target)

    # Calculate the difference to get changeset.
    got_target_values, got_changeset_values = new_values.calculate_changeset(current_values)

    assert got_changeset_values == expected_changeset_values
    assert got_target_values == expected_target_values


@pytest.mark.parametrize('tasks_allocations,expected_error', [
    ({'tx': {'cpu_shares': 3}}, 'invalid task id'),
    ({'t1_task_id': {'wrong_type': 5}}, 'unsupported allocation type'),
    ({'t1_task_id': {'rdt': RDTAllocation()},
      't2_task_id': {'rdt': RDTAllocation()},
      't3_task_id': {'rdt': RDTAllocation()}},
     'too many resource groups for available CLOSids'),
])
def test_convert_invalid_task_allocations(tasks_allocations, expected_error):
    """After allocations are converted, check that for improper input values
    proper validation exception with appropriate message is raised."""
    containers = {task('/t1'): container('/t1'),
                  task('/t2'): container('/t2'),
                  task('/t3'): container('/t3'),
                  }
    with pytest.raises(InvalidAllocations, match=expected_error):
        got_allocations_values = TasksAllocationsValues.create(
            True, tasks_allocations, containers, platform_mock)
        got_allocations_values.validate()


@pytest.mark.parametrize(
    'tasks_allocations,expected_resgroup_reallocation_count',
    (
            # No RDT allocations.
            (
                    {
                        't1_task_id': {AllocationType.QUOTA: 0.6},
                    },
                    0
            ),
            # The both task in the same resctrl group.
            (
                    {
                        't1_task_id': {'rdt': RDTAllocation(name='be', l3='L3:0=ff')},
                        't2_task_id': {'rdt': RDTAllocation(name='be', l3='L3:0=ff')}
                    },
                    1
            ),
            # The tasks in seperate resctrl group.
            (
                    {
                        't1_task_id': {'rdt': RDTAllocation(name='be', l3='L3:0=ff')},
                        't2_task_id': {'rdt': RDTAllocation(name='le', l3='L3:0=ff')}
                    },
                    2
            ),
            # The tasks in root group (even with diffrent l3 values)
            (
                    {
                        't1_task_id': {'rdt': RDTAllocation(name='', l3='L3:0=ff')},
                        't2_task_id': {'rdt': RDTAllocation(name='', l3='L3:0=ff')}
                    },
                    1
            ),
            # The tasks are in autonamed groups (force execution always)
            (
                    {
                        't1_task_id': {'rdt': RDTAllocation(l3='L3:0=ff')},
                        't2_task_id': {'rdt': RDTAllocation(l3='L3:0=ff')}
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
    allocations_values = TasksAllocationsValues.create(
        True, tasks_allocations, containers, platform_mock)
    allocations_values.validate()
    with patch('wca.resctrl.ResGroup.write_schemata') as mock, \
            patch('wca.cgroups.Cgroup._write'), patch('wca.cgroups.Cgroup._read'):
        allocations_values.perform_allocations()
        assert mock.call_count == expected_resgroup_reallocation_count


@pytest.mark.parametrize(
    'default_rdt_l3, default_rdt_mb,'
    'config_rdt_mb_control_enabled, config_rdt_cache_control_enabled,'
    'platform_rdt_mb_control_enabled, platform_rdt_cache_control_enabled,'
    'expected_error,'
    'expected_final_rdt_mb_control_enabled_with_value,'
    'expected_cleanup_arguments', [
        # rdt mb is not enabled and not detected on platform, there should be no call nor exception
        (None, None, False, False, False, False, None, False, (None, None, False)),
        # rdt mb is not enabled but detected on platform - configure l3 to max, but not mb
        (None, None, False, False, True, False, None, False, (None, 'MB:0=100', False)),
        # mask based on cbm_mask below
        # rdt mb is enabled and not detected on platform, there should be exception
        (None, None, True, False, False, True, None, False, None),
        # rdt mb is enabled and available on platform, there should be no exception
        (None, None, True, False, True, False, None, True, (None, 'MB:0=100', False)),
        # rdt mb is enabled and available on platform, there should be no exception, but use MB=50
        (None, 'MB:0=50', True, True, True, True, None, True, ('L3:0=fff', 'MB:0=50', False)),
        # rdt mb is enabled and available on platform, there should be no exception, but use MB=10
        # which is the same as minimal bandwidth
        (None, 'MB:0=10', True, True, True, True, None, True, ('L3:0=fff', 'MB:0=10', False)),
        # rdt mb is enabled and available on platform, there should be no exception, but use L3=f
        ('L3:0=00f', None, True, True, True, True, None, True, ('L3:0=00f', 'MB:0=100', False)),
        # rdt mb is enabled and available on platform, there should be no exception, but use both
        ('L3:0=00f', 'MB:0=50', True, True, True, True, None, True, ('L3:0=00f', 'MB:0=50', False)),
        # rdt mb is not enabled and not available on platform, no exception, and just set L3
        ('L3:0=00f', 'MB:0=50', False, False, False, False, None, False, (None, None, False)),
        # wrong values
        ('wrongl3', 'MB:0=50', True, True, True, True, 'wrong', True, None),
        ('L3:0=00f', 'wrong mb', True, True, True, True, 'wrong', True, None),
        # rdt mb is less than minimal bandwidth
        ('L3:0=00f', 'MB:0=9', True, True, True, True, 'wrong', True, None),
    ]
)
@patch('wca.resctrl.cleanup_resctrl')
@patch('wca.platforms.collect_platform_information', return_value=(platform_mock, [], {}))
def test_rdt_initialize(rdt_max_values_mock, cleanup_resctrl_mock,
                        default_rdt_l3, default_rdt_mb,
                        config_rdt_mb_control_enabled,
                        config_rdt_cache_control_enabled,
                        platform_rdt_mb_control_enabled,
                        platform_rdt_cache_control_enabled,
                        expected_error,
                        expected_final_rdt_mb_control_enabled_with_value,
                        expected_cleanup_arguments,
                        ):
    allocation_configuration = AllocationConfiguration(
        default_rdt_mb=default_rdt_mb,
        default_rdt_l3=default_rdt_l3
    )
    runner = AllocationRunner(
        measurement_runner=MeasurementRunner(
            node=Mock(spec=Node),
            interval=1,
            rdt_enabled=True,
            metrics_storage=Mock(spec=Storage),
            allocation_configuration=allocation_configuration,
            ),
        allocator=Mock(spec=Allocator),
        anomalies_storage=Mock(spec=Storage),
        allocations_storage=Mock(spec=Storage),
        rdt_mb_control_required=config_rdt_mb_control_enabled,
        rdt_cache_control_required=config_rdt_cache_control_enabled
    )

    with patch('tests.testing.platform_mock.rdt_information', Mock(
            spec=RDTInformation,
            cbm_mask='fff', min_cbm_bits='2',
            mb_min_bandwidth=10,
            mb_bandwidth_gran=10,
            rdt_mb_control_enabled=platform_rdt_mb_control_enabled,
            rdt_cache_control_enabled=platform_rdt_cache_control_enabled)):
        assert runner._initialize_rdt() is not expected_error

    if expected_final_rdt_mb_control_enabled_with_value:
        assert runner._rdt_mb_control_required == expected_final_rdt_mb_control_enabled_with_value

    if expected_cleanup_arguments:
        cleanup_resctrl_mock.assert_called_with(*expected_cleanup_arguments)
    else:
        assert cleanup_resctrl_mock.call_count == 0


@patch('wca.runners.allocation.have_tasks_qos_label', return_value=True)
@patch('wca.runners.allocation.are_all_tasks_of_single_qos', return_value=False)
@pytest.mark.parametrize(
    'allocations, should_raise_exception',
    (
            ({'t1': {AllocationType.SHARES: 10}}, True),
            ({'t1': {AllocationType.QUOTA: 100}}, False),
            ({'t1': {AllocationType.QUOTA: 100}, 't2': {AllocationType.SHARES: 10}}, True),
    )
)
def test_validate_shares_allocation_for_kubernetes(mock_1, mock_2, allocations,
                                                   should_raise_exception):
    if should_raise_exception:
        with pytest.raises(InvalidAllocations):
            validate_shares_allocation_for_kubernetes(tasks=[], allocations=allocations)


@patch('builtins.open', side_effect=FileNotFoundError())
def test_get_tasks_allocations_fail(*mock):
    containers = {
        task('/t1', labels={'label_key': 'label_value'}, resources={'cpu': 3}):
            Container('/t1', platform_mock,
                      allocation_configuration=AllocationConfiguration(
                          cpu_quota_period=1000))
    }

    assert {} == _get_tasks_allocations(containers)


@pytest.mark.parametrize(
        'allocations, tasks_data, expected',
        (({'t1_task_id': {AllocationType.SHARES: 10}},
            {'t1_task_id': task_data('/t1')},
            {'t1_task_id': task_data('/t1', allocations={AllocationType.SHARES: 10})}),
         ({'t1_task_id': {AllocationType.SHARES: 10},
           't2_task_id': {AllocationType.SHARES: 20}},
            {'t1_task_id': task_data('/t1')},
            {'t1_task_id': task_data('/t1', allocations={AllocationType.SHARES: 10})}),
         ({}, {'t1_task_id': task_data('/t1'), 't2_task_id': task_data('/t2')},
            {'t1_task_id': task_data('/t1'), 't2_task_id': task_data('/t2')}))
        )
def test_update_tasks_data_with_allocations(allocations, tasks_data, expected):
    _update_tasks_data_with_allocations(tasks_data, allocations)
    assert tasks_data == expected
