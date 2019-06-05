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
import re
import socket
import time
from typing import List, Dict, Set, Tuple, Optional

from wca.metrics import Metric, MetricName
from wca.profiling import profiler

from dataclasses import dataclass

try:
    from pkg_resources import get_distribution, DistributionNotFound
except ImportError:
    # When running from pex use vendored library from pex.
    from pex.vendor._vendored.setuptools.pkg_resources import get_distribution, DistributionNotFound


log = logging.getLogger(__name__)

# 0-based logical processor number (matches the value of "processor" in /proc/cpuinfo)
CpuId = int


def get_wca_version():
    """Returns information about wca version."""
    try:
        version = get_distribution('wca').version
    except DistributionNotFound:
        log.warning("Version is not available. "
                    "Probably egg-info directory does not exist"
                    "(which is required for pkg_resources module "
                    "to find the version).")
        return "unknown_version"

    return version


def get_cpu_model() -> str:
    """Returns information about cpu model from /proc/cpuinfo."""
    if os.path.isfile('/proc/cpuinfo'):
        with open('/proc/cpuinfo') as fref:
            for line in fref.readlines():
                if line.startswith("model name"):
                    s = re.search("model name\\s*:\\s*(.*)\\s*$", line)
                    if s:
                        return s.group(1)
                    break
    return "unknown_cpu_model"


@dataclass
class RDTInformation:
    # Reflects state of the system.

    # Monitoring.
    rdt_cache_monitoring_enabled: bool  # based /sys/fs/resctrl/mon_data/mon_L3_00/llc_occupancy
    rdt_mb_monitoring_enabled: bool   # based on /sys/fs/resctrl/mon_data/mon_L3_00/mbm_total_bytes

    # Allocation.
    rdt_cache_control_enabled: bool   # based on 'L3:' in /sys/fs/resctrl/schemata
    rdt_mb_control_enabled: bool      # based on 'MB:' in /sys/fs/resctrl/schemata

    # Cache control read-only parameters. Available only if CAT control
    # is supported by platform,otherwise set to None.
    cbm_mask: Optional[str]           # based on /sys/fs/resctrl/info/L3/cbm_mask
    min_cbm_bits: Optional[str]       # based on /sys/fs/resctrl/info/L3/min_cbm_bits
    num_closids: Optional[int]        # based on /sys/fs/resctrl/info/L3/num_closids

    # MB control read-only parameters.
    mb_bandwidth_gran: Optional[int]  # based on /sys/fs/resctrl/info/MB/bandwidth_gran
    mb_min_bandwidth: Optional[int]   # based on /sys/fs/resctrl/info/MB/bandwidth_gran

    def is_control_enabled(self):
        return self.rdt_mb_control_enabled or self.rdt_cache_control_enabled

    def is_monitoring_enabled(self):
        return self.rdt_mb_monitoring_enabled or self.rdt_cache_monitoring_enabled


@dataclass
class Platform:
    # Topology:
    sockets: int  # number of sockets
    cores: int  # number of physical cores in total (sum over all sockets)
    cpus: int  # logical processors equal to the output of "nproc" Linux command

    cpu_model: str

    # Utilization (usage):
    # counter like, sum of all modes based on /proc/stat
    # "cpu line" with 10ms resolution expressed in [ms]
    cpus_usage: Dict[CpuId, int]

    # [bytes] based on /proc/meminfo (gauge like)
    # difference between MemTotal and MemAvail (or MemFree)
    total_memory_used: int

    # [unix timestamp] Recorded timestamp of finishing data gathering (as returned from time.time)
    timestamp: float

    rdt_information: Optional[RDTInformation]


def create_metrics(platform: Platform) -> List[Metric]:
    """Creates a list of Metric objects from data in Platform object"""
    platform_metrics = list()
    platform_metrics.append(
        Metric.create_metric_with_metadata(
            name=MetricName.MEM_USAGE,
            value=platform.total_memory_used)
    )
    for cpu_id, cpu_usage in platform.cpus_usage.items():
        platform_metrics.append(
            Metric.create_metric_with_metadata(
                name=MetricName.CPU_USAGE_PER_CPU,
                value=cpu_usage,
                labels={"cpu": str(cpu_id)}
            )
        )
    return platform_metrics


