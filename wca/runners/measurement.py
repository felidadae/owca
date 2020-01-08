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

import re
import resource
from abc import abstractmethod
from dataclasses import dataclass

from wca import platforms, profiling
from wca import resctrl
from wca import security
from wca.allocators import AllocationConfiguration
from wca.config import Numeric, Str
from wca.containers import ContainerManager, Container
from wca.detectors import TaskData, TasksData, TaskResource
from wca.logger import trace, get_logging_metrics, TRACE
from wca.metrics import Metric, MetricName, MissingMeasurementException, \
    export_metrics_from_measurements, METRICS_METADATA, MetricSource, MetricType, MetricUnit, \
    MetricGranularity, MetricMetadata
from wca.nodes import Node, Task
from wca.nodes import TaskSynchronizationException
from wca.perf import check_perf_event_count_limit, filter_out_event_names_for_cpu
from wca.perf_uncore import UncorePerfCounters, _discover_pmu_uncore_config, \
    UNCORE_IMC_EVENTS, PMUNotAvailable, UncoreDerivedMetricsGenerator, \
    UNCORE_UPI_EVENTS
from wca.profiling import profiler
from wca.runners import Runner
from wca.storage import DEFAULT_STORAGE, MetricPackage, Storage

log = logging.getLogger(__name__)

_INITIALIZE_FAILURE_ERROR_CODE = 1


class TaskLabelGenerator:
    @abstractmethod
    def generate(self, task: Task) -> Optional[str]:
        """Generate new label value based on `task` object
        (e.g. based on other label value or one of task resource).
        `task` input parameter should not be modified."""
        ...


@dataclass
class TaskLabelRegexGenerator(TaskLabelGenerator):
    """
    Generate new label value based on other label value.
    """
    pattern: str
    repl: str
    source: str = 'task_name'  # by default use `task_name`

    def __post_init__(self):
        # Verify whether syntax for pattern and repl is correct.
        re.sub(self.pattern, self.repl, "")

    def generate(self, task: Task) -> Optional[str]:
        source_val = task.labels.get(self.source, None)
        if source_val is None:
            err_msg = "Source label {} not found in task {}".format(self.source, task.name)
            log.warning(err_msg)
            return None
        return re.sub(self.pattern, self.repl, source_val)


@dataclass
class TaskLabelResourceGenerator(TaskLabelGenerator):
    """Add label based on initial resource assignment of a task."""
    resource_name: str

    def generate(self, task: Task) -> Optional[str]:
        return str(task.resources.get(self.resource_name, "unknown"))


