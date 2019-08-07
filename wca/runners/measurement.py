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
from abc import abstractmethod
from dataclasses import dataclass
import logging
import resource
import time
from typing import Dict, List, Tuple, Optional
import re

from wca import nodes, storage, platforms, profiling
from wca import resctrl
from wca import security
from wca.allocators import AllocationConfiguration
from wca.config import Numeric, Str
from wca.containers import ContainerManager, Container
from wca.detectors import TasksMeasurements, TasksResources, TasksLabels
from wca.logger import trace, get_logging_metrics
from wca.mesos import create_metrics
from wca.metrics import Metric, MetricType, MetricName, MissingMeasurementException
from wca.nodes import Task
from wca.profiling import profiler
from wca.runners import Runner
from wca.storage import MetricPackage, DEFAULT_STORAGE

log = logging.getLogger(__name__)

_INITIALIZE_FAILURE_ERROR_CODE = 1

DEFAULT_EVENTS = (MetricName.INSTRUCTIONS, MetricName.CYCLES,
                  MetricName.CACHE_MISSES, MetricName.CACHE_REFERENCES, MetricName.MEMSTALL)


class TaskLabelGenerator:
    @abstractmethod
    def generate(self, tasks) -> None:
        """add additional labels to each task based on already existing labels"""
        ...


@dataclass
class TaskLabelRegexGenerator(TaskLabelGenerator):
    pattern: str
    repl: str
    source: str = 'task_name'  # by default use `task_name`: specially created for that purpose

    def generate(self, tasks, target) -> None:
        for task in tasks:
            source_val = task.labels.get(self.source, None)
            if source_val is None:
                err_msg = "Source label {} not found in task {}".format(self.source, task.name)
                log.warning(err_msg)
                continue
            if target in task.labels:
                err_msg = "Target label {} already existing in task {}. Skipping.".format(
                    target, task.name)
                log.debug(err_msg)
                continue
            task.labels[target] = re.sub(self.pattern, self.repl, source_val)
            if task.labels[target] == "" or task.labels[target] is None:
                log.debug('Label {} for task {} set to empty string.')
            if task.labels[target] is None:
                log.debug('Label {} for task {} set to None.')


