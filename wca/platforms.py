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
import json
import logging
import shlex
import socket
import subprocess  # nosec: B404, we deliberately use this module
import time
from collections import defaultdict
from itertools import groupby
from json.decoder import JSONDecodeError
from typing import List, Dict, Optional, Set

import os
from dataclasses import dataclass
from enum import Enum

from wca.metrics import Metric, MetricName, Measurements, export_metrics_from_measurements
from wca.profiling import profiler

try:
    from pkg_resources import get_distribution, DistributionNotFound
except ImportError:
    # When running from pex use vendored library from pex.
    from pex.vendor._vendored.setuptools.pkg_resources import get_distribution, DistributionNotFound

log = logging.getLogger(__name__)


class CPUCodeName(Enum):
    """Only Server platforms. """
    UNKNOWN = 'unknown'
    HASWELL = 'Haswell'
    BROADWELL = 'Broadwell'
    SKYLAKE = 'Skylake'
    CASCADE_LAKE = 'Cascade Lake'
    COOPER_LAKE = 'Cooper Lake'
    ICE_LAKE = 'Ice Lake'


def _parse_cpuinfo() -> List[Dict[str, str]]:
    """Make dictionary from '/proc/cpuinfo' file."""
    with open('/proc/cpuinfo') as f:
        cpuinfo_string = f.read()
    return [
        dict(
            [list(map(str.strip, line.split(':')))
             for line in cpu.split('\n')]
        )
        for cpu in filter(None, cpuinfo_string.split('\n\n'))
    ]


def get_cpu_codename(model: int, stepping: int) -> CPUCodeName:
    """Returns CPU codename based on model and stepping information."""

    # https://elixir.bootlin.com/linux/v5.3/source/arch/x86/include/asm/intel-family.h#L64
    if model in [
        0x4E, 0x5E,  # Client
        0x55  # Server
    ]:
        # Intel quirk to recognize Cascade Lake:
        # https://github.com/torvalds/linux/blob/54ecb8f7028c5eb3d740bb82b0f1d90f2df63c5c/arch/x86/kernel/cpu/resctrl/core.c#L887
        if stepping > 4:
            return CPUCodeName.CASCADE_LAKE
        else:
            return CPUCodeName.SKYLAKE
    elif model in [
        0x3D, 0x47,  # Client
        0x4F, 0x56  # Server
    ]:
        return CPUCodeName.BROADWELL
    else:
        return CPUCodeName.UNKNOWN


# 0-based logical processor number (matches the value of "processor" in /proc/cpuinfo)
CpuId = int
NodeId = int

_version = None


def get_wca_version():
    """Returns information about wca version."""
    global _version
    if _version is None:
        try:
            _version = get_distribution('wca').version
        except DistributionNotFound:
            log.warning("Version is not available. "
                        "Probably egg-info directory does not exist"
                        "(which is required for pkg_resources module "
                        "to find the version).")
            _version = "unknown_version"

    return _version


@dataclass
class RDTInformation:
    # Reflects state of the system.

    # Monitoring.
    rdt_cache_monitoring_enabled: bool  # based /sys/fs/resctrl/mon_data/mon_L3_00/llc_occupancy
    rdt_mb_monitoring_enabled: bool  # based on /sys/fs/resctrl/mon_data/mon_L3_00/mbm_total_bytes

    # Allocation.
    rdt_cache_control_enabled: bool  # based on 'L3:' in /sys/fs/resctrl/schemata
    rdt_mb_control_enabled: bool  # based on 'MB:' in /sys/fs/resctrl/schemata

    # Cache control read-only parameters. Available only if CAT control
    # is supported by platform,otherwise set to None.
    cbm_mask: Optional[str]  # based on /sys/fs/resctrl/info/L3/cbm_mask
    min_cbm_bits: Optional[str]  # based on /sys/fs/resctrl/info/L3/min_cbm_bits
    num_closids: Optional[int]  # based on /sys/fs/resctrl/info/L3/num_closids or MB/closids

    # MB control read-only parameters.
    mb_bandwidth_gran: Optional[int]  # based on /sys/fs/resctrl/info/MB/bandwidth_gran
    mb_min_bandwidth: Optional[int]  # based on /sys/fs/resctrl/info/MB/min_bandwidth

    def is_control_enabled(self) -> bool:
        return self.rdt_mb_control_enabled or self.rdt_cache_control_enabled

    def is_monitoring_enabled(self) -> bool:
        return self.rdt_mb_monitoring_enabled or self.rdt_cache_monitoring_enabled


