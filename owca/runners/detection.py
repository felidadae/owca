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
from typing import Dict

from dataclasses import dataclass, field

from owca import nodes, storage, detectors
from owca.detectors import convert_anomalies_to_metrics, \
    update_anomalies_metrics_with_task_information
from owca.runners.base import Runner, BaseRunnerMixin
from owca.storage import MetricPackage

log = logging.getLogger(__name__)


@dataclass
class DetectionRunner(Runner, BaseRunnerMixin):
    """Watch over tasks running on this cluster on this node, collect observation
    and report externally (using storage) detected anomalies.
    """
    node: nodes.Node
    metrics_storage: storage.Storage
    anomalies_storage: storage.Storage
    detector: detectors.AnomalyDetector
    action_delay: float = 0.  # [s]
    rdt_enabled: bool = True
    extra_labels: Dict[str, str] = field(default_factory=dict)
    ignore_privileges_check: bool = False

    def __post_init__(self):
        BaseRunnerMixin.__init__(
            self,
            rdt_enabled=self.rdt_enabled,
            rdt_mb_control_enabled=False,
            allocation_configuration=None
        )

    def run(self):
        if not self.configure_rdt(self.rdt_enabled, self.ignore_privileges_check):
            return

        while True:
            # Prepare algorithm input data and send input based metrics.
            platform, tasks_measurements, \
                tasks_resources, tasks_labels, tasks_allocations, common_labels = \
                self._prepare_input_data_and_send_metrics_package(
                    self.node, self.metrics_storage, self.extra_labels)

            # Detector callback
            detect_start = time.time()
            anomalies, extra_metrics = self.detector.detect(
                platform, tasks_measurements, tasks_resources, tasks_labels)
            detect_duration = time.time() - detect_start
            log.debug('Anomalies detected (in %.2fs): %d', detect_duration, len(anomalies))

            # Prepare anomaly metrics
            anomaly_metrics = convert_anomalies_to_metrics(anomalies)
            update_anomalies_metrics_with_task_information(anomaly_metrics, tasks_labels)

            # Prepare and send all output (anomalies) metrics.
            anomalies_package = MetricPackage(self.anomalies_storage)
            anomalies_package.add_metrics(
                anomaly_metrics,
                extra_metrics,
                self.get_anomalies_statistics_metrics(anomalies, detect_duration)
            )
            anomalies_package.send(common_labels)

            if not self.wait_or_finish(self.action_delay):
                break

        self.cleanup()
