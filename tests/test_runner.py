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


from unittest.mock import patch, Mock

from owca.runner import DetectionRunner
from owca.mesos import MesosNode, sanitize_mesos_label
from owca import storage
from owca import platforms
from owca.metrics import Metric, MetricType
from owca.detectors import AnomalyDetector
from owca.testing import anomaly_metrics, anomaly, task
from tests.test_containers import container, metric


# We are mocking objects used by containers.
@patch('owca.testing._create_uuid_from_tasks_ids', return_value='fake-uuid')
@patch('owca.detectors._create_uuid_from_tasks_ids', return_value='fake-uuid')
@patch('owca.runner.are_privileges_sufficient', return_value=True)
@patch('owca.containers.ResGroup')
@patch('owca.containers.PerfCounters')
@patch('owca.platforms.collect_topology_information', return_value=(1, 1, 1))
@patch('owca.containers.Cgroup.get_measurements', return_value=dict(cpu_usage=23))
@patch('time.time', return_value=1234567890.123)
def test_runner_containers_state(*mocks):
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
    task_labels_sanitized_with_task_id = {'task_id': 'task-id-/t1'}
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

    platform_mock = Mock(spec=platforms.Platform)
    with patch('owca.platforms.collect_platform_information', return_value=(
            platform_mock, [metric('platform-cpu-usage')], {})):
        runner.run()

    # store() method was called twice:
    # 1. Before calling detect() to store state of the environment.
    metrics_storage.store.assert_called_once_with([
        Metric('owca_up', type=MetricType.COUNTER, value=1234567890.123, labels=extra_labels),
        Metric('owca_tasks', type=MetricType.GAUGE, value=1, labels=extra_labels),
        metric('platform-cpu-usage', labels=extra_labels),  # Store metrics from platform ...
        Metric(name='cpu_usage', value=23,
               labels=dict(extra_labels, **task_labels_sanitized_with_task_id)),
    ])  # and task

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
        {'task-id-/t1': {'cpu_usage': 23}},
        {'task-id-/t1': {'cpus': 8}},
        {'task-id-/t1': task_labels_sanitized_with_task_id}
    )

    # assert expected state (new container based on first task /t1)
    assert (runner.containers_manager.containers ==
            {task('/t1', resources=dict(cpus=8.), labels=task_labels): container('/t1')})

    runner.wait_or_finish.assert_called_once()
