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


from typing import List, Optional, Dict, Tuple, Set
import pprint
import logging

from dataclasses import dataclass

from owca import logger
from owca.allocators import AllocationConfiguration, TaskAllocations, TasksAllocations, \
    _calculate_tasks_allocations_changeset, AllocationType
from owca.logger import trace
from owca.nodes import Task
from owca.resctrl import ResGroup, ResGroupName, RESCTRL_ROOT_NAME
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
    rdt_mb_control_enabled: bool = False
    task_name: str = None  # defaults to flatten value of provided cgroup_path
    resgroup: ResGroup = None  # do not manage self.resgroup object, just reference it

    def __post_init__(self):
        self.cgroup = Cgroup(
            self.cgroup_path,
            platform_cpus=self.platform_cpus,
            allocation_configuration=self.allocation_configuration,
        )
        self.task_name = self.task_name or _convert_cgroup_path_to_resgroup_name(self.cgroup_path)
        self.perf_counters = PerfCounters(self.cgroup_path, event_names=DEFAULT_EVENTS)

    def get_pids(self) -> List[str]:
        return list(map(str, self.cgroup.get_tasks()))

    def sync(self):
        """Called every run iteration to keep pids of cgroup and resctrl in sync."""
        if self.rdt_enabled:
            self.resgroup.add_tasks(self.get_pids(), mongroup_name=self.task_name)

    def change_resgroup(self, new_resgroup):
        """Remove tasks from current group and add to the new one."""
        assert self.rdt_enabled
        # Remove pids from old group
        self.resgroup.remove_tasks(mongroup_name=self.task_name)
        # Add pids to new group
        new_resgroup.add_tasks(self.get_pids(), mongroup_name=self.task_name)
        self.resgroup = new_resgroup

    def get_measurements(self) -> Measurements:
        try:
            return flatten_measurements([
                self.cgroup.get_measurements(),
                self.resgroup.get_measurements(self.task_name) if self.rdt_enabled else {},
                self.perf_counters.get_measurements(),
            ])
        except FileNotFoundError:
            log.debug('Could not read measurements for container %s. '
                      'Probably the mesos container has died during the current runner iteration.',
                      self.cgroup_path)
            # Returning empty measurements.
            return {}

    def cleanup(self):
        self.perf_counters.cleanup()
        if self.rdt_enabled:
            self.resgroup.remove_tasks(self.task_name)

    def get_allocations(self) -> TaskAllocations:
        # In only detect mode, without allocation configuration return nothing.
        if not self.allocation_configuration:
            return {}
        allocations: TaskAllocations = dict()
        allocations.update(self.cgroup.get_allocations())
        if self.rdt_enabled:
            allocations.update(self.resgroup.get_allocations(self.resgroup.name))

        log.debug('allocations on task=%r from resgroup=%r allocations:\n%s',
                  self.task_name, self.resgroup, pprint.pformat(allocations))

        return allocations

    def perform_allocations(self, allocations: TaskAllocations, allocate_rdt=True):
        self.cgroup.perform_allocations(allocations)
        if self.rdt_enabled and allocate_rdt:
            self.resgroup.perform_allocations(allocations)

    def __hash__(self):
        return hash(str(self.cgroup_path))


