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
import pytest
from unittest.mock import Mock
from unittest.mock import patch

from owca import platforms
from owca import storage
from owca.detectors import AnomalyDetector
from owca.nodes import Node
from owca.mesos import sanitize_mesos_label, MesosNode
from owca.metrics import Metric, MetricType
from owca.runners.detection import DetectionRunner
from owca.testing import metric, task, anomaly, anomaly_metrics, container

platform_mock = Mock(
    spec=platforms.Platform, sockets=1,
    rdt_cbm_mask='fffff', rdt_min_cbm_bits=1, rdt_mb_control_enabled=False, rdt_num_closids=2)

CPU_USAGE=23
CPU_COUNT = 8.
TIME_TICK=1234567890.123
TASK_UUID='fake-uuid'
@patch('resource.getrusage', return_value=Mock(ru_maxrss=1234))
@patch('owca.platforms.collect_platform_information', return_value=(
        platform_mock, [metric('platform-cpu-usage')], {}))
@patch('owca.testing._create_uuid_from_tasks_ids', return_value=TASK_UUID)
@patch('owca.detectors._create_uuid_from_tasks_ids', return_value=TASK_UUID)
@patch('owca.runners.base.are_privileges_sufficient', return_value=True)
@patch('owca.containers.ResGroup')
@patch('owca.containers.PerfCounters')
@patch('owca.platforms.collect_topology_information', return_value=(1, 1, 1))
@patch('owca.containers.Cgroup.get_measurements', return_value=dict(cpu_usage=CPU_USAGE))
@patch('time.time', return_value=TIME_TICK)
@pytest.mark.parametrize('subcgroups', ([], ['/t1/c1'], ['/t1/c1', '/t1/c2']))
def test_detection_runner_containers_state(_1,_2,_3,_4,_5,_6,_7,_8,_9, _10, subcgroups):
    """Tests proper interaction between runner instance and functions for
    creating anomalies and calculating the desired state.
    Also tests labelling of metrics during iteration loop.

    Note: it both test Container and ContainerSet. In case of ContainerSet class,
    where there are more than single subcgroup the resulting metrics value for the
    task are computed as:  CPU_USAGE * len(subcgroups).
    The more general formula for both Container and ContainerSet is:
    CPU_USAGE * (len(subcgroups) if subcgroups else 1).
    """

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

    task_t1 = task(cgroup_path='/t1', subcgroups_paths=subcgroups,
                   resources=dict(cpus=CPU_COUNT), labels=task_labels)
    node_mock = Mock(spec=Node, get_tasks=Mock(return_value=[task_t1]))

    metrics_storage = Mock(spec=storage.Storage, store=Mock())
    anomalies_storage = Mock(spec=storage.Storage, store=Mock())

    contended_task_id = 'task1'
    contending_task_ids = ['task2']
    anomaly_ = anomaly(contended_task_id=contended_task_id, contending_task_ids=contending_task_ids,
                       metrics=[metric('contention_related_metric')])
    detector_mock = Mock(spec=AnomalyDetector,
                         detect=Mock(return_value=([anomaly_], [metric('bar')])))

    extra_labels = dict(extra_label_key='extra_label_value')

    runner = DetectionRunner(node=node_mock, metrics_storage=metrics_storage,
                             anomalies_storage=anomalies_storage, detector=detector_mock,
                             rdt_enabled=False, extra_labels=extra_labels)
    # Mock to finish after one iteration.
    runner.wait_or_finish = Mock(return_value=False)

    # ----- Call run method of DetectionRunner -----
    runner.run()

    # Assert store() method was called twice. First time:
    #   1) Before calling detect() to store state of the environment.
    assert metrics_storage.store.call_args[0][0] == [
        Metric('owca_up', type=MetricType.COUNTER, value=TIME_TICK, labels=extra_labels),
        Metric('owca_tasks', type=MetricType.GAUGE, value=1, labels=extra_labels),
        Metric('owca_memory_usage_bytes', type=MetricType.GAUGE, value=2468*1024,
               labels=extra_labels),
        Metric('owca_duration_seconds', value=0.0, type='gauge',
               labels=dict(extra_labels, function='collect_platform_information'), ),
        Metric('owca_duration_seconds', value=0.0, type='gauge',
               labels=dict(extra_labels, function='get_tasks')),
        Metric('owca_duration_seconds', value=0.0, type='gauge',
               labels=dict(extra_labels, function='iteration')),
        Metric('owca_duration_seconds', value=0.0, type='gauge',
               labels=dict(extra_labels, function='prepare_task_data')),
        Metric('owca_duration_seconds', value=0.0, type='gauge',
               labels=dict(extra_labels, function='sleep')),
        Metric('owca_duration_seconds', value=0.0, type='gauge',
               labels=dict(extra_labels, function='sync')),
        metric('platform-cpu-usage', labels=extra_labels),
        Metric(name='cpu_usage', value=CPU_USAGE * (len(subcgroups) if subcgroups else 1),
               labels=dict(extra_labels, **task_labels_sanitized_with_task_id))]

    # And second time:
    #   2) After calling detect to store information about detected anomalies.
    expected_anomaly_metrics = anomaly_metrics(contended_task_id=contended_task_id,
                                               contending_task_ids=contending_task_ids)
    for m in expected_anomaly_metrics:
        m.labels.update(extra_labels)
    expected_anomaly_metrics.extend([
        metric('contention_related_metric',
               labels=dict({'uuid': TASK_UUID, 'type': 'anomaly'}, **extra_labels)),
        metric('bar', extra_labels),
        Metric('anomaly_count', type=MetricType.COUNTER, value=1, labels=extra_labels),
        Metric('anomaly_last_occurence', type=MetricType.COUNTER, value=TIME_TICK,
               labels=extra_labels),
        Metric(name='detect_duration', value=0.0, labels=extra_labels, type=MetricType.GAUGE),
    ])
    anomalies_storage.store.assert_called_once_with(expected_anomaly_metrics)

    # Assert that detector was called with proper arguments.
    detector_mock.detect.assert_called_once_with(
        platform_mock,
        {'t1_task_id': {'cpu_usage': CPU_USAGE * (len(subcgroups) if subcgroups else 1)}},
        {'t1_task_id': {'cpus': CPU_COUNT}},
        {'t1_task_id': task_labels_sanitized_with_task_id})

    # Assert expected state of runner.containers_manager (new container based on first task /t1).
    assert len(runner.containers_manager.containers) == 1
    task_, container_ = list(runner.containers_manager.containers.items())[0]
    assert task_ == task_t1
    assert container_.get_cgroup_path() == '/t1'

    # Assert that only one iteration was done.
    runner.wait_or_finish.assert_called_once()
