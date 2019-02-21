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
from typing import Dict, Callable, Any

from dataclasses import dataclass, field

from owca import nodes, storage
from owca.allocations import AllocationsDict, InvalidAllocations, AllocationValue
from owca.allocators import TasksAllocations, AllocationConfiguration, AllocationType, Allocator, \
    TaskAllocations, RDTAllocation
from owca.cgroups_allocations import QuotaAllocationValue, SharesAllocationValue
from owca.containers import Container
from owca.detectors import convert_anomalies_to_metrics, \
    update_anomalies_metrics_with_task_information
from owca.logger import trace
from owca.resctrl_allocations import RDTAllocationValue, RDTGroups
from owca.runners.base import Runner, BaseRunnerMixin
from owca.storage import MetricPackage

log = logging.getLogger(__name__)

RegistryType = Dict[AllocationType, Callable[[Any, Container, dict], AllocationValue]]


class TaskAllocationsValues(AllocationsDict):

    @staticmethod
    def create(task_allocations: TaskAllocations,
               container: Container,
               registry: RegistryType,
               common_labels: Dict[str, str]):
        simple_dict = {}
        for allocation_type, raw_value in task_allocations.items():
            if allocation_type not in registry:
                raise InvalidAllocations('unknown allocation type')
            constructor = registry[allocation_type]
            allocation_value = constructor(raw_value, container, common_labels)
            simple_dict[allocation_type] = allocation_value
        return TaskAllocationsValues(simple_dict)


class TasksAllocationsValues(AllocationsDict):

    @staticmethod
    def create(tasks_allocations: TasksAllocations, containers, platform):
        """Convert plain raw object TasksAllocations to boxed intelligent AllocationsDict
        that can be serialized to metrics, validated and perform contained allocations.

        Simple tasks allocations objects are augmented using runner and container manager
        context to implement their responsibilities.
        """

        # Shared object to optimize schemata write and detect CLOSids exhaustion.
        rdt_groups = RDTGroups(closids_limit=platform.rdt_num_closids)

        def rdt_allocation_value_constructor(rdt_allocation: RDTAllocation, container,
                                             common_labels):
            return RDTAllocationValue(
                container.get_name(),
                rdt_allocation,
                container.get_resgroup(),
                container.cgroup.get_pids,
                platform.sockets,
                platform.rdt_mb_control_enabled,
                platform.rdt_cbm_mask,
                platform.rdt_min_cbm_bits,
                common_labels=common_labels,
                rdt_groups=rdt_groups,
            )

        registry = {
            AllocationType.RDT: rdt_allocation_value_constructor,
            AllocationType.QUOTA: QuotaAllocationValue,
            AllocationType.SHARES: SharesAllocationValue,
        }

        task_id_to_containers = {task.task_id: container for task, container in containers.items()}
        simple_dict = {}
        for task_id, task_allocations in tasks_allocations.items():
            if task_id not in task_id_to_containers:
                raise InvalidAllocations('invalid task id %r' % task_id)
            else:
                container = task_id_to_containers[task_id]
                this_container_labels = dict(container_name=container.get_name(), task=task_id)
                allocation_value = TaskAllocationsValues.create(
                    task_allocations, container, registry, this_container_labels)
                allocation_value.validate()
                simple_dict[task_id] = allocation_value

        return TasksAllocationsValues(simple_dict)


@dataclass
class AllocationRunner(Runner, BaseRunnerMixin):
    # Required
    node: nodes.Node
    allocator: Allocator
    metrics_storage: storage.Storage
    anomalies_storage: storage.Storage
    allocations_storage: storage.Storage

    # Optional
    action_delay: float = 1.  # [s]
    rdt_enabled: bool = True
    rdt_mb_control_enabled: bool = None  # None means will be automatically set during configure_rdt
    extra_labels: Dict[str, str] = field(default_factory=dict)
    ignore_privileges_check: bool = False
    allocation_configuration: AllocationConfiguration = \
        field(default_factory=AllocationConfiguration)

    def __post_init__(self):
        BaseRunnerMixin.__init__(
            self, self.rdt_enabled, self.rdt_mb_control_enabled, self.allocation_configuration)

    @trace(log)
    def run(self):
        if not self.configure_rdt(self.rdt_enabled, self.ignore_privileges_check):
            return

        while True:
            # Prepare algorithm inputs and send input based metrics.
            (platform, tasks_measurements, tasks_resources, tasks_labels,
             current_tasks_allocations, common_labels) = \
                self._prepare_input_data_and_send_metrics_package(
                    self.node, self.metrics_storage, self.extra_labels)
            log.debug('Tasks detected: %r', list(current_tasks_allocations.keys()))

            # Allocator callback
            allocate_start = time.time()
            new_tasks_allocations, anomalies, extra_metrics = self.allocator.allocate(
                platform, tasks_measurements, tasks_resources, tasks_labels,
                current_tasks_allocations)
            allocate_duration = time.time() - allocate_start

            log.debug('Anomalies detected: %d', len(anomalies))

            log.debug('current: %s', current_tasks_allocations)
            current_allocations = TasksAllocationsValues.create(
                current_tasks_allocations, self.containers_manager.containers, platform)

            allocations_changeset = None
            try:

                log.debug('new: %s', new_tasks_allocations)
                new_allocations = TasksAllocationsValues.create(
                    new_tasks_allocations, self.containers_manager.containers, platform)

                new_allocations.validate()

                # if there are left allocations to apply
                if new_allocations is not None:

                    # log.log(TRACE, 'new (after validation):\n %s', pprint.pformat(
                    # new_allocations))

                    target_allocations, allocations_changeset = new_allocations.calculate_changeset(
                        current_allocations)
                    target_allocations.validate()

                else:
                    target_allocations = current_allocations

                errors = []

            except InvalidAllocations as e:
                log.error('invalid allocations: %s', str(e))
                errors = [str(e)]
                target_allocations = TasksAllocationsValues.create(
                    current_tasks_allocations, self.containers_manager.containers, platform)

            if allocations_changeset:
                log.debug('changeset: %s', allocations_changeset)
                log.info('performing allocations on %d tasks', len(allocations_changeset))
                allocations_changeset.perform_allocations()

            # Note: anomaly metrics include metrics found in ContentionAnomaly.metrics.
            anomaly_metrics = convert_anomalies_to_metrics(anomalies)
            update_anomalies_metrics_with_task_information(anomaly_metrics, tasks_labels)

            anomalies_package = MetricPackage(self.anomalies_storage)
            anomalies_package.add_metrics(self.get_anomalies_statistics_metrics(anomalies))
            anomalies_package.add_metrics(extra_metrics)
            anomalies_package.send(common_labels)

            # Store allocations information
            allocations_metrics = target_allocations.generate_metrics()
            allocations_package = MetricPackage(self.allocations_storage)

            allocations_statistic_metrics = self.get_allocations_statistics_metrics(
                new_tasks_allocations, allocate_duration, errors)
            allocations_package.add_metrics(
                allocations_metrics,
                extra_metrics,
                allocations_statistic_metrics,
            )
            allocations_package.send(common_labels)

            if not self.wait_or_finish(self.action_delay):
                break

        self.cleanup()
