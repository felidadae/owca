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
from dataclasses import dataclass
from enum import Enum
from typing import List, Dict, Union, Tuple, Optional

from owca.metrics import Metric
from owca.mesos import TaskId
from owca.platforms import Platform
from owca.detectors import TasksMeasurements, TasksResources, TasksLabels, Anomaly
import logging

log = logging.getLogger(__name__)


class AllocationType(str, Enum):

    QUOTA = 'cpu_quota'
    SHARES = 'cpu_shares'
    RDT = 'rdt'


@dataclass
class RDTAllocation:
    # defaults to TaskId from TasksAllocations
    name: str = None
    # CAT: optional - when no provided doesn't change the existing allocation
    l3: str = None
    # MBM: optional - when no provided doesn't change the existing allocation
    mb: str = None


TaskAllocations = Dict[AllocationType, Union[float, RDTAllocation]]
TasksAllocations = Dict[TaskId, TaskAllocations]


@dataclass
class AllocationConfiguration:

    # Default value for cpu.cpu_period [ms] (used as denominator).
    cpu_quota_period: int = 1000

    # Number of minimum shares, when ``cpu_shares`` allocation is set to 0.0.
    cpu_shares_min: int = 2
    # Number of shares to set, when ``cpu_shares`` allocation is set to 1.0.
    cpu_shares_max: int = 10000

    # Default Allocation for default root group
    default_rdt_allocation: RDTAllocation = None


class Allocator(ABC):

    @abstractmethod
    def allocate(
            self,
            platform: Platform,
            tasks_measurements: TasksMeasurements,
            tasks_resources: TasksResources,
            tasks_labels: TasksLabels,
            tasks_allocations: TasksAllocations,
    ) -> (TasksAllocations, List[Anomaly], List[Metric]):
        ...


class NOPAllocator(Allocator):

    def allocate(self, platform, tasks_measurements, tasks_resources,
                 tasks_labels, tasks_allocations):
        return [], [], []


# @TODO remove from code
class TestingAllocator(Allocator):
    def __init__(self):
        self.testing_allocator_mode_index = 0
        self.testing_allocator_modes = ['empty', 
                                        'one_group', 
                                        'seperate_group', 
                                        'all_in_root_group', 
                                        'empty']

    def allocate(
            self,
            platform: Platform,
            tasks_measurements: TasksMeasurements,
            tasks_resources: TasksResources,
            tasks_labels: TasksLabels,
            tasks_allocations: TasksAllocations,
    ) -> (TasksAllocations, List[Anomaly], List[Metric]):
        testing_allocator_mode = self.testing_allocator_modes[self.testing_allocator_mode_index]
        log.debug('TestingAllocator mode is {}'.format(testing_allocator_mode))
        self.testing_allocator_mode_index = (self.testing_allocator_mode_index + 1)
        if self.testing_allocator_mode_index == 5:
            exit(1)

        new_tasks_allocations = {}
        if testing_allocator_mode == 'empty':
            return [], [], []
        elif testing_allocator_mode == 'one_group':
            for task_id in tasks_resources:
                new_tasks_allocations[task_id] = {
                    AllocationType.QUOTA: 1000,
                    AllocationType.RDT: RDTAllocation(name='only_group', l3='L3:0=00fff;1=0ffff')
                }
        elif testing_allocator_mode == 'seperate_group':
            for task_id in tasks_resources:
                new_tasks_allocations[task_id] = {
                    AllocationType.QUOTA: 2000,
                    AllocationType.RDT: RDTAllocation()
                }
        elif testing_allocator_mode == 'all_in_root_group':
            for task_id in tasks_resources:
                new_tasks_allocations[task_id] = {
                    AllocationType.QUOTA: 2000,
                    AllocationType.RDT: RDTAllocation(name='')
                }

        return (new_tasks_allocations, [], [])



# -----------------------------------------------------------------------
# private logic to handle allocations
# -----------------------------------------------------------------------


def convert_allocations_to_metrics(allocations) -> List[Metric]:
    # TODO: convenrt allocations to metrics
    return []


def _merge_rdt_allocation(old_rdt_allocation: Optional[RDTAllocation],
                          new_rdt_allocation: RDTAllocation)\
        -> Tuple[RDTAllocation, RDTAllocation]:
    # new name, then new allocation will be used (overwrite) but no merge
    if old_rdt_allocation is None or old_rdt_allocation.name != new_rdt_allocation.name:
        return new_rdt_allocation, new_rdt_allocation
    else:
        all_rdt_allocation = RDTAllocation(
            name=old_rdt_allocation.name,
            l3=new_rdt_allocation.l3 or old_rdt_allocation.l3,
            mb=new_rdt_allocation.mb or old_rdt_allocation.mb,
         )
        resulting_rdt_allocation = RDTAllocation(
            name=new_rdt_allocation.name,
            l3=new_rdt_allocation.l3,
            mb=new_rdt_allocation.mb,
        )
        return all_rdt_allocation, resulting_rdt_allocation


def _calculate_task_allocations(
        old_task_allocations: TaskAllocations,
        new_task_allocations: TaskAllocations)\
        -> Tuple[TaskAllocations, TaskAllocations]:
    """Return allocations difference on single task level.
    all - are the sum of existing and new
    resulting - are just new allocaitons
    """
    all_task_allocations: TaskAllocations = dict(old_task_allocations)
    resulting_task_allocations: TaskAllocations = {}

    for allocation_type, value in new_task_allocations.items():
        # treat rdt diffrently
        if allocation_type == AllocationType.RDT:
            old_rdt_allocation = old_task_allocations.get(AllocationType.RDT)
            all_rdt_allocation, resulting_rdt_allocation = \
                _merge_rdt_allocation(old_rdt_allocation, value)
            all_task_allocations[AllocationType.RDT] = all_rdt_allocation
            resulting_task_allocations[AllocationType.RDT] = resulting_rdt_allocation
        else:
            all_task_allocations[allocation_type] = value

    resulting_task_allocations: TaskAllocations = new_task_allocations
    return all_task_allocations, resulting_task_allocations


def _calculate_tasks_allocations(
        old_tasks_allocations: TasksAllocations, new_tasks_allocations: TasksAllocations) \
        -> Tuple[TasksAllocations, TasksAllocations]:
    """Return all_allocations that are the effect on applied new_allocations on
    old_allocations, additionally returning allocations that need to be applied just now.
    """
    all_tasks_allocations: TasksAllocations = {}
    resulting_tasks_allocations: TasksAllocations = {}

    # check and merge & overwrite with old allocations
    for task_id, old_task_allocations in old_tasks_allocations.items():
        if task_id in new_tasks_allocations:
            new_task_allocations = new_tasks_allocations[task_id]
            all_task_allocations, resulting_task_allocations = _calculate_task_allocations(
                old_task_allocations, new_task_allocations)
            all_tasks_allocations[task_id] = all_task_allocations
            resulting_tasks_allocations[task_id] = resulting_task_allocations
        else:
            all_tasks_allocations[task_id] = old_task_allocations

    # if there are any new_allocations on task level that yet not exists in old_allocations
    # then just add them to both list
    only_new_tasks_ids = set(new_tasks_allocations) - set(old_tasks_allocations)
    for only_new_task_id in only_new_tasks_ids:
        task_allocations = new_tasks_allocations[only_new_task_id]
        all_tasks_allocations[only_new_task_id] = task_allocations
        resulting_tasks_allocations[only_new_task_id] = task_allocations

    return all_tasks_allocations, resulting_tasks_allocations
