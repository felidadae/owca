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
from unittest.mock import patch, call

from owca import platforms
from owca import storage
from owca.allocators import AllocationType, RDTAllocation, Allocator
from owca.mesos import MesosNode
from owca.metrics import Metric
from owca.runners.allocation import AllocationRunner
from owca.testing import metric, task

platform_mock = Mock(
    spec=platforms.Platform, sockets=1,
    rdt_cbm_mask='fffff', rdt_min_cbm_bits=1, rdt_mb_control_enabled=False, rdt_num_closids=2)

@patch('time.time', return_value=1234567890.123)
@patch('owca.platforms.collect_topology_information', return_value=(1, 1, 1))
@patch('owca.platforms.collect_platform_information', return_value=(
        platform_mock, [metric('platform-cpu-usage')], {}))
@patch('owca.runners.base.are_privileges_sufficient', return_value=True)
@patch('owca.runners.allocation.AllocationRunner.configure_rdt', return_value=True)
@patch('resource.getrusage', return_value=Mock(ru_maxrss=1234))
@patch('owca.containers.PerfCounters')
@patch('owca.cgroups.Cgroup.get_measurements', return_value=dict(cpu_usage=23))
@patch('owca.cgroups.Cgroup.get_pids', return_value=['123'])
@patch('owca.cgroups.Cgroup.set_quota')
@patch('owca.cgroups.Cgroup.set_shares')
@patch('owca.resctrl.ResGroup.add_pids')
@patch('owca.resctrl.ResGroup.remove')
@patch('owca.resctrl.ResGroup.get_measurements')
@patch('owca.resctrl.ResGroup.get_mon_groups')
@patch('owca.resctrl.ResGroup.write_schemata')
@patch('owca.resctrl.read_mon_groups_relation', return_value={'': []})
@patch('owca.detectors._create_uuid_from_tasks_ids', return_value='fake-uuid')
@patch('owca.testing._create_uuid_from_tasks_ids', return_value='fake-uuid')
def test_allocation_runner_containers_state(*mocks):
    """ Low level system calls are not mocked - but higher level objects and functions:
        Cgroup, Resgroup, Platform, etc. Thus the test do not cover the full usage scenario
        (such tests would be much harder to write).
    """
    # Node mock.
    mesos_node_mock = Mock(spec=MesosNode,
                           get_tasks=Mock(return_value=[
                               task('/t1', resources=dict(cpus=8.), labels={})
                           ]
                           ))

    # Patch Container get_allocations
    initial_tasks_allocations = {AllocationType.QUOTA: 1.,
                                 AllocationType.RDT: RDTAllocation(name='',
                                                                   l3='L3:0=fffff',
                                                                   mb='mb:0=50')}
    patch('owca.containers.Container.get_allocations',
          return_value=initial_tasks_allocations).__enter__()

    # Storage mocks.
    metrics_storage_mock = Mock(spec=storage.Storage, store=Mock())
    anomalies_storage_mock = Mock(spec=storage.Storage, store=Mock())
    allocations_storage_mock = Mock(spec=storage.Storage, store=Mock())

    # Allocator mock (lower the quota and number of cache ways in dedicated group).
    new_t1_allocations = {AllocationType.QUOTA: .5,
                          AllocationType.RDT: RDTAllocation(name=None, l3='L3:0=0000f')}
    allocations = {'t1_task_id': new_t1_allocations}
    allocator_mock = Mock(spec=Allocator, allocate=Mock(return_value=(allocations, [], [])))

    # Patch some of the functions of AllocationRunner.
    runner = AllocationRunner(
        node=mesos_node_mock,
        metrics_storage=metrics_storage_mock,
        anomalies_storage=anomalies_storage_mock,
        allocations_storage=allocations_storage_mock,
        rdt_enabled=True,
        ignore_privileges_check=True,
        allocator=allocator_mock,
        extra_labels={},
    )
    runner.wait_or_finish = Mock(return_value=False)

    ############
    # First run.
    runner.run()

    # Check whether allocate run with proper arguments.
    # [0][0] means all arguments
    assert runner.allocator.allocate.call_args_list[0][0] == (
        platform_mock,
        {'t1_task_id': {'cpu_usage': 23}},
        {'t1_task_id': {'cpus': 8.0}},
        {'t1_task_id': {'task_id': 't1_task_id'}},
        {'t1_task_id': initial_tasks_allocations},
    )

    runner.node.assert_has_calls([call.get_tasks()])
    metrics_storage_mock.store.assert_called_once()
    anomalies_storage_mock.store.assert_called_once()
    allocations_storage_mock.store.assert_called_once()

    # [0][0] means all arguments [0][0][0] means first of plain arguments
    assert allocations_storage_mock.store.call_args_list[0][0][0] == [
        Metric(name='allocation_cpu_quota', value=0.5,
               labels={'allocation_type': 'cpu_quota', 'container_name': 't1',
                       'task': 't1_task_id'},
               type='gauge'),
        Metric(name='allocation_rdt_l3_cache_ways', value=4,
               labels={'allocation_type': 'rdt_l3_cache_ways',
                       'group_name': 't1', 'domain_id': '0', 'container_name': 't1',
                       'task': 't1_task_id'},
               type='gauge'),
        Metric(name='allocation_rdt_l3_mask', value=0xf,
               labels={'allocation_type': 'rdt_l3_mask',
                       'group_name': 't1', 'domain_id': '0', 'container_name': 't1',
                       'task': 't1_task_id'},
               type='gauge'),
        Metric(name='allocations_count', value=1, labels={}, type='counter'),
        Metric(name='allocations_errors', value=0, labels={}, type='counter'),
        Metric(name='allocation_duration', value=0.0, labels={}, type='gauge')
    ]

    ############################
    # Second run (more tasks t2)
    mesos_node_mock.get_tasks.return_value = [
        task('/t1', resources=dict(cpus=8.), labels={}),
        task('/t2', resources=dict(cpus=9.), labels={})
    ]
    runner.run()

    assert allocations_storage_mock.store.call_args[0][0] == [
        # First tasks allocations after explict set
        Metric(name='allocation_cpu_quota', value=0.5,
               labels={'allocation_type': 'cpu_quota', 'container_name': 't1',
                       'task': 't1_task_id'},
               type='gauge'),
        Metric(name='allocation_rdt_l3_cache_ways', value=4,
               labels={'allocation_type': 'rdt_l3_cache_ways',
                       'group_name': 't1', 'domain_id': '0', 'container_name': 't1',
                       'task': 't1_task_id'},
               type='gauge'),
        Metric(name='allocation_rdt_l3_mask', value=15,
               labels={'allocation_type': 'rdt_l3_mask',
                       'group_name': 't1', 'domain_id': '0', 'container_name': 't1',
                       'task': 't1_task_id'},
               type='gauge'),
        # Second task allocations based on date from system
        Metric(name='allocation_cpu_quota', value=1.,
               labels={'allocation_type': 'cpu_quota', 'container_name': 't2',
                       'task': 't2_task_id'},
               type='gauge'),
        Metric(name='allocation_rdt_l3_cache_ways', value=20,
               labels={'allocation_type': 'rdt_l3_cache_ways',
                       'group_name': '', 'domain_id': '0', 'container_name': 't2',
                       'task': 't2_task_id'},
               type='gauge'),
        Metric(name='allocation_rdt_l3_mask', value=0xfffff,
               labels={'allocation_type': 'rdt_l3_mask', 'group_name': '',
                       'domain_id': '0', 'container_name': 't2', 'task': 't2_task_id'},
               type='gauge'),
        Metric(name='allocation_rdt_mb', value=50,
               labels={'allocation_type': 'rdt_mb',
                       'group_name': '', 'domain_id': '0', 'container_name': 't2',
                       'task': 't2_task_id'}, type='gauge'),
        Metric(name='allocations_count', value=2, labels={}, type='counter'),
        Metric(name='allocations_errors', value=0, labels={}, type='counter'),
        Metric(name='allocation_duration', value=0.0, labels={}, type='gauge')
    ]

    ############
    # Third run - modify L3 cache and put in the same group
    runner.allocator.allocate.return_value = \
        {
            't1_task_id': {
                AllocationType.QUOTA: 0.7,
                AllocationType.RDT: RDTAllocation(name='one_group', l3='L3:0=00fff')
            },
            't2_task_id': {
                AllocationType.QUOTA: 0.8,
                AllocationType.RDT: RDTAllocation(name='one_group', l3='L3:0=00fff')
            }
        }, [], []
    runner.run()

    assert allocations_storage_mock.store.call_args[0][0] == [
        # Task t1
        Metric(name='allocation_cpu_quota', value=0.7, type='gauge',
               labels={'allocation_type': 'cpu_quota', 'container_name': 't1',
                       'task': 't1_task_id'}),
        Metric(name='allocation_rdt_l3_cache_ways', value=12, type='gauge',
               labels={'allocation_type': 'rdt_l3_cache_ways',
                       'group_name': 'one_group', 'domain_id': '0', 'container_name': 't1',
                       'task': 't1_task_id'}),
        Metric(name='allocation_rdt_l3_mask', value=0xfff, type='gauge',
               labels={'allocation_type': 'rdt_l3_mask',
                       'group_name': 'one_group', 'domain_id': '0', 'container_name': 't1',
                       'task': 't1_task_id'}),
        # Task t2
        Metric(name='allocation_cpu_quota', value=0.8, type='gauge',
               labels={'allocation_type': 'cpu_quota', 'container_name': 't2',
                       'task': 't2_task_id'}),
        Metric(name='allocation_rdt_l3_cache_ways', value=12, type='gauge',
               labels={'allocation_type': 'rdt_l3_cache_ways',
                       'group_name': 'one_group', 'domain_id': '0', 'container_name': 't2',
                       'task': 't2_task_id'}),
        Metric(name='allocation_rdt_l3_mask', value=4095, type='gauge',
               labels={'allocation_type': 'rdt_l3_mask',
                       'group_name': 'one_group', 'domain_id': '0', 'container_name': 't2',
                       'task': 't2_task_id'}),
        # Stats
        Metric(name='allocations_count', value=4, labels={}, type='counter'),
        Metric(name='allocations_errors', value=0, labels={}, type='counter'),
        Metric(name='allocation_duration', value=0.0, labels={}, type='gauge')
    ]
