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


from typing import List, Optional, Dict, Tuple
import logging

from dataclasses import dataclass

from owca import logger
from owca.allocators import AllocationConfiguration, TaskAllocations, TasksAllocations
from owca.nodes import Task
from owca.resctrl import ResGroup
from owca.cgroups import Cgroup
from owca.perf import PerfCounters
from owca.metrics import Measurements, MetricName

log = logging.getLogger(__name__)

DEFAULT_EVENTS = (MetricName.INSTRUCTIONS, MetricName.CYCLES, MetricName.CACHE_MISSES)


def flatten_measurements(measurements: List[Measurements]):
    all_measurements_flat = dict()

    for measurement in measurements:
        assert not set(measurement.keys()) & set(all_measurements_flat.keys()), \
            'When flatting measurements the keys should not overlap!'
        all_measurements_flat.update(measurement)
    return all_measurements_flat

def _convert_cgroup_path_to_resgroup_name(cgroup_path):
    """Return resgroup compatbile name for cgroup path (remove special characters like /)."""
    assert cgroup_path.startswith('/'), 'Provide cgroup_path with leading /'
    # cgroup path without leading '/'
    relative_cgroup_path = cgroup_path[1:]  
    # Resctrl group is flat so flatten then cgroup hierarchy.
    return relative_cgroup_path.replace('/', '-')


@dataclass
class Container:

    cgroup_path: str
    platform_cpus: int
    allocation_configuration: Optional[AllocationConfiguration] = None
    rdt_enabled: bool = True
    task_name: str = None  # defaults to flatten value of provided cgroup_path

    def __post_init__(self):
        self.cgroup = Cgroup(
            self.cgroup_path,
            platform_cpus=self.platform_cpus,
            allocation_configuration=self.allocation_configuration,
        )
        self.task_name = self.task_name or _convert_cgroup_path_to_resgroup_name(self.cgroup_path)
        self.perf_counters = PerfCounters(self.cgroup_path, event_names=DEFAULT_EVENTS)
        self.resgroup = ResGroup(name=self.task_name) if self.rdt_enabled else None
    
    def get_pids(self) -> List[int]:
        return self.cgroup.get_tasks()

    def sync(self):
        if self.rdt_enabled:
            tasks = list(map(str, self.get_pids()))
            log.debug('sync %d tasks to %r', len(tasks), self.task_name)
            self.resgroup.add_tasks(tasks, self.task_name)

    def get_measurements(self) -> Measurements:
        return flatten_measurements([
            self.cgroup.get_measurements(),
            self.resgroup.get_measurements(self.task_name) if self.rdt_enabled else {},
            self.perf_counters.get_measurements(),
        ])

    def cleanup(self):
        if self.rdt_enabled:
            self.resgroup.cleanup()
        self.perf_counters.cleanup()

    def get_allocations(self) -> TaskAllocations:
        # In only detect mode, without allocation configuration return nothing.
        if not self.allocation_configuration:
            return {}
        allocations: TaskAllocations = dict()
        allocations.update(self.cgroup.get_allocations())
        if self.rdt_enabled:
            allocations.update(self.resgroup.get_allocations())
        return allocations

    def perform_allocations(self, allocations: TaskAllocations):
        self.cgroup.perform_allocations(allocations)
        if self.rdt_enabled:
            self.resgroup.perform_allocations(allocations)


class ContainerManager:
    """Main engine of synchornizing state between found orechestratios software tasks,
    its containers and resctrl system.

    - sync_container_state - is responsible for mapping Tasks to Container objects
            and managing underlaying ResGroup objects
    - sync_allocations - is responsible for applying TaskAllocations to underlaying
            Cgroup and ResGroup objects

    """

    def __init__(self, rdt_enabled: bool, platform_cpus: int,
                 allocation_configuration: Optional[AllocationConfiguration]):
        self.containers: Dict[Task, Container] = {}
        self.resgroups: Dict[ResGroup, List[Container]] = {}
        self.rdt_enabled = rdt_enabled
        self.platform_cpus = platform_cpus
        self.allocation_configuration = allocation_configuration

    def sync_containers_state(self, tasks) -> Dict[Task, Container]:
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
            self.containers[new_task] = Container(
                new_task.cgroup_path,
                rdt_enabled=self.rdt_enabled,
                platform_cpus=self.platform_cpus,
                allocation_configuration=self.allocation_configuration
            )

        # Sync state of individual containers.
        for container in self.containers.values():
            container.sync()

        return self.containers

    def _perfom_allocations(self, tasks_allocations):
        for task, container in self.containers.items():
            if task.task_id in tasks_allocations:
                task_allocations = tasks_allocations[task.task_id]
                container.perform_allocations(task_allocations)

    def cleanup(self):
        # cleanup
        for container in self.containers.values():
            container.cleanup()

    def sync_allocations(self, old_allocations: TasksAllocations,
                         new_allocations: TasksAllocations):
        """After new allocations returned from allocate function, calculate the difference
        between actual state and expected and execute nessesary steps to apply required changes
        to system.
        Required changes to system means:
        - created if nesseasry RdtGroups


        :param old_allocations:
        :param new_allocations:
        :return:
        """
        all_allocations, resulting_allocations = self._calculate_resulting_allocations(
                old_allocations, new_allocations)
        log.log(logger.TRACE, 'Resulting allocations to execute: %r', resulting_allocations)

        self._perfom_allocations(resulting_allocations)

        return all_allocations

    def _calculate_resulting_allocations(
            self, old_allocations: TasksAllocations, new_allocations: TasksAllocations) \
            -> Tuple[TasksAllocations, TasksAllocations]:
        # TODO: implement me!!!!
        return {}, {}


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
