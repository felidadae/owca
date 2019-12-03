# Copyright (c) 2019 Intel Corporation
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
from typing import Dict, Callable, Any, List

from wca import platforms
from wca import resctrl
from wca.allocations import AllocationsDict, InvalidAllocations, AllocationValue, \
    MissingAllocationException
from wca.allocators import TasksAllocations, AllocationConfiguration, AllocationType, Allocator, \
    TaskAllocations, RDTAllocation
from wca.cgroups_allocations import QuotaAllocationValue, SharesAllocationValue, \
    CPUSetCPUSAllocationValue, CPUSetMemoryMigrateAllocationValue, CPUSetMEMSAllocationValue, \
    MigratePagesAllocationValue
from wca.config import assure_type
from wca.containers import ContainerInterface, Container
from wca.detectors import convert_anomalies_to_metrics, \
    update_anomalies_metrics_with_task_information, Anomaly, TasksData
from wca.kubernetes import have_tasks_qos_label, are_all_tasks_of_single_qos
from wca.metrics import Metric, MetricType
from wca.nodes import Task
from wca.resctrl_allocations import (RDTAllocationValue, RDTGroups,
                                     normalize_mb_string,
                                     validate_l3_string)
from wca.runners import Runner
from wca.runners.detection import AnomalyStatistics
from wca.runners.measurement import MeasurementRunner
from wca.storage import MetricPackage, DEFAULT_STORAGE, Storage

log = logging.getLogger(__name__)

# Helper type to have a mapping from type to callable that creates proper AllocationValue.
# Used by Allocation to AllocationValue converters. First argument is a raw (simple value)
# and third (dict) is an common_labels.
RegistryType = Dict[AllocationType, Callable[[Any, Container, dict], AllocationValue]]


class TaskAllocationsValues(AllocationsDict):
    """Subclass of generic AllocationsDict that is dedicated to be used only for specific case
    at second level mapping between, task and and its allocations.
    Provides an staticmethod as constructor.
    """

    @staticmethod
    def create(task_allocations: TaskAllocations,
               container: Container,
               registry: RegistryType,
               common_labels: Dict[str, str]) -> 'TaskAllocationsValues':
        """Factory function for TaskAllocationsValues based on raw task_allocations
        and container, registry and common_labels.

        Registry is used to map specific kinds of allocations to proper constructors.
        """
        simple_dict = {}
        for allocation_type, raw_value in task_allocations.items():
            if allocation_type not in registry:
                raise InvalidAllocations('unsupported allocation type: %r' % allocation_type)
            constructor = registry[allocation_type]
            allocation_value = constructor(raw_value, container, common_labels)
            simple_dict[allocation_type] = allocation_value
        return TaskAllocationsValues(simple_dict)


