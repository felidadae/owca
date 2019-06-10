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
import pytest

from wca import storage
from wca.detectors import AnomalyDetector, LABEL_CONTENDED_TASK_ID, \
    LABEL_CONTENDING_WORKLOAD_INSTANCE, LABEL_WORKLOAD_INSTANCE
from wca.mesos import MesosNode
from wca.runners.detection import DetectionRunner
from tests.testing import metric, anomaly, \
    assert_metric, redis_task_with_default_labels, prepare_runner_patches, \
    platform_mock, assert_subdict, TASK_CPU_USAGE


@prepare_runner_patches
@pytest.mark.parametrize('subcgroups', ([], ['/T/c1'], ['/T/c1', '/T/c2']))
def test_detection_runner(subcgroups):
    # Tasks mock
    t1 = redis_task_with_default_labels('t1', subcgroups)
    t2 = redis_task_with_default_labels('t2', subcgroups)

    # Detector mock - simulate returning one anomaly and additional metric
    detector_mock = Mock(
        spec=AnomalyDetector,
        detect=Mock(
            return_value=(
                [anomaly(
                    t1.task_id, [t2.task_id], metrics=[
                        metric('contention_related_metric')
                    ]
                )],  # one anomaly + related metric
                [metric('extra_metric_from_detector')]  # one extra metric
            )
        )
    )

    runner = DetectionRunner(
        node=Mock(spec=MesosNode, get_tasks=Mock(return_value=[t1, t2])),
        metrics_storage=Mock(spec=storage.Storage, store=Mock()),
        anomalies_storage=Mock(spec=storage.Storage, store=Mock()),
        detector=detector_mock,
        rdt_enabled=False,
        extra_labels=dict(extra_label='extra_value')  # extra label with some extra value
    )
    runner._wait = Mock()
    runner._initialize()

    # Mock to finish after one iteration.
    runner._iterate()

    got_anomalies_metrics = runner._anomalies_storage.store.mock_calls[0][1][0]

    # Check that anomaly based metrics,
    assert_metric(got_anomalies_metrics, 'anomaly', expected_metric_some_labels={
        LABEL_WORKLOAD_INSTANCE: t1.labels[LABEL_WORKLOAD_INSTANCE],
        LABEL_CONTENDED_TASK_ID: t1.task_id,
        LABEL_CONTENDING_WORKLOAD_INSTANCE: t2.labels[LABEL_WORKLOAD_INSTANCE]
    })
    assert_metric(got_anomalies_metrics, 'contention_related_metric',
                  expected_metric_some_labels=dict(extra_label='extra_value'))
    assert_metric(got_anomalies_metrics, 'extra_metric_from_detector')
    assert_metric(got_anomalies_metrics, 'anomaly_count', expected_metric_value=1)
    assert_metric(got_anomalies_metrics, 'anomaly_last_occurrence')

    # Check that detector was called with proper arguments.
    (platform, tasks_measurements,
     tasks_resources, tasks_labels) = detector_mock.detect.mock_calls[0][1]
    # Make sure that proper values are propagate to detect method for t1.
    assert platform == platform_mock
    # Measurements have to mach get_measurements mock from measurements_patch decorator.
    cpu_usage = TASK_CPU_USAGE * (len(subcgroups) if subcgroups else 1)
    assert_subdict(tasks_measurements, {t1.task_id: {'cpu_usage': cpu_usage}})
    # Labels should have extra LABEL_WORKLOAD_INSTANCE based on redis_task_with_default_labels
    # and sanitized version of other labels for mesos (without prefix).
    assert_subdict(tasks_labels, {t1.task_id: {LABEL_WORKLOAD_INSTANCE: 'redis_6792_t1'}})
    assert_subdict(tasks_labels, {t1.task_id: {'load_generator': 'rpc-perf-t1'}})
    # Resources should match resources from redis_task_with_default_labels
    assert_subdict(tasks_resources, {t1.task_id: t1.resources})

    # Check any metrics for t2
    assert_subdict(tasks_measurements, {t2.task_id: {'cpu_usage': cpu_usage}})
