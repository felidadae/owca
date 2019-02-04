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
import pprint
import time
from typing import Dict

from dataclasses import dataclass, field

from owca import platforms, nodes, storage
from owca.allocations import AllocationsDict, Registry, InvalidAllocationValue, \
    CommonLablesAllocationValue, ContextualErrorAllocationValue
from owca.allocators import TasksAllocations, AllocationConfiguration, AllocationType, Allocator
from owca.cgroups import SharesAllocationValue, QuotaAllocationValue
from owca.containers import Container
from owca.detectors import convert_anomalies_to_metrics, \
    update_anomalies_metrics_with_task_information
from owca.logger import TRACE, trace
from owca.nodes import Task
from owca.resctrl import RDTAllocation, RDTAllocationValue, DeduplicatingRDTAllocationsValue
from owca.runners.base import Runner, BaseRunnerMixin
from owca.storage import MetricPackage

log = logging.getLogger(__name__)


def convert_to_allocations_values(tasks_allocations: TasksAllocations,
                                  containers: Dict[Task, Container],
                                  platform: platforms.Platform,
                                  allocation_configuration: AllocationConfiguration
                                  ) -> AllocationsDict:
    """Convert plain raw object TasksAllocations to boxed inteligent AllocationsDict
    that can be serialized to metrics, validated and perform contained allocations.

    Simple tasks allocations objects are augumented using runner and container manager
    context to implement their resposiblities.
    """
    registry = Registry()
    registry.register_automapping_type(dict, AllocationsDict)
    task_id_to_containers = {task.task_id: container for task, container in containers.items()}

    def context_aware_adapter(specific_constructor):
        def generic_constructor(raw_value, ctx, registry):
            if len(ctx) != 2:
                return InvalidAllocationValue(
                    raw_value, 'expected context to be task_id/allocation_type got %s' % ','.join(
                        ctx))
            task_id = ctx[0]

            if task_id not in task_id_to_containers:
                return InvalidAllocationValue(raw_value, 'task_id %r not found (ctx=%r)' % (
                    task_id, '.'.join(ctx)))

            container = task_id_to_containers[task_id]
            allocation_value = specific_constructor(raw_value, container)

            errors, new_allocation_value = allocation_value.validate()
            if new_allocation_value is None:
                return InvalidAllocationValue(allocation_value, 'some errors during creation',
                                              errors)

            log.log(TRACE, 'adapter: specific constructor: %r -> %r', specific_constructor,
                    allocation_value)
            allocation_value = CommonLablesAllocationValue(
                allocation_value,
                container_name=container.container_name,
            )
            log.log(TRACE, 'adapter: common labels constructor: %r', allocation_value)
            allocation_value = ContextualErrorAllocationValue(
                allocation_value,
                prefix_message='for task=%r - ' % task_id
            )
            log.log(TRACE, 'adapter: ContextualError constructor: %r', allocation_value)
            return allocation_value

        return generic_constructor

    shared_already_executed_names = set()
    all_resgroups_names = set()

    def rdt_allocation_value_constructor(rdt_allocation: RDTAllocation, container: Container):
        rdt_value = RDTAllocationValue(
            container.container_name,
            rdt_allocation, container.resgroup, container.cgroup.get_pids,
            platform.sockets, platform.rdt_mb_control_enabled,
            platform.rdt_cbm_mask, platform.rdt_min_cbm_bits,
        )
        return DeduplicatingRDTAllocationsValue(
            rdt_value,
            maximum_closids=platform.rdt_num_closids,
            already_executed_resgroup_names=shared_already_executed_names,
            existing_groups=all_resgroups_names,
        )

    registry.register_automapping_type((AllocationType.RDT, RDTAllocation),
                                       context_aware_adapter(rdt_allocation_value_constructor))

    def share_allocation_value_constructor(normalized_shares, container: Container):
        return SharesAllocationValue(normalized_shares, container.cgroup)

    registry.register_automapping_type((AllocationType.SHARES, int),
                                       context_aware_adapter(share_allocation_value_constructor))
    registry.register_automapping_type((AllocationType.SHARES, float),
                                       context_aware_adapter(share_allocation_value_constructor))

    def quota_allocation_value_constructor(normalized_quota, container: Container):
        return QuotaAllocationValue(normalized_quota, container.cgroup)

    registry.register_automapping_type((AllocationType.QUOTA, float),
                                       context_aware_adapter(quota_allocation_value_constructor))
    registry.register_automapping_type((AllocationType.QUOTA, int),
                                       context_aware_adapter(quota_allocation_value_constructor))

    def invalid_type_constructor(raw_value, ctx, registry):
        allocation_type = ctx[1]
        return InvalidAllocationValue(raw_value, 'unknown allocation type %r on %s' % (
            allocation_type, '.'.join(ctx)))

    registry.register_automapping_type(None, invalid_type_constructor)

    return AllocationsDict(tasks_allocations, None, registry=registry)


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
            platform, tasks_measurements, tasks_resources, \
                tasks_labels, current_tasks_allocations, common_labels = \
                self._prepare_input_data_and_send_metrics_package(
                    self.node, self.metrics_storage, self.extra_labels)

            # Allocator callback
            allocate_start = time.time()
            new_tasks_allocations, anomalies, extra_metrics = self.allocator.allocate(
                platform, tasks_measurements, tasks_resources, tasks_labels,
                current_tasks_allocations)
            allocate_duration = time.time() - allocate_start

            log.debug('Anomalies detected: %d', len(anomalies))

            log.debug('current:\n %s', pprint.pformat(current_tasks_allocations))
            current_allocations = convert_to_allocations_values(
                current_tasks_allocations, self.containers_manager.containers, platform,
                self.allocation_configuration)

            log.debug('new:\n %s', pprint.pformat(new_tasks_allocations))
            new_allocations = convert_to_allocations_values(
                new_tasks_allocations, self.containers_manager.containers, platform,
                self.allocation_configuration)

            validation_errors, new_allocations = new_allocations.validate()
            if validation_errors:
                log.warning('Validation errors: %s', validation_errors)

            # if there are left allocations to apply
            if new_allocations is not None:

                log.log(TRACE, 'new (after validation):\n %s', pprint.pformat(new_allocations))

                target_allocations, allocations_changeset, calculating_errors = \
                    new_allocations.calculate_changeset(current_allocations)

                if calculating_errors:
                    log.warning('Calculating changeset errors: %s', calculating_errors)

                target_validation_errors, target_allocations = target_allocations.validate()
                if target_validation_errors:
                    log.warning('Validation target errors: %s', target_validation_errors)

                log.log(TRACE, 'current (values):\n %s', pprint.pformat(current_allocations))
                log.log(TRACE, 'new (values):\n %s', pprint.pformat(new_allocations))
                log.debug('---------------------------------------')
                log.log(TRACE, 'allocation_changeset:\n %s', pprint.pformat(allocations_changeset))
                log.debug('---------------------------------------')

                # MAIN function
                if allocations_changeset:
                    allocations_changeset.perform_allocations()

            else:
                calculating_errors = []
                target_allocations = current_allocations

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
                new_tasks_allocations, allocate_duration, calculating_errors + validation_errors)
            allocations_package.add_metrics(
                allocations_metrics,
                extra_metrics,
                allocations_statistic_metrics,
            )
            allocations_package.send(common_labels)

            if not self.wait_or_finish(self.action_delay):
                break

        self.cleanup()