class MeasurementRunner(Runner):
    """MeasurementRunner run iterations to collect platform, resource, task measurements
    and store them in metrics_storage component.

    Arguments:
        node: component used for tasks discovery
        metrics_storage: storage to store platform, internal, resource and task metrics
            (defaults to DEFAULT_STORAGE/LogStorage to output for standard error)
        action_delay: iteration duration in seconds (None disables wait and iterations)
            (defaults to 1 second)
        rdt_enabled: enables or disabled support for RDT monitoring
            (defaults to None(auto) based on platform capabilities)
        extra_labels: additional labels attached to every metrics
            (defaults to empty dict)
        event_names: perf counters to monitor
            (defaults to instructions, cycles, cache-misses, memstalls)
        enable_derived_metrics: enable derived metrics ips, ipc and cache_hit_ratio
            (based on enabled_event names), default to False
        task_label_generator: component to add new labels based on sanitized labels read
            from orchestrator
    """

    def __init__(
            self,
            node: nodes.Node,
            metrics_storage: storage.Storage = DEFAULT_STORAGE,
            action_delay: Numeric(0, 60) = 1.,  # [s]
            rdt_enabled: Optional[bool] = None,  # Defaults(None) - auto configuration.
            extra_labels: Dict[Str, Str] = None,
            event_names: List[str] = None,
            enable_derived_metrics: bool = False,
            tasks_label_generator: Dict[str, TaskLabelGenerator] = None,
            _allocation_configuration: Optional[AllocationConfiguration] = None,
    ):

        self._node = node
        self._metrics_storage = metrics_storage
        self._action_delay = action_delay
        self._rdt_enabled = rdt_enabled
        # Disabled by default, to be overridden by subclasses.
        self._rdt_mb_control_required = False
        # Disabled by default, to overridden by subclasses.
        self._rdt_cache_control_required = False
        self._extra_labels = extra_labels or dict()
        self._finish = False  # Guard to stop iterations.
        self._last_iteration = time.time()  # Used internally by wait function.
        self._allocation_configuration = _allocation_configuration
        self._event_names = event_names or DEFAULT_EVENTS
        self._enable_derived_metrics = enable_derived_metrics
        if tasks_label_generator is None:
            self._tasks_label_generator = {
                'application':
                    TaskLabelRegexGenerator('$', '', 'task_name'),
                'application_version_name':
                    TaskLabelRegexGenerator('.*$', '', 'task_name'),
            }
        else:
            self._tasks_label_generator = tasks_label_generator

    @profiler.profile_duration(name='sleep')
    def _wait(self):
        """Decides how long one iteration should take.
        Additionally calculate residual time, based on time already taken by iteration.
        """
        now = time.time()
        iteration_duration = now - self._last_iteration

        residual_time = max(0., self._action_delay - iteration_duration)
        time.sleep(residual_time)
        self._last_iteration = time.time()

    def _initialize(self) -> Optional[int]:
        """Check privileges, RDT availability and prepare internal state.
        Can return error code that should stop Runner.
        """
        if not security.are_privileges_sufficient(self._rdt_enabled):
            log.error("Impossible to use perf_event_open/resctrl subsystems. "
                      "You need to: adjust /proc/sys/kernel/perf_event_paranoid (set to -1); "
                      "or has CAP_DAC_OVERRIDE and CAP_SETUID capabilities set."
                      "You can run process as root too.")
            return 1

        # Initialization (auto discovery Intel RDT features).

        rdt_available = resctrl.check_resctrl()
        if self._rdt_enabled is None:
            self._rdt_enabled = rdt_available
            log.info('RDT enabled (auto configuration): %s', self._rdt_enabled)
        elif self._rdt_enabled is True and not rdt_available:
            log.error('RDT explicitly enabled but not available - exiting!')
            return 1

        if self._rdt_enabled:
            # Resctrl is enabled and available, call a placeholder to allow further initialization.
            rdt_initialization_ok = self._initialize_rdt()
            if not rdt_initialization_ok:
                return 1

        # Postpone the container manager initialization after rdt checks were performed.
        platform_cpus, _, platform_sockets = platforms.collect_topology_information()

        platform, _, _ = platforms.collect_platform_information(self._rdt_enabled)
        rdt_information = platform.rdt_information

        # We currently do not support RDT without monitoring.
        if self._rdt_enabled and not rdt_information.is_monitoring_enabled():
            log.error('RDT monitoring is required - please enable CAT '
                      'or MBM with kernel parameters!')
            return 1

        self._containers_manager = ContainerManager(
            rdt_information=rdt_information,
            platform_cpus=platform_cpus,
            platform_sockets=platform_sockets,
            allocation_configuration=self._allocation_configuration,
            event_names=self._event_names,
            enable_derived_metrics=self._enable_derived_metrics,
        )
        return None

    def _iterate(self):
        iteration_start = time.time()

        # Get information about tasks.
        tasks = self._node.get_tasks()
        log.debug('Tasks detected: %d', len(tasks))

        for task in tasks:
            sanitized_labels = dict()
            for label_key, label_value in task.labels.items():
                sanitized_labels.update({sanitize_label(label_key):
                                         label_value})
            task.labels = sanitized_labels

        # Generate new labels.
        for new_label, task_label_generator in self._tasks_label_generator.items():
            task_label_generator.generate(tasks, new_label)

        # Keep sync of found tasks and internally managed containers.
        containers = self._containers_manager.sync_containers_state(tasks)

        # Platform information
        platform, platform_metrics, platform_labels = platforms.collect_platform_information(
            self._rdt_enabled)

        # Common labels
        common_labels = dict(platform_labels, **self._extra_labels)

        # Tasks data
        tasks_measurements, tasks_resources, tasks_labels = _prepare_tasks_data(containers)
        tasks_metrics = _build_tasks_metrics(tasks_labels, tasks_measurements)

        self._iterate_body(containers, platform, tasks_measurements, tasks_resources,
                           tasks_labels, common_labels)

        self._wait()

        iteration_duration = time.time() - iteration_start
        profiling.profiler.register_duration('iteration', iteration_duration)

        # Generic metrics.
        metrics_package = MetricPackage(self._metrics_storage)
        metrics_package.add_metrics(_get_internal_metrics(tasks))
        metrics_package.add_metrics(platform_metrics)
        metrics_package.add_metrics(tasks_metrics)
        metrics_package.add_metrics(profiling.profiler.get_metrics())
        metrics_package.add_metrics(get_logging_metrics())
        metrics_package.send(common_labels)

    def run(self) -> int:
        """Loop that gathers platform and tasks metrics and calls _iterate_body.
        _iterate_body is a method to be subclassed.
        """
        error_code = self._initialize()
        if error_code is not None:
            return error_code

        while True:
            self._iterate()

            if self._finish:
                break

        # Cleanup phase.
        self._containers_manager.cleanup()
        return 0

    def _iterate_body(self, containers, platform, tasks_measurements, tasks_resources,
                      tasks_labels, common_labels):
        """No-op implementation of inner loop body - called by iterate"""

    def _initialize_rdt(self) -> bool:
        """Nothing to configure in RDT to measure resource usage.
        Returns state of rdt initialization (True ok, False for error)
        """
        return True


