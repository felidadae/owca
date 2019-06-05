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
from abc import ABC, abstractmethod
from typing import List, Optional, Dict

from wca import cgroups
from wca import logger
from wca import perf
from wca import resctrl
from wca.allocators import AllocationConfiguration, TaskAllocations
from wca.metrics import Measurements, merge_measurements, DerivedMetricsGenerator
from wca.nodes import Task
from wca.platforms import RDTInformation
from wca.profiling import profiler
from wca.resctrl import ResGroup
from wca.logger import TRACE

log = logging.getLogger(__name__)

CPU_USAGE = 'cpuacct.usage'


def flatten_measurements(measurements: List[Measurements]):
    all_measurements_flat = dict()

    for measurement in measurements:
        assert not set(measurement.keys()) & set(all_measurements_flat.keys()), \
            'When flatting measurements the keys should not overlap!'
        all_measurements_flat.update(measurement)
    return all_measurements_flat


def _sanitize_cgroup_path(cgroup_path):
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
    def get_resgroup(self) -> ResGroup:
        ...

    @abstractmethod
    def get_name(self) -> str:
        """Returns cgroup_path cleaned."""

    @abstractmethod
    def get_cgroup(self) -> cgroups.Cgroup:
        ...

    @abstractmethod
    def get_subcgroups(self) -> List[cgroups.Cgroup]:
        ...

    @abstractmethod
    def get_cgroup_path(self) -> str:
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
                 platform_sockets: int,
                 rdt_information: Optional[RDTInformation],
                 allocation_configuration: Optional[AllocationConfiguration] = None,
                 resgroup: ResGroup = None,
                 event_names: List[str] = None,
                 enable_derived_metrics: bool = False
                 ):
        self._cgroup_path = cgroup_path
        self._name = _sanitize_cgroup_path(self._cgroup_path)
        self._allocation_configuration = allocation_configuration

        self._rdt_information = rdt_information
        self._resgroup = resgroup

        # Create Cgroup object representing itself.
        self._cgroup = cgroups.Cgroup(
            cgroup_path=self._cgroup_path,
            platform_cpus=platform_cpus,
            platform_sockets=platform_sockets,
            allocation_configuration=allocation_configuration)

        # Create Cgroup objects for children.
        self._subcontainers: Dict[str, Container] = {}
        for cgroup_path in cgroup_paths:
            self._subcontainers[cgroup_path] = Container(
                cgroup_path=cgroup_path,
                rdt_information=None,
                platform_cpus=platform_cpus,
                platform_sockets=platform_sockets,
                allocation_configuration=allocation_configuration,
                event_names=event_names,
                enable_derived_metrics=enable_derived_metrics,
            )

    def get_subcgroups(self) -> List[cgroups.Cgroup]:
        return [container.get_cgroup() for container in self._subcontainers.values()]

    def set_resgroup(self, resgroup: ResGroup):
        self._resgroup = resgroup

    def get_resgroup(self) -> ResGroup:
        return self._resgroup

    def get_name(self) -> str:
        return self._name

    def get_cgroup(self) -> cgroups.Cgroup:
        return self._cgroup

    def get_cgroup_path(self) -> str:
        return self._cgroup_path

    def get_pids(self) -> List[str]:
        all_pids = []
        for container in self._subcontainers.values():
            all_pids.extend(container.get_pids())
        return all_pids

    def sync(self):
        """Called every run iteration to keep pids of cgroup and resctrl in sync."""
        if self._rdt_information:
            self._resgroup.add_pids(pids=self.get_pids(), mongroup_name=self._name)

    def get_measurements(self) -> Measurements:
        measurements = dict()

        # Merge cgroup and perf_counters measurements. As we set rdt_enabled to False
        #   for subcontainers, it will ignore rdt measurements.
        measurements_list: List[Measurements] = [container.get_measurements()
                                                 for container in self._subcontainers.values()]

        merged_measurements = merge_measurements(measurements_list)
        measurements.update(merged_measurements)

        # Resgroup management is entirely done in this class.
        if self._rdt_information and self._rdt_information.is_monitoring_enabled():
            measurements.update(
                self._resgroup.get_measurements(
                    self._name, self._rdt_information.rdt_mb_monitoring_enabled,
                    self._rdt_information.rdt_cache_monitoring_enabled))

        return measurements

    def cleanup(self):
        for container in self._subcontainers.values():
            container.cleanup()
        if self._rdt_information:
            self._resgroup.remove(self._name)

    def get_allocations(self) -> TaskAllocations:
        allocations: TaskAllocations = dict()
        allocations.update(self._cgroup.get_allocations())
        if self._rdt_information and self._rdt_information.is_control_enabled():
            allocations.update(self._resgroup.get_allocations())

        log.debug('allocations on task=%r from resgroup=%r allocations:\n%s',
                  self._name, self._resgroup, pprint.pformat(allocations))

        return allocations

    def __repr__(self):
        return "ContainerSet(cgroup_path={}, resgroup={})".format(
            self._cgroup_path, self._resgroup)


