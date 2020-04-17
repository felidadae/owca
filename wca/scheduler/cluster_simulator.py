# Copyright (c) 2020 Intel Corporation
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
from typing import Dict, List, Optional

from dataclasses import dataclass

from wca.logger import TRACE
from wca.scheduler.algorithms import Algorithm, RescheduleResult
from wca.scheduler.types import ExtenderArgs, NodeName
from wca.scheduler.types import ResourceType

log = logging.getLogger(__name__)


class Resources:
    """Wrapper over dict to support some useful operations like subtract/add/divide."""

    def __init__(self, resources: Dict[ResourceType, float], membw_ratio=1):
        """membw_ratio: ratio of MEMBW_READ / MEMBW_WRITE."""
        self.data = resources

    def __repr__(self):
        return repr(self.data)

    @staticmethod
    def create_empty(dimensions):
        return Resources({d: 0 for d in dimensions})

    def copy(self):
        r = Resources({})
        r.data = self.data.copy()
        return r

    def __bool__(self):
        return all([val > 0 or abs(val) < 0.0001 for val in self.data.values()])

    def __sub__(self, other):
        me = self.copy()
        me.subtract(other)
        return me

    def subtract(self, b):
        """simply loops over all dimensions and use - operator"""
        assert set(self.data.keys()) == set(b.data.keys())
        for key in self.data.keys():
            self.data[key] -= b.data[key]

    def subtract_aep_aware(self, b, membw_read_write_ratio):
        """Mutates self. """
        self_keys = set(self.data.keys())
        b_keys = set(b.data.keys())
        assert self_keys == b_keys, 'two different set of keys for resources %s vs %s' % (
            self_keys, b_keys)
        for key in self.data.keys():
            if key == ResourceType.MEMBW_READ or key == ResourceType.MEMBW_WRITE:
                continue
            self.data[key] -= b.data[key]

        # Special case for MEMBW
        if ResourceType.MEMBW_READ in self.data and ResourceType.MEMBW_WRITE in self.data:
            READ = ResourceType.MEMBW_READ
            WRITE = ResourceType.MEMBW_WRITE
            x = self.data
            y = b.data
            # mirror calculations for WRITE from READ; that are not two separate dimensions;
            x[READ] = x[READ] - y[READ] - y[WRITE] * membw_read_write_ratio
            x[WRITE] = x[WRITE] - y[WRITE] - y[READ] / membw_read_write_ratio

    def __add__(self, other):
        me = self.copy()
        me.add(other)
        return me

    def add(self, b):
        """simply loops over all dimensions and use + operator"""
        assert set(self.data.keys()) == set(b.data.keys())
        for key in self.data.keys():
            self.data[key] += b.data[key]

    @staticmethod
    def sum(array):
        r = Resources.create_empty(list(array[0].data.keys()))
        for el in array:
            r = r + el
        return r

    def __truediv__(self, other):
        me = self.copy()
        me.divide(other)
        return me

    def divide(self, b):
        assert set(self.data.keys()) == set(b.data.keys())
        for key in self.data.keys():
            self.data[key] /= b.data[key]


class Task:
    def __init__(self, name, requested, duration=None, assignment=None, node_name: NodeName = None):
        self.name: str = name
        # assigment is binding done by scheudler and algorithm
        self.assignment: Node = assignment
        # node name simulates nodeName fomr K8S, which means binding without scheduler
        # https://kubernetes.io/docs/concepts/configuration/assign-pod-node/#nodename
        self.node_name: NodeName = node_name
        self.requested: Resources = requested
        self.life_time: int = 0
        self.duration: int = duration

    def __hash__(self):
        return id(self.name)

    def remove_dimension(self, resource_type: ResourceType):
        """Post-creation removal of one of the dimensions."""
        del self.requested.data[resource_type]

    def add_dimension(self, resource_type: ResourceType, requested_val):
        """Post-creation addition of a dimension."""
        self.requested.data[resource_type] = requested_val

    CORE_NAME_SEP = '___'

    def get_core_name(self):
        if self.CORE_NAME_SEP in self.name:
            return self.name[:self.name.find(self.CORE_NAME_SEP)]
        return self.name

    def update(self):
        """Update state of task when it becomes older by delta_time."""
        if self.assignment is not None:
            self.life_time += 1
            if self.duration is not None and self.life_time > self.duration:
                log.debug('task=%r end of life - unassigned', self.name)
                self.assignment = None

    def __repr__(self):
        return "Task(name: {}, assignment: {}, requested: {})".format(
            self.name, 'None' if self.assignment is None else self.assignment.name,
            str(self.requested))

    def copy(self):
        return Task(self.name, self.requested.copy(), None)