@profiler.profile_duration('prepare_tasks_data')
@trace(log, verbose=False)
def _prepare_tasks_data(containers: Dict[Task, Container]) -> \
        Tuple[TasksMeasurements, TasksResources, TasksLabels]:
    """Prepare all resource usage and resource allocation information and
    creates container-specific labels for all the generated metrics.
    """
    # Prepare empty structures for return all the information.
    tasks_measurements: TasksMeasurements = {}
    tasks_resources: TasksResources = {}
    tasks_labels: TasksLabels = {}

    for task, container in containers.items():
        # Task measurements and measurements based metrics.
        try:
            task_measurements = container.get_measurements()
        except MissingMeasurementException as e:
            log.warning('One or more measurements are missing '
                        'for container {} - ignoring! '
                        '(because {})'.format(container, e))
            continue

        # Prepare tasks labels based on tasks metadata labels and task id.
        task_labels = {
            sanitize_label(label_key): label_value
            for label_key, label_value
            in task.labels.items()
        }
        task_labels['task_id'] = task.task_id

        # Add additional label with cpu initial assignment, to simplify
        # management of distributed model system for plugin:
        # https://github.com/intel/platform-resource-manager/tree/master/prm
        task_labels['initial_task_cpu_assignment'] = \
            str(task.resources.get('cpus', task.resources.get('cpu_limits', "unknown")))

        # Aggregate over all tasks.
        tasks_labels[task.task_id] = task_labels
        tasks_measurements[task.task_id] = task_measurements
        tasks_resources[task.task_id] = task.resources

    return tasks_measurements, tasks_resources, tasks_labels


def _build_tasks_metrics(tasks_labels: TasksLabels,
                         tasks_measurements: TasksMeasurements) -> List[Metric]:
    tasks_metrics: List[Metric] = []

    for task_id, task_measurements in tasks_measurements.items():
        task_metrics = create_metrics(task_measurements)
        # Decorate metrics with task specific labels.
        for task_metric in task_metrics:
            task_metric.labels.update(tasks_labels[task_id])
        tasks_metrics += task_metrics
    return tasks_metrics


def _get_internal_metrics(tasks: List[Task]) -> List[Metric]:
    """Internal wca metrics e.g. memory usage, profiling information."""

    # Memory usage.
    memory_usage_rss_self = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    memory_usage_rss_children = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    memory_usage_rss = memory_usage_rss_self + memory_usage_rss_children

    metrics = [
        Metric(name='wca_up', type=MetricType.COUNTER, value=time.time()),
        Metric(name='wca_tasks', type=MetricType.GAUGE, value=len(tasks)),
        Metric(name='wca_memory_usage_bytes', type=MetricType.GAUGE,
               value=int(memory_usage_rss * 1024)),
    ]

    return metrics


MESOS_LABELS_PREFIXES_TO_DROP = ('org.apache.', 'aurora.metadata.')


def sanitize_label(label_key):
    """Removes unwanted prefixes from Aurora & Mesos e.g. 'org.apache.aurora'
    and replaces invalid characters like "." with underscore.
    """
    # Drop unwanted prefixes
    for unwanted_prefix in MESOS_LABELS_PREFIXES_TO_DROP:
        if label_key.startswith(unwanted_prefix):
            label_key = label_key.replace(unwanted_prefix, '')

    # Prometheus labels cannot contain ".".
    label_key = label_key.replace('.', '_')

    return label_key
