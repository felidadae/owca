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
from unittest.mock import Mock, patch
import pytest

from wca import storage
from wca.allocators import AllocationType, RDTAllocation, Allocator
from wca.mesos import MesosNode
from wca.runners.allocation import AllocationRunner
from wca.runners.measurement import MeasurementRunner
from tests.testing import redis_task_with_default_labels,\
    prepare_runner_patches, assert_subdict, assert_metric,\
    platform_mock

# Patch Container get_allocations (simulate allocations read from OS filesystem)
_os_tasks_allocations = {
    AllocationType.QUOTA: 1.,
    AllocationType.RDT: RDTAllocation(name='', l3='L3:0=fffff', mb='MB:0=50')
}


@prepare_runner_patches
@patch('wca.containers.Container.get_allocations',    return_value=_os_tasks_allocations)
@patch('wca.containers.ContainerSet.get_allocations', return_value=_os_tasks_allocations)
@patch('wca.platforms.collect_platform_information', return_value=(platform_mock, [], {}))
@pytest.mark.parametrize('subcgroups', ([], ['/T/c1'], ['/T/c1', '/T/c2']))
def test_allocation_runner(
        _get_allocations_mock, _get_allocations_mock_, platform_mock,
        subcgroups):
    """ Low level system calls are not mocked - but higher level objects and functions:
        Cgroup, Resgroup, Platform, etc. Thus the test do not cover the full usage scenario
        (such tests would be much harder to write).
    """
    # Tasks mock
    t1 = redis_task_with_default_labels('t1', subcgroups)
    t2 = redis_task_with_default_labels('t2', subcgroups)

    # Allocator mock (lower the quota and number of cache ways in dedicated group).
    # Patch some of the functions of AllocationRunner.
    runner = AllocationRunner(
        measurement_runner=MeasurementRunner(
            node=Mock(spec=MesosNode, get_tasks=Mock(return_value=[])),
            metrics_storage=Mock(spec=storage.Storage, store=Mock()),
            rdt_enabled=True,
            gather_hw_mm_topology=False,
            extra_labels=dict(extra_labels='extra_value'),
            ),
        anomalies_storage=Mock(spec=storage.Storage, store=Mock()),
        allocations_storage=Mock(spec=storage.Storage, store=Mock()),
        rdt_mb_control_required=True,
        rdt_cache_control_required=True,
        allocator=Mock(spec=Allocator, allocate=Mock(return_value=({}, [], []))))

    runner._measurement_runner._wait = Mock()
    runner._measurement_runner._initialize()

    ############
    # First run (one task, one allocation).
    runner._measurement_runner._node.get_tasks.return_value = [t1]
    runner._allocator.allocate.return_value = (
        {t1.task_id: {AllocationType.QUOTA: .5,
                      AllocationType.RDT: RDTAllocation(name=None, l3='L3:0=0000f')}},
        [], []
    )
    runner._measurement_runner._iterate()

    # Check that allocator.allocate was called with proper arguments.
    assert runner._allocator.allocate.call_count == 1
    (_, tasks_data) = runner._allocator.allocate.mock_calls[0][1]
    assert_subdict(tasks_data[t1.task_id].allocations, _os_tasks_allocations)

    # Check allocation metrics ...
    got_allocations_metrics = runner._allocations_storage.store.call_args[0][0]
    # ... generic allocation metrics ...
    assert_metric(got_allocations_metrics,
                  'allocations_count',
                  dict(extra_labels='extra_value'),
                  expected_metric_value=1)
    assert_metric(got_allocations_metrics,
                  'allocations_errors',
                  dict(extra_labels='extra_value'),
                  expected_metric_value=0)
    assert_metric(got_allocations_metrics,
                  'allocation_duration',
                  dict(extra_labels='extra_value'))
    # ... and allocation metrics for task t1.
    assert_metric(got_allocations_metrics,
                  'allocation_cpu_quota',
                  dict(task=t1.task_id,
                       extra_labels='extra_value'), 0.5)
    assert_metric(got_allocations_metrics,
                  'allocation_rdt_l3_cache_ways',
                  dict(task=t1.task_id, extra_labels='extra_value'), 4)
    assert_metric(got_allocations_metrics,
                  'allocation_rdt_l3_mask',
                  dict(task=t1.task_id, extra_labels='extra_value'), 15)

    ############################
    # Second run (two tasks, one allocation)
    runner._measurement_runner._node.get_tasks.return_value = [t1, t2]
    first_run_t1_task_allocations = {
        t1.task_id: {AllocationType.QUOTA: .5,
                     AllocationType.RDT: RDTAllocation(name=None, l3='L3:0=0000f')}
    }
    runner._allocator.allocate.return_value = (first_run_t1_task_allocations, [], [])
    runner._measurement_runner._iterate()

    # Check allocation metrics...
    got_allocations_metrics = runner._allocations_storage.store.call_args[0][0]
    # ... generic allocation metrics ...
    assert_metric(got_allocations_metrics, 'allocations_count', expected_metric_value=2)
    assert_metric(got_allocations_metrics, 'allocations_errors', expected_metric_value=0)
    assert_metric(got_allocations_metrics, 'allocation_duration')
    # ... and metrics for task t1 ...
    assert_metric(got_allocations_metrics, 'allocation_cpu_quota', dict(task=t1.task_id), 0.5)
    assert_metric(got_allocations_metrics, 'allocation_rdt_l3_cache_ways', dict(task=t1.task_id), 4)
    assert_metric(got_allocations_metrics, 'allocation_rdt_l3_mask', dict(task=t1.task_id), 15)

    # Check allocate call.
    (_, tasks_data) = runner._allocator.allocate.mock_calls[1][1]
    # (note: tasks_allocations are always read from filesystem)
    assert_subdict(tasks_data[t1.task_id].allocations, _os_tasks_allocations)
    assert_subdict(tasks_data[t2.task_id].allocations, _os_tasks_allocations)

    ############
    # Third run (two tasks, two allocations) - modify L3 cache and put in the same group
    runner._measurement_runner._node.get_tasks.return_value = [t1, t2]
    runner._allocator.allocate.return_value = \
        {
            t1.task_id: {
                AllocationType.QUOTA: 0.7,
                AllocationType.RDT: RDTAllocation(name='one_group', l3='L3:0=00fff')
            },
            t2.task_id: {
                AllocationType.QUOTA: 0.8,
                AllocationType.RDT: RDTAllocation(name='one_group', l3='L3:0=00fff')
            }
        }, [], []
    runner._measurement_runner._iterate()

    got_allocations_metrics = runner._allocations_storage.store.call_args[0][0]

    assert_metric(got_allocations_metrics, 'allocations_count', expected_metric_value=4)
    # ... and metrics for task t1 ...
    assert_metric(got_allocations_metrics, 'allocation_cpu_quota', dict(task=t1.task_id), 0.7)
    assert_metric(got_allocations_metrics, 'allocation_cpu_quota', dict(task=t2.task_id), 0.8)
    assert_metric(got_allocations_metrics, 'allocation_rdt_l3_cache_ways',
                  dict(task=t1.task_id, group_name='one_group'), 12)  # 00fff=12
    assert_metric(got_allocations_metrics, 'allocation_rdt_l3_cache_ways',
                  dict(task=t1.task_id, group_name='one_group'), 12)  # 00fff=12
