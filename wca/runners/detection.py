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
import logging
import time
from typing import Dict, List, Optional

from wca.config import Numeric, Str, assure_type
from wca import nodes, storage, detectors
from wca.detectors import convert_anomalies_to_metrics, \
    update_anomalies_metrics_with_task_information, Anomaly
from wca.metrics import Metric, MetricType
from wca.profiling import profiler
from wca.runners.measurement import MeasurementRunner, TaskLabelGenerator
from wca.storage import MetricPackage, DEFAULT_STORAGE

log = logging.getLogger(__name__)


class AnomalyStatistics:

    def __init__(self):
        self._anomaly_last_occurrence = None
        self._anomaly_counter = 0

    def validate(self, anomalies: List[Anomaly]):
        assure_type(anomalies, List[Anomaly])

    def get_metrics(self, anomalies: List[Anomaly]) -> List[Metric]:
        """Extra external plugin anomaly statistics."""

        self.validate(anomalies)

        if len(anomalies):
            self._anomaly_last_occurrence = time.time()
            self._anomaly_counter += len(anomalies)

        statistics_metrics = [
            Metric(name='anomaly_count', type=MetricType.COUNTER, value=self._anomaly_counter),
        ]
        if self._anomaly_last_occurrence:
            statistics_metrics.extend([
                Metric(name='anomaly_last_occurrence', type=MetricType.COUNTER,
                       value=self._anomaly_last_occurrence),
            ])
        return statistics_metrics


class DetectionRunner(MeasurementRunner):
    """DetectionRunner extends MeasurementRunner with ability to callback Detector,
    serialize received anomalies and storing them in anomalies_storage.

    Arguments:
        node: component used for tasks discovery
        metrics_storage: storage to store platform, internal, resource and task metrics
            (defaults to DEFAULT_STORAGE/LogStorage to output for standard error)
        anomalies_storage: storage to store serialized anomalies and extra metrics
            (defaults to DEFAULT_STORAGE/LogStorage to output for standard error)
        action_delay: iteration duration in seconds (None disables wait and iterations)
            (defaults to 1 second)
        rdt_enabled: enables or disabled support for RDT monitoring and allocation
            (defaults to None(auto) based on platform capabilities)
        extra_labels: additional labels attached to every metric
            (defaults to empty dict)
        event_names: perf counters to monitor
            (defaults to instructions, cycles, cache-misses, memstalls)
        enable_derived_metrics: enable derived metrics ips, ipc and cache_hit_ratio
            (based on enabled_event names), default to False
    """

    def __init__(
            self,
            node: nodes.Node,
            detector: detectors.AnomalyDetector,
            metrics_storage: storage.Storage = DEFAULT_STORAGE,
            anomalies_storage: storage.Storage = DEFAULT_STORAGE,
            action_delay: Numeric(0, 60) = 1.,
            rdt_enabled: Optional[bool] = None,
            extra_labels: Dict[Str, Str] = None,
            event_names: Optional[List[str]] = None,
            enable_derived_metrics: bool = False,
            tasks_label_generator: Dict[str, TaskLabelGenerator] = None,
    ):
        super().__init__(node, metrics_storage,
                         action_delay, rdt_enabled,
                         extra_labels, event_names,
                         enable_derived_metrics, tasks_label_generator)
        self._detector = detector

        # Anomaly.
        self._anomalies_storage = anomalies_storage
        self._anomalies_statistics = AnomalyStatistics()

    def _iterate_body(self, containers, platform, tasks_measurements,
                      tasks_resources, tasks_labels, common_labels):
        """Detector callback body."""

        # Call Detector's detect function.
        detection_start = time.time()
        anomalies, extra_metrics = self._detector.detect(
            platform, tasks_measurements, tasks_resources, tasks_labels)
        detection_duration = time.time() - detection_start
        profiler.register_duration('detect', detection_duration)
        log.debug('Anomalies detected: %d', len(anomalies))

        # Prepare anomaly metrics
        anomaly_metrics = convert_anomalies_to_metrics(anomalies, tasks_labels)
        update_anomalies_metrics_with_task_information(anomaly_metrics, tasks_labels)

        # Prepare and send all output (anomalies) metrics.
        anomalies_package = MetricPackage(self._anomalies_storage)
        anomalies_package.add_metrics(
            anomaly_metrics,
            extra_metrics,
            self._anomalies_statistics.get_metrics(anomalies)
        )
        anomalies_package.send(common_labels)
