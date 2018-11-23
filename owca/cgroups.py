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
import os
from typing import Optional

from dataclasses import dataclass

from owca import logger
from owca.allocators import TaskAllocations, AllocationType, AllocationConfiguration
from owca.metrics import Measurements, MetricName

log = logging.getLogger(__name__)

CPU_USAGE = 'cpuacct.usage'
CPU_QUOTA = 'cpu.cfs_quota_us'
CPU_PERIOD = 'cpu.cfs_period_us'
CPU_SHARES = 'cpu.shares'
BASE_SUBSYSTEM_PATH = '/sys/fs/cgroup/cpu'

@dataclass
class Cgroup:

    cgroup_path: str

    # Values used for normlization of allocations
    platform_cpus: int  # required for quota normalization
    allocation_configuration: Optional[AllocationConfiguration] = None

    def __post_init__(self):
        assert self.cgroup_path.startswith('/'), 'Provide cgroup_path with leading /'
        relative_cgroup_path = self.cgroup_path[1:]  # cgroup path without leading '/'
        self.cgroup_fullpath = os.path.join(BASE_SUBSYSTEM_PATH, relative_cgroup_path)

    def get_measurements(self) -> Measurements:

        with open(os.path.join(self.cgroup_fullpath, CPU_USAGE)) as \
                cpu_usage_file:
            cpu_usage = int(cpu_usage_file.read())

        return {MetricName.CPU_USAGE_PER_TASK: cpu_usage}

    def _read(self, cgroup_control_file: str) -> int:
        """Read helper to store any and convert value from cgroup control file."""
        with open(os.path.join(self.cgroup_fullpath, cgroup_control_file)) as f:
            return int(f.read())

    def _write(self, cgroup_control_file: str, value: int):
        """Write helper to store any int value in cgroup control file."""
        with open(os.path.join(self.cgroup_fullpath, cgroup_control_file)) as f:
            log.log(logger.TRACE)
            f.write(str(value))

    def _get_normalized_shares(self) -> float:
        """Return normalized using cpu_shreas_min and cpu_shares_max for normalization."""
        shares = self._read(CPU_SHARES)
        return (shares - self.allocation_configuration.cpu_shares_min) / \
               self.allocation_configuration.cpu_shares_max

    def _set_normalized_shares(self, shares_normalized):
        """Store shares normalized values in cgroup files system. For denormalization
        we use reverse formule to _get_normalized_shares."""
        assert self.allocation_configuration is not None, \
            'allocation configuration cannot be used without configuration!'
        shares = (shares_normalized * self.allocation_configuration.pu_shares_max) + \
                 self.allocation_configuration.cpu_shares_min
        self._write(CPU_SHARES, shares)

    def _get_normalized_quota(self) -> float:
        current_quota = self._read(CPU_QUOTA)
        current_period = self._read(CPU_PERIOD)
        if current_quota == -1:
            return float('Inf')  # quota is not set (TODO: consider using 0)
        # Period 0 is invalid arugment for cgroup cpu subsystem. so division is safe.
        return current_quota / current_period / self.platform_cpus

    def _set_normalized_quota(self, quota_normalized: float):
        """Unconditionally sets quota and period if nessesary."""
        assert self.allocation_configuration is not None, \
            'allocation configuration cannot be used without configuration!'
        current_period = self._read(CPU_PERIOD)

        # synchornize quota if nessesary
        if current_period != self.allocation_configuration.cpu_quota_period:
            self._write(CPU_QUOTA, self.allocation_configuration.cpu_quota_period)
        quota = quota_normalized * self.allocation_configuration.cpu_quota_period * \
                self.platform_cpus
        self._write(CPU_QUOTA, quota)

    def get_allocations(self) -> TaskAllocations:
        return {
           AllocationType.QUOTA: self._get_normalized_quota(),
           AllocationType.SHARES: self._get_normalized_shares(),
        }

    def perform_allocations(self, allocations: TaskAllocations):
        if AllocationType.QUOTA in allocations:
            self._set_normalized_quota(allocations[AllocationType.QUOTA])
        if AllocationType.SHARES in allocations:
            self._set_normalized_shares(allocations[AllocationType.SHARES])