class TasksAllocationsValues(AllocationsDict):
    """Subclass of AllocationsDict that is dedicate to be used only for specific case
    of first level mapping between, many tasks and TaskAllocationsValues.
    Provides an staticmethod as constructor.
    """

    @staticmethod
    def create(rdt_enabled: bool, tasks_allocations: TasksAllocations, containers, platform) \
            -> 'TasksAllocationsValues':
        """Convert plain raw object TasksAllocations to boxed intelligent AllocationsDict
        that can be serialized to metrics, validated and can perform contained allocations.

        Beneath simple tasks allocations objects are augmented using data
        from runner: containers and platform to provide context
        to implement their responsibilities.

        Additionally local object rdt_groups is created to limit number of created RDTGroups
        and optimize writes for schemata file.
        """
        # Shared object to optimize schemata write and detect CLOSids exhaustion.

        registry = {
            AllocationType.QUOTA: QuotaAllocationValue,
            AllocationType.SHARES: SharesAllocationValue,
            AllocationType.CPUSET_CPUS: CPUSetCPUSAllocationValue,
            AllocationType.CPUSET_MEMS: CPUSetMEMSAllocationValue,
            AllocationType.CPUSET_MEMORY_MIGRATE: CPUSetMemoryMigrateAllocationValue,
            AllocationType.MIGRATE_PAGES: MigratePagesAllocationValue,
        }

        if rdt_enabled:
            assert platform.rdt_information.num_closids is not None, 'invalid platform rdt init'
            rdt_groups = RDTGroups(closids_limit=platform.rdt_information.num_closids)

            def rdt_allocation_value_constructor(rdt_allocation: RDTAllocation,
                                                 container: ContainerInterface,
                                                 common_labels: Dict[str, str]):
                return RDTAllocationValue(
                    container.get_name(),
                    rdt_allocation,
                    container.get_resgroup(),
                    container.get_pids,
                    platform.sockets,
                    platform.rdt_information,
                    common_labels=common_labels,
                    rdt_groups=rdt_groups,
                )

            registry[AllocationType.RDT] = rdt_allocation_value_constructor

        task_id_to_containers = {task.task_id: container for task, container in containers.items()}
        task_id_to_labels = {task.task_id: task.labels for task, container in containers.items()}

        simple_dict = {}
        for task_id, task_allocations in tasks_allocations.items():
            if task_id not in task_id_to_containers:
                raise InvalidAllocations('invalid task id %r' % task_id)
            else:
                container = task_id_to_containers[task_id]
                # Check consistency of container with RDT state.
                assert (container._platform.rdt_information is not None) == rdt_enabled
                extra_labels = dict(container_name=container.get_name(), task=task_id)
                extra_labels.update(task_id_to_labels[task_id])
                allocation_value = TaskAllocationsValues.create(
                    task_allocations, container, registry, extra_labels)
                allocation_value.validate()
                simple_dict[task_id] = allocation_value

        return TasksAllocationsValues(simple_dict)


def validate_shares_allocation_for_kubernetes(tasks: List[Task], allocations: TasksAllocations):
    """Additional allocations validation step needed only for Kubernetes."""
    # Ignore if not KubernetesNode.
    if not have_tasks_qos_label(tasks):
        return

    if not are_all_tasks_of_single_qos(tasks):
        for task_id, allocation in allocations.items():
            if AllocationType.SHARES in allocation:
                raise InvalidAllocations('not all tasks are of the same Kubernetes QOS class '
                                         'and at least one of the allocation contains '
                                         'cpu share. Mixing QoS classes and shares allocation '
                                         'is not supported.')