@dataclass
class Platform:
    # Topology:
    sockets: int  # number of sockets
    cores: int  # number of physical cores in total (sum over all sockets)
    cpus: int  # logical processors equal to the output of "nproc" Linux command
    numa_nodes: int  # number of NUMA nodes

    cpu_model: str  # /proc/cpuinfo -> model_name
    cpu_model_number: int  # /proc/cpuinfo -> model
    cpu_codename: CPUCodeName
    # mapping from socket, core id to CPU based on /proc/cpuinfo
    topology: Dict[int, Dict[int, List[int]]]

    cpu_model: str

    # NUMA info
    # mapping from numa node id to CPU (to support SNC), based on /sys/devices/system/numa
    node_cpus: Dict[int, Set[int]]
    # Distance based on /sys/devices/system/node/node*/distance
    node_distances: Dict[int, Dict[int, int]]
    # [unix timestamp] Recorded timestamp of finishing data gathering (as returned from time.time)
    timestamp: float

    rdt_information: Optional[RDTInformation]

    measurements: Measurements

    swap_enabled: bool


class MissingPlatformStaticInformation(Exception):
    pass


_platform_static_information_initialized = False
_platform_static_information = {}


def get_platform_static_information(strict_mode: bool) -> Measurements:
    """Time-consuming gathering information function that calles external binaries e.g.
    lshw and ipmctl. Assumption is that this information is not changing over life of WCA
    application and should be called only once upon WCA starting.
    :param strict_mode: raise expection if collection
                        is not possible e.g. required binaries is missing
    :return: cached platform information
    """
    # RETURN MEMORY DIMM DETAILS based on lshw
    global _platform_static_information
    global _platform_static_information_initialized
    # TODO: PoC to be replaced with ACPI/HMAT table parsing if possible
    if not _platform_static_information_initialized:

        try:
            # nosec: B603. We deliberately use 'subprocess'. There is a permanent input.
            ipmctl_output = subprocess.check_output(  # nosec
                shlex.split('ipmctl show -u B -memoryresources')).decode("utf-8")
            memorymode_size = 0
            for line in ipmctl_output.splitlines():
                if 'MemoryCapacity' in line:
                    memorymode_size = line.split('=')[1].split(' ')[0]
            _platform_static_information[MetricName.PLATFORM_MEM_MODE_SIZE_BYTES] = int(
                memorymode_size)
        except FileNotFoundError:
            log.warning('ipmctl unavailable, cannot read memory mode size')
            if strict_mode:
                raise MissingPlatformStaticInformation

        try:
            # nosec: B603. We deliberately use 'subprocess'. There is a permanent input.
            lshw_raw = subprocess.check_output(  # nosec
                shlex.split('lshw -class memory -json -quiet -sanitize -notime'))
            lshw_str = lshw_raw.decode("utf-8")
            lshw_str = lshw_str.rstrip()
            lshw_str = '[' + lshw_str[0:(len(lshw_str) - 1)] + ']'
            lshw_data = json.loads(lshw_str)
            nvm_dimm_count = 0
            ram_dimm_count = 0
            nvm_dimm_size = 0
            ram_dimm_size = 0
            for system in lshw_data:
                if system['id'] == 'memory' and 'children' in system:
                    for bank in system['children']:
                        if '[empty]' in bank['description']:
                            continue
                        elif 'DDR4' in bank['description']:
                            assert bank['units'] == 'bytes'
                            ram_dimm_count += 1
                            ram_dimm_size += bank['size']
                        elif 'Non-volatile' in bank['description']:
                            assert bank['units'] == 'bytes'
                            nvm_dimm_count += 1
                            nvm_dimm_size += bank['size']

            _platform_static_information[MetricName.PLATFORM_DIMM_COUNT] = {}
            _platform_static_information[MetricName.PLATFORM_DIMM_COUNT]['ram'] = int(
                ram_dimm_count)
            _platform_static_information[MetricName.PLATFORM_DIMM_COUNT]['nvm'] = int(
                nvm_dimm_count)
            _platform_static_information[MetricName.PLATFORM_DIMM_TOTAL_SIZE_BYTES] = {}
            _platform_static_information[MetricName.PLATFORM_DIMM_TOTAL_SIZE_BYTES]['ram'] = int(
                ram_dimm_size)
            _platform_static_information[MetricName.PLATFORM_DIMM_TOTAL_SIZE_BYTES]['nvm'] = int(
                nvm_dimm_size)
        except FileNotFoundError:
            log.warning('lshw unavailable, cannot read memory topology size!')
            if strict_mode:
                raise MissingPlatformStaticInformation

        except JSONDecodeError:
            log.warning('lshw unavailable (incorrect version or missing data), '
                        'cannot parse output, cannot read memory topology size!')
            if strict_mode:
                raise MissingPlatformStaticInformation

        _platform_static_information_initialized = True
        log.debug('platform static information: %r', _platform_static_information)

    return _platform_static_information