class MeasurementRunner(Runner):
    """rst

    MeasurementRunner run iterations to collect platform, resource, task measurements
    and store them in metrics_storage component.

    - `node`: **type**:

        Component used for tasks discovery.

    - ``metrics_storage``: **type** = `DEFAULT_STORAGE`

        Storage to store platform, internal, resource and task metrics.
        (defaults to DEFAULT_STORAGE/LogStorage to output for standard error)

    - ``interval``: **Numeric(0,60)** = *1.*

        Iteration duration in seconds (None disables wait and iterations).
        (defaults to 1 second)

    - ``rdt_enabled``: **Optional[bool]** = *None*

        Enables or disabled support for RDT monitoring.
        (defaults to None(auto) based on platform capabilities)

    - ``gather_hw_mm_topology``: **Optional[bool]** = *None*

        Gather hardware/memory topology based on lshw and ipmctl.
        (defaults to None(auto) based on lshw and ipmctl binaries availability)

    - ``extra_labels``: **Optional[Dict[Str, Str]]** = *None*

        Additional labels attached to every metrics.
        (defaults to empty dict)

    - ``event_names``: **List[str]** = `[]`

        Perf counters to monitor.
        (defaults to not collect perf counters - empty list of events)

    - ``perf_aggregate_cpus``: **bool** = `True`

        Should perf events collected for cgroups be aggregated (sum) by CPUs.
        (defaults to true, to limit number of exposed metrics)

    - ``enable_derived_metrics``: **bool** = *False*

        Enable derived metrics ips, ipc and cache_hit_ratio.
        (based on enabled_event names, default to False)

    - ``enable_perf_uncore``: **bool** = *None*

        Enable perf event uncore metrics.
        (defaults to None - automatic, if available enable)

    - ``task_label_generators``: **Optional[Dict[str, TaskLabelGenerator]]** = *None*

        Component to generate additional labels for tasks.
        (optional)

    - ``allocation_configuration``: **Optional[AllocationConfiguration]** = *None*

        Allows fine grained control over allocations.
        (defaults to AllocationConfiguration() instance)

    - ``wss_reset_interval``: **int** = *0*

        Interval of resetting WSS (WorkingSetSize).
        (defaults to 0, which means that metric is not collected, e.g. when set to 1
        ``clear_refs`` will be reset every measurement iteration defined by ``interval`` option.)

    - ``include_optional_labels``: **bool** = *False*

        Attach following labels to all metrics:
        `sockets`, `cores`, `cpus`, `cpu_model`, `cpu_model_number` and `wca_version`
        (defaults to False)
    """

    def __init__(
            self,
            node: Node,
            metrics_storage: Storage = DEFAULT_STORAGE,
            interval: Numeric(0, 60) = 1.,
            rdt_enabled: Optional[bool] = None,
            gather_hw_mm_topology: Optional[bool] = None,
            extra_labels: Optional[Dict[Str, Str]] = None,
            event_names: List[str] = [],
            perf_aggregate_cpus: bool = True,
            enable_derived_metrics: bool = False,
            enable_perf_uncore: Optional[bool] = None,
            task_label_generators: Optional[Dict[str, TaskLabelGenerator]] = None,
            allocation_configuration: Optional[AllocationConfiguration] = None,
            wss_reset_interval: int = 0,
            include_optional_labels: bool = False
    ):

        self._node = node
        self._metrics_storage = metrics_storage
        self._interval = interval
        self._rdt_enabled = rdt_enabled
        self._gather_hw_mm_topology = gather_hw_mm_topology
        self._include_optional_labels = include_optional_labels

        self._extra_labels = {k: str(v) for k, v in
                              extra_labels.items()} if extra_labels else dict()
        log.debug('Extra labels: %r', self._extra_labels)
        self._finish = False  # Guard to stop iterations.
        self._last_iteration = time.time()  # Used internally by wait function.
        self._allocation_configuration = allocation_configuration
        self._event_names = event_names
        self._perf_aggregate_cpus = perf_aggregate_cpus

        # TODO: fix those workarounds for dynamic levels and dynamic perf event metrics.
        # First add dynamic metrics
        for event_name in event_names:
            # is dynamic raw event
            if '__r' in event_name:
                log.debug('Creating metadata for dynamic metric: %r', event_name)
                METRICS_METADATA[event_name] = MetricMetadata(
                    'Hardware PMU counter (raw event)',
                    MetricType.COUNTER,
                    MetricUnit.NUMERIC,
                    MetricSource.PERF_SUBSYSTEM_WITH_CGROUPS,
                    MetricGranularity.TASK,
                    [],
                    'no (event_names)',
                )
        # We had the modify levels for all metrics
        # The set proper levels based on perf_aggregate_cpus value
        if not perf_aggregate_cpus:
            log.debug('Enabling "cpu" level for PERF_SUBSYSTEM_WITH_CGROUPS and derived metrics.')
            for metric_metadata in METRICS_METADATA.values():
                if metric_metadata.source == MetricSource.PERF_SUBSYSTEM_WITH_CGROUPS:
                    metric_metadata.levels = ['cpu']
                if metric_metadata.source == MetricSource.DERIVED_PERF_WITH_CGROUPS:
                    metric_metadata.levels = ['cpu']

        self._enable_derived_metrics = enable_derived_metrics
        self._enable_perf_uncore = enable_perf_uncore

        self._task_label_generators = task_label_generators or {}

        self._wss_reset_interval = wss_reset_interval

        self._uncore_pmu = None

        self._initialize_rdt_callback = None
        self._iterate_body_callback = None

    def _set_initialize_rdt_callback(self, func):
        self._initialize_rdt_callback = func

    def _set_iterate_body_callback(self, func):
        self._iterate_body_callback = func

    @profiler.profile_duration(name='sleep')
    def _wait(self):
        """Decides how long one iteration should take.
        Additionally calculate residual time, based on time already taken by iteration.
        """
        now = time.time()
        iteration_duration = now - self._last_iteration

        residual_time = max(0., self._interval - iteration_duration)
        time.sleep(residual_time)
        self._last_iteration = time.time()

    def _initialize(self) -> Optional[int]:
        """Check RDT availability, privileges and prepare internal state.
        Can return error code that should stop Runner.
        """

        # Initialization (auto discovery Intel RDT features).
        rdt_available = resctrl.check_resctrl()
        if self._rdt_enabled is None:
            self._rdt_enabled = rdt_available
            log.info('RDT enabled (auto configuration): %s', self._rdt_enabled)
        elif self._rdt_enabled is True and not rdt_available:
            log.error('RDT explicitly enabled but not available - exiting!')
            return 1

        # _allocation_configuration is set in allocation mode (AllocationRunner)
        # so we need access to write in cgroups.
        write_to_cgroup = self._allocation_configuration is not None
        use_resctrl = self._rdt_enabled
        use_perf = len(self._event_names) > 0

        if not security.are_privileges_sufficient(write_to_cgroup, use_resctrl, use_perf):
            return 1

        if self._rdt_enabled:
            # Resctrl is enabled and available, call a placeholder to allow further initialization.
            # For MeasurementRunner it's nothing to configure in RDT to measure resource usage.

            # Check if it's needed to specific rdt initialization in case
            # of using MeasurementRunner functionality in other runner.
            if self._initialize_rdt_callback is not None:
                rdt_initialization_ok = self._initialize_rdt_callback()

                if not rdt_initialization_ok:
                    return 1

        log.debug('rdt_enabled: %s', self._rdt_enabled)
        log.debug('gather_hw_mm_topology: %s', self._gather_hw_mm_topology)
        platform, _, _ = platforms.collect_platform_information(
            self._rdt_enabled,
            gather_hw_mm_topology=self._gather_hw_mm_topology
        )
        rdt_information = platform.rdt_information

        self._event_names = filter_out_event_names_for_cpu(
            self._event_names, platform.cpu_codename)

        log.info('Enabling %i perf events (for cgroups).', len(self._event_names))
        log.debug('Enabling perf events: %s', ', '.join(self._event_names))
        # Check and assume most popular number of available number of HW counters.
        if self._event_names:
            if not check_perf_event_count_limit(self._event_names, platform.cpus, platform.cores):
                return 1

        # We currently do not support RDT without monitoring.
        if self._rdt_enabled and not rdt_information.is_monitoring_enabled():
            log.error('RDT monitoring is required - please enable CAT '
                      'or MBM with kernel parameters!')
            return 1

        self._containers_manager = ContainerManager(
            platform=platform,
            allocation_configuration=self._allocation_configuration,
            event_names=self._event_names,
            enable_derived_metrics=self._enable_derived_metrics,
            wss_reset_interval=self._wss_reset_interval,
            perf_aggregate_cpus=self._perf_aggregate_cpus
        )

        self._init_uncore_pmu(self._enable_derived_metrics, self._enable_perf_uncore, platform)

        return None

    def _init_uncore_pmu(self, enable_derived_metrics, enable_perf_uncore,
                         platform: platforms.Platform):
        strict_mode = enable_perf_uncore is True
        _enable_perf_uncore = enable_perf_uncore in (True, None)
        self._uncore_pmu = None
        self._uncore_get_measurements = lambda: {}
        if _enable_perf_uncore:
            pmu_events = {}
            try:
                # Cpus and events for perf uncore imc
                cpus_imc, pmu_events_imc = _discover_pmu_uncore_config(
                    UNCORE_IMC_EVENTS, 'uncore_imc_')
                pmu_events.update(pmu_events_imc)
                # Cpus and events for perf uncore upi
                cpus_upi, pmu_events_upi = _discover_pmu_uncore_config(
                    UNCORE_UPI_EVENTS, 'uncore_upi_')
                pmu_events.update(pmu_events_upi)

                cpus = list(set(cpus_imc + cpus_upi))

            except PMUNotAvailable as e:
                self._uncore_pmu = None
                self._uncore_get_measurements = lambda: {}
                if strict_mode:
                    raise
                else:
                    log.warning('Perf pmu metrics requested, but not available. '
                                'Not collecting perf pmu metrics! '
                                'error={}'.format(e))
                    return

            # Prepare uncore object
            self._uncore_pmu = UncorePerfCounters(
                cpus=cpus,
                pmu_events=pmu_events,
                platform=platform,
            )

            # Wrap with derived..
            if enable_derived_metrics:
                self._uncore_derived_metrics = UncoreDerivedMetricsGenerator(
                    self._uncore_pmu.get_measurements)
                self._uncore_get_measurements = self._uncore_derived_metrics.get_measurements
            else:
                self._uncore_get_measurements = self._uncore_pmu.get_measurements

    def _iterate(self):
        iteration_start = time.time()

        # Get information about tasks.
        try:
            tasks = self._node.get_tasks()
        except TaskSynchronizationException as e:
            log.error('Cannot synchronize tasks with node (error=%s) - skip this iteration!', e)
            self._wait()
            return

        append_additional_labels_to_tasks(self._task_label_generators, tasks)
        log.debug('Tasks detected: %d', len(tasks))

        # Keep sync of found tasks and internally managed containers.
        containers = self._containers_manager.sync_containers_state(tasks)
        log.log(TRACE, 'Tasks container mapping:\n%s', '\n'.join(
            ['%s(%s)  =  %s' % (task.name, task.task_id, container._cgroup_path) for task, container
             in containers.items()]))

        # @TODO why not in platform module?
        extra_platform_measurements = self._uncore_get_measurements()

        # Platform information
        platform, platform_metrics, platform_labels = platforms.collect_platform_information(
            self._rdt_enabled, self._gather_hw_mm_topology,
            extra_platform_measurements=extra_platform_measurements,
            include_optional_labels=False,
        )

        # Common labels
        common_labels = dict(platform_labels, **self._extra_labels)

        try:
            tasks_data = _prepare_tasks_data(containers)
        except MissingMeasurementException as e:
            log.error('Cannot synchronize tasks measurements (error=%s) - skip this iteration!', e)
            self._wait()
            return

        # Inject other runners code.
        if self._iterate_body_callback is not None:
            self._iterate_body_callback(containers, platform, tasks_data, common_labels)

        self._wait()

        iteration_duration = time.time() - iteration_start
        profiling.profiler.register_duration('iteration', iteration_duration)

        # Generic metrics.
        metrics_package = MetricPackage(self._metrics_storage)
        metrics_package.add_metrics(_get_internal_metrics(tasks))
        metrics_package.add_metrics(platform_metrics)
        metrics_package.add_metrics(_build_tasks_metrics(tasks_data))
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