class Container(ContainerInterface):
    def __init__(self, cgroup_path: str, platform_cpus: int,
                 platform_sockets: int,
                 rdt_information: Optional[RDTInformation],
                 resgroup: ResGroup = None,
                 allocation_configuration:
                 Optional[AllocationConfiguration] = None,
                 event_names: List[str] = None,
                 enable_derived_metrics: bool = False):
        self._cgroup_path = cgroup_path
        self._name = _sanitize_cgroup_path(self._cgroup_path)
        self._allocation_configuration = allocation_configuration
        self._rdt_information = rdt_information
        self._resgroup = resgroup
        self._event_names = event_names

        self._cgroup = cgroups.Cgroup(
            cgroup_path=self._cgroup_path,
            platform_cpus=platform_cpus,
            platform_sockets=platform_sockets,
            allocation_configuration=allocation_configuration)

        self._derived_metrics_generator = None
        if self._event_names:
            self._perf_counters = perf.PerfCounters(self._cgroup_path, event_names=event_names)
            if enable_derived_metrics:
                self._derived_metrics_generator = DerivedMetricsGenerator(
                    event_names, self._perf_counters.get_measurements)

    def get_subcgroups(self) -> List[cgroups.Cgroup]:
        """Returns empty list as Container class cannot have subcontainers -
           for this use ContainerSet."""
        return []

    def set_resgroup(self, resgroup: ResGroup):
        self._resgroup = resgroup

    def get_cgroup(self) -> cgroups.Cgroup:
        return self._cgroup

    def get_resgroup(self) -> ResGroup:
        return self._resgroup

    def get_name(self) -> str:
        return self._name

    def get_cgroup_path(self) -> str:
        return self._cgroup_path

    def get_pids(self) -> List[str]:
        return self._cgroup.get_pids()

    def sync(self):
        """Called every run iteration to keep pids of cgroup and resctrl in sync."""
        if self._rdt_information:
            self._resgroup.add_pids(self._cgroup.get_pids(), mongroup_name=self._name)

    def get_measurements(self) -> Measurements:
        # Cgroup measurements
        try:
            cgroup_measurements = self._cgroup.get_measurements()
        except FileNotFoundError:
            log.warning('Could not read measurements for container %s. '
                        'Probably the mesos container has died during '
                        'the current runner iteration.',
                        self._cgroup_path)
            # Returning empty measurements.
            cgroup_measurements = {}

        # Perf events measurements
        if self._event_names:
            if self._derived_metrics_generator:
                # derived metrics
                perf_measurements = self._derived_metrics_generator.get_measurements()
            else:
                # raw counters only
                perf_measurements = self._perf_counters.get_measurements()
        else:
            perf_measurements = {}

        # RDT/resctrl measurements
        if self._rdt_information and self._rdt_information.is_monitoring_enabled():
            rdt_measurements = \
                self._resgroup.get_measurements(
                    self._name, self._rdt_information.rdt_mb_monitoring_enabled,
                    self._rdt_information.rdt_cache_monitoring_enabled)
        else:
            rdt_measurements = {}

        return flatten_measurements([
            cgroup_measurements,
            rdt_measurements,
            perf_measurements,
        ])

    def cleanup(self):
        if self._event_names:
            self._perf_counters.cleanup()
        if self._rdt_information:
            self._resgroup.remove(self._name)

    def get_allocations(self) -> TaskAllocations:
        allocations: TaskAllocations = dict()
        allocations.update(self._cgroup.get_allocations())
        if self._rdt_information and self._rdt_information.is_control_enabled():
            allocations.update(self._resgroup.get_allocations())

        log.debug('allocations on task=%r from resgroup=%r allocations:\n%s',
                  self._name, self._resgroup, pprint.pformat(allocations))

        return allocations