def create_labels(platform: Platform) -> Dict[str, str]:
    """Returns dict of topology and hostname labels"""
    labels = dict()
    # Topology labels
    labels["sockets"] = str(platform.sockets)
    labels["cores"] = str(platform.cores)
    labels["cpus"] = str(platform.cpus)
    # Additional labels
    labels["host"] = socket.gethostname()
    labels["wca_version"] = get_wca_version()
    labels["cpu_model"] = get_cpu_model()
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


def collect_topology_information() -> (int, int, int):
    """
    Reads files from /sys/devices/system/cpu to collect topology information
    :return: tuple (nr_of_online_cpus, nr_of_cores, nr_of_sockets)
    """

    def read_cpu_info_file(cpu, rel_file_path) -> int:
        with open(os.path.join(sys_devices_system_cpu_path,
                               cpu, rel_file_path)) as f:
            return int(f.read())

    sys_devices_system_cpu_path = "/sys/devices/system/cpu"
    cpus = os.listdir(sys_devices_system_cpu_path)
    # Filter out all unneeded folders
    cpu_regex = re.compile(r'cpu[0-9]+')
    cpus = [cpu for cpu in cpus if cpu_regex.match(cpu)]
    cores_sockets_pairs: Set[Tuple[int, int]] = set()
    sockets = set()
    nr_of_online_cpus = 0

    for cpu in cpus:
        # Check whether current cpu is online
        # There is no online status file for cpu0 so we omit checking it
        # and assume it is online
        if cpu != "cpu0":
            cpu_online_status = read_cpu_info_file(cpu, "online")
            if 1 == cpu_online_status:
                nr_of_online_cpus += 1
            else:
                # If the cpu is not online, files topology/{physical_package_id, core_id}
                # do not exist, so we continue
                continue
        else:
            nr_of_online_cpus += 1

        socket_id = read_cpu_info_file(cpu, "topology/physical_package_id")
        core_id = read_cpu_info_file(cpu, "topology/core_id")
        cores_sockets_pairs.add((socket_id, core_id))
        sockets.add(socket_id)

    # Get nr of cores by counting unique (socket_id, core_id) tuples
    nr_of_cores = len(cores_sockets_pairs)
    # Get nr of sockets by counting unique socket_ids
    nr_of_sockets = len(sockets)

    return nr_of_online_cpus, nr_of_cores, nr_of_sockets


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
        num_closids = int(_read_value('info/L3/num_closids'))
    else:
        cbm_mask, min_cbm_bits, num_closids = None, None, None

    rdt_mb_control_enabled = 'MB:' in schemata_body
    if rdt_mb_control_enabled:
        mb_bandwidth_gran = int(_read_value('info/MB/bandwidth_gran'))
        mb_min_bandwidth = int(_read_value('info/MB/min_bandwidth'))
        mb_num_closids = int(_read_value('info/MB/num_closids'))
    else:
        mb_bandwidth_gran, mb_min_bandwidth, mb_num_closids = None, None, None

    if rdt_cache_control_enabled and rdt_mb_control_enabled:
        num_closids = min(num_closids, mb_num_closids)

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
def collect_platform_information(rdt_enabled: bool = True) -> (
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
    # Static information
    nr_of_cpus, nr_of_cores, no_of_sockets = collect_topology_information()
    if rdt_enabled:
        rdt_information = _collect_rdt_information()
    else:
        rdt_information = None

    # Dynamic information
    cpus_usage = parse_proc_stat(read_proc_stat())
    total_memory_used = parse_proc_meminfo(read_proc_meminfo())
    platform = Platform(
        sockets=no_of_sockets,
        cores=nr_of_cores,
        cpus=nr_of_cpus,
        cpu_model=get_cpu_model(),
        cpus_usage=cpus_usage,
        total_memory_used=total_memory_used,
        timestamp=time.time(),
        rdt_information=rdt_information
    )
    assert len(platform.cpus_usage) == platform.cpus, \
        "Inconsistency in cpu data returned by kernel"
    return platform, create_metrics(platform), create_labels(platform)