class Node:
    """
        initial - all available
        unassigned - free/unassigned memory (modified every update)
    """

    def __init__(self, name, available_resources):
        self.name = name
        self.initial = available_resources
        self.unassigned = available_resources.copy()

    def __repr__(self):
        return "Node(name: {}, initial: {})".format(self.name, str(self.initial))

    def get_membw_read_write_ratio(self):
        d_ = self.initial.data
        if ResourceType.MEMBW_READ in d_ and ResourceType.MEMBW_WRITE in d_:
            return d_[ResourceType.MEMBW_READ] / d_[ResourceType.MEMBW_WRITE]
        return 1

    def _calculate_unassigned(self, tasks) -> Resources:
        unassigned: Resources = self.initial.copy()
        for task in tasks:
            if task.assignment == self:
                unassigned.subtract_aep_aware(
                    task.requested, self.get_membw_read_write_ratio())
        return unassigned

    def validate_assignment(self, tasks, new_task):
        """Check if there is enough resources on the node for a >>new_task<<."""
        unassigned = self._calculate_unassigned(tasks)
        unassigned.subtract_aep_aware(new_task.requested, self.get_membw_read_write_ratio())
        return bool(unassigned)


@dataclass
class ClusterSimulator:
    tasks: List[Task]
    nodes: List[Node]
    algorithm: Algorithm
    allow_rough_assignment: bool = True
    # If there is no new tasks, should it try reassign unassigned tasks.
    retry_scheduling: bool = False

    def __post_init__(self):
        self.rough_assignments_per_node: Dict[Node, int] = {node: 0 for node in self.nodes}

    def get_task_by_name(self, task_name: str) -> Optional[Task]:
        filtered = [task for task in self.tasks if task.name == task_name]
        assert len(filtered) == 1
        return filtered[0] if filtered else None

    def get_node_by_name(self, node_name: str) -> Optional[Node]:
        filtered = [node for node in self.nodes if node.name == node_name]
        assert len(filtered) == 1
        return filtered[0] if filtered else None

    def _get_dimensions_from_first_node(self):
        return self.nodes[0].initial.data.keys()

    def per_node_resource_usage(self, if_percentage: bool = False) -> Dict[Node, Resources]:
        """if_percentage: if output in percentage or original resource units"""
        first_node_dimensions = self._get_dimensions_from_first_node()
        node_resource_usage = {node: Resources.create_empty(first_node_dimensions) for node in
                               self.nodes}
        for task in self.tasks:
            if task.assignment is None:
                continue
            node_resource_usage[task.assignment] += task.requested

        if if_percentage:
            return {node: node_resource_usage[node] / node.initial
                    for node in node_resource_usage.keys()}
        node_usage = {node: node_resource_usage[node] for node in node_resource_usage.keys()}
        log.log(TRACE, 'Per node resource usage: %r', {n.name: u for n, u in node_usage.items()})
        return node_usage

    def cluster_resource_usage(self, if_percentage: bool = False) -> Dict[Node, Resources]:
        node_resource_usage = self.per_node_resource_usage()

        r = Resources.sum([usage for usage in node_resource_usage.values()])
        if if_percentage:
            r = r / Resources.sum([node.initial for node in self.nodes])
        return r

    def update_tasks_life(self):
        for task in self.tasks:
            task.update()

    def perform_assignment(self, task, node) -> bool:
        """Perform binding with rough_assigment_check"""
        # Taking all dimensions supported by Simulator whether the app fit the node.
        task_fits_node = node.validate_assignment(self.tasks, task)
        if task_fits_node or self.allow_rough_assignment:
            task.assignment = node
            if not task_fits_node:
                self.rough_assignments_per_node[node] += 1
            return True
        return False

    def call_scheduler(self, new_task: Task) -> Node:
        """To map simulator structure into required by scheduler.Algorithm interface.
        Returns task_name -> node_name.
        """

        log.log(TRACE, "State before calling scheduler; new_task={}; nodes={}".format(
            new_task, self.nodes))

        node_names = [node.name for node in self.nodes]
        pod = {'metadata': {'labels': {'app': new_task.get_core_name()},
                            'name': new_task.name, 'namespace': 'default'}}
        extender_args = ExtenderArgs([], pod, node_names)

        extender_filter_result = self.algorithm.filter(extender_args)
        filtered_nodes = [node for node in extender_args.NodeNames
                          if node not in extender_filter_result.FailedNodes]
        log.log(TRACE, "Nodes left after filtering: ({})".format(','.join(filtered_nodes)))

        extender_args.NodeNames = filtered_nodes  # to prioritize pass only filtered nodes
        extender_prioritize_result = self.algorithm.prioritize(extender_args)
        priorities_str = ','.join(["{}:{}".format(el.Host, str(el.Score))
                                   for el in extender_prioritize_result])
        log.log(TRACE, "Priorities of nodes: ({})".format(priorities_str))
        if extender_prioritize_result:
            best_node = max(extender_prioritize_result, key=lambda el: el.Score).Host
        else:
            best_node = None
        log.debug("Best node chosen in prioritize step: {}".format(best_node))

        if best_node is None:
            return None
        return self.get_node_by_name(best_node)

    def iterate(self, new_tasks) -> int:
        log.debug("--- Iteration starts ---")

        # Handle new
        log.debug("New_tasks={}".format(new_tasks))
        new_unassigned_tasks = []
        for new_task in new_tasks:
            self.tasks.append(new_task)
            if new_task.node_name is not None:
                node = self.get_node_by_name(new_task.node_name)
                assert node is not Node
                new_task.assignment = node
                new_task.node_name = None  # node_name bindings happens only once
                log.debug('iteration: %s -> node=%s (by node_name)', new_task.name, node.name)
            else:
                new_unassigned_tasks.append(new_task)

        # Retry scheduling for unassigned tasks.
        if not new_unassigned_tasks and self.retry_scheduling:
            unassigned_tasks = [task for task in self.tasks if task.assignment is None]
            if unassigned_tasks:
                log.debug('Rescheduling unassigned tasks: %s', [t.name for t in unassigned_tasks])
        else:
            unassigned_tasks = new_unassigned_tasks

        assigned_count = 0  # required by tests
        if unassigned_tasks:
            # Assignments
            assignments = {}
            for task in unassigned_tasks:
                node = self.call_scheduler(task)
                if node is not None:
                    assignments[task] = node
                    assigned_count += self.perform_assignment(task, node)

            log.log(TRACE, "Tried assignments %r: successful = %d" % (assignments, assigned_count))
        elif not new_tasks:
            # Rescheduling - unassign task from given nodes.
            reschedule_result: RescheduleResult = self.algorithm.reschedule()

            if reschedule_result:
                for task_name_to_remove in reschedule_result:
                    task = self.get_task_by_name(task_name_to_remove)
                    task.assignment = None

        # Can unbind tasks if task lived long enough.
        self.update_tasks_life()

        log.debug("--- Iteration ends ---")
        return assigned_count

    def iterate_single_task(self, new_task: Optional[Task]):
        """Try to assign new_task"""
        new_tasks = [] if new_task is None else [new_task]
        if new_task is not None:
            assert new_task.name not in set([task.name for task in self.tasks]), \
                'Tasks names must be unique, use suffixes'
            assert new_task not in self.tasks, \
                'Each Task must be separate object (deep copy)'

        return self.iterate(new_tasks=new_tasks)