def create_metrics(platform: Platform) -> List[Metric]:
    """Creates a list of Metric objects from data in Platform object"""
    platform_metrics = []

    platform_metrics.extend([
        Metric.create_metric_with_metadata(MetricName.PLATFORM_TOPOLOGY_CORES,
                                           value=platform.cores),
        Metric.create_metric_with_metadata(MetricName.PLATFORM_TOPOLOGY_CPUS,
                                           value=platform.cpus),
        Metric.create_metric_with_metadata(MetricName.PLATFORM_TOPOLOGY_SOCKETS,
                                           value=platform.sockets),
        Metric.create_metric_with_metadata(MetricName.PLATFORM_LAST_SEEN,
                                           value=time.time()),
    ])

    # Exporting measurements into metrics.
    platform_metrics.extend(export_metrics_from_measurements(platform.measurements))

    platform_metrics.append(
        Metric.create_metric_with_metadata(
            MetricName.WCA_INFORMATION,
            value=1,
            labels=dict(
                sockets=str(platform.sockets),
                cores=str(platform.cores),
                cpus=str(platform.cpus),
                cpu_model=platform.cpu_model,
                wca_version=get_wca_version(),
            )
        )
    )

    return platform_metrics


def create_labels(platform: Platform, include_optional_labels: bool) -> Dict[str, str]:
    """Returns dict of topology and hostname labels
    Note: Those will will assigned to every returned metric.
    """
    labels = dict()

    # REQUIRED (for host identification)
    labels["host"] = socket.gethostname()

    # OPTIONAL (for further metrics analysis)
    if include_optional_labels:
        # Topology labels
        labels["sockets"] = str(platform.sockets)
        labels["cores"] = str(platform.cores)
        labels["cpus"] = str(platform.cpus)
        # Additional labels
        labels["cpu_model"] = platform.cpu_model
        labels["wca_version"] = get_wca_version()

    return labels


def parse_proc_meminfo(proc_meminfo_output: str) -> int:
    """Parses output /proc/meminfo and returns total memory used in bytes"""

    # Used memory calculated the same way the 'free' tool does it
    # References: http://man7.org/linux/man-pages/man1/free.1.html
    #             http://man7.org/linux/man-pages/man5/proc.5.html
    # Although it is not stated in the manpage, proc/meminfo always returns
    # memory in kB, or to be exact, KiB (1024 bytes) which can be seen in source code:
    # https://github.com/torvalds/linux/blob/master/fs/proc/meminfo.c

    def get_value_from_line(line) -> int:
        # Value will be always in the second column of the line
        return int(line.split()[1])

    total = 0
    free = 0
    buffers = 0
    cache = 0
    for line in proc_meminfo_output.split("\n"):
        if line.startswith("MemTotal"):
            total = get_value_from_line(line)
        elif line.startswith("MemFree"):
            free = get_value_from_line(line)
        elif line.startswith("Buffers"):
            buffers = get_value_from_line(line)
        elif line.startswith("Cached"):
            cache = get_value_from_line(line)

    # KiB to Bytes
    return (total - free - buffers - cache) << 10


def read_proc_meminfo() -> str:
    """Reads /proc/meminfo"""
    with open('/proc/meminfo') as f:
        out = f.read()
    return out


BASE_SYSFS_NODES_PATH = '/sys/devices/system/node'


def get_numa_nodes_count() -> int:
    """returns how many numa nodes are available"""
    node_count = 0
    for nodedir in os.listdir(BASE_SYSFS_NODES_PATH):
        if nodedir.startswith('node'):
            node_count += 1
    return node_count


