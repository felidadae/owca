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
from typing import Optional, List, Union, Dict, Set

import os
from dataclasses import dataclass
from enum import Enum

from wca import logger
from wca import platforms
from wca.allocations import MissingAllocationException
from wca.allocators import TaskAllocations, AllocationType, AllocationConfiguration
from wca.metrics import Measurements, MetricName, MissingMeasurementException
from wca.platforms import decode_listformat, encode_listformat

log = logging.getLogger(__name__)

TASKS = 'tasks'  # all PIDs including threads ids
PROCS = 'cgroup.procs'  # just process ids (better for calculating WSS)

QUOTA_CLOSE_TO_ZERO_SENSITIVITY = 0.01

# Constants (range limits0 when dealing with cgroups quota and shares.
MIN_SHARES = 2
QUOTA_NOT_SET = -1
QUOTA_MINIMUM_VALUE = 1000
QUOTA_NORMALIZED_MAX = 1.0


class CgroupSubsystem(str, Enum):
    CPU = '/sys/fs/cgroup/cpu'
    CPUSET = '/sys/fs/cgroup/cpuset'
    PERF_EVENT = '/sys/fs/cgroup/perf_event'
    MEMORY = '/sys/fs/cgroup/memory'

    def __repr__(self):
        return repr(self.value)


class CgroupType(str, Enum):
    CPU = 'cpu'
    CPUSET = 'cpuset'
    PERF_EVENT = 'perf_event'
    MEMORY = 'memory'

    def __repr__(self):
        return repr(self.value)


class CgroupResource(str, Enum):
    CPU_USAGE = 'cpuacct.usage'
    CPU_QUOTA = 'cpu.cfs_quota_us'
    CPU_PERIOD = 'cpu.cfs_period_us'
    CPU_SHARES = 'cpu.shares'
    CPUSET_CPUS = 'cpuset.cpus'
    CPUSET_MEMS = 'cpuset.mems'
    CPUSET_MEMORY_MIGRATE = 'cpuset.memory_migrate'
    MEMORY_USAGE = 'memory.usage_in_bytes'
    MEMORY_MAX_USAGE = 'memory.max_usage_in_bytes'
    MEMORY_LIMIT = 'memory.limit_in_bytes'
    MEMORY_SOFT_LIMIT = 'memory.soft_limit_in_bytes'
    NUMA_STAT = 'memory.numa_stat'
    MEMORY_STAT = 'memory.stat'

    def __repr__(self):
        return repr(self.value)