class ContainerManager:
    """Responsible for synchronizing state between found orchestration software tasks,
    their containers and resctrl system. """

    def __init__(self, rdt_information: Optional[RDTInformation], platform_cpus: int,
                 platform_sockets: int,
                 allocation_configuration: Optional[AllocationConfiguration],
                 event_names: List[str], enable_derived_metrics: bool = False):
        self.containers: Dict[Task, ContainerInterface] = {}
        self._rdt_information = rdt_information
        self._platform_cpus = platform_cpus
        self._platform_sockets = platform_sockets
        self._allocation_configuration = allocation_configuration
        self._event_names = event_names
        self._enable_derived_metrics = enable_derived_metrics

    def _create_container(self, task: Task) -> ContainerInterface:
        """Check whether the task groups multiple containers,
           is so use ContainerSet class, otherwise Container class.
           ContainerSet shares interface with Container."""
        if len(task.subcgroups_paths):
            container = ContainerSet(
                cgroup_path=task.cgroup_path,
                cgroup_paths=task.subcgroups_paths,
                rdt_information=self._rdt_information,
                platform_cpus=self._platform_cpus,
                platform_sockets=self._platform_sockets,
                allocation_configuration=self._allocation_configuration,
                event_names=self._event_names,
                enable_derived_metrics=self._enable_derived_metrics,
            )
        else:
            container = Container(
                cgroup_path=task.cgroup_path,
                rdt_information=self._rdt_information,
                platform_cpus=self._platform_cpus,
                platform_sockets=self._platform_sockets,
                allocation_configuration=self._allocation_configuration,
                event_names=self._event_names,
                enable_derived_metrics=self._enable_derived_metrics,
            )
        return container

    @profiler.profile_duration('sync_containers_state')
    def sync_containers_state(self, tasks: List[Task]) -> Dict[Task, ContainerInterface]:
        """Syncs state of ContainerManager with a system by removing orphaned containers,
        and creating containers for newly arrived tasks, and synchronizing containers' state.

        Function is responsible for cleaning and initializing stateful subsystems such as:
        - perf counters: opens file descriptors for counters,
        - resctrl (ResGroups): creates and manages directories in resctrl filesystem and scarce
            "closid" hardware identifiers

        Can throw OutOfClosidsException.
        """

        # Find difference between discovered tasks and already watched containers.
        new_tasks, containers_to_cleanup = _find_new_and_dead_tasks(
            tasks, list(self.containers.values()))

        if containers_to_cleanup:
            log.debug('sync_containers_state: cleaning up %d containers',
                      len(containers_to_cleanup))
            log.log(logger.TRACE, 'sync_containers_state: containers_to_cleanup=%r',
                    containers_to_cleanup)

            # Clean up and remove orphaned containers.
            for container_to_cleanup in containers_to_cleanup:
                container_to_cleanup.cleanup()

        # Recreate self.containers.
        # mutated state e.g. labels for Kubernetes
        containers = {}
        for task in tasks:
            for known_task, container in self.containers.items():
                if task.cgroup_path == known_task.cgroup_path:
                    containers[task] = container
                    continue
        self.containers = containers

        if new_tasks:
            log.debug('Found %d new tasks', len(new_tasks))
            log.log(logger.TRACE, 'sync_containers_state: new_tasks=%r', new_tasks)

        # Prepare state of currently assigned resgroups
        # and remove some orphaned resgroups.
        container_name_to_ctrl_group = {}
        if self._rdt_information:
            assert self._rdt_information.is_monitoring_enabled(), \
                "rdt_enabled requires RDT monitoring for keeping groups relation."
            mon_groups_relation = resctrl.read_mon_groups_relation()
            log.log(TRACE, 'mon_groups_relation (before cleanup): %s',
                    pprint.pformat(mon_groups_relation))
            resctrl.clean_taskless_groups(mon_groups_relation)

            mon_groups_relation = resctrl.read_mon_groups_relation()
            log.log(TRACE, 'mon_groups_relation (after cleanup): %s',
                    pprint.pformat(mon_groups_relation))

            # Calculate inverse relation of container_name
            # to res_group name based on mon_groups_relations.
            for ctrl_group, container_names in mon_groups_relation.items():
                for container_name in container_names:
                    container_name_to_ctrl_group[container_name] = ctrl_group
            log.log(TRACE, 'container_name_to_ctrl_group: %s',
                    pprint.pformat(container_name_to_ctrl_group))

        # Create new containers and store them.
        for new_task in new_tasks:
            self.containers[new_task] = self._create_container(new_task)

        # Sync "state" of individual containers.
        # Note: only pids are synchronized, not allocations.
        for container in self.containers.values():
            if self._rdt_information:
                if container.get_name() in container_name_to_ctrl_group:
                    resgroup_name = container_name_to_ctrl_group[container.get_name()]
                    container.set_resgroup(ResGroup(name=resgroup_name))
                else:
                    # Every newly detected container is first assigned to the root group.
                    container.set_resgroup(ResGroup(name=''))
            container.sync()

        log.log(logger.TRACE, 'sync_containers_state: containers=%r', self.containers)

        return self.containers

    def cleanup(self):
        for container in self.containers.values():
            container.cleanup()


def _find_new_and_dead_tasks(
        discovered_tasks: List[Task], known_containers: List[Container]
) -> (List[Task], List[Container]):
    """Returns the of newly discovered tasks and containers without tasks,
    by comparing running tasks against list of known containers.

    Assumptions:
    * One-to-one relationship between task and container
    * cgroup_path for task and container need to be identical to establish the relationship
    * cgroup_path is unique for each task

    :returns
    - list of tasks to start watching
    - orphaned containers to clean up
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