def parse_node_meminfo() -> (Dict[NodeId, int], Dict[NodeId, int]):
    """Parses /sys/devices/system/node/node*/meminfo and returns free/used
    return values are in bytes.
    """
    node_free = {}
    node_used = {}
    for nodedir in os.listdir(BASE_SYSFS_NODES_PATH):
        if nodedir.startswith('node'):
            meminfo_filename = os.path.join(BASE_SYSFS_NODES_PATH, nodedir, 'meminfo')
            with open(meminfo_filename) as f:
                for line in f.readlines():
                    s = line.split()
                    if len(s) != 5:
                        continue
                    if s[2] == "MemFree:":
                        node_free[int(s[1])] = int(s[3]) << 10
                    if s[2] == "MemUsed:":
                        node_used[int(s[1])] = int(s[3]) << 10
    return node_free, node_used


def parse_node_cpus() -> Dict[NodeId, Set[int]]:
    """
    Parses /sys/devices/system/node/node*/cpulist"
    Read CPU to NUMA node mapping based on /sys/devices/system/node
    :return: mapping from numa_node -> list of cpus (as List[Set] of int)
    """
    node_cpus = {}
    for nodedir in os.listdir(BASE_SYSFS_NODES_PATH):
        if nodedir.startswith('node'):
            node_id = int(nodedir[4:])
            cpu_list_filename = os.path.join(BASE_SYSFS_NODES_PATH, nodedir, 'cpulist')
            with open(cpu_list_filename) as cpu_list_file:
                node_cpus[node_id] = decode_listformat(cpu_list_file.read())
    return node_cpus


VMSTAT_METRICS = {
    MetricName.PLATFORM_VMSTAT_NUMA_PAGES_MIGRATED: 'numa_pages_migrated',
    MetricName.PLATFORM_VMSTAT_PGMIGRATE_SUCCESS: 'pgmigrate_success',
    MetricName.PLATFORM_VMSTAT_PGMIGRATE_FAIL: 'pgmigrate_fail',
    MetricName.PLATFORM_VMSTAT_NUMA_HINT_FAULTS: 'numa_hint_faults',
    MetricName.PLATFORM_VMSTAT_NUMA_HINT_FAULTS_LOCAL: 'numa_hint_faults_local',
    MetricName.PLATFORM_VMSTAT_PGFAULTS: 'pgfault',
}


def parse_proc_vmstat() -> Measurements:
    """Read/parse and return measurements based on /proc/vmstat/"""
    measurements = {}
    with open('/proc/vmstat') as f:
        for line in f.readlines():
            for metric_name, key in VMSTAT_METRICS.items():
                if line.startswith(key):
                    measurements[metric_name] = int(line.split()[1])
    return measurements


def parse_node_distances() -> Dict[int, Dict[int, int]]:
    """
    Parses "/sys/devices/system/node/node*/distance"
    Read distance to NUMA node mapping based on /sys/devices/system/node
    :return: mapping from numa_node -> dict of distances (as dict with int key and value)
    """
    node_distances = {}

    for nodedir in os.listdir(BASE_SYSFS_NODES_PATH):
        if nodedir.startswith('node'):
            node_id = int(nodedir[4:])
            distance_filename = os.path.join(BASE_SYSFS_NODES_PATH, nodedir, 'distance')
            with open(distance_filename) as distance_file:
                distances = distance_file.readline()
                node_distances[node_id] = {i: int(val) for i, val in enumerate(distances.split())}

    return node_distances


def parse_proc_stat(proc_stat_output) -> Dict[CpuId, int]:
    """Parses output of /proc/stat and calculates cpu usage for each cpu"""
    cpus_usage = {}

    for line in proc_stat_output.split("\n"):
        if line and line.startswith("cpu"):
            cpu_stat_fields = line.split(" ")
            # first 3 characters in line are 'cpu', so everything after that,
            #  up to next space is a cpu id
            cpu_id = cpu_stat_fields[0][3:]
            # first line of output has aggregated values for all cpus, which we don't need
            if cpu_id == '':
                continue
            else:
                cpu_id = int(cpu_id)
            # reference: http://man7.org/linux/man-pages/man5/proc.5.html
            user = int(cpu_stat_fields[1])
            nice = int(cpu_stat_fields[2])
            system = int(cpu_stat_fields[3])
            irq = int(cpu_stat_fields[6])
            softirq = int(cpu_stat_fields[7])
            steal = int(cpu_stat_fields[8])
            # As we are monitoring cpu usage, idle and iowait are not used
            # idle = int(cpu_stat_fields[4])
            # iowait = int(cpu_stat_fields[5])
            # guest and guest nice times are already included in user and nice counters
            # so they are not added to the total time
            # guest = int(cpu_stat_fields[9])
            # guest_nice = int(cpu_stat_fields[10])
            cpu_usage = user + nice + system + irq + softirq + steal
            cpus_usage[cpu_id] = cpu_usage
    return cpus_usage