@dataclass
class Cgroup:
    cgroup_path: str

    # Values used for normalization of allocations
    allocation_configuration: Optional[AllocationConfiguration] = None
    platform: Optional[platforms.Platform] = None

    def __post_init__(self):
        assert self.cgroup_path.startswith('/'), 'Provide cgroup_path with leading /'
        relative_cgroup_path = self.cgroup_path[1:]  # cgroup path without leading '/'
        self.cgroup_cpu_fullpath = os.path.join(CgroupSubsystem.CPU, relative_cgroup_path)
        self.cgroup_cpuset_fullpath = os.path.join(CgroupSubsystem.CPUSET, relative_cgroup_path)
        self.cgroup_perf_event_fullpath = os.path.join(
            CgroupSubsystem.PERF_EVENT, relative_cgroup_path)
        self.cgroup_memory_fullpath = os.path.join(CgroupSubsystem.MEMORY,
                                                   relative_cgroup_path)

    def get_measurements(self) -> Measurements:
        try:
            with open(os.path.join(self.cgroup_cpu_fullpath, CgroupResource.CPU_USAGE)) as \
                    cpu_usage_file:
                # scale to seconds
                cpu_usage = float(cpu_usage_file.read()) / 1e9
        except FileNotFoundError as e:
            raise MissingMeasurementException(
                'File {} is missing. Cpu usage unavailable.'.format(e.filename))

        measurements = {MetricName.TASK_CPU_USAGE_SECONDS: cpu_usage}

        for cgroup_resource, metric_name in [
            [CgroupResource.MEMORY_USAGE, MetricName.TASK_MEM_USAGE_BYTES],
            [CgroupResource.MEMORY_MAX_USAGE, MetricName.TASK_MEM_MAX_USAGE_BYTES],
            [CgroupResource.MEMORY_LIMIT, MetricName.TASK_MEM_LIMIT_BYTES],
            [CgroupResource.MEMORY_SOFT_LIMIT, MetricName.TASK_MEM_SOFT_LIMIT_BYTES],
        ]:
            try:
                with open(os.path.join(self.cgroup_memory_fullpath,
                                       cgroup_resource)) as resource_file:
                    value = int(resource_file.read())
                measurements[metric_name] = value
            except FileNotFoundError as e:
                raise MissingMeasurementException(
                    'File {} is missing. Metric unavailable.'.format(e.filename))

        # Memory stat - e.g. page faults
        try:
            with open(os.path.join(self.cgroup_memory_fullpath,
                                   CgroupResource.MEMORY_STAT)) as resource_file:
                for line in resource_file.readlines():
                    if line.startswith('pgfault'):
                        _, value = line.split()
                        measurements[MetricName.TASK_MEM_PAGE_FAULTS] = int(value)
                        break
        except FileNotFoundError as e:
            raise MissingMeasurementException(
                'File {} is missing. Metric unavailable.'.format(e.filename))

        def get_metric(metric):
            with open(os.path.join(
                    self.cgroup_memory_fullpath, CgroupResource.NUMA_STAT)) as resource_file:
                for line in resource_file.readlines():
                    # Requires mem.use_hierarchy = 1
                    if line.startswith(metric):
                        for stat in line.split()[1:]:
                            k, v = stat.split("=")
                            k, v = k[1:], int(v)
                            if MetricName.TASK_MEM_NUMA_PAGES not in measurements:
                                measurements[MetricName.TASK_MEM_NUMA_PAGES] = {k: v}
                            else:
                                measurements[MetricName.TASK_MEM_NUMA_PAGES][k] = v
                        break

        try:
            has_hierarchical_metrics = False
            get_metric("hierarchical_total=")
            if not has_hierarchical_metrics:
                import warnings
                warnings.warn(
                    "No hierarchical_total in NUMA memory stat for tasks in cgroup. Using total=."
                )
                get_metric("total=")

        except FileNotFoundError as e:
            raise MissingMeasurementException(
                'File {} is missing. Metric unavailable.'.format(e.filename))

        # Check whether consecutive keys.
        assert (MetricName.TASK_MEM_NUMA_PAGES not in measurements or
                list(measurements[MetricName.TASK_MEM_NUMA_PAGES].keys()) ==
                [str(el) for el in range(0, self.platform.numa_nodes)])

        return measurements

    def _get_proper_path(
            self, cgroup_control_file: str,
            cgroup_control_type: CgroupType) -> str:
        if cgroup_control_type == CgroupType.CPU:
            return os.path.join(self.cgroup_cpu_fullpath, cgroup_control_file)
        if cgroup_control_type == CgroupType.PERF_EVENT:
            return os.path.join(self.cgroup_perf_event_fullpath, cgroup_control_file)
        if cgroup_control_type == CgroupType.CPUSET:
            return os.path.join(self.cgroup_cpuset_fullpath, cgroup_control_file)
        if cgroup_control_type == CgroupType.MEMORY:
            return os.path.join(self.cgroup_cpuset_fullpath, cgroup_control_file)

        raise NotImplementedError(cgroup_control_type)

    def _read_raw(self, cgroup_control_file: str, cgroup_control_type: CgroupType) -> str:
        """Read helper to store any and convert value from cgroup control file."""
        path = self._get_proper_path(cgroup_control_file, cgroup_control_type)
        try:
            with open(path) as file:
                raw_value = file.read()
                log.log(logger.TRACE, 'cgroup: read %s=%r', file.name, raw_value)
        except FileNotFoundError as e:
            raise MissingAllocationException(
                'File {} is missing. Allocation unavailable.'.format(e.filename))

        return raw_value

    def _read(self, cgroup_control_file: str, cgroup_control_type: CgroupType) -> int:
        """Read helper to store any and convert value to int from cgroup control file."""
        raw_value = self._read_raw(cgroup_control_file, cgroup_control_type)
        value = int(raw_value)
        return value

    def _write(
            self, cgroup_control_file: str, value: Union[int, str],
            cgroup_control_type: CgroupType):
        """Write helper to store any int value in cgroup control file."""
        path = self._get_proper_path(cgroup_control_file, cgroup_control_type)
        with open(path, 'wb') as file:
            raw_value = bytes(str(value), encoding='utf8')
            log.log(logger.TRACE, 'cgroup: write %s=%r', file.name, raw_value)
            file.write(raw_value)

    def _get_normalized_shares(self) -> float:
        """Return normalized using cpu_shares and cpu_shares_unit for normalization."""
        assert self.allocation_configuration is not None, \
            'normalization configuration cannot be used without configuration!'
        shares = self._read(CgroupResource.CPU_SHARES, CgroupType.CPU)
        return shares / self.allocation_configuration.cpu_shares_unit

    def _get_normalized_quota(self) -> float:
        """Read normalized quota against configured period and number of available cpus."""
        assert self.allocation_configuration is not None, \
            'normalization configuration cannot be used without configuration!'
        current_quota = self._read(CgroupResource.CPU_QUOTA, CgroupType.CPU)
        current_period = self._read(CgroupResource.CPU_PERIOD, CgroupType.CPU)

        if current_quota == QUOTA_NOT_SET:
            return QUOTA_NORMALIZED_MAX
        # Period 0 is invalid argument for cgroup cpu subsystem. so division is safe.
        return current_quota / current_period / self.platform.cpus

    def get_allocations(self) -> TaskAllocations:
        assert self.allocation_configuration is not None, \
            'reading normalized allocations is not possible without configuration!'
        return {
            AllocationType.QUOTA: self._get_normalized_quota(),
            AllocationType.SHARES: self._get_normalized_shares(),
            AllocationType.CPUSET_CPUS: self._get_cpuset_cpus(),
            AllocationType.CPUSET_MEMS: self._get_cpuset_mems(),
            AllocationType.CPUSET_MEMORY_MIGRATE: self._get_memory_migrate(),
        }

    def get_pids(self, include_threads=True) -> List[str]:
        if include_threads:
            file = TASKS
        else:
            file = PROCS
        try:
            with open(os.path.join(self.cgroup_cpu_fullpath, file)) as file:
                return list(file.read().splitlines())
        except FileNotFoundError:
            log.debug('Soft warning: cgroup disappeard during sync, ignore it.')
            return []

    def set_shares(self, normalized_shares: float):
        """Store shares normalized values in cgroup files system. For de-normalization,
        we use reverse formula to _get_normalized_shares."""
        assert self.allocation_configuration is not None, \
            'allocation configuration cannot be used without configuration!'

        shares = int(normalized_shares * self.allocation_configuration.cpu_shares_unit)
        if shares < MIN_SHARES:
            log.warning('cpu.shares smaller than allowed minimum. '
                        'Setting cpu.shares to allowed minimum: '
                        '{}'.format(MIN_SHARES))
            shares = MIN_SHARES

        self._write(CgroupResource.CPU_SHARES, shares, CgroupType.CPU)

    def set_quota(self, normalized_quota: float):
        """Unconditionally sets quota and period if necessary."""
        assert self.allocation_configuration is not None, \
            'setting quota cannot be used without configuration!'
        current_period = self._read(CgroupResource.CPU_PERIOD, CgroupType.CPU)

        if current_period != self.allocation_configuration.cpu_quota_period:
            self._write(
                CgroupResource.CPU_PERIOD, self.allocation_configuration.cpu_quota_period,
                CgroupType.CPU)

        if normalized_quota >= QUOTA_NORMALIZED_MAX:
            if normalized_quota > QUOTA_NORMALIZED_MAX:
                log.warning('Quota greater than allowed. Not setting quota.')
            quota = QUOTA_NOT_SET
        else:
            # synchronize period if necessary
            quota = int(normalized_quota * self.allocation_configuration.cpu_quota_period *
                        self.platform.cpus)
            # Minimum quota detected
            if quota < QUOTA_MINIMUM_VALUE:
                log.warning('Quota is smaller than allowed minimum. '
                            'Setting quota value to allowed minimum: '
                            '{}'.format(QUOTA_MINIMUM_VALUE))
                quota = QUOTA_MINIMUM_VALUE

        self._write(CgroupResource.CPU_QUOTA, quota, CgroupType.CPU)

    def _write_listformat(self, intset: Set[int], resource: CgroupResource,
                          cgroup_type: CgroupType):
        encoded_value = encode_listformat(intset)
        try:
            self._write(resource, encoded_value, cgroup_type)
        except PermissionError:
            log.warning(
                'Cannot write {}: "{}" to "{}"! Permission denied.'.format(
                    CgroupResource.CPUSET_CPUS, encoded_value, self.cgroup_cpuset_fullpath))

    def _read_listformat(self, resource: CgroupResource, cgroup_type: CgroupType):
        listformat = decode_listformat(self._read_raw(resource, cgroup_type).strip())
        return encode_listformat(listformat)

    def set_cpuset_cpus(self, cpus: Set[int]):
        """Set cpuset.cpus."""
        self._write_listformat(cpus, CgroupResource.CPUSET_CPUS, CgroupType.CPUSET)

    def set_cpuset_mems(self, mems: Set[int] = None):
        """Set cpuset.mems."""
        self._write_listformat(mems, CgroupResource.CPUSET_MEMS, CgroupType.CPUSET)

    def _get_cpuset_cpus(self) -> str:
        """Get current cpuset.cpus (encoded as comma separated sorted normalized list of cpus)."""
        return self._read_listformat(CgroupResource.CPUSET_CPUS, CgroupType.CPUSET)

    def _get_cpuset_mems(self) -> str:
        """Get current cpuset.mems (encoded as comma separated sorted normalized list of cpus)."""
        return self._read_listformat(CgroupResource.CPUSET_MEMS, CgroupType.CPUSET)

    def _set_memory_migrate(self, value: int):
        self._write(CgroupResource.CPUSET_MEMORY_MIGRATE, value, CgroupType.CPUSET)

    def _get_memory_migrate(self) -> int:
        return self._read(CgroupResource.CPUSET_MEMORY_MIGRATE, CgroupType.CPUSET)


def build_cpu_to_socket_mapping(node_cpus: Dict[int, Set[int]]) -> Dict[int, int]:
    mapping = {}
    for node, cpus in node_cpus.items():
        for cpu in cpus:
            mapping[cpu] = node
    return mapping
