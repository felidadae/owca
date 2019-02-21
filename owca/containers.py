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


from abc import ABC, abstractmethod
import logging
import pprint
from typing import List, Optional, Dict

from owca import logger
from owca import resctrl
from owca.allocators import AllocationConfiguration, TaskAllocations
from owca.cgroups import Cgroup
from owca.metrics import Measurements, MetricName, sum_measurements
from owca.nodes import Task
from owca.perf import PerfCounters
from owca.resctrl import ResGroup

log = logging.getLogger(__name__)

DEFAULT_EVENTS = (MetricName.INSTRUCTIONS, MetricName.CYCLES,
                  MetricName.CACHE_MISSES, MetricName.MEMSTALL)
CPU_USAGE = 'cpuacct.usage'


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


class ContainerInterface(ABC):
    @abstractmethod
    def set_resgroup(self, resgroup: ResGroup):
        ...

    @abstractmethod
    def get_resgroup(self):
        ...

    @abstractmethod
    def get_name(self):
        """Returns cgroup_path cleaned."""

    @abstractmethod
    def get_cgroup(self) -> Cgroup:
        ...

    @abstractmethod
    def get_cgroup_path(self) -> Cgroup:
        ...

    @abstractmethod
    def get_pids(self) -> List[str]:
        ...

    @abstractmethod
    def sync(self) -> None:
        ...

    @abstractmethod
    def get_measurements(self) -> Measurements:
        ...

    @abstractmethod
    def cleanup(self) -> None:
        ...

    @abstractmethod
    def get_allocations(self) -> TaskAllocations:
        ...


class ContainerSet(ContainerInterface):
    def __init__(self,
                 cgroup_path: str, cgroup_paths: List[str], platform_cpus: int,
                 allocation_configuration: Optional[AllocationConfiguration] = None,
                 resgroup: ResGroup = None, rdt_enabled: bool = True,
                 rdt_mb_control_enabled: bool = False):
        self._cgroup_path = cgroup_path
        self._name = _convert_cgroup_path_to_resgroup_name(self._cgroup_path)
        self._allocation_configuration = allocation_configuration
        self._rdt_enabled = rdt_enabled
        self._rdt_mb_control_enabled = rdt_mb_control_enabled
        self._resgroup = resgroup

        # Create Cgroup object representing itself.
        self._cgroup = Cgroup(
            cgroup_path=self._cgroup_path,
            platform_cpus=platform_cpus,
            allocation_configuration=allocation_configuration)

        # Create Cgroup objects for children.
        self._subcontainers: Dict[str, Container] = {}
        for cgroup_path in cgroup_paths:
            self._subcontainers[cgroup_path] = Container(
                cgroup_path=cgroup_path,
                # Managament of RDT is done only in ContainerSet class.
                rdt_enabled=False,
                rdt_mb_control_enabled=False,
                platform_cpus=platform_cpus,
                allocation_configuration=allocation_configuration)

    def set_resgroup(self, resgroup: ResGroup):
        self._resgroup = resgroup

    def get_resgroup(self):
        return self._resgroup

    def get_name(self):
        return self._name

    def get_cgroup(self):
        return self._cgroup

    def get_cgroup_path(self) -> Cgroup:
        return self._cgroup_path

    def get_pids(self) -> List[str]:
        all_pids = []
        for container in self._subcontainers.values():
            all_pids.extend(container.get_pids())
        return all_pids

    def sync(self):
        """Called every run iteration to keep pids of cgroup and resctrl in sync."""
        if self._rdt_enabled:
            self._resgroup.add_pids(pids=self.get_pids(), mongroup_name=self._name)

    def get_measurements(self) -> Measurements:
        measurements = dict()
        try:
            # Merge cgroup and perf_counters measurements.
            measurements_list: List[Measurements] = []
            for container in self._subcontainers.values():
                m = container.cgroup.get_measurements()
                m.update(container.perf_counters.get_measurements())
                measurements_list.append(m)

            summed_measurements, ignored_metrics = sum_measurements(measurements_list)
            measurements.update(summed_measurements)
            log.warning('ContainerSet.get_measuremenets: ignored metrics {} while summing up.'
                        .format(ignored_metrics))

            # Resgroup management is entirely done in this class.
            if self._rdt_enabled:
                measurements.update(self._resgroup.get_measurements(self._name))

        except FileNotFoundError:
            log.warning('Could not read measurements for container (ContainerSet) %s. '
                      'Probably the mesos container has died during the current runner iteration.',
                      self._cgroup_path)
            # Returning empty measurements.
            return {}
        return measurements

    def cleanup(self):
        for container in self._subcontainers.values():
            container.cleanup()
        if self._rdt_enabled:
            self._resgroup.remove(self._name)

    def get_allocations(self) -> TaskAllocations:
        # In only detect mode, without allocation configuration return nothing.
        if not self._allocation_configuration:
            return {}
        allocations: TaskAllocations = dict()
        allocations.update(self._cgroup.get_allocations())
        if self._rdt_enabled:
            allocations.update(self._resgroup.get_allocations())

        log.debug('allocations on task=%r from resgroup=%r allocations:\n%s',
                  self._name, self._resgroup, pprint.pformat(allocations))

        return allocations

    def __repr__(self):
        return "ContainerSet(cgroup_path={}, resgroup={})".format(
            self._cgroup_path, self._resgroup)

    # TODO remove from code or rename to a standard function
    # def __eq__(self, other):
    #     return (self._cgroup_path == other._cgroup_path and
    #             len(self._subcontainers) == len(other._subcontainers) and
    #             all([child_a == child_b for child_a, child_b in zip(self._subcontainers, other._subcontainers)]))