def read_proc_stat() -> str:
    """Reads /proc/stat"""
    with open('/proc/stat') as f:
        out = f.read()
    return out


def collect_topology_information(parsed_cpuinfo: List[Dict[str, str]]) -> (int, int, int,
                                                                           Dict[int, Dict[
                                                                               int, List[int]]],
                                                                           Dict[int, List[int]]
                                                                           ):
    """
    Reads files from /sys/devices/system/cpu to collect topology information
    :return: tuple (nr_of_online_cpus, nr_of_cores, nr_of_sockets,
                    mapping from [socket][core] -> list of cpus)
    """

    def by_physical_id(processor):
        return int(processor['physical id'])

    def by_core_id(processor):
        return int(processor['core id'])

    topology = defaultdict(dict)

    for physical_id, socket_processors in groupby(
            sorted(parsed_cpuinfo, key=by_physical_id), key=by_physical_id):
        for core_id, core_processors in groupby(
                sorted(list(socket_processors), key=by_core_id), key=by_core_id):
            topology[int(physical_id)][
                int(core_id)] = [int(p['processor']) for p in core_processors]

    # get rid of defaultdict
    topology = dict(topology)

    nr_of_online_cpus = len(parsed_cpuinfo)
    nr_of_cores = sum(len(core_ids) for core_ids in topology.values())
    nr_of_sockets = len(topology)

    return nr_of_online_cpus, nr_of_cores, nr_of_sockets, topology


BASE_RESCTRL_PATH = '/sys/fs/resctrl'
MON_DATA = 'mon_data'
MON_L3_00 = 'mon_L3_00'
MBM_TOTAL = 'mbm_total_bytes'
LLC_OCCUPANCY = 'llc_occupancy'


def _collect_rdt_information() -> RDTInformation:
    """Returns rdt information values.
    Assumes resctrl is already mounted.
    """

    rdt_cache_monitoring_enabled = os.path.exists(
        os.path.join(BASE_RESCTRL_PATH, 'mon_data/mon_L3_00', LLC_OCCUPANCY))
    rdt_mb_monitoring_enabled = os.path.exists(
        os.path.join(BASE_RESCTRL_PATH, 'mon_data/mon_L3_00', MBM_TOTAL))

    def _read_value(subpath):
        with open(os.path.join(BASE_RESCTRL_PATH, subpath)) as f:
            return f.read().strip()

    schemata_body = _read_value('schemata')

    rdt_cache_control_enabled = 'L3' in schemata_body
    if rdt_cache_control_enabled:
        cbm_mask = _read_value('info/L3/cbm_mask')
        min_cbm_bits = _read_value('info/L3/min_cbm_bits')
        cache_num_closids = int(_read_value('info/L3/num_closids'))
    else:
        cbm_mask, min_cbm_bits, cache_num_closids = None, None, None

    rdt_mb_control_enabled = 'MB:' in schemata_body
    if rdt_mb_control_enabled:
        mb_bandwidth_gran = int(_read_value('info/MB/bandwidth_gran'))
        mb_min_bandwidth = int(_read_value('info/MB/min_bandwidth'))
        mb_num_closids = int(_read_value('info/MB/num_closids'))
    else:
        mb_bandwidth_gran, mb_min_bandwidth, mb_num_closids = None, None, None

    if rdt_cache_control_enabled or rdt_mb_control_enabled:
        # Minimum of available closids readt from MB or L3
        num_closids = min(filter(None, [cache_num_closids, mb_num_closids]))
    else:
        num_closids = None

    return RDTInformation(rdt_cache_monitoring_enabled,
                          rdt_mb_monitoring_enabled,
                          rdt_cache_control_enabled,
                          rdt_mb_control_enabled,
                          cbm_mask,
                          min_cbm_bits,
                          num_closids,
                          mb_bandwidth_gran,
                          mb_min_bandwidth)