def append_additional_labels_to_tasks(task_label_generators: Dict[str, TaskLabelGenerator],
                                      tasks: List[Task]) -> None:
    for task in tasks:
        # Add labels uniquely identifying a task.
        task.labels['task_id'] = task.task_id
        task.labels['task_name'] = task.name

        # Generate new labels based on formula inputted by a user (using TasksLabelGenerator).
        for target, task_label_generator in task_label_generators.items():
            if target in task.labels:
                err_msg = "Target label {} already existing in task {}. Skipping.".format(
                    target, task.name)
                log.debug(err_msg)
                continue
            val = task_label_generator.generate(task)
            if val is None:
                log.debug('Label {} for task {} not set, as its value is None.'
                          .format(target, task.name))
            else:
                if val == "":
                    log.debug('Label {} for task {} set to empty string.'.format(target, task.name))
                task.labels[target] = val


@profiler.profile_duration('prepare_tasks_data')
@trace(log, verbose=False)
def _prepare_tasks_data(containers: Dict[Task, Container]) -> TasksData:
    """Prepare all resource usage and resource allocation information and
    creates container-specific labels for all the generated metrics.
    """
    # Prepare empty structure for return all the information.
    tasks_data: TasksData = {}
    now = time.time()

    for task, container in containers.items():
        # Task measurements and measurements based metrics.
        try:
            task_measurements = container.get_measurements()
        except MissingMeasurementException as e:
            log.warning('One or more measurements are missing '
                        'for container {} - ignoring! '
                        '(because {})'.format(container, e))
            raise
        # Extra internal metrics
        task_measurements[MetricName.TASK_UP.value] = 1
        task_measurements[MetricName.TASK_LAST_SEEN.value] = now

        # Extra metrics from orchestrator about resources
        if TaskResource.CPUS in task.resources:
            task_measurements[MetricName.TASK_REQUESTED_CPUS.value] = task.resources[
                TaskResource.CPUS.value]
        if TaskResource.MEM in task.resources:
            task_measurements[MetricName.TASK_REQUESTED_MEM_BYTES.value] = task.resources[
                TaskResource.MEM.value]

        tasks_data[task.task_id] = TaskData(
            name=task.name,
            task_id=task.task_id,
            cgroup_path=task.cgroup_path,
            subcgroups_paths=task.subcgroups_paths,
            labels=task.labels,
            resources=task.resources,
            measurements=task_measurements
        )

    return tasks_data


def _build_tasks_metrics(tasks_data: TasksData) -> List[Metric]:
    """Build metrics for all tasks."""
    tasks_metrics: List[Metric] = []

    for task, data in tasks_data.items():
        task_metrics = export_metrics_from_measurements(data.measurements)

        # Decorate metrics with task specific labels.
        for task_metric in task_metrics:
            task_metric.labels.update(data.labels)

        tasks_metrics += task_metrics

    return tasks_metrics


def _get_internal_metrics(tasks: List[Task]) -> List[Metric]:
    """Internal wca metrics e.g. memory usage, profiling information."""

    # Memory usage.
    memory_usage_rss_self = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    memory_usage_rss_children = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    memory_usage_rss = memory_usage_rss_self + memory_usage_rss_children

    metrics = [
        Metric.create_metric_with_metadata(MetricName.WCA_UP, value=time.time()),
        Metric.create_metric_with_metadata(MetricName.WCA_TASKS, value=len(tasks)),
        Metric.create_metric_with_metadata(MetricName.WCA_MEM_USAGE_BYTES,
                                           value=int(memory_usage_rss * 1024)),
    ]

    return metrics
