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
from abc import ABC, abstractmethod
from enum import Enum
from typing import List, Dict, Union, Optional

from dataclasses import dataclass

from wca.config import Numeric, Str
from wca.detectors import TasksData, Anomaly
from wca.metrics import Metric
from wca.nodes import TaskId
from wca.platforms import Platform

log = logging.getLogger(__name__)


class AllocationType(str, Enum):
    QUOTA = 'cpu_quota'
    SHARES = 'cpu_shares'
    RDT = 'rdt'
    CPUSET_CPUS = 'cpuset_cpus'
    CPUSET_MEMS = 'cpuset_mems'
    CPUSET_MEMORY_MIGRATE = 'cpuset_memory_migrate'
    MIGRATE_PAGES = 'migrate_pages'

    def __repr__(self):
        return repr(self.value)


@dataclass(unsafe_hash=True, frozen=True)
class RDTAllocation:
    # defaults to TaskId from TasksAllocations
    name: Optional[str] = None
    # CAT: optional - when no provided doesn't change the existing allocation
    # e.g. 0:01100,1:001
    l3: Str = None
    # MBM: optional - when no provided doesn't change the existing allocation
    # eg. '0:20,1:80'
    mb: Str = None


TaskAllocations = Dict[AllocationType, Union[float, int, RDTAllocation, str]]
TasksAllocations = Dict[TaskId, TaskAllocations]


@dataclass
class AllocationConfiguration:
    """rst

    - ``cpu_quota_period``: **Numeric** = *1000*

        Default value for cpu.cpu_period [ms] (used as denominator).

    - ``cpu_shares_unit``: **Numeric** = *1000*

        Multiplier of AllocationType.CPU_SHARES allocation value.
        E.g. setting 'CPU_SHARES' to 2.0 will set 2000 shares effectively
        in cgroup cpu controller.

    - ``default_rdt_l3``: **Str** = *None*

        Default resource allocation for last level cache (L3)
        for root RDT group. Root RDT group is used as default group for all tasks,
        unless explicitly reconfigured by allocator.
        `None` (the default value) means no limit (effectively set to maximum available value).

    - ``default_rdt_mb``: **Str** = *None*

        Default resource allocation for memory bandwitdh
        for root RDT group. Root RDT group is used as default group for all tasks,
        unless explicitly reconfigured by allocator.
        `None` (the default value) means no limit (effectively set to maximum available value).

    """
    # Default value for cpu.cpu_period [ms] (used as denominator).
    cpu_quota_period: Numeric(1000, 1000000) = 1000

    # Multiplier of AllocationType.CPU_SHARES allocation value.
    # E.g. setting 'CPU_SHARES' to 2.0 will set 2000 shares effectively
    # in cgroup cpu controller.
    cpu_shares_unit: Numeric(1000, 1000000) = 1000

    # Default resource allocation for last level cache (L3) and memory bandwidth
    # for root RDT group.
    # Root RDT group is used as default group for all tasks, unless explicitly reconfigured by
    # allocator.
    # `None` (the default value) means no limit (effectively set to maximum available value).
    default_rdt_l3: Str = None
    default_rdt_mb: Str = None


class Allocator(ABC):

    @abstractmethod
    def allocate(
            self,
            platform: Platform,
            tasks_data: TasksData
    ) -> (TasksAllocations, List[Anomaly], List[Metric]):
        """Resource allocation callback method, responsible for returning information
        how resources should be allocated.

        To make optimal decisions allocate method can use all provided information about
        platform, platform metrics and tasks' initially assigned resources, tasks'
        current resource usage (measurements), tasks' metadata (labels) and current configured
        allocations.

        For debugging purposes and accountability method can additionally return:
        - detected anomalies (that were used as input for allocation logic),
        - any helpful metrics (e.g. derived metrics)
        """


class NOPAllocator(Allocator):
    """
    Dummy allocator which does nothing.
    """

    def allocate(self, platform, tasks_data):
        return {}, [], []