@profiler.profile_duration(name='collect_platform_information')
def collect_platform_information(rdt_enabled: bool = True,
                                 gather_hw_mm_topology: bool = False,
                                 extra_platform_measurements: Optional[Measurements] = None,
                                 include_optional_labels: bool = False) -> (
        Platform, List[Metric], Dict[str, str]):
    """Returns Platform information, metrics and common labels.

    Returned objects meaning:
    - Platform is a static information about topology as well as some metrics about platform
    level resource usages.
    - List[Metric] covers the same information as platform but serialized to storage accepted type.
    - Dist[str, str] - "common labels" are used to mark every other metric
        (generated by other sources) e.g. host

    Note: returned metrics should be consistent with information covered by platform

    """
    cpu_info = _parse_cpuinfo()
    # Static information
    nr_of_cpus, nr_of_cores, no_of_sockets, topology = collect_topology_information(cpu_info)
    if rdt_enabled:
        rdt_information = _collect_rdt_information()
    else:
        rdt_information = None

    # All information are based on first CPU.
    cpu_model = cpu_info[0]['model name']
    cpu_model_number = int(cpu_info[0]['model'])
    cpu_codename = get_cpu_codename(int(cpu_info[0]['model']), int(cpu_info[0]['stepping']))

    # Dynamic information
    platform_measurements = {}
    platform_measurements[MetricName.PLATFORM_CPU_USAGE] = parse_proc_stat(read_proc_stat())
    platform_measurements[MetricName.PLATFORM_MEM_USAGE_BYTES] = parse_proc_meminfo(
        read_proc_meminfo())
    node_free, node_used = parse_node_meminfo()
    platform_measurements[MetricName.PLATFORM_MEM_NUMA_FREE_BYTES] = node_free
    platform_measurements[MetricName.PLATFORM_MEM_NUMA_USED_BYTES] = node_used

    # Merge local platform measurements with passed extra_platform_measurements
    platform_measurements.update(extra_platform_measurements
                                 if extra_platform_measurements is not None
                                 else {})

    if gather_hw_mm_topology is None:
        platform_static_information = get_platform_static_information(strict_mode=False)
    elif gather_hw_mm_topology:
        platform_static_information = get_platform_static_information(strict_mode=True)
    else:
        platform_static_information = {}
    platform_measurements.update(platform_static_information)

    platform_measurements.update(parse_proc_vmstat())

    platform = Platform(
        sockets=no_of_sockets,
        cores=nr_of_cores,
        cpus=nr_of_cpus,
        numa_nodes=get_numa_nodes_count(),
        topology=topology,
        cpu_model=cpu_model,
        cpu_model_number=cpu_model_number,
        cpu_codename=cpu_codename,
        timestamp=time.time(),
        rdt_information=rdt_information,
        node_cpus=parse_node_cpus(),
        node_distances=parse_node_distances(),
        measurements=platform_measurements,
        swap_enabled=is_swap_enabled()
    )
    assert len(platform_measurements[MetricName.PLATFORM_CPU_USAGE]) == platform.cpus, \
        "Inconsistency in cpu data returned by kernel"
    return platform, create_metrics(platform), create_labels(platform, include_optional_labels)


def decode_listformat(value: str) -> Set[int]:
    """Parse "List Format" as describe by man cpuset(7)

    can raise ValueError in case in improper input.
    """
    cores = set()

    if not value:
        return set()

    ranges = value.split(',')

    for r in ranges:
        boundaries = r.split('-')

        if len(boundaries) == 1:
            cores.add(int(boundaries[0].strip()))
        elif len(boundaries) == 2:
            start = int(boundaries[0].strip())
            end = int(boundaries[1].strip())

            for i in range(start, end + 1):
                cores.add(i)

    return set(cores)


def encode_listformat(ints: Set[int]) -> str:
    """ Encode as "List Format" man cpuset(7) list of ints as comma separated list of cpus.
    Works for numa nodes as well.
    Assumptions:
    - returned list is sorted and always comma separated.
    """
    assert all(isinstance(i, int) for i in ints), 'simple type check'
    return ','.join(map(str, sorted(ints)))


def is_swap_enabled() -> bool:
    mem_info = read_proc_meminfo()
    for line in mem_info.split('\n'):
        if line.startswith("SwapTotal"):
            value = line.split()[1]
            if value.startswith('0'):
                return False
            return True
    return False
