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


import hashlib
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import List, Dict

from owca.metrics import Metric, Measurements, MetricType
from owca.nodes import TaskId
from owca.platforms import Platform


# Mapping from task to its measurements.
TasksMeasurements = Dict[TaskId, Measurements]
TasksResources = Dict[TaskId, Dict[str, float]]
TasksLabels = Dict[TaskId, Dict[str, str]]


class ContendedResource(str, Enum):

    MEMORY_BW = 'memory bandwidth'
    LLC = 'cache'
    CPUS = 'cpus'
    TDP = 'thermal design power'
    UNKN = 'unknown resource'


def _create_uuid_from_tasks_ids(task_ids: List[TaskId]):
    """Returns unique identifier based on combination of tasks_ids."""
    # Assumption here that, it is enough to just take
    # 16bytes of 64 for unique different tasks combinations.
    sha256 = hashlib.sha256(','.join(sorted(task_ids)).encode('utf-8')).digest()
    return str(uuid.UUID(bytes=sha256[:16]))


class Anomaly(ABC):

    @abstractmethod
    def generate_metrics(self) -> List[Metric]:
        ...


@dataclass
class ContentionAnomaly(Anomaly):

    resource: ContendedResource
    contended_task_id: TaskId
    contending_task_ids: List[TaskId]

    # List of metrics describing context of contention
    metrics: List[Metric]

    # Type of anomaly (will be used to label anomaly metrics)
    anomaly_type = 'contention'

    def generate_metrics(self):
        """Encodes contention anomaly as list of metrics.

        Anomaly of multiple tasks together, will be encode as many metrics.
        Note, it can return more metrics that provided anomalies because it is necessary
        to encode relation in this way.
        For example:
        anomaly = ContentionAnomaly(
            resource=ContendedResource.LLC,
            contended_task_id='task1',
            contending_task_ids=['task2', 'task3'],
            metrics=[Metrics(name='cpi', type='gauge', value=10)],
        )

        wile be encoded as two metrics of type counters:

        metrics = [
            Metric(name='anomaly', type='counter', value=1,
                labels=dict(
                    uuid="1234",
                    contended_task_id="task1",
                    contending_task_id='task2',
                    type="contention"))
            Metric(name='anomaly', type='counter', value=1,
                labels=dict(
                    uuid="1234",
                    contended_task_id="task1",
                    contending_task_id='task3',
                    type="contention"))
            Metrics(name='cpi', type='gauge', value=10,
                labels=dict(type='anomaly', uuid="1234", contended_task_id="task1"))
        ]

        Note, that contention related metrics will get additional labels (type and uuid).

        Effectively being encoded as in Prometheus format:

        # HELP anomaly ...
        # TYPE anomaly counter
        anomaly{type="contention", contended_task_id="task1", contending_task_ids="task2",  resource="cache", uuid="1234"} 1 # noqa
        anomaly{type="contention", contended_task_id="task1", contending_task_ids="task3", resource="cache", uuid="1234"} 1 # noqa
        cpi{contended_task_id="task1", uuid="1234", type="anomaly"} 10
        """
        metrics = []
        for task_id in self.contending_task_ids:
            metrics.append(
                Metric(
                    name='anomaly',
                    value=1,
                    type=MetricType.COUNTER,
                    labels=dict(
                        contended_task_id=self.contended_task_id,
                        contending_task_id=task_id,
                        resource=self.resource,
                        uuid=self._uuid(),
                        type=self.anomaly_type,
                    )
                )
            )

        # Mark contention related metrics with two labels: uuid and type='anomaly'.
        for metric in self.metrics:
            metric.labels.update(
                uuid=self._uuid(),
                type='anomaly'
            )

        return metrics + self.metrics

    def _uuid(self):
        """Returns unique identifier based on combination of tasks_ids."""
        return _create_uuid_from_tasks_ids([self.contended_task_id] + self.contending_task_ids)


class AnomalyDetector(ABC):

    @abstractmethod
    def detect(
            self,
            platform: Platform,
            tasks_measurements: TasksMeasurements,
            tasks_resources: TasksResources,
            tasks_labels: TasksLabels
            ) -> (List[Anomaly], List[Metric]):
        ...


class NOPAnomalyDetector(AnomalyDetector):

    def detect(self, platform, tasks_measurements, tasks_resources, tasks_labels):
        return [], []


def convert_anomalies_to_metrics(anomalies: List[Anomaly]) -> List[Metric]:
    """Takes anomalies on input and convert them to something that can be
    stored persistently adding help/type fields and labels.
    """
    metrics = []
    for anomaly in anomalies:
        metrics.extend(anomaly.generate_metrics())

    return metrics