class Container(ContainerInterface):
    def __init__(self, cgroup_path: str, platform_cpus: int, resgroup: ResGroup = None,
                 allocation_configuration: Optional[AllocationConfiguration] = None,
                 rdt_enabled: bool = True, rdt_mb_control_enabled: bool = False):
        self._cgroup_path = cgroup_path
        self._name = _convert_cgroup_path_to_resgroup_name(self._cgroup_path)
        self._allocation_configuration = allocation_configuration
        self._rdt_enabled = rdt_enabled
        self._rdt_mb_control_enabled = rdt_mb_control_enabled
        self._resgroup = resgroup

        self.cgroup = Cgroup(
            cgroup_path=self._cgroup_path,
            platform_cpus=platform_cpus,
            allocation_configuration=allocation_configuration)
        self.perf_counters = PerfCounters(self._cgroup_path, event_names=DEFAULT_EVENTS)

    def set_resgroup(self, resgroup: ResGroup):
        self._resgroup = resgroup

    def get_cgroup(self):
        return self.cgroup

    def get_resgroup(self):
        return self._resgroup

    def get_name(self):
        return self._name

    def get_cgroup_path(self) -> Cgroup:
        return self._cgroup_path

    def get_pids(self):
        return self.cgroup.get_pids()

    def sync(self):
        """Called every run iteration to keep pids of cgroup and resctrl in sync."""
        if self._rdt_enabled:
            self._resgroup.add_pids(self.cgroup.get_pids(), mongroup_name=self._name)

    def get_measurements(self) -> Measurements:
        try:
            return flatten_measurements([
                self.cgroup.get_measurements(),
                self._resgroup.get_measurements(self._name) if self._rdt_enabled else {},
                self.perf_counters.get_measurements(),
            ])
        except FileNotFoundError:
            log.debug('Could not read measurements for container %s. '
                      'Probably the mesos container has died during the current runner iteration.',
                      self._cgroup_path)
            # Returning empty measurements.
            return {}

    def cleanup(self):
        self.perf_counters.cleanup()
        if self._rdt_enabled:
            self._resgroup.remove(self._name)

    def get_allocations(self) -> TaskAllocations:
        # In only detect mode, without allocation configuration return nothing.
        if not self._allocation_configuration:
            return {}
        allocations: TaskAllocations = dict()
        allocations.update(self.cgroup.get_allocations())
        if self._rdt_enabled:
            allocations.update(self._resgroup.get_allocations())

        log.debug('allocations on task=%r from resgroup=%r allocations:\n%s',
                  self._name, self._resgroup, pprint.pformat(allocations))

        return allocations

    # TODO remove, as may give wrong impression.
    def __eq__(self, other):
        return self._cgroup_path == other._cgroup_path


