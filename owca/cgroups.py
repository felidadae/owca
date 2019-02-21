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

# Constants (range limits0 when dealing with cgroups quota and shares.
MIN_SHARES = 2
QUOTA_NOT_SET = -1
QUOTA_MINIMUM_VALUE = 1000
QUOTA_NORMALIZED_MAX = 1.0


@dataclass
class Cgroup:
    cgroup_path: str

    # Values used for normalization of allocations
    platform_cpus: int = None  # required for quota normalization (None by default until others PRs)
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
        with open(os.path.join(self.cgroup_fullpath, cgroup_control_file)) as file:
            raw_value = int(file.read())
            log.log(logger.TRACE, 'cgroup: read %s=%r', file.name, raw_value)
            return raw_value

    def _write(self, cgroup_control_file: str, value: int):
        """Write helper to store any int value in cgroup control file."""
        with open(os.path.join(self.cgroup_fullpath, cgroup_control_file), 'wb') as file:
            raw_value = bytes(str(value), encoding='utf8')
            log.log(logger.TRACE, 'cgroup: write %s=%r', file.name, raw_value)
            file.write(raw_value)

    def _get_normalized_shares(self) -> float:
        """Return normalized using cpu_shares and cpu_shares_unit for normalization."""
        assert self.allocation_configuration is not None, \
            'normalization configuration cannot be used without configuration!'
        shares = self._read(CPU_SHARES)
        return shares / self.allocation_configuration.cpu_shares_unit

    def _get_normalized_quota(self) -> float:
        """Read normalized quota against configured period and number of available cpus."""
        assert self.allocation_configuration is not None, \
            'normalization configuration cannot be used without configuration!'
        current_quota = self._read(CPU_QUOTA)
        current_period = self._read(CPU_PERIOD)
        if current_quota == QUOTA_NOT_SET:
            return QUOTA_NORMALIZED_MAX
        # Period 0 is invalid argument for cgroup cpu subsystem. so division is safe.
        return current_quota / current_period / self.platform_cpus

    def get_allocations(self) -> TaskAllocations:
        assert self.allocation_configuration is not None, \
            'reading normalized allocations is not possible without configuration!'
        return {
            AllocationType.QUOTA: self._get_normalized_quota(),
            AllocationType.SHARES: self._get_normalized_shares(),
        }

    def get_pids(self) -> List[str]:
        with open(os.path.join(self.cgroup_fullpath, TASKS)) as file:
            return list(file.read().splitlines())

    def set_shares(self, normalized_shares: float):
        """Store shares normalized values in cgroup files system. For de-normalization,
        we use reverse formula to _get_normalized_shares."""
        assert self.allocation_configuration is not None, \
            'allocation configuration cannot be used without configuration!'

        shares = int(normalized_shares * self.allocation_configuration.cpu_shares_unit)
        if shares < MIN_SHARES:
            shares = MIN_SHARES

        self._write(CPU_SHARES, shares)

    def set_quota(self, normalized_quota: float):
        """Unconditionally sets quota and period if necessary."""
        assert self.allocation_configuration is not None, \
            'setting quota cannot be used without configuration!'
        current_period = self._read(CPU_PERIOD)

        if current_period != self.allocation_configuration.cpu_quota_period:
            self._write(CPU_PERIOD, self.allocation_configuration.cpu_quota_period)

        if normalized_quota >= QUOTA_NORMALIZED_MAX:
            quota = QUOTA_NOT_SET
        else:
            # synchronize period if necessary
            quota = int(normalized_quota * self.allocation_configuration.cpu_quota_period *
                        self.platform_cpus)
            # Minimum quota detected
            if quota < QUOTA_MINIMUM_VALUE:
                quota = QUOTA_MINIMUM_VALUE

        self._write(CPU_QUOTA, quota)
