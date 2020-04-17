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
import itertools
import random
from collections import defaultdict
from typing import List, Dict, Set

from wca.scheduler.cluster_simulator import Task
from wca.scheduler.types import ResourceType as ResourceType, NodeName


def extend_membw_dimensions_to_write_read(taskset):
    """replace dimensions rt.MEMBW with rt.MEMBW_WRITE and rt.MEMBW_READ"""
    new_taskset = []
    for task in taskset:
        task_ = task.copy()
        membw = task_.requested.data[ResourceType.MEMBW]
        task_.remove_dimension(ResourceType.MEMBW)
        task_.add_dimension(ResourceType.MEMBW_READ, membw)
        task_.add_dimension(ResourceType.MEMBW_WRITE, 0)
        new_taskset.append(task_)
    return new_taskset


def randomly_choose_from_taskset(taskset, size, seed):
    random.seed(seed)
    r = []
    for i in range(size):
        random_idx = random.randint(0, len(taskset) - 1)
        task = taskset[random_idx].copy()
        task.name += Task.CORE_NAME_SEP + str(i)
        r.append(task)
    return r


def randomly_choose_from_taskset_single(taskset, dimensions, name_suffix):
    random_idx = random.randint(0, len(taskset) - 1)
    task = taskset[random_idx].copy()
    task.name += Task.CORE_NAME_SEP + str(name_suffix)

    task_dim = set(task.requested.data.keys())
    dim_to_remove = task_dim.difference(dimensions)
    for dim in dim_to_remove:
        task.remove_dimension(dim)

    return task


class TaskGenerator:

    def __call__(self, index: int) -> Task:
        raise NotImplementedError


class TaskGeneratorRandom(TaskGenerator):
    """Takes randomly from given task_definitions"""

    def __init__(self, task_definitions, max_items, seed):
        self.max_items = max_items
        self.task_definitions = task_definitions
        random.seed(seed)

    def __call__(self, index: int):
        if index >= self.max_items:
            return None
        return self.rand_from_taskset(str(index))

    def rand_from_taskset(self, name_suffix: str):
        return randomly_choose_from_taskset_single(
            extend_membw_dimensions_to_write_read(self.task_definitions),
            {ResourceType.CPU, ResourceType.MEM, ResourceType.MEMBW_READ, ResourceType.MEMBW_WRITE},
            name_suffix)


class TaskGeneratorClasses(TaskGenerator):
    """Multiple each possible kind of tasks by replicas"""

    def __init__(self, task_definitions: List[Task], counts: Dict[str, int], dimensions=None,
                 class_node_names: Dict[str, NodeName] = None
                 ):
        self.counts = counts
        self.tasks = []
        if dimensions is not None:
            self.task_definitions = taskset_dimensions(dimensions, task_definitions)
        else:
            self.task_definitions = task_definitions

        # default node binding for each class
        class_node_names = class_node_names or {}

        classes = defaultdict(list)  # task_name: List[Tasks]
        for task_def_name, replicas in counts.items():
            for task_def in self.task_definitions:
                if task_def.name == task_def_name:
                    for r in range(replicas):
                        task_copy = task_def.copy()
                        task_copy.name += Task.CORE_NAME_SEP + str(r)
                        task_copy.node_name = class_node_names.get(task_def_name)
                        classes[task_def_name].append(task_copy)

        # merge with zip
        for tasks in itertools.zip_longest(*classes.values()):
            self.tasks.extend(filter(None, tasks))

    def __call__(self, index: int):
        if self.tasks:
            return self.tasks.pop()
        return None

    def __str__(self):
        total_tasks = sum(self.counts.values())
        kinds = ','.join([
            '%s=%s' % (task_def_name, count)
            for task_def_name, count in self.counts.items()])
        return '%d(%s)' % (total_tasks, kinds)


class TaskGeneratorEqual(TaskGenerator):
    """Multiple each possible kind of tasks by replicas"""

    def __init__(self, task_definitions: List[Task], replicas, alias=None,
                 duration=None, dimensions=None, node_name: NodeName = None):
        self.replicas = replicas
        self.tasks = []
        self.task_definitions = task_definitions
        self.alias = alias
        self.duration = duration

        if dimensions is not None:
            task_definitions = taskset_dimensions(dimensions, task_definitions)

        for r in range(replicas):
            for task_def in task_definitions:
                task_copy = task_def.copy()
                task_copy.duration = self.duration
                task_copy.name += Task.CORE_NAME_SEP + str(r)
                task_copy.node_name = node_name
                self.tasks.append(task_copy)

    def __call__(self, index: int):
        if self.tasks:
            return self.tasks.pop()
        return None

    def __str__(self):
        if self.alias is not None:
            return self.alias
        total_tasks = len(self.task_definitions) * self.replicas
        kinds = ','.join(['%s=%s' % (task_def.name, self.replicas)
                          for task_def in sorted(self.task_definitions, key=lambda t: t.name)])
        return '%d(%s)' % (total_tasks, kinds)


def taskset_dimensions(dimensions: Set[ResourceType], taskset):
    new_taskset = []
    dimensions_to_remove = set(taskset[0].requested.data.keys()).difference(dimensions)
    for task in taskset:
        task_copy = task.copy()
        for dim in dimensions_to_remove:
            task_copy.remove_dimension(dim)
        new_taskset.append(task_copy)
    return new_taskset