class ContainerManager:
    """Main engine of synchronizing state between found orchestration software tasks,
    its containers and resctrl system.

    - sync_container_state - is responsible for mapping Tasks to Container objects
            and managing underlaying ResGroup objects
    - sync_allocations - is responsible for applying TaskAllocations to underlaying
            Cgroup and ResGroup objects
    """

    def __init__(self, rdt_enabled: bool, rdt_mb_control_enabled: bool, platform_cpus: int,
                 allocation_configuration: Optional[AllocationConfiguration]):
        self.containers: Dict[Task, ContainerInterface] = {}
        self.rdt_enabled = rdt_enabled
        self.rdt_mb_control_enabled = rdt_mb_control_enabled
        self.platform_cpus = platform_cpus
        self.allocation_configuration = allocation_configuration

    def sync_containers_state(self, tasks) -> Dict[Task, ContainerInterface]:
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

        # Cleanup and remove orphaned containers (_cleanup).
        for container_to_cleanup in containers_to_cleanup:
            container_to_cleanup.cleanup()

        # Recreate self.containers.
        self.containers = {task: container
                           for task, container in self.containers.items()
                           if task in tasks}

        if new_tasks:
            log.debug('sync_containers_state: found %d new tasks', len(new_tasks))
            log.log(logger.TRACE, 'sync_containers_state: new_tasks=%r', new_tasks)

        # Prepare state of currently assigned resgroups
        # and remove some orphaned resgroups
        container_name_to_resgroup_name = {}
        if self.rdt_enabled:
            mon_groups_relation = resctrl.read_mon_groups_relation()
            log.debug('mon_groups_relation: %s', pprint.pformat(mon_groups_relation))
            resctrl.clean_taskless_groups(mon_groups_relation)

            mon_groups_relation = resctrl.read_mon_groups_relation()
            log.debug('mon_groups_relation (after cleanup): %s',
                      pprint.pformat(mon_groups_relation))

            # Calculate inverse relation of task_id to res_group name based on mon_groups_relations
            for ctrl_group, container_names in mon_groups_relation.items():
                for container_name in container_names:
                    container_name_to_resgroup_name[container_name] = ctrl_group
            log.debug('container_name_to_resgroup_name: %s',
                      pprint.pformat(container_name_to_resgroup_name))

        # Create new containers and store them.
        for new_task in new_tasks:
            # Check whether the task groups multiple containers,
            #   is so use ContainerSet class, otherwise Container class.
            #   ContainerSet shares interface with Container.
            if len(new_task.subcgroups_paths):
                container = ContainerSet(
                    cgroup_path=new_task.cgroup_path,
                    cgroup_paths=new_task.subcgroups_paths,
                    rdt_enabled=self.rdt_enabled,
                    rdt_mb_control_enabled=self.rdt_mb_control_enabled,
                    platform_cpus=self.platform_cpus,
                    allocation_configuration=self.allocation_configuration)
            else:
                container = Container(
                    cgroup_path=new_task.cgroup_path,
                    rdt_enabled=self.rdt_enabled,
                    rdt_mb_control_enabled=self.rdt_mb_control_enabled,
                    platform_cpus=self.platform_cpus,
                    allocation_configuration=self.allocation_configuration)
            self.containers[new_task] = container

        # Sync "state" of individual containers.
        # Note: only pids are synchronized, not allocations.
        for container in self.containers.values():
            if self.rdt_enabled:
                if container.get_name() in container_name_to_resgroup_name:
                    container.set_resgroup(ResGroup(
                        name=container_name_to_resgroup_name[container.get_name()],
                        rdt_mb_control_enabled=self.rdt_mb_control_enabled))
                else:
                    # Every newly detected container is first assigned to the root group.
                    container.set_resgroup(ResGroup(
                        name='',
                        rdt_mb_control_enabled=self.rdt_mb_control_enabled))
            container.sync()

        return self.containers

    def cleanup(self):
        for container in self.containers.values():
            container.cleanup()


def _calculate_desired_state(
        discovered_tasks: List[Task], known_containers: List[ContainerInterface]
) -> (List[Task], List[ContainerInterface]):
    """Prepare desired state of system by comparing actual running Mesos tasks and already
    watched containers.

    Assumptions:
    * One-to-one relationship between task and container
    * cgroup_path for task and container need to be identical to establish the relationship
    * cgroup_path is unique for each task

    :returns "list of Mesos tasks to start watching"
    and "orphaned containers to _cleanup" (there are no more Mesos tasks matching those containers)
    """
    discovered_task_cgroup_paths = {task.cgroup_path for task in discovered_tasks}
    containers_cgroup_paths = {container.get_cgroup_path() for container in known_containers}

    # Filter out containers which are still running according to Mesos agent.
    # In other words pick orphaned containers.
    containers_to_delete = [container for container in known_containers
                            if container.get_cgroup_path() not in discovered_task_cgroup_paths]

    # Filter out tasks which are monitored using "Container abstraction".
    # In other words pick new, not yet monitored tasks.
    new_tasks = [task for task in discovered_tasks
                 if task.cgroup_path not in containers_cgroup_paths]

    return new_tasks, containers_to_delete
