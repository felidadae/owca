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
from typing import Optional, List

from dataclasses import dataclass

from owca import logger
from owca.allocators import TaskAllocations, AllocationType, AllocationConfiguration
from owca.metrics import Measurements, MetricName

log = logging.getLogger(__name__)

CPU_USAGE = 'cpuacct.usage'
CPU_QUOTA = 'cpu.cfs_quota_us'
CPU_PERIOD = 'cpu.cfs_period_us'
CPU_SHARES = 'cpu.shares'
TASKS = 'tasks'
BASE_SUBSYSTEM_PATH = '/sys/fs/cgroup/cpu'

QUOTA_CLOSE_TO_ZERO_SENSITIVITY = 0.01


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
            v = int(f.read())
            log.log(logger.TRACE, 'cgroup: read %s=%r', f.name, v)
            return v

    def _write(self, cgroup_control_file: str, value: int):
        """Write helper to store any int value in cgroup control file."""
        with open(os.path.join(self.cgroup_fullpath, cgroup_control_file), 'wb') as f:
            raw_value = bytes(str(value), encoding='utf8')
            log.log(logger.TRACE, 'cgroup: write %s=%r', f.name, raw_value)
            f.write(raw_value)

    def _get_normalized_shares(self) -> float:
        """Return normalized using cpu_shreas_min and cpu_shares_unit for normalization."""
        assert self.allocation_configuration is not None, \
            'normalization configuration cannot be used without configuration!'
        shares = self._read(CPU_SHARES)
        return (shares / self.allocation_configuration.cpu_shares_unit)

    def set_normalized_shares(self, shares_normalized):
        """Store shares normalized values in cgroup files system. For denormalization
        we use reverse formule to _get_normalized_shares."""
        assert self.allocation_configuration is not None, \
            'allocation configuration cannot be used without configuration!'

        shares = int(shares_normalized * self.allocation_configuration.cpu_shares_unit)
        if shares < 2:
            shares = 2

        self._write(CPU_SHARES, shares)

    def get_normalized_quota(self) -> float:
        """Read normlalized quota against configured period and number of available cpus."""
        assert self.allocation_configuration is not None, \
            'normalization configuration cannot be used without configuration!'
        current_quota = self._read(CPU_QUOTA)
        current_period = self._read(CPU_PERIOD)
        if current_quota == -1:
            return 1.0
        # Period 0 is invalid arugment for cgroup cpu subsystem. so division is safe.
        return current_quota / current_period / self.platform_cpus

    def set_normalized_quota(self, quota_normalized: float):
        """Unconditionally sets quota and period if nessesary."""
        assert self.allocation_configuration is not None, \
            'setting quota cannot be used without configuration!'
        current_period = self._read(CPU_PERIOD)

        if current_period != self.allocation_configuration.cpu_quota_period:
            self._write(CPU_PERIOD, self.allocation_configuration.cpu_quota_period)

        if quota_normalized >= 1.0:
            quota = -1
        else:
            # synchornize period if nessesary
            quota = int(quota_normalized * self.allocation_configuration.cpu_quota_period *
                        self.platform_cpus)
            # Minimum quota detected
            if quota < 1000:
                quota = 1000

        self._write(CPU_QUOTA, quota)

    def get_allocations(self) -> TaskAllocations:
        assert self.allocation_configuration is not None, \
            'reading normalized allocations is not possible without configuration!'
        return {
            AllocationType.QUOTA: self.get_normalized_quota(),
            AllocationType.SHARES: self._get_normalized_shares(),
        }

    def get_pids(self) -> List[str]:
        with open(os.path.join(self.cgroup_fullpath, TASKS)) as f:
            return list(f.read().splitlines())
