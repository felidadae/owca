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

"""
The module contains high level tests of the project.
The classes derived from BaseRunnerMixin class are tested.
"""

from unittest.mock import patch, Mock, call

import pytest

from owca import platforms
from owca import storage
from owca.allocators import Allocator, AllocationType, AllocationConfiguration
from owca.detectors import AnomalyDetector
from owca.mesos import MesosNode, sanitize_mesos_label
from owca.metrics import Metric, MetricType
from owca.resctrl import RDTAllocation
from owca.runners.allocation import convert_to_allocations_values, AllocationRunner
from owca.runners.detection import DetectionRunner
from owca.testing import anomaly_metrics, anomaly, task, container, metric, allocation_metric

platform_mock = Mock(
    spec=platforms.Platform, sockets=1,
    rdt_cbm_mask='fffff', rdt_min_cbm_bits=1, rdt_mb_control_enabled=False, rdt_num_closids=2)


@pytest.mark.parametrize('tasks_allocations,expected_errors', [
    ({'tx': {'cpu_shares': 3}}, ["task_id 'tx' not found (ctx='tx.cpu_shares')"]),
    ({'cpu_shares': 3}, ['expected context to be task_id/allocation_type got cpu_shares']),
    ({'t1': {'wrong_type': 5}}, ["unknown allocation type 'wrong_type' on t1.wrong_type"]),
    ({'t1_task_id': {'rdt': RDTAllocation()},
      't2_task_id': {'rdt': RDTAllocation()},
      't3_task_id': {'rdt': RDTAllocation()}},
     ["for task='t1_task_id' - too many closids(3)!",
      "for task='t2_task_id' - too many closids(3)!",
      'some errors during creation',
      'too many closids(3)!']),
])
def test_convert_invalid_task_allocations(tasks_allocations, expected_errors):
    allocation_configuration = AllocationConfiguration()
    containers = {task('/t1'): container('/t1'),
                  task('/t2'): container('/t2'),
                  task('/t3'): container('/t3'),
                  }
    got_allocations_values = convert_to_allocations_values(
        tasks_allocations, containers, platform_mock, allocation_configuration)
    errors, got_allocations_values = got_allocations_values.validate()
    assert errors == expected_errors


# We are mocking objects used by containers.
@patch('owca.platforms.collect_platform_information', return_value=(
        platform_mock, [metric('platform-cpu-usage')], {}))
@patch('owca.testing._create_uuid_from_tasks_ids', return_value='fake-uuid')
@patch('owca.detectors._create_uuid_from_tasks_ids', return_value='fake-uuid')
@patch('owca.runners.base.are_privileges_sufficient', return_value=True)
@patch('owca.containers.ResGroup')
@patch('owca.containers.PerfCounters')
@patch('owca.platforms.collect_topology_information', return_value=(1, 1, 1))
@patch('owca.containers.Cgroup.get_measurements', return_value=dict(cpu_usage=23))
@patch('time.time', return_value=1234567890.123)
def test_detection_runner_containers_state(*mocks):
    """Tests proper interaction between runner instance and functions for
    creating anomalies and calculating the desired state.

    Also tests labelling of metrics during iteration loop.
    """

    # Task labels
    task_labels = {
        'org.apache.aurora.metadata.application': 'redis',
        'org.apache.aurora.metadata.load_generator': 'rpc-perf',
        'org.apache.aurora.metadata.name': 'redis--6792',
    }
    task_labels_sanitized = {
        sanitize_mesos_label(label_key): label_value
        for label_key, label_value
        in task_labels.items()
    }
    task_labels_sanitized_with_task_id = {'task_id': 't1_task_id'}
    task_labels_sanitized_with_task_id.update(task_labels_sanitized)

    # Node mock
    node_mock = Mock(spec=MesosNode, get_tasks=Mock(return_value=[
        task('/t1', resources=dict(cpus=8.), labels=task_labels)]))

    # Storage mocks
    metrics_storage = Mock(spec=storage.Storage, store=Mock())
    anomalies_storage = Mock(spec=storage.Storage, store=Mock())

    # Detector mock - simulate returning one anomaly and additional metric
    detector_mock = Mock(
        spec=AnomalyDetector,
        detect=Mock(
            return_value=(
                [anomaly(
                    'task1', ['task2'], metrics=[
                        metric('contention_related_metric')
                    ]
                )],  # one anomaly + related metric
                [metric('bar')]  # one extra metric
            )
        )
    )

    extra_labels = dict(el='ev')  # extra label with some extra value

    runner = DetectionRunner(
        node=node_mock,
        metrics_storage=metrics_storage,
        anomalies_storage=anomalies_storage,
        detector=detector_mock,
        rdt_enabled=False,
        extra_labels=extra_labels,
    )

    # Mock to finish after one iteration.
    runner.wait_or_finish = Mock(return_value=False)

    runner.run()

    # store() method was called twice:
    # 1. Before calling detect() to store state of the environment.
    assert metrics_storage.store.call_args[0][0] == [
        Metric('owca_up', type=MetricType.COUNTER, value=1234567890.123, labels=extra_labels),
        Metric('owca_tasks', type=MetricType.GAUGE, value=1, labels=extra_labels),
        metric('platform-cpu-usage', labels=extra_labels),  # Store metrics from platform ...
        Metric(name='cpu_usage', value=23,
               labels=dict(extra_labels, **task_labels_sanitized_with_task_id)),
    ]

    # 2. After calling detect to store information about detected anomalies.
    expected_anomaly_metrics = anomaly_metrics('task1', ['task2'])
    for m in expected_anomaly_metrics:
        m.labels.update(extra_labels)

    expected_anomaly_metrics.extend([
        metric('contention_related_metric',
               labels=dict({'uuid': 'fake-uuid', 'type': 'anomaly'}, **extra_labels)),
        metric('bar', extra_labels),
        Metric('anomaly_count', type=MetricType.COUNTER, value=1, labels=extra_labels),
        Metric('anomaly_last_occurence', type=MetricType.COUNTER, value=1234567890.123,
               labels=extra_labels),
        Metric(name='detect_duration', value=0.0, labels={'el': 'ev'}, type=MetricType.GAUGE),
    ])
    anomalies_storage.store.assert_called_once_with(expected_anomaly_metrics)

    # Check that detector was called with proper arguments.
    detector_mock.detect.assert_called_once_with(
        platform_mock,
        {'t1_task_id': {'cpu_usage': 23}},
        {'t1_task_id': {'cpus': 8}},
        {'t1_task_id': task_labels_sanitized_with_task_id}
    )

    # assert expected state (new container based on first task /t1)
    assert (runner.containers_manager.containers ==
            {task('/t1', resources=dict(cpus=8.), labels=task_labels): container('/t1')})

    runner.wait_or_finish.assert_called_once()