class AllocationRunner(Runner):
    """Runner is responsible for getting information about tasks from node,
    calling allocate() callback on allocator, performing returning allocations
    and storing all allocation related metrics in allocations_storage.

    Because Allocator interface is also detector, we store serialized detected anomalies
    in anomalies_storage and all other measurements in metrics_storage.

    Arguments:
        measurement_runner: Measurement runner object.
        allocator: Component that provides allocation logic.
        anomalies_storage: Storage to store serialized anomalies and extra metrics.
            (defaults to DEFAULT_STORAGE/LogStorage to output for standard error)
        allocations_storage: Storage to store serialized resource allocations.
            (defaults to DEFAULT_STORAGE/LogStorage to output for standard error)
        rdt_mb_control_required: Indicates that MB control is required,
            if the platform does not support this feature the WCA will exit.
        rdt_cache_control_required: Indicates tha L3 control is required,
            if the platform does not support this feature the WCA will exit.
        remove_all_resctrl_groups (bool): Remove all RDT controls groups upon starting.
            (defaults to False)
    """

    def __init__(
            self,
            measurement_runner: MeasurementRunner,
            allocator: Allocator,
            allocations_storage: Storage = DEFAULT_STORAGE,
            anomalies_storage: Storage = DEFAULT_STORAGE,
            rdt_mb_control_required: bool = False,
            rdt_cache_control_required: bool = False,
            remove_all_resctrl_groups: bool = False
    ):

        if not measurement_runner._allocation_configuration:
            measurement_runner._allocation_configuration = AllocationConfiguration()

        self._measurement_runner = measurement_runner

        # Allocation specific.
        self._allocator = allocator
        self._allocations_storage = allocations_storage

        self._rdt_mb_control_required = rdt_mb_control_required
        self._rdt_cache_control_required = rdt_cache_control_required

        # Anomaly.
        self._anomalies_storage = anomalies_storage
        self._anomalies_statistics = AnomalyStatistics()

        # Internal allocation statistics
        self._allocations_counter = 0
        self._allocations_errors = 0

        self._remove_all_resctrl_groups = remove_all_resctrl_groups

        self._measurement_runner._set_iterate_body_callback(self._iterate_body)
        self._measurement_runner._set_initialize_rdt_callback(self._initialize_rdt)

    def run(self) -> int:
        self._measurement_runner.run()

    def _initialize_rdt(self) -> bool:
        platform, _, _ = platforms.collect_platform_information()

        # Cache control check.
        if self._rdt_cache_control_required and \
                not platform.rdt_information.rdt_cache_control_enabled:
            # Wanted unavailable feature - halt
            log.error('RDT cache control enabled but is not supported by platform!')
            return False

        # MB control check.
        if self._rdt_mb_control_required and \
                not platform.rdt_information.rdt_mb_control_enabled:
            # Some wanted unavailable feature - halt.
            log.error('RDT memory bandwidth enabled but '
                      'allocation is not supported by platform!')
            return False

        # Prepare initial values for L3, MB...
        root_rdt_l3, root_rdt_mb = resctrl.get_max_rdt_values(
            platform.rdt_information.cbm_mask,
            platform.sockets,
            platform.rdt_information.rdt_mb_control_enabled,
            platform.rdt_information.rdt_cache_control_enabled
        )

        # ...override max values with values from allocation configuration
        if self._measurement_runner._allocation_configuration.default_rdt_l3 is not None and \
                platform.rdt_information.rdt_cache_control_enabled:
            root_rdt_l3 = self._measurement_runner._allocation_configuration.default_rdt_l3
        if self._measurement_runner._allocation_configuration.default_rdt_mb is not None and \
                platform.rdt_information.rdt_mb_control_enabled:
            root_rdt_mb = self._measurement_runner._allocation_configuration.default_rdt_mb

        try:
            if root_rdt_l3 is not None:
                validate_l3_string(root_rdt_l3, platform.sockets,
                                   platform.rdt_information.cbm_mask,
                                   platform.rdt_information.min_cbm_bits)

            if root_rdt_mb is not None:
                normalized_root_rdt_mb = normalize_mb_string(
                    root_rdt_mb,
                    platform.sockets,
                    platform.rdt_information.mb_min_bandwidth,
                    platform.rdt_information.mb_bandwidth_gran)
                resctrl.cleanup_resctrl(
                    root_rdt_l3, normalized_root_rdt_mb, self._remove_all_resctrl_groups)
            else:
                resctrl.cleanup_resctrl(
                    root_rdt_l3, root_rdt_mb, self._remove_all_resctrl_groups)
        except InvalidAllocations as e:
            log.error('Cannot initialize RDT subsystem: %s', e)
            return False

        return True

    def _iterate_body(self,
                      containers, platform,
                      tasks_data: TasksData,
                      common_labels):
        """Allocator callback body."""

        current_allocations = _get_tasks_allocations(containers)

        _update_tasks_data_with_allocations(tasks_data, current_allocations)

        # Allocator callback
        allocate_start = time.time()
        new_allocations, anomalies, extra_metrics = self._allocator.allocate(
            platform, tasks_data)
        allocate_duration = time.time() - allocate_start

        # Validate callback output
        _validate_allocate_return_vals(new_allocations, anomalies, extra_metrics)

        log.debug('Anomalies detected: %d', len(anomalies))
        log.debug('Current allocations: %s', current_allocations)

        # Create context aware allocations objects for current allocations.
        current_allocations_values = TasksAllocationsValues.create(
            self._measurement_runner._rdt_enabled, current_allocations,
            self._measurement_runner._containers_manager.containers, platform)

        # Handle allocations: calculate changeset and target allocations.
        allocations_changeset_values = None
        target_allocations_values = current_allocations_values
        try:
            # Special validation step needed for Kubernetes.
            validate_shares_allocation_for_kubernetes(tasks=containers.keys(),
                                                      allocations=new_allocations)

            # Create and validate context aware allocations objects for new allocations.
            log.debug('New allocations: %s', new_allocations)
            new_allocations_values = TasksAllocationsValues.create(
                self._measurement_runner._rdt_enabled, new_allocations,
                self._measurement_runner._containers_manager.containers, platform)
            new_allocations_values.validate()

            # Calculate changeset and target_allocations.
            if new_allocations_values is not None:
                target_allocations_values, allocations_changeset_values = \
                    new_allocations_values.calculate_changeset(current_allocations_values)
                target_allocations_values.validate()

            self._allocations_counter += len(new_allocations)

        except InvalidAllocations as e:
            # Handle any allocation validation error.
            # Log errors and restore current to generate proper metrics.
            log.error('Invalid allocations: %s', str(e))
            log.warning('Ignoring all allocations in this iteration due to validation error!')
            self._allocations_errors += 1
            target_allocations_values = current_allocations_values

        # Handle allocations: perform allocations based on changeset.
        if allocations_changeset_values:
            log.debug('Allocations changeset: %s', allocations_changeset_values)
            log.info('Performing allocations on %d tasks.', len(
                allocations_changeset_values))
            allocations_changeset_values.perform_allocations()

        # Prepare anomaly metrics.
        anomaly_metrics = convert_anomalies_to_metrics(anomalies, tasks_data)
        update_anomalies_metrics_with_task_information(anomaly_metrics, tasks_data)

        # Store anomalies information
        anomalies_package = MetricPackage(self._anomalies_storage)
        anomalies_package.add_metrics(
            anomaly_metrics,
            extra_metrics,
            self._anomalies_statistics.get_metrics(anomalies)
        )
        anomalies_package.send(common_labels)

        # Prepare allocations metrics.
        allocations_metrics = target_allocations_values.generate_metrics()
        allocations_statistic_metrics = _get_allocations_statistics_metrics(
            self._allocations_counter, self._allocations_errors, allocate_duration)

        # Store allocations metrics.
        allocations_package = MetricPackage(self._allocations_storage)
        allocations_package.add_metrics(
            allocations_metrics,
            extra_metrics,
            allocations_statistic_metrics,
        )
        allocations_package.send(common_labels)