class ContainerManager:
    """Main engine of synchornizing state between found orechestratios software tasks,
    its containers and resctrl system.

    - sync_container_state - is responsible for mapping Tasks to Container objects
            and managing underlaying ResGroup objects
    - sync_allocations - is responsible for applying TaskAllocations to underlaying
            Cgroup and ResGroup objects
    """

    def __init__(self, rdt_enabled: bool, rdt_mb_control_enabled: bool, platform_cpus: int,
                 allocation_configuration: Optional[AllocationConfiguration]):
        self.containers: Dict[Task, Container] = {}
        self.rdt_enabled = rdt_enabled
        self.rdt_mb_control_enabled = rdt_mb_control_enabled
        self.platform_cpus = platform_cpus
        self.allocation_configuration = allocation_configuration

        self.resgroups_containers_relation: Dict[ResGroupName, Tuple[ResGroup, Set[Container]]]
        if self.rdt_enabled:
            self.resgroups_containers_relation = {
                RESCTRL_ROOT_NAME: (ResGroup(name=RESCTRL_ROOT_NAME,
                                             rdt_mb_control_enabled=self.rdt_mb_control_enabled,
                                             ), set())
            }
        else:
            self.resgroups_containers_relation = {}

    def _get_container_by_taskid(self, task_id) -> Optional[Container]:
        for task, container in self.containers.items():
            if task.task_id == task_id:
                return container
        return None

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
            log.debug('sync_containers_state: cleaning up %d containers',
                      len(containers_to_cleanup))
            log.log(logger.TRACE, 'sync_containers_state: containers_to_cleanup=%r',
                    containers_to_cleanup)

        # Cleanup and remove orphaned containers (cleanup).
        for container_to_cleanup in containers_to_cleanup:
            container_to_cleanup.cleanup()

            if self.rdt_enabled and container_to_cleanup.resgroup is not None:
                resgroup = container_to_cleanup.resgroup

                # Remove container from resgroup relation
                self.resgroups_containers_relation[resgroup.name][1].remove(
                    container_to_cleanup)

                # For non root resgroups, checkout how many containers left and
                # remove if emtpy.
                if resgroup.name != RESCTRL_ROOT_NAME:
                    if len(self.resgroups_containers_relation[resgroup.name][1]) == 0:
                        log.debug('sync_containers_state: removing resgroup: %s', resgroup.name)
                        resgroup.cleanup()
                        del self.resgroups_containers_relation[resgroup.name]

        # Recreate self.containers.
        self.containers = {task: container
                           for task, container in self.containers.items()
                           if task in tasks}

        if new_tasks:
            log.debug('sync_containers_state: found %d new tasks', len(new_tasks))
            log.log(logger.TRACE, 'sync_containers_state: new_tasks=%r', new_tasks)

        # Create new containers and store them.
        for new_task in new_tasks:
            container = Container(
                new_task.cgroup_path,
                rdt_enabled=self.rdt_enabled,
                rdt_mb_control_enabled=self.rdt_mb_control_enabled,
                platform_cpus=self.platform_cpus,
                allocation_configuration=self.allocation_configuration,
            )
            self.containers[new_task] = container
            if self.rdt_enabled:
                # Every newly detected containers is first assigne to root group.
                container.resgroup = self._get_resgroup_by_name(RESCTRL_ROOT_NAME)

                _, containers = self.resgroups_containers_relation[RESCTRL_ROOT_NAME]
                containers.add(container)

        # Sync "state" of individual containers.
        for container in self.containers.values():
            container.sync()

        return self.containers

    @trace(log)
    def _perfom_allocations(self, tasks_allocations):
        executed_rdt_allocations: Set(str) = set()
        for task, container in self.containers.items():
            if task.task_id in tasks_allocations:
                task_allocations = tasks_allocations[task.task_id]

                # Do not execute the same rdt allocation (with the same name)
                # over and over again.
                if task_allocations.get('rdt') is not None and \
                        not task_allocations['rdt'].name in executed_rdt_allocations:
                    allocate_rdt = True
                    executed_rdt_allocations.add(task_allocations['rdt'].name)
                else:
                    allocate_rdt = False

                container.perform_allocations(task_allocations, allocate_rdt)

    # Managing resgroup and containers relation
    def _get_resgroup_by_name(self, name):
        assert self.rdt_enabled
        return self.resgroups_containers_relation[name][0]

    @trace(log, verbose=False)
    def _reassign_resgroups(self, tasks_allocations):
        """Manage container to resgroup relation according provided _allocations."""

        def _relations_to_string():
            r = ""
            for resgroup_name, (resgroup, containers) in self.resgroups_containers_relation.items():
                task_names = [container.task_name for container in containers]
                r += " \'{}\' -> [{}]\n".format(resgroup_name, ", ".join(task_names))
            return r.rstrip()

        # for debugging
        before_value = _relations_to_string()
        reassigments_count = 0

        for task_id, task_allocation in tasks_allocations.items():
            if AllocationType.RDT in task_allocation:
                # Helper vars.
                container = self._get_container_by_taskid(task_id)
                if container is None:
                    log.warning('reassign_resgroups: there is no container for task_id=%r', task_id)
                    continue

                task_rdt_allocation = task_allocation[AllocationType.RDT]

                # Skip allocations than remain in the same rdt group.
                if container.resgroup.name == task_rdt_allocation.name:
                    continue

                # Firstly remove from previous resgroup.
                self.resgroups_containers_relation[container.resgroup.name][1].remove(container)

                # Cleanup & remove empty (non-root) group.
                if not self.resgroups_containers_relation[container.resgroup.name][1]:
                    if container.resgroup.name != RESCTRL_ROOT_NAME:
                        log.debug('reassign_resgroups: removing empty resgroup: %r',
                                  container.resgroup.name)
                        self.resgroups_containers_relation[container.resgroup.name][0].cleanup()
                        del self.resgroups_containers_relation[container.resgroup.name]

                if task_rdt_allocation.name in self.resgroups_containers_relation:
                    # Move container to existing resgroup.
                    log.debug('reassign_resgroups: move to resgroup: %r', task_rdt_allocation)
                    container.change_resgroup(self._get_resgroup_by_name(task_rdt_allocation.name))
                    self.resgroups_containers_relation[task_rdt_allocation.name][1].add(container)
                else:
                    # Creation of a new resgroup.
                    new_resgroup_name = (task_rdt_allocation.name
                                         if task_rdt_allocation.name is not None else task_id)
                    log.debug('reassign_resgroups: create resgroup: %r', new_resgroup_name)
                    new_resgroup = ResGroup(name=new_resgroup_name,
                                            rdt_mb_control_enabled=self.rdt_mb_control_enabled)
                    self.resgroups_containers_relation[new_resgroup_name] = \
                        (new_resgroup, {container})
                    container.change_resgroup(new_resgroup)

                reassigments_count += 1

        log.debug('reassign_resgroups: reassigments: %i', reassigments_count)
        if reassigments_count:
            log.debug('reassign_resgroups: before:\n%s', before_value)
            log.debug('reassign_resgroups: after:\n%s', _relations_to_string())

    def cleanup(self):
        # cleanup
        for container in self.containers.values():
            container.cleanup()

    @trace(log, verbose=False)
    def sync_allocations(self, current_tasks_allocations: TasksAllocations,
                         new_tasks_allocations: TasksAllocations):
        """After new allocations returned from allocate function, calculate the difference
        between actual state and expected and execute nessesary steps to apply required changes
        to system.
        Required changes to system means:
        - created if nesseasry RdtGroups
        """
        log.debug('sync_allocations: current_tasks_allocations=%i new_tasks_allocations=%i',
                  len(current_tasks_allocations), len(new_tasks_allocations))

        target_tasks_allocations, tasks_allocations_changeset = \
            _calculate_tasks_allocations_changeset(current_tasks_allocations, new_tasks_allocations)
        log.log(logger.TRACE, 'sync_allocations: tasks allocations changeset (%i) to execute: %r',
                len(tasks_allocations_changeset), tasks_allocations_changeset)

        log.info('Allocations to execute: %i', len(tasks_allocations_changeset))

        # Syncing real part (resctrl groups are created/removed and cgroups files are written).
        if self.rdt_enabled:
            self._reassign_resgroups(tasks_allocations_changeset)

        self._perfom_allocations(tasks_allocations_changeset)

        return target_tasks_allocations


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