@patch('time.time', return_value=1234567890.123)
@patch('owca.platforms.collect_topology_information', return_value=(1, 1, 1))
@patch('owca.platforms.collect_platform_information', return_value=(
        platform_mock, [metric('platform-cpu-usage')], {}))
@patch('owca.runners.base.are_privileges_sufficient', return_value=True)
@patch('owca.runners.allocation.AllocationRunner.configure_rdt', return_value=True)
@patch('owca.containers.PerfCounters')
@patch('owca.cgroups.Cgroup.get_measurements', return_value=dict(cpu_usage=23))
@patch('owca.cgroups.Cgroup.get_pids', return_value=['123'])
@patch('owca.cgroups.Cgroup.set_normalized_quota')
@patch('owca.cgroups.Cgroup.set_normalized_shares')
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
                                 AllocationType.RDT: RDTAllocation(name='', l3='L3:0=fffff')}
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
        {'t1_task_id': {'cpus': 8}},
        {'t1_task_id': {'task_id': 't1_task_id'}},
        {'t1_task_id': initial_tasks_allocations},
    )

    runner.node.assert_has_calls([call.get_tasks()])
    metrics_storage_mock.store.assert_called_once()
    anomalies_storage_mock.store.assert_called_once()
    allocations_storage_mock.store.assert_called_once()

    # [0][0] means all arguments [0][0][0] means first of plain arguments
    assert allocations_storage_mock.store.call_args_list[0][0][0] == [
        Metric(name='allocation', value=0.5,
               labels={'allocation_type': 'cpu_quota', 'container_name': 't1'},
               type='gauge'),
        Metric(name='allocation', value=4,
               labels={'allocation_type': 'rdt_l3_cache_ways',
                       'group_name': 't1', 'domain_id': '0', 'container_name': 't1'},
               type='gauge'),
        Metric(name='allocation', value=0xf,
               labels={'allocation_type': 'rdt_l3_mask',
                       'group_name': 't1', 'domain_id': '0', 'container_name': 't1'},
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
        Metric(name='allocation', value=0.5,
               labels={'allocation_type': 'cpu_quota', 'container_name': 't1'},
               type='gauge'),
        Metric(name='allocation', value=4,
               labels={'allocation_type': 'rdt_l3_cache_ways',
                       'group_name': 't1', 'domain_id': '0', 'container_name': 't1'},
               type='gauge'),
        Metric(name='allocation', value=15,
               labels={'allocation_type': 'rdt_l3_mask',
                       'group_name': 't1', 'domain_id': '0', 'container_name': 't1'},
               type='gauge'),
        # Second task allocations based on date from system
        Metric(name='allocation', value=1.,
               labels={'allocation_type': 'cpu_quota', 'container_name': 't2'},
               type='gauge'),
        Metric(name='allocation', value=20,
               labels={'allocation_type': 'rdt_l3_cache_ways',
                       'group_name': '', 'domain_id': '0', 'container_name': 't2'},
               type='gauge'),
        Metric(name='allocation', value=0xfffff,
               labels={'allocation_type': 'rdt_l3_mask', 'group_name': '',
                       'domain_id': '0', 'container_name': 't2'},
               type='gauge'),
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
        Metric(name='allocation', value=0.7, type='gauge',
               labels={'allocation_type': 'cpu_quota', 'container_name': 't1'}),
        Metric(name='allocation', value=12, type='gauge',
               labels={'allocation_type': 'rdt_l3_cache_ways',
                       'group_name': 'one_group', 'domain_id': '0', 'container_name': 't1'}),
        Metric(name='allocation', value=0xfff, type='gauge',
               labels={'allocation_type': 'rdt_l3_mask',
                       'group_name': 'one_group', 'domain_id': '0', 'container_name': 't1'}),
        # Task t2
        Metric(name='allocation', value=0.8, type='gauge',
               labels={'allocation_type': 'cpu_quota', 'container_name': 't2'}),
        Metric(name='allocation', value=12, type='gauge',
               labels={'allocation_type': 'rdt_l3_cache_ways',
                       'group_name': 'one_group', 'domain_id': '0', 'container_name': 't2'}),
        Metric(name='allocation', value=4095, type='gauge',
               labels={'allocation_type': 'rdt_l3_mask',
                       'group_name': 'one_group', 'domain_id': '0', 'container_name': 't2'}),
        # Stats
        Metric(name='allocations_count', value=4, labels={}, type='counter'),
        Metric(name='allocations_errors', value=0, labels={}, type='counter'),
        Metric(name='allocation_duration', value=0.0, labels={}, type='gauge')
    ]


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
    allocation_configuration = AllocationConfiguration()
    containers = {task('/t1'): container('/t1', resgroup_name='', with_config=True),
                  task('/t2'): container('/t2', resgroup_name='', with_config=True)}
    allocations = convert_to_allocations_values(
        tasks_allocations, containers, platform_mock, allocation_configuration)
    errors, allocations = allocations.validate()
    assert not errors
    if allocations:
        with patch('owca.resctrl.ResGroup.write_schemata') as mock, \
                patch('owca.cgroups.Cgroup._write'), patch('owca.cgroups.Cgroup._read'):
            allocations.perform_allocations()
            assert mock.call_count == expected_resgroup_reallocation_count


@pytest.mark.parametrize('tasks_allocations,expected_metrics', (
        ({}, []),
        ({'t1_task_id': {AllocationType.SHARES: 0.5}}, [
            Metric(name='allocation', value=0.5,
                   type=MetricType.GAUGE,
                   labels={'allocation_type': 'cpu_shares', 'container_name': 't1'})
        ]),
        ({'t1_task_id': {AllocationType.RDT: RDTAllocation(mb='mb:0=20')}}, [
            allocation_metric('rdt_mb', 20, group_name='t1', domain_id='0', container_name='t1')
        ]),
        ({'t1_task_id': {AllocationType.SHARES: 0.5,
                         AllocationType.RDT: RDTAllocation(mb='mb:0=20')}}, [
             Metric(
                 name='allocation', value=0.5,
                 type=MetricType.GAUGE,
                 labels={'allocation_type': AllocationType.SHARES, 'container_name': 't1'}
             ),
             allocation_metric('rdt_mb', 20, group_name='t1', domain_id='0', container_name='t1')
         ]),
        ({'t1_task_id': {
            AllocationType.SHARES: 0.5, AllocationType.RDT: RDTAllocation(mb='mb:0=30')
        },
             't2_task_id': {
                 AllocationType.QUOTA: 0.6,
                 AllocationType.RDT: RDTAllocation(name='b', l3='L3:0=f'),
             }
         }, [
             Metric(
                 name='allocation', value=0.5,
                 type=MetricType.GAUGE,
                 labels={'allocation_type': AllocationType.SHARES, 'container_name': 't1'}
             ),
             allocation_metric('rdt_mb', 30, group_name='t1', domain_id='0', container_name='t1'),
             Metric(
                 name='allocation', value=0.6,
                 type=MetricType.GAUGE,
                 labels={'allocation_type': AllocationType.QUOTA, 'container_name': 't2'}
             ),
             allocation_metric('rdt_l3_cache_ways', 4, group_name='b',
                               domain_id='0', container_name='t2'),
             allocation_metric('rdt_l3_mask', 15, group_name='b',
                               domain_id='0', container_name='t2'),
         ]),
))
def test_convert_task_allocations_to_metrics(tasks_allocations, expected_metrics):
    allocation_configuration = AllocationConfiguration()
    containers = {task('/t1'): container('/t1'),
                  task('/t2'): container('/t2'),
                  }
    allocations = convert_to_allocations_values(
        tasks_allocations, containers, platform_mock, allocation_configuration)
    errors, allocations = allocations.validate()
    assert not errors
    if allocations:
        metrics_got = allocations.generate_metrics()
    else:
        metrics_got = []
    assert metrics_got == expected_metrics
