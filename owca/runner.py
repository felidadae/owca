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
from typing import List, Dict, Optional
from abc import ABC, abstractmethod

from dataclasses import dataclass, field

from owca import detectors, nodes
from owca import logger
from owca import platforms
from owca import storage
from owca.containers import Container
from owca.detectors import (TasksMeasurements, TasksResources,
                            TasksLabels, convert_anomalies_to_metrics)
from owca.mesos import create_metrics, sanitize_mesos_label
from owca.metrics import Metric, MetricType
from owca.nodes import Task
from owca.resctrl import check_resctrl, cleanup_resctrl
from owca.security import are_privileges_sufficient

log = logging.getLogger(__name__)


def _calculate_desired_state(
        discovered_tasks: List[Task], known_containers: List[Container]
) -> (List[Task], List[Container]):
    """Prepare desired state of system by comparing actual running Mesos tasks and already
    watched containers.

    Assumptions:
    * One-to-one relationship between task and container
    * cgroup_path for task and container need to be identical to establish the relationship
    * cgroup_path is unique for each task

    :returns "list of Mesos tasks to start watching" and "orphaned containers to cleanup" (there are
    no more Mesos tasks matching those containers)
    """
    discovered_task_cgroup_paths = {task.cgroup_path for task in discovered_tasks}
    containers_cgroup_paths = {container.cgroup_path for container in known_containers}

    # Filter out containers which are still running according to Mesos agent.
    # In other words pick orphaned containers.
    containers_to_delete = [container for container in known_containers
                            if container.cgroup_path not in discovered_task_cgroup_paths]

    # Filter out tasks which are monitored using "Container abstraction".
    # In other words pick new, not yet monitored tasks.
    new_tasks = [task for task in discovered_tasks
                 if task.cgroup_path not in containers_cgroup_paths]

    return new_tasks, containers_to_delete


class Runner(ABC):
    """Base class for main loop run that is started by main entrypoint."""

    @abstractmethod
    def run(self):
        ...