def _get_tasks_allocations(containers) -> TasksAllocations:
    tasks_allocations = {}
    for task, container in containers.items():
        try:
            tasks_allocations[task.task_id] = container.get_allocations()
        except MissingAllocationException as e:
            log.warning('One or more allocations are missing for '
                        'container {} - ignoring! '
                        '(because {})'.format(container, e))
            continue

    return tasks_allocations


def _get_allocations_statistics_metrics(allocations_count, allocations_errors, allocation_duration):
    """Extra external plugin allocations statistics."""

    metrics = [
        Metric(name='allocations_count', type=MetricType.COUNTER,
               value=allocations_count),
        Metric(name='allocations_errors', type=MetricType.COUNTER,
               value=allocations_errors),
    ]

    if allocation_duration is not None:
        metrics.extend([
            Metric(name='allocation_duration', type=MetricType.GAUGE,
                   value=allocation_duration)
        ])

    return metrics


def _validate_allocate_return_vals(
        tasks: TasksAllocations, anomalies: List[Anomaly], metrics: List[Metric]):
    assure_type(tasks, TasksAllocations)
    assure_type(anomalies, List[Anomaly])
    assure_type(metrics, List[Metric])


def _update_tasks_data_with_allocations(tasks_data: TasksData,
                                        current_allocations: TaskAllocations):
    for task, data in tasks_data.items():
        if task in current_allocations:
            data.allocations = current_allocations[task]
