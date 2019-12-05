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
from typing import List

from wca.config import assure_type
from wca.detectors import (convert_anomalies_to_metrics,
                           update_anomalies_metrics_with_task_information,
                           Anomaly, AnomalyDetector)
from wca.metrics import Metric, MetricType
from wca.profiling import profiler
from wca.runners import Runner
from wca.runners.measurement import MeasurementRunner
from wca.storage import MetricPackage, DEFAULT_STORAGE, Storage

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


class DetectionRunner(Runner):
    """rst
    DetectionRunner extends MeasurementRunner with ability to callback Detector,
    serialize received anomalies and storing them in anomalies_storage.

    - ``measurement_runner``: **MeasurementRunner**

        Measurement runner object.

    - ``allocator``: **AnomalyDetector**

        Component that provides allocation logic.

    - ``anomalies_storages``: **Storage** = *DEFAULT_STORAGE*

        Storage to store serialized anomalies.
    """

    def __init__(
            self,
            measurement_runner: MeasurementRunner,
            detector: AnomalyDetector,
            anomalies_storage: Storage = DEFAULT_STORAGE
    ):
        self._measurement_runner = measurement_runner
        self._detector = detector

        # Anomaly.
        self._anomalies_storage = anomalies_storage
        self._anomalies_statistics = AnomalyStatistics()

        self._measurement_runner._set_iterate_body_callback(self._iterate_body)

    def run(self):
        self._measurement_runner._run()

    def _iterate_body(self, containers, platform, tasks_data, common_labels):
        """Detector callback body."""

        # Call Detector's detect function.
        detection_start = time.time()
        anomalies, extra_metrics = self._detector.detect(
            platform, tasks_data)
        detection_duration = time.time() - detection_start
        profiler.register_duration('detect', detection_duration)
        log.debug('Anomalies detected: %d', len(anomalies))

        # Prepare anomaly metrics
        anomaly_metrics = convert_anomalies_to_metrics(anomalies, tasks_data)
        update_anomalies_metrics_with_task_information(anomaly_metrics, tasks_data)

        # Prepare and send all output (anomalies) metrics.
        anomalies_package = MetricPackage(self._anomalies_storage)
        anomalies_package.add_metrics(
            anomaly_metrics,
            extra_metrics,
            self._anomalies_statistics.get_metrics(anomalies)
        )
        anomalies_package.send(common_labels)
