from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import List, Dict, Union

from owca.metrics import Metric
from owca.mesos import TaskId
from owca.platforms import Platform
from owca.detectors import TasksMeasurements, TasksResources, TasksLabels, Anomaly


class AllocationType(Enum, str):

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
    cpu_quota_period : int = 100

    # Number of minimum shares, when ``cpu_shares`` allocation is set to 0.0.
    cpu_min_shares: int = 2
    # Number of shares to set, when ``cpu_shares`` allocation is set to 1.0.
    cpu_max_shares: int = 10000



class Allocator(ABC):

    @abstractmethod
    def allocate(
            self,
            platform: Platform,
            tasks_measurements: TasksMeasurements,
            tasks_resources: TasksResources,
            tasks_labels: TasksLabels,
            tasks_allocations: TaskAllocations,
    ) -> (TasksAllocations, List[Anomaly], List[Metric]):
        ...


class NOPAllocator:

    def detect(self, platform, tasks_measurements, tasks_resources,
               tasks_labels, task_allocations):
        return [], [], []