@dataclass
class DetectionRunner(Runner):
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

    def __post_init__(self):
        self.containers: Dict[Task, Container] = {}
        self.anomaly_counter: int = 0
        self.anomaly_last_occurence: Optional[int] = None

    def wait_or_finish(self):
        """Decides how long one run takes and when to finish.
        TODO: handle graceful shutdown on signal
        """
        time.sleep(self.action_delay)
        return True

    def _sync_containers_state(self, tasks):
        """Sync internal state of runner by removing orphaned containers, and creating containers
        for newly arrived tasks, and synchronizing containers' state.

        Function is responsible for cleaning or initializing measurements stateful subsystems
        and their external resources, e.g.:
        - perf counters opens file descriptors for counters,
        - resctrl (ResGroups) creates and manages directories under resctrl fs and scarce "clsid"
            hardware identifiers

        """
        # Find difference between discovered Mesos tasks and already watched containers.
        new_tasks, containers_to_cleanup = _calculate_desired_state(
            tasks, list(self.containers.values()))

        if containers_to_cleanup:
            log.debug('state: cleaning up %d containers', len(containers_to_cleanup))
            log.log(logger.TRACE, 'state: containers_to_cleanup=%r', containers_to_cleanup)

        # Cleanup and remove orphaned containers (cleanup).
        for container_to_cleanup in containers_to_cleanup:
            container_to_cleanup.cleanup()
        self.containers = {task: container
                           for task, container in self.containers.items()
                           if task in tasks}

        if new_tasks:
            log.debug('state: found %d new tasks', len(new_tasks))
            log.log(logger.TRACE, 'state: new_tasks=%r', new_tasks)

        # Create new containers and store them.
        for new_task in new_tasks:
            self.containers[new_task] = Container(new_task.cgroup_path,
                                                  rdt_enabled=self.rdt_enabled)

        # Sync state of individual containers.
        for container in self.containers.values():
            container.sync()

    @logger.trace(log)
    def run(self):
        if self.rdt_enabled and not check_resctrl():
            return
        elif not self.rdt_enabled:
            log.warning('Rdt disabled. Skipping collecting measurements '
                        'and resctrl synchronization')
        else:
            # Resctrl is enabled and available - cleanup previous runs.
            cleanup_resctrl()

        if not are_privileges_sufficient():
            log.critical("Impossible to use perf_event_open. You need to: adjust "
                         "/proc/sys/kernel/perf_event_paranoid; or has CAP_DAC_OVERRIDE capability"
                         " set. You can run process as root too. See man 2 perf_event_open for "
                         "details.")
            return

        while True:
            # Collect information about tasks running on node.
            tasks = self.node.get_tasks()

            # Keep sync of found tasks and internally managed containers.
            self._sync_containers_state(tasks)

            # Owca internal metrics.
            internal_metrics = [
                Metric(name='owca_up', type=MetricType.COUNTER, value=time.time()),
                Metric(name='owca_tasks', type=MetricType.GAUGE, value=len(tasks)),
            ]

            # Platform information
            platform, platform_metrics, platform_labels = platforms.collect_platform_information()

            # Common labels
            common_labels = dict(platform_labels, **self.extra_labels)

            # Update platform_metrics with common labels.
            for metric in platform_metrics + internal_metrics:
                metric.labels.update(common_labels)

            # Build labeled tasks_metrics and task_metrics_values.
            tasks_measurements: TasksMeasurements = {}
            tasks_resources: TasksResources = {}
            tasks_labels: TasksLabels = {}
            tasks_metrics: List[Metric] = []
            for task, container in self.containers.items():
                # Single task data
                task_measurements = container.get_measurements()
                task_metrics = create_metrics(task_measurements)
                # Prepare tasks labels based on Mesos tasks metadata labels and task id.
                task_labels = {
                    sanitize_mesos_label(label_key): label_value
                    for label_key, label_value
                    in task.labels.items()
                }
                task_labels['task_id'] = task.task_id

                # Task scoped label decoration.
                for task_metric in task_metrics:
                    task_metric.labels.update(common_labels)
                    task_metric.labels.update(task_labels)

                # Aggregate over all tasks.
                tasks_labels[task.task_id] = task_labels
                tasks_measurements[task.task_id] = task_measurements
                tasks_resources[task.task_id] = task.resources
                tasks_metrics += task_metrics

            self.metrics_storage.store(platform_metrics + tasks_metrics + internal_metrics)

            anomalies, extra_metrics = self.detector.detect(
                platform, tasks_measurements, tasks_resources, tasks_labels)

            log.debug('Anomalies detected: %d', len(anomalies))

            # Note: anomaly metrics include metrics found in ContentionAnomaly.metrics.
            anomaly_metrics = convert_anomalies_to_metrics(anomalies)

            for anomaly_metric in anomaly_metrics:
                # Extra labels for anomaly metrics for information about task.
                if 'contended_task_id' in anomaly_metric.labels:  # Only for anomaly metrics.
                    contended_task_id = anomaly_metric.labels['contended_task_id']
                    anomaly_metric.labels.update(
                        tasks_labels.get(contended_task_id, {})
                    )

            # Extra anomaly statistics
            if len(anomalies):
                self.anomaly_last_occurence = time.time()
                self.anomaly_counter += len(anomalies)

            statistics_metrics = [
                Metric(name='anomaly_count', type=MetricType.COUNTER, value=self.anomaly_counter),
            ]
            if self.anomaly_last_occurence:
                statistics_metrics.extend([
                    Metric(name='anomaly_last_occurence', type=MetricType.COUNTER,
                           value=self.anomaly_last_occurence),
                ])

            # Update anomaly & extra metrics with common labels.
            for metric in anomaly_metrics + extra_metrics + statistics_metrics:
                metric.labels.update(common_labels)

            self.anomalies_storage.store(anomaly_metrics + extra_metrics + statistics_metrics)

            if not self.wait_or_finish():
                break

        # cleanup
        for container in self.containers.values():
            container.cleanup()
