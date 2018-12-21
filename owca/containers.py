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


from typing import List, Optional

from dataclasses import dataclass

from owca.allocators import AllocationConfiguration, TaskAllocations
from owca.resctrl import ResGroup
from owca.cgroups import Cgroup
from owca.perf import PerfCounters
from owca.metrics import Measurements, MetricName


DEFAULT_EVENTS = (MetricName.INSTRUCTIONS, MetricName.CYCLES, MetricName.CACHE_MISSES)


def flatten_measurements(measurements: List[Measurements]):
    all_measurements_flat = dict()

    for measurement in measurements:
        assert not set(measurement.keys()) & set(all_measurements_flat.keys()), \
            'When flatting measurements the keys should not overlap!'
        all_measurements_flat.update(measurement)
    return all_measurements_flat


@dataclass
class Container:

    cgroup_path: str
    platform_cpus: int
    allocation_configuration: Optional[AllocationConfiguration] = None
    rdt_enabled: bool = True

    def __post_init__(self):
        self.cgroup = Cgroup(
            self.cgroup_path,
            platform_cpus=self.platform_cpus,
            allocation_configuration=self.allocation_configuration,
        )
        self.perf_counters = PerfCounters(self.cgroup_path, event_names=DEFAULT_EVENTS)
        self.resgroup = ResGroup(self.cgroup_path) if self.rdt_enabled else None

    def sync(self):
        if self.rdt_enabled:
            self.resgroup.sync()

    def get_measurements(self) -> Measurements:
        return flatten_measurements([
            self.cgroup.get_measurements(),
            self.resgroup.get_measurements() if self.rdt_enabled else {},
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
