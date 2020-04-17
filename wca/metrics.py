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
import time
from typing import Dict, Union, List, Tuple, Callable, Optional

from dataclasses import dataclass, field
from enum import Enum
from operator import sub


log = logging.getLogger(__name__)


class MetricName(str, Enum):
    # --- Task ---
    # Perf events based.
    TASK_INSTRUCTIONS = 'task_instructions'
    TASK_CYCLES = 'task_cycles'
    TASK_CACHE_MISSES = 'task_cache_misses'
    TASK_CACHE_REFERENCES = 'task_cache_references'
    TASK_STALLED_MEM_LOADS = 'task_stalled_mem_loads'
    # Perf event platform specific metrics
    # offcore_requests_outstanding_l3_miss_demand_data_rd
    TASK_OFFCORE_REQUESTS_L3_MISS_DEMAND_DATA_RD = 'task_offcore_requests_l3_miss_demand_data_rd'
    TASK_OFFCORE_REQUESTS_DEMAND_DATA_RD = 'task_offcore_requests_demand_data_rd'
    TASK_OFFCORE_REQUESTS_DEMAND_RFO = 'task_offcore_requests_demand_rfo'
    TASK_OFFCORE_REQUESTS_OUTSTANDING_L3_MISS_DEMAND_DATA_RD = \
        'task_offcore_requests_outstanding_l3_miss_demand_data_rd'
    TASK_MEM_LOAD_RETIRED_LOCAL_PMM = 'task_mem_load_retired_local_pmm'
    TASK_MEM_LOAD_RETIRED_LOCAL_DRAM = 'task_mem_load_retired_local_dram'
    TASK_MEM_LOAD_RETIRED_REMOTE_DRAM = 'task_mem_load_retired_remote_dram'
    TASK_MEM_INST_RETIRED_LOADS = 'task_mem_inst_retired_loads'
    TASK_MEM_INST_RETIRED_STORES = 'task_mem_inst_retired_stores'
    TASK_DTLB_LOAD_MISSES = 'task_dtlb_load_misses'
    # Extra perf based.
    TASK_SCALING_FACTOR_AVG = 'task_scaling_factor_avg'
    TASK_SCALING_FACTOR_MAX = 'task_scaling_factor_max'
    # Perf event task based derived
    # instructions/second
    TASK_IPS = 'task_ips'
    # instructions/cycle
    TASK_IPC = 'task_ipc'
    # (cache-references - cache_misses) / cache_references
    TASK_CACHE_HIT_RATIO = 'task_cache_hit_ratio'
    # (cache-references - cache_misses) / cache_references
    TASK_CACHE_MISSES_PER_KILO_INSTRUCTIONS = 'task_cache_misses_per_kilo_instructions'

    # Resctrl based.
    TASK_LLC_OCCUPANCY_BYTES = 'task_llc_occupancy_bytes'
    TASK_MEM_BANDWIDTH_BYTES = 'task_mem_bandwidth_bytes'
    TASK_MEM_BANDWIDTH_LOCAL_BYTES = 'task_mem_bandwidth_local_bytes'
    TASK_MEM_BANDWIDTH_REMOTE_BYTES = 'task_mem_bandwidth_remote_bytes'

    # Cgroup based.
    TASK_CPU_USAGE_SECONDS = 'task_cpu_usage_seconds'
    TASK_MEM_USAGE_BYTES = 'task_mem_usage_bytes'
    TASK_MEM_MAX_USAGE_BYTES = 'task_mem_max_usage_bytes'
    TASK_MEM_LIMIT_BYTES = 'task_mem_limit_bytes'
    TASK_MEM_SOFT_LIMIT_BYTES = 'task_mem_soft_limit_bytes'
    TASK_MEM_NUMA_PAGES = 'task_mem_numa_pages'
    TASK_MEM_PAGE_FAULTS = 'task_mem_page_faults'

    # /proc/PID/based
    TASK_WSS_REFERENCED_BYTES = 'task_wss_referenced_bytes'

    # From Kubernetes/Mesos or other orchestrator system.
    # From Kubernetes (requested) or Mesos (resources)
    TASK_REQUESTED_CPUS = 'task_requested_cpus'
    TASK_REQUESTED_MEM_BYTES = 'task_requested_mem_bytes'

    # Generic
    TASK_LAST_SEEN = 'task_last_seen'
    TASK_UP = 'task_up'
    TASK_SUBCONTAINERS = 'task_subcontainers'

    # ----------------- Platform ----------------------
    # Static information
    PLATFORM_TOPOLOGY_CORES = 'platform_topology_cores'
    PLATFORM_TOPOLOGY_CPUS = 'platform_topology_cpus'
    PLATFORM_TOPOLOGY_SOCKETS = 'platform_topology_sockets'
    # RAM topology
    PLATFORM_DIMM_COUNT = 'platform_dimm_count'
    PLATFORM_DIMM_TOTAL_SIZE_BYTES = 'platform_dimm_total_size_bytes'
    PLATFORM_MEM_MODE_SIZE_BYTES = 'platform_mem_mode_size_bytes'
    PLATFORM_DIMM_SPEED_BYTES_PER_SECOND = 'platform_dimm_speed_bytes_per_second'

    # /proc based (platform scope).
    # Utilization (usage): counter like, sum of all modes based on /proc/stat
    # "cpu line" with 10ms resolution expressed in [ms]
    PLATFORM_CPU_USAGE = 'platform_cpu_usage'
    # [bytes] based on /proc/meminfo (gauge like)
    # difference between MemTotal and MemAvail (or MemFree)
    PLATFORM_MEM_USAGE_BYTES = 'platform_mem_usage_bytes'

    # NUMA for whole platform
    PLATFORM_MEM_NUMA_FREE_BYTES = 'platform_mem_numa_free_bytes'
    PLATFORM_MEM_NUMA_USED_BYTES = 'platform_mem_numa_used_bytes'

    # /proc/vmstat
    PLATFORM_VMSTAT_NUMA_PAGES_MIGRATED = 'platform_vmstat_numa_pages_migrated'
    PLATFORM_VMSTAT_PGMIGRATE_SUCCESS = 'platform_vmstat_pgmigrate_success'
    PLATFORM_VMSTAT_PGMIGRATE_FAIL = 'platform_vmstat_pgmigrate_fail'
    PLATFORM_VMSTAT_NUMA_HINT_FAULTS = 'platform_vmstat_numa_hint_faults'
    PLATFORM_VMSTAT_NUMA_HINT_FAULTS_LOCAL = 'platform_vmstat_numa_hint_faults_local'
    PLATFORM_VMSTAT_PGFAULTS = 'platform_vmstat_pgfaults'

    # Perf event based from uncore PMU and derived
    PLATFORM_PMM_BANDWIDTH_READS = 'platform_pmm_bandwidth_reads'
    PLATFORM_PMM_BANDWIDTH_WRITES = 'platform_pmm_bandwidth_writes'
    PLATFORM_CAS_COUNT_READS = 'platform_cas_count_reads'
    PLATFORM_CAS_COUNT_WRITES = 'platform_cas_count_writes'
    PLATFORM_UPI_RXL_FLITS = 'platform_upi_rxl_flits'
    PLATFORM_UPI_TXL_FLITS = 'platform_upi_txl_flits'
    PLATFORM_RPQ_OCCUPANCY = 'platform_rpq_occupancy'
    PLATFORM_RPQ_INSERTS = 'platform_rpq_inserts'
    PLATFORM_IMC_CLOCKTICKS = 'platform_imc_clockticks'
    PLATFORM_RPQ_READ_LATENCY_SECONDS = 'platform_rpq_read_latency_seconds'
    # Derived
    PLATFORM_PMM_READS_BYTES_PER_SECOND = 'platform_pmm_reads_bytes_per_second'
    PLATFORM_PMM_WRITES_BYTES_PER_SECOND = 'platform_pmm_writes_bytes_per_second'
    PLATFORM_PMM_TOTAL_BYTES_PER_SECOND = 'platform_pmm_total_bytes_per_second'
    PLATFORM_DRAM_READS_BYTES_PER_SECOND = 'platform_dram_reads_bytes_per_second'
    PLATFORM_DRAM_WRITES_BYTES_PER_SECOND = 'platform_dram_writes_bytes_per_second'
    PLATFORM_DRAM_TOTAL_BYTES_PER_SECOND = 'platform_dram_total_bytes_per_second'
    PLATFORM_DRAM_HIT_RATIO = 'platform_dram_hit_ratio'
    # Based on UPI Flits
    PLATFORM_UPI_BANDWIDTH_BYTES_PER_SECOND = 'platform_upi_bandwidth_bytes_per_second'
    # Extra perf uncore based
    PLATFORM_SCALING_UNCORE_FACTOR = 'platform_scaling_uncore_factor'

    # Generic
    PLATFORM_LAST_SEEN = 'platform_last_seen'
    # ---------------- Internal -------------------------
    # Generic for WCA.
    WCA_UP = 'wca_up'
    WCA_INFORMATION = 'wca_information'
    WCA_TASKS = 'wca_tasks'
    WCA_MEM_USAGE_BYTES = 'wca_mem_usage_bytes'
    WCA_DURATION_SECONDS = 'wca_duration_seconds'
    WCA_DURATION_SECONDS_AVG = 'wca_duration_seconds_avg'
    # -------------pmembw---------------
    PLATFORM_CAPACITY_PER_NVDIMM_BYTES = 'platform_capacity_per_nvdimm_bytes'
    PLATFORM_AVG_POWER_PER_NVDIMM_WATTS = 'platform_avg_power_per_nvdimm_watts'
    PLATFORM_NVDIMM_READ_BANDWIDTH_BYTES_PER_SECOND = \
        'platform_nvdimm_read_bandwidth_bytes_per_second'
    PLATFORM_NVDIMM_WRITE_BANDWIDTH_BYTES_PER_SECOND = \
        'platform_nvdimm_write_bandwidth_bytes_per_second'

    def __repr__(self):
        return repr(self.value)


for key_name, value_name in MetricName.__members__.items():
    assert key_name == value_name.upper(), 'metric name mismatch %s' % key_name


class MetricType(str, Enum):
    GAUGE = 'gauge'  # arbitrary value (can go up and down)
    COUNTER = 'counter'  # monotonically increasing counter

    def __repr__(self):
        return repr(self.value)


MetricValue = Union[float, int]


class MetricGranularity(str, Enum):
    PLATFORM = 'platform'
    TASK = 'task'
    INTERNAL = 'internal'

    def __repr__(self):
        return repr(self.value)


class MetricUnit(str, Enum):
    BYTES = 'bytes'
    BYTES_PER_SECOND = 'bytes_per_second'
    SECONDS = 'seconds'
    NUMERIC = 'numeric'
    TIMESTAMP = 'timestamp'
    WATTS = 'watts'

    def __repr__(self):
        return repr(self.value)


class MetricSource(str, Enum):
    PERF_SUBSYSTEM_WITH_CGROUPS = 'perf subsystem with cgroups'
    PERF_SUBSYSTEM_UNCORE = 'perf subsystem with dynamic PMUs (uncore)'
    RESCTRL = 'resctrl filesystem'
    CGROUP = 'cgroup filesystem'
    PROCFS = '/proc filesystem'
    SYSFS = '/sys filesystem'
    INTERNAL = 'internal'
    DERIVED_PERF_WITH_CGROUPS = 'derived from perf subsystem with cgroups'
    DERIVED_PERF_UNCORE = 'derived from perf uncore'
    ORCHESTRATOR = 'orchestrator'
    DMIDECODE_BINARY = 'dmidecode binary output'
    IPMCTL_BINARY = 'ipmctl binary output'

    def __repr__(self):
        return repr(self.value)


# Order is enabled to allow sorting metrics according their metadata.
@dataclass(order=True)
class MetricMetadata:
    help: str
    type: MetricType
    unit: MetricUnit
    source: MetricSource
    granularity: MetricGranularity
    levels: Optional[List[str]]
    enabled: str
    # function used to merge measurements across many cgroups for ContainerSet
    # default behavior is sum (to cover both counters and resources like memory bandwidth, memory
    # usage or cache usage)
    merge_operation: Optional[Callable[[List[Union[float, int]]], Union[float, int]]] = sum


# Structure linking a metric with its type and help.
METRICS_METADATA: Dict[MetricName, MetricMetadata] = {
    # -------- Task -----------------
    # --- Perf subsystem with cgroups
    MetricName.TASK_INSTRUCTIONS:
        MetricMetadata(
            'Hardware PMU counter for number of instructions (PERF_COUNT_HW_INSTRUCTIONS). '
            'Fixed counter. '
            'Predefined perf PERF_TYPE_HARDWARE. Please man perf_event_open for more details.',
            MetricType.COUNTER,
            MetricUnit.NUMERIC,
            MetricSource.PERF_SUBSYSTEM_WITH_CGROUPS,
            MetricGranularity.TASK,
            [],
            'no (event_names)',
        ),
    MetricName.TASK_CYCLES:
        MetricMetadata(
            'Hardware PMU counter for number of cycles (PERF_COUNT_HW_CPU_CYCLES). '
            'Fixed counter. '
            'Predefined perf PERF_TYPE_HARDWARE. Please man perf_event_open for more details.',
            MetricType.COUNTER,
            MetricUnit.NUMERIC,
            MetricSource.PERF_SUBSYSTEM_WITH_CGROUPS,
            MetricGranularity.TASK,
            [],
            'no (event_names)',
        ),
    MetricName.TASK_CACHE_MISSES:
        MetricMetadata(
            'Hardware PMU counter for cache-misses (PERF_COUNT_HW_CACHE_MISSES).'
            'Predefined perf PERF_TYPE_HARDWARE. Please man perf_event_open for more details.',
            MetricType.COUNTER,
            MetricUnit.NUMERIC,
            MetricSource.PERF_SUBSYSTEM_WITH_CGROUPS,
            MetricGranularity.TASK,
            [],
            'no (event_names)',
        ),
    MetricName.TASK_CACHE_REFERENCES:
        MetricMetadata(
            'Hardware PMU counter for number of cache references (PERF_COUNT_HW_CACHE_REFERENCES).'
            'Predefined perf PERF_TYPE_HARDWARE. Please man perf_event_open for more details.',
            MetricType.COUNTER,
            MetricUnit.NUMERIC,
            MetricSource.PERF_SUBSYSTEM_WITH_CGROUPS,
            MetricGranularity.TASK,
            [],
            'no (event_names)',
        ),
    MetricName.TASK_STALLED_MEM_LOADS:
        MetricMetadata(
            'Execution stalls while memory subsystem has an outstanding load.'
            'CYCLE_ACTIVITY.STALLS_MEM_ANY'
            'Intel SDM October 2019 19-24 Vol. 3B, Table 19-3',
            MetricType.COUNTER,
            MetricUnit.NUMERIC,
            MetricSource.PERF_SUBSYSTEM_WITH_CGROUPS,
            MetricGranularity.TASK,
            [],
            'no (event_names)',
        ),
    MetricName.TASK_OFFCORE_REQUESTS_L3_MISS_DEMAND_DATA_RD:
        MetricMetadata(
            'Increment each cycle of the number of offcore outstanding demand data read '
            'requests from SQ that missed L3.'
            'Counts number of Offcore outstanding Demand Data Read requests '
            'that miss L3 cache in the superQ every cycle.'
            'OFFCORE_REQUESTS_OUTSTANDING.L3_MISS_DEMAND_DATA_RD'
            'Intel SDM October 2019 19-24 Vol. 3B, Table 19-3',
            MetricType.COUNTER,
            MetricUnit.NUMERIC,
            MetricSource.PERF_SUBSYSTEM_WITH_CGROUPS,
            MetricGranularity.TASK,
            [],
            'no (event_names)',
        ),
    MetricName.TASK_OFFCORE_REQUESTS_DEMAND_DATA_RD:
        MetricMetadata(
            'Counts the Demand Data Read requests sent to uncore. '
            'OFFCORE_REQUESTS.DEMAND_DATA_RD '
            'Intel SDM October 2019 19-24 Vol. 3B, Table 19-3',
            MetricType.COUNTER,
            MetricUnit.NUMERIC,
            MetricSource.PERF_SUBSYSTEM_WITH_CGROUPS,
            MetricGranularity.TASK,
            [],
            'no (event_names)',
        ),
    MetricName.TASK_OFFCORE_REQUESTS_DEMAND_RFO:
        MetricMetadata(
            'Demand RFO read requests sent to uncore, including regular RFOs, locks, ItoM. '
            'OFFCORE_REQUESTS.DEMAND_RFO '
            'Intel SDM October 2019 19-24 Vol. 3B, Table 19-3',
            MetricType.COUNTER,
            MetricUnit.NUMERIC,
            MetricSource.PERF_SUBSYSTEM_WITH_CGROUPS,
            MetricGranularity.TASK,
            [],
            'no (event_names)',
        ),
    MetricName.TASK_OFFCORE_REQUESTS_OUTSTANDING_L3_MISS_DEMAND_DATA_RD:
        MetricMetadata(
            'Demand Data Read requests who miss L3 cache. '
            'OFFCORE_REQUESTS.L3_MISS_DEMAND_DATA_RD.'
            'Intel SDM October 2019 19-24 Vol. 3B, Table 19-3',
            MetricType.COUNTER,
            MetricUnit.NUMERIC,
            MetricSource.PERF_SUBSYSTEM_WITH_CGROUPS,
            MetricGranularity.TASK,
            [],
            'no (event_names)',
        ),
    MetricName.TASK_MEM_LOAD_RETIRED_LOCAL_PMM:
        MetricMetadata(
            'Retired load instructions with '
            'local Intel® Optane™ DC persistent memory as the data source and the data'
            'request missed L3 (AppDirect or Memory Mode), and DRAM cache (Memory Mode). '
            'MEM_LOAD_RETIRED.LOCAL_PMM (Mnemonic) '
            'For CLX, Intel SDM October 2019 19-24 Vol. 3B, Table 19-4',
            MetricType.COUNTER,
            MetricUnit.NUMERIC,
            MetricSource.PERF_SUBSYSTEM_WITH_CGROUPS,
            MetricGranularity.TASK,
            [],
            'no (event_names)',
        ),
    MetricName.TASK_MEM_LOAD_RETIRED_LOCAL_DRAM:
        MetricMetadata(
            'Retired load instructions which '
            'data sources missed L3 but serviced from local DRAM.'
            'MEM_LOAD_L3_MISS_RETIRED.LOCAL_DRAM '
            'Intel SDM October 2019 Chapters 19-24 Vol. 3B Table 19-3',
            MetricType.COUNTER,
            MetricUnit.NUMERIC,
            MetricSource.PERF_SUBSYSTEM_WITH_CGROUPS,
            MetricGranularity.TASK,
            [],
            'no (event_names)',
        ),
    MetricName.TASK_MEM_LOAD_RETIRED_REMOTE_DRAM:
        MetricMetadata(
            'Retired load instructions '
            'which data sources missed L3 but serviced from remote dram. '
            'MEM_LOAD_L3_MISS_RETIRED.REMOTE_DRAM'
            'Intel SDM October 2019 Chapters 19-24 Vol. 3B Table 19-3',
            MetricType.COUNTER,
            MetricUnit.NUMERIC,
            MetricSource.PERF_SUBSYSTEM_WITH_CGROUPS,
            MetricGranularity.TASK,
            [],
            'no (event_names)',
        ),
    MetricName.TASK_MEM_INST_RETIRED_LOADS:
        MetricMetadata(
            'MEM_INST_RETIRED.ALL_LOADS '
            'All retired load instructions. '
            'Intel SDM October 2019 Chapters 19-24 Vol. 3B Table 19-3',
            MetricType.COUNTER,
            MetricUnit.NUMERIC,
            MetricSource.PERF_SUBSYSTEM_WITH_CGROUPS,
            MetricGranularity.TASK,
            [],
            'no (event_names)',
        ),
    MetricName.TASK_MEM_INST_RETIRED_STORES:
        MetricMetadata(
            'MEM_INST_RETIRED.ALL_STORES '
            'All retired store instructions. '
            'Intel SDM October 2019 Chapters 19-24 Vol. 3B Table 19-3',
            MetricType.COUNTER,
            MetricUnit.NUMERIC,
            MetricSource.PERF_SUBSYSTEM_WITH_CGROUPS,
            MetricGranularity.TASK,
            [],
            'no (event_names)',
        ),
    MetricName.TASK_DTLB_LOAD_MISSES:
        MetricMetadata(
            'DTLB_LOAD_MISSES.WALK_COMPLETED'
            'Counts demand data loads that caused a completed'
            'page walk of any page size (4K/2M/4M/1G). This implies'
            'it missed in all TLB levels. The page walk can end with'
            'or without a fault'
            'Intel SDM October 2019 Chapters 19-24 Vol. 3B Table 19-3',
            MetricType.COUNTER,
            MetricUnit.NUMERIC,
            MetricSource.PERF_SUBSYSTEM_WITH_CGROUPS,
            MetricGranularity.TASK,
            [],
            'no (event_names)',
        ),
    # Perf subsystem meta metrics (errors)
    MetricName.TASK_SCALING_FACTOR_AVG:
        MetricMetadata(
            'Perf subsystem metric scaling factor, averaged value of all events and cpus '
            '(value 1.0 is the best, meaning that there is no scaling at all for any metric).',
            MetricType.GAUGE,
            MetricUnit.NUMERIC,
            MetricSource.PERF_SUBSYSTEM_WITH_CGROUPS,
            MetricGranularity.TASK,
            [],
            'auto (depending on event_names)',
        ),
    MetricName.TASK_SCALING_FACTOR_MAX:
        MetricMetadata(
            'Perf subsystem metric scaling factor, maximum value of all events and cpus '
            '(value 1.0 is the best, meaning that there is no scaling at all for any metric).',
            MetricType.GAUGE,
            MetricUnit.NUMERIC,
            MetricSource.PERF_SUBSYSTEM_WITH_CGROUPS,
            MetricGranularity.TASK,
            [],
            'auto (depending on event_names)',
        ),
    # perf per task derived
    MetricName.TASK_IPS:
        MetricMetadata(
            'Instructions per second.',
            MetricType.GAUGE,
            MetricUnit.NUMERIC,
            MetricSource.DERIVED_PERF_WITH_CGROUPS,
            MetricGranularity.TASK,
            [],
            'no (enable_derived_metrics)',
        ),
    MetricName.TASK_IPC:
        MetricMetadata(
            'Instructions per cycle.',
            MetricType.GAUGE,
            MetricUnit.NUMERIC,
            MetricSource.DERIVED_PERF_WITH_CGROUPS,
            MetricGranularity.TASK,
            [],
            'no (enable_derived_metrics)',
        ),
    MetricName.TASK_CACHE_HIT_RATIO:
        MetricMetadata(
            'Cache hit ratio, based on cache-misses and cache-references.',
            MetricType.GAUGE,
            MetricUnit.NUMERIC,
            MetricSource.DERIVED_PERF_WITH_CGROUPS,
            MetricGranularity.TASK,
            [],
            'no (enable_derived_metrics)',
        ),
    MetricName.TASK_CACHE_MISSES_PER_KILO_INSTRUCTIONS:
        MetricMetadata(
            'Cache misses per kilo instructions.',
            MetricType.GAUGE,
            MetricUnit.NUMERIC,
            MetricSource.DERIVED_PERF_WITH_CGROUPS,
            MetricGranularity.TASK,
            [],
            'no (enable_derived_metrics)',
        ),

    # --- resctrl/RDT
    MetricName.TASK_LLC_OCCUPANCY_BYTES:
        MetricMetadata(
            'LLC occupancy from resctrl filesystem based on Intel RDT technology.',
            MetricType.GAUGE,
            MetricUnit.BYTES,
            MetricSource.RESCTRL,
            MetricGranularity.TASK,
            [],
            'auto (rdt_enabled)',
        ),
    MetricName.TASK_MEM_BANDWIDTH_BYTES:
        MetricMetadata(
            'Total memory bandwidth using Memory Bandwidth Monitoring.',
            MetricType.COUNTER,
            MetricUnit.BYTES,
            MetricSource.RESCTRL,
            MetricGranularity.TASK,
            [],
            'auto (rdt_enabled)',
        ),
    MetricName.TASK_MEM_BANDWIDTH_LOCAL_BYTES:
        MetricMetadata(
            'Total local memory bandwidth using Memory Bandwidth Monitoring.',
            MetricType.COUNTER,
            MetricUnit.BYTES,
            MetricSource.RESCTRL,
            MetricGranularity.TASK,
            [],
            'auto (rdt_enabled)',
        ),
    MetricName.TASK_MEM_BANDWIDTH_REMOTE_BYTES:
        MetricMetadata(
            'Total remote memory bandwidth using Memory Bandwidth Monitoring.',
            MetricType.COUNTER,
            MetricUnit.BYTES,
            MetricSource.RESCTRL,
            MetricGranularity.TASK,
            [],
            'auto (rdt_enabled)',
        ),

    # --- cgroup per tasks
    MetricName.TASK_CPU_USAGE_SECONDS:
        MetricMetadata(
            'Time taken by task based on cpuacct.usage (total kernel and user space).',
            MetricType.COUNTER,
            MetricUnit.SECONDS,
            MetricSource.CGROUP,
            MetricGranularity.TASK,
            [],
            'yes',
        ),
    MetricName.TASK_MEM_USAGE_BYTES:
        MetricMetadata(
            'Memory usage_in_bytes per tasks returned from cgroup memory subsystem.',
            MetricType.GAUGE,
            MetricUnit.BYTES,
            MetricSource.CGROUP,
            MetricGranularity.TASK,
            [],
            'yes',
        ),
    MetricName.TASK_MEM_MAX_USAGE_BYTES:
        MetricMetadata(
            'Memory max_usage_in_bytes per tasks returned from cgroup memory subsystem.',
            MetricType.GAUGE,
            MetricUnit.BYTES,
            MetricSource.CGROUP,
            MetricGranularity.TASK,
            [],
            'yes',
        ),
    MetricName.TASK_MEM_LIMIT_BYTES:
        MetricMetadata(
            'Memory limit_in_bytes per tasks returned from cgroup memory subsystem.',
            MetricType.GAUGE,
            MetricUnit.BYTES,
            MetricSource.CGROUP,
            MetricGranularity.TASK,
            [],
            'yes',
        ),
    MetricName.TASK_MEM_SOFT_LIMIT_BYTES:
        MetricMetadata(
            'Memory soft_limit_in_bytes per tasks returned from cgroup memory subsystem.',
            MetricType.GAUGE,
            MetricUnit.BYTES,
            MetricSource.CGROUP,
            MetricGranularity.TASK,
            [],
            'yes',
        ),
    MetricName.TASK_MEM_NUMA_PAGES:
        MetricMetadata(
            'Number of used pages per NUMA node'
            '(key: hierarchical_total is used if available or just'
            'total with warning), from cgroup memory controller from memory.numa_stat file.',
            MetricType.GAUGE,
            MetricUnit.NUMERIC,
            MetricSource.CGROUP,
            MetricGranularity.TASK,
            ['numa_node'],
            'yes',
        ),
    MetricName.TASK_MEM_PAGE_FAULTS:
        MetricMetadata(
            'Number of page faults for task.',
            MetricType.COUNTER,
            MetricUnit.NUMERIC,
            MetricSource.CGROUP,
            MetricGranularity.TASK,
            [],
            'yes',
        ),
    MetricName.TASK_WSS_REFERENCED_BYTES:
        MetricMetadata(
            'Task referenced bytes during last measurements cycle based on /proc/smaps '
            'Referenced field, with /proc/PIDs/clear_refs set to 1 accordinn wss_reset_interval.'
            'Warning: this is intrusive collection, '
            'because can influence kernel page reclaim policy and add latency.'
            'Refer to https://github.com/brendangregg/wss#wsspl-referenced-page-flag for more '
            'details.',
            MetricType.GAUGE,
            MetricUnit.BYTES,
            '/procs/PIDS/smaps',
            MetricGranularity.TASK,
            [],
            'yes',
        ),

    # Generic or from orchestration
    MetricName.TASK_REQUESTED_CPUS:
        MetricMetadata(
            'Tasks resources cpus initial requests.',
            MetricType.GAUGE,
            MetricUnit.NUMERIC,
            MetricSource.ORCHESTRATOR,
            MetricGranularity.TASK,
            [],
            'yes',
        ),
    MetricName.TASK_REQUESTED_MEM_BYTES:
        MetricMetadata(
            'Tasks resources memory initial requests.',
            MetricType.GAUGE,
            MetricUnit.BYTES,
            MetricSource.ORCHESTRATOR,
            MetricGranularity.TASK,
            [],
            'yes',
        ),
    MetricName.TASK_LAST_SEEN:
        MetricMetadata(
            'Time the task was last seen.',
            MetricType.COUNTER,
            MetricUnit.TIMESTAMP,
            MetricSource.INTERNAL,
            MetricGranularity.TASK,
            [],
            'yes',
        ),
    MetricName.TASK_UP:
        MetricMetadata(
            'Always returns 1 for running task.',
            MetricType.COUNTER,
            MetricUnit.NUMERIC,
            MetricSource.INTERNAL,
            MetricGranularity.TASK,
            [],
            'yes',
        ),
    MetricName.TASK_SUBCONTAINERS:
        MetricMetadata(
            'Returns number of Kubernetes Pod Containers or 0 for others.',
            MetricType.GAUGE,
            MetricUnit.NUMERIC,
            MetricSource.INTERNAL,
            MetricGranularity.TASK,
            [],
            'yes',
        ),
    # ----------------------- Platform ---------------------------------
    MetricName.PLATFORM_TOPOLOGY_CORES:
        MetricMetadata(
            'Platform information about number of physical cores',
            MetricType.GAUGE,
            MetricUnit.NUMERIC,
            MetricSource.INTERNAL,
            MetricGranularity.PLATFORM,
            [],
            'yes'
        ),
    MetricName.PLATFORM_TOPOLOGY_CPUS:
        MetricMetadata(
            'Platform information about number of logical cpus',
            MetricType.GAUGE,
            MetricUnit.NUMERIC,
            MetricSource.INTERNAL,
            MetricGranularity.PLATFORM,
            [],
            'yes',
        ),
    MetricName.PLATFORM_TOPOLOGY_SOCKETS:
        MetricMetadata(
            'Platform information about number of sockets',
            MetricType.GAUGE,
            MetricUnit.NUMERIC,
            MetricSource.INTERNAL,
            MetricGranularity.PLATFORM,
            [],
            'yes',
        ),
    # RAM topology
    MetricName.PLATFORM_DIMM_COUNT:
        MetricMetadata(
            'Number of RAM DIMM (all types memory modules)',
            MetricType.GAUGE,
            MetricUnit.NUMERIC,
            MetricSource.DMIDECODE_BINARY,
            MetricGranularity.PLATFORM,
            ['dimm_type'],
            'no (gather_hw_mm_topology)'
        ),
    MetricName.PLATFORM_DIMM_TOTAL_SIZE_BYTES:
        MetricMetadata(
            'Total RAM size (all types memory modules)',
            MetricType.GAUGE,
            MetricUnit.BYTES,
            MetricSource.DMIDECODE_BINARY,
            MetricGranularity.PLATFORM,
            ['dimm_type'],
            'no (gather_hw_mm_topology)',
        ),
    MetricName.PLATFORM_MEM_MODE_SIZE_BYTES:
        MetricMetadata(
            'Size of RAM (Persistent memory) configured in memory mode.',
            MetricType.GAUGE,
            MetricUnit.NUMERIC,
            MetricSource.IPMCTL_BINARY,
            MetricGranularity.PLATFORM,
            [],
            'no (gather_hw_mm_topology)',
        ),
    MetricName.PLATFORM_DIMM_SPEED_BYTES_PER_SECOND:
        MetricMetadata(
            'Total platform DRAM speed',
            MetricType.GAUGE,
            MetricUnit.BYTES_PER_SECOND,
            MetricSource.DMIDECODE_BINARY,
            MetricGranularity.PLATFORM,
            [],
            'no (gather_hw_mm_topology)'
        ),
    # /proc fs based
    MetricName.PLATFORM_CPU_USAGE:
        MetricMetadata(
            'Logical CPU usage in 1/USER_HZ (usually 10ms).'
            'Calculated using values based on /proc/stat.',
            MetricType.COUNTER,
            MetricUnit.NUMERIC,
            MetricSource.PROCFS,
            MetricGranularity.PLATFORM,
            ['cpu'],
            'yes'
        ),
    MetricName.PLATFORM_MEM_USAGE_BYTES:
        MetricMetadata(
            'Total memory used by platform in bytes based on /proc/meminfo '
            'and uses heuristic based on linux free tool (total - free - buffers - cache).',
            MetricType.GAUGE,
            MetricUnit.BYTES,
            MetricSource.PROCFS,
            MetricGranularity.PLATFORM,
            [],
            'yes'
        ),

    # VM Stat based
    MetricName.PLATFORM_MEM_NUMA_FREE_BYTES:
        MetricMetadata(
            'NUMA memory free per NUMA node based on /sys/devices/system/node/* (MemFree:)',
            MetricType.GAUGE,
            MetricUnit.BYTES,
            MetricSource.SYSFS,
            MetricGranularity.PLATFORM,
            ['numa_node'],
            'yes'
        ),
    MetricName.PLATFORM_MEM_NUMA_USED_BYTES:
        MetricMetadata(
            'NUMA memory free per NUMA used based on /sys/devices/system/node/* (MemUsed:)',
            MetricType.GAUGE,
            MetricUnit.BYTES,
            MetricSource.SYSFS,
            MetricGranularity.PLATFORM,
            ['numa_node'],
            'yes',
        ),
    # VMStat
    MetricName.PLATFORM_VMSTAT_NUMA_PAGES_MIGRATED:
        MetricMetadata(
            'Virtual Memory stats based on /proc/vmstat for number of migrates pages (autonuma)',
            MetricType.COUNTER,
            MetricUnit.NUMERIC,
            MetricSource.PROCFS,
            MetricGranularity.PLATFORM,
            [],
            'yes',
        ),
    MetricName.PLATFORM_VMSTAT_PGMIGRATE_SUCCESS:
        MetricMetadata(
            'Virtual Memory stats based on /proc/vmstat for number of migrates pages (succeed)',
            MetricType.COUNTER,
            MetricUnit.NUMERIC,
            MetricSource.PROCFS,
            MetricGranularity.PLATFORM,
            [],
            'yes',
        ),
    MetricName.PLATFORM_VMSTAT_PGMIGRATE_FAIL:
        MetricMetadata(
            'Virtual Memory stats based on /proc/vmstat for number of migrates pages (failed)',
            MetricType.COUNTER,
            MetricUnit.NUMERIC,
            MetricSource.PROCFS,
            MetricGranularity.PLATFORM,
            [],
            'yes',
        ),
    MetricName.PLATFORM_VMSTAT_NUMA_HINT_FAULTS:
        MetricMetadata(
            'Virtual Memory stats based on /proc/vmstat for pgfaults for migration hints',
            MetricType.COUNTER,
            MetricUnit.NUMERIC,
            MetricSource.PROCFS,
            MetricGranularity.PLATFORM,
            [],
            'yes'
        ),
    MetricName.PLATFORM_VMSTAT_NUMA_HINT_FAULTS_LOCAL:
        MetricMetadata(
            'Virtual Memory stats based on /proc/vmstat: pgfaults for migration hints (local)',
            MetricType.COUNTER,
            MetricUnit.NUMERIC,
            MetricSource.PROCFS,
            MetricGranularity.PLATFORM,
            [],
            'yes'
        ),
    MetricName.PLATFORM_VMSTAT_PGFAULTS:
        MetricMetadata(
            'Virtual Memory stats based on /proc/vmstat:number of page faults',
            MetricType.COUNTER,
            MetricUnit.NUMERIC,
            MetricSource.PROCFS,
            MetricGranularity.PLATFORM,
            [],
            'yes'
        ),
    # Perf uncore
    MetricName.PLATFORM_PMM_BANDWIDTH_READS:
        MetricMetadata(
            'Persistent memory module number of reads.',
            MetricType.COUNTER,
            MetricUnit.NUMERIC,
            MetricSource.PERF_SUBSYSTEM_UNCORE,
            MetricGranularity.PLATFORM,
            ['socket', 'pmu_type'],
            'no (uncore_event_names)',
        ),
    MetricName.PLATFORM_PMM_BANDWIDTH_WRITES:
        MetricMetadata(
            'Persistent memory module number of writes.',
            MetricType.COUNTER,
            MetricUnit.NUMERIC,
            MetricSource.PERF_SUBSYSTEM_UNCORE,
            MetricGranularity.PLATFORM,
            ['socket', 'pmu_type'],
            'no (uncore_event_names)',
        ),
    MetricName.PLATFORM_CAS_COUNT_READS:
        MetricMetadata(
            'Column adress select number of reads',
            MetricType.COUNTER,
            MetricUnit.NUMERIC,
            MetricSource.PERF_SUBSYSTEM_UNCORE,
            MetricGranularity.PLATFORM,
            ['socket', 'pmu_type'],
            'no (uncore_event_names)',
        ),
    MetricName.PLATFORM_CAS_COUNT_WRITES:
        MetricMetadata(
            'Column adress select number of writes',
            MetricType.COUNTER,
            MetricUnit.NUMERIC,
            MetricSource.PERF_SUBSYSTEM_UNCORE,
            MetricGranularity.PLATFORM,
            ['socket', 'pmu_type'],
            'no (uncore_event_names)',
        ),
    MetricName.PLATFORM_UPI_RXL_FLITS:
        MetricMetadata(
            'TBD',
            MetricType.COUNTER,
            MetricUnit.NUMERIC,
            MetricSource.PERF_SUBSYSTEM_UNCORE,
            MetricGranularity.PLATFORM,
            ['socket', 'pmu_type'],
            'no (uncore_event_names)',
        ),
    MetricName.PLATFORM_UPI_TXL_FLITS:
        MetricMetadata(
            'TBD',
            MetricType.COUNTER,
            MetricUnit.NUMERIC,
            MetricSource.PERF_SUBSYSTEM_UNCORE,
            MetricGranularity.PLATFORM,
            ['socket', 'pmu_type'],
            'no (uncore_event_names)',
        ),
    MetricName.PLATFORM_RPQ_OCCUPANCY:
        MetricMetadata(
            'Pending queue occupancy',
            MetricType.GAUGE,
            MetricUnit.NUMERIC,
            MetricSource.PERF_SUBSYSTEM_UNCORE,
            MetricGranularity.PLATFORM,
            ['socket', 'pmu_type'],
            'no (uncore_event_names)'
        ),
    MetricName.PLATFORM_RPQ_INSERTS:
        MetricMetadata(
            'Pending queue allocations',
            MetricType.GAUGE,
            MetricUnit.NUMERIC,
            MetricSource.PERF_SUBSYSTEM_UNCORE,
            MetricGranularity.PLATFORM,
            ['socket', 'pmu_type'],
            'no (uncore_event_names)'
        ),
    MetricName.PLATFORM_IMC_CLOCKTICKS:
        MetricMetadata(
            'IMC clockticks',
            MetricType.COUNTER,
            MetricUnit.NUMERIC,
            MetricSource.PERF_SUBSYSTEM_UNCORE,
            MetricGranularity.PLATFORM,
            ['socket', 'pmu_type'],
            'no (uncore_event_names)'
        ),
    MetricName.PLATFORM_RPQ_READ_LATENCY_SECONDS:
        MetricMetadata(
            'Read latency',
            MetricType.GAUGE,
            MetricUnit.SECONDS,
            MetricSource.DERIVED_PERF_UNCORE,
            MetricGranularity.PLATFORM,
            ['socket'],
            'no (uncore_event_names: platform_imc_clockticks, platform_rpq_occupancy, '
            'platform_rpq_inserts and set enable_derived_metrics)'
        ),
    # Perf uncore derived
    MetricName.PLATFORM_PMM_READS_BYTES_PER_SECOND:
        MetricMetadata(
            'TBD',
            MetricType.GAUGE,
            MetricUnit.NUMERIC,
            MetricSource.DERIVED_PERF_UNCORE,
            MetricGranularity.PLATFORM,
            ['socket', 'pmu_type'],
            'no (uncore_event_names: platform_pmm_bandwidth_reads '
            'and set enable_derived_metrics)',
        ),
    MetricName.PLATFORM_PMM_WRITES_BYTES_PER_SECOND:
        MetricMetadata(
            'TBD',
            MetricType.GAUGE,
            MetricUnit.NUMERIC,
            MetricSource.DERIVED_PERF_UNCORE,
            MetricGranularity.PLATFORM,
            ['socket', 'pmu_type'],
            'no (uncore_event_names: platform_pmm_bandwidth_writes '
            'and set enable_derived_metrics)',
        ),
    MetricName.PLATFORM_PMM_TOTAL_BYTES_PER_SECOND:
        MetricMetadata(
            'TBD',
            MetricType.GAUGE,
            MetricUnit.NUMERIC,
            MetricSource.DERIVED_PERF_UNCORE,
            MetricGranularity.PLATFORM,
            ['socket', 'pmu_type'],
            'no (uncore_event_names: platform_pmm_bandwidth_reads, '
            'platform_pmm_bandwidth_writes and set enable_derived_metrics)',
        ),
    MetricName.PLATFORM_DRAM_READS_BYTES_PER_SECOND:
        MetricMetadata(
            'TBD',
            MetricType.GAUGE,
            MetricUnit.NUMERIC,
            MetricSource.DERIVED_PERF_UNCORE,
            MetricGranularity.PLATFORM,
            ['socket', 'pmu_type'],
            'no (uncore_event_names: platform_cas_count_reads and set enable_derived_metrics)',
        ),
    MetricName.PLATFORM_DRAM_WRITES_BYTES_PER_SECOND:
        MetricMetadata(
            'TBD',
            MetricType.GAUGE,
            MetricUnit.NUMERIC,
            MetricSource.DERIVED_PERF_UNCORE,
            MetricGranularity.PLATFORM,
            ['socket', 'pmu_type'],
            'no (uncore_event_names: platform_cas_count_writes and set enable_derived_metrics)',
        ),
    MetricName.PLATFORM_DRAM_TOTAL_BYTES_PER_SECOND:
        MetricMetadata(
            'TBD',
            MetricType.GAUGE,
            MetricUnit.NUMERIC,
            MetricSource.DERIVED_PERF_UNCORE,
            MetricGranularity.PLATFORM,
            ['socket', 'pmu_type'],
            'no (uncore_event_names: platform_cas_count_reads, '
            'platform_cas_count_writes and set enable_derived_metrics)',
        ),
    MetricName.PLATFORM_DRAM_HIT_RATIO:
        MetricMetadata(
            'TBD',
            MetricType.GAUGE,
            MetricUnit.NUMERIC,
            MetricSource.DERIVED_PERF_UNCORE,
            MetricGranularity.PLATFORM,
            ['socket', 'pmu_type'],
            'no (uncore_event_names: platform_cas_count_reads, '
            'platform_cas_count_writes and set enable_derived_metrics)',
        ),
    MetricName.PLATFORM_UPI_BANDWIDTH_BYTES_PER_SECOND:
        MetricMetadata(
            'TBD',
            MetricType.COUNTER,
            MetricUnit.NUMERIC,
            MetricSource.DERIVED_PERF_UNCORE,
            MetricGranularity.PLATFORM,
            ['socket', 'pmu_type'],
            'no (uncore_event_names: platform_upi_txl_flits, '
            'platform_upi_rxl_flits and set enable_derived_metrics)',
        ),
    MetricName.PLATFORM_SCALING_UNCORE_FACTOR:
        MetricMetadata(
            'Perf uncore subsystem metric scaling factor'
            '(value 1.0 is the best, meaning that there is no scaling at all '
            'for any uncore metric)',
            MetricType.GAUGE,
            MetricUnit.NUMERIC,
            MetricSource.PERF_SUBSYSTEM_UNCORE,
            MetricGranularity.PLATFORM,
            ['socket', 'pmu_type'],
            'auto, (depending on uncore_event_names)'
        ),
    MetricName.PLATFORM_LAST_SEEN:
        MetricMetadata(
            'Timestamp the information about platform was last collected',
            MetricType.COUNTER,
            MetricUnit.TIMESTAMP,
            MetricSource.INTERNAL,
            MetricGranularity.PLATFORM,
            [],
            'yes',
        ),
    # ---------------------------- WCA internal ----------------------------
    MetricName.WCA_UP:
        MetricMetadata(
            'Health check for WCA returning timestamps of last iteration',
            MetricType.COUNTER,
            MetricUnit.TIMESTAMP,
            MetricSource.INTERNAL,
            MetricGranularity.INTERNAL,
            [],
            'yes',
        ),
    MetricName.WCA_INFORMATION:
        MetricMetadata(
            'Special metric to cover some meta information like wca_version or cpu_model '
            'or platform topology (to be used instead of include_optional_labels)',
            MetricType.GAUGE,
            MetricUnit.NUMERIC,
            MetricSource.INTERNAL,
            MetricGranularity.INTERNAL,
            [],
            'yes',
        ),
    MetricName.WCA_TASKS:
        MetricMetadata(
            'Number of discovered tasks',
            MetricType.GAUGE,
            MetricUnit.NUMERIC,
            MetricSource.INTERNAL,
            MetricGranularity.INTERNAL,
            [],
            'yes',
        ),
    MetricName.WCA_MEM_USAGE_BYTES:
        MetricMetadata(
            'Memory usage by WCA itself (getrusage for self and children).',
            MetricType.GAUGE,
            MetricUnit.BYTES,
            MetricSource.INTERNAL,
            MetricGranularity.INTERNAL,
            [],
            'yes',
        ),
    MetricName.WCA_DURATION_SECONDS:
        MetricMetadata(
            'Internal WCA function call duration metric for profiling',
            MetricType.GAUGE,
            MetricUnit.NUMERIC,
            MetricSource.INTERNAL,
            MetricGranularity.INTERNAL,
            [],
            'yes',
        ),
    MetricName.WCA_DURATION_SECONDS_AVG:
        MetricMetadata(
            'Internal WCA function call duration metric for profiling (average from last restart)',
            MetricType.GAUGE,
            MetricUnit.NUMERIC,
            MetricSource.INTERNAL,
            MetricGranularity.INTERNAL,
            [],
            'yes',
        ),
    # --------------------- pmembw ------------------------
    MetricName.PLATFORM_CAPACITY_PER_NVDIMM_BYTES:
        MetricMetadata(
            'Platform capacity per NVDIMM',
            MetricType.GAUGE,
            MetricUnit.BYTES,
            MetricSource.INTERNAL,
            MetricGranularity.PLATFORM,
            [],
            'yes'
        ),
    MetricName.PLATFORM_AVG_POWER_PER_NVDIMM_WATTS:
        MetricMetadata(
            'Average power used by NVDIMM on the platform',
            MetricType.GAUGE,
            MetricUnit.WATTS,
            MetricSource.INTERNAL,
            MetricGranularity.PLATFORM,
            [],
            'yes'
        ),
    MetricName.PLATFORM_NVDIMM_READ_BANDWIDTH_BYTES_PER_SECOND:
        MetricMetadata(
            'Theoretical reads bandwidth per platform',
            MetricType.GAUGE,
            MetricUnit.BYTES_PER_SECOND,
            MetricSource.INTERNAL,
            MetricGranularity.PLATFORM,
            ['socket'],
            'yes'
        ),
    MetricName.PLATFORM_NVDIMM_WRITE_BANDWIDTH_BYTES_PER_SECOND:
        MetricMetadata(
            'Theoretical writes bandwidth per platform',
            MetricType.GAUGE,
            MetricUnit.BYTES_PER_SECOND,
            MetricSource.INTERNAL,
            MetricGranularity.PLATFORM,
            ['socket'],
            'yes'
        ),
}

# Make sure the same order is used.
for key1, key2 in zip(MetricName.__members__.values(), METRICS_METADATA.keys()):
    assert key1 == key2, 'order mismatch %s' % key1


@dataclass
class Metric:
    name: Union[str, MetricName]
    value: MetricValue
    labels: Dict[str, str] = field(default_factory=dict)
    unit: Union[MetricUnit] = None
    type: MetricType = None
    help: str = None
    granularity: MetricGranularity = None

    @staticmethod
    def create_metric_with_metadata(name, value, labels=None, granularity=None):
        metric = Metric(
            name=name,
            value=value,
            labels=labels or dict(),
            granularity=granularity
        )
        if name in METRICS_METADATA:
            metric.type = METRICS_METADATA[name].type
            metric.help = METRICS_METADATA[name].help
            metric.unit = METRICS_METADATA[name].unit
            metric.granularity = METRICS_METADATA[name].granularity
        return metric


LevelMeasurements = Dict[Union[str, int], Union[MetricValue, 'LevelMeasurements']]

Measurements = Union[
    # Simple mapping from name to value
    # "task_llc_occupancy_bytes": 1234566,
    Dict[MetricName, MetricValue],

    # recursive hierarchical type  (levels may be represented by str or int)
    # e.g. for levels=[CPU]
    # "task_instructions": {0: 1234, 1: 2452},
    Dict[MetricName, LevelMeasurements]
]


def merge_measurements(measurements_list: List[Measurements]) -> \
        Tuple[Measurements, List[MetricName]]:
    """Returns dictionary with metrics which are contained in all input measurements with value set
       to arithmetic sum."""
    summed_metrics: Measurements = {}

    all_metrics_names = set()  # Sum of set of names.
    for measurements in measurements_list:
        all_metrics_names.update(measurements.keys())

    for metric_name in all_metrics_names:
        if metric_name in METRICS_METADATA:
            operation = METRICS_METADATA[metric_name].merge_operation
        else:
            log.debug('By default, unknown metric %r uses "sum" as merge operation.', metric_name)
            operation = sum

        # Unknown metric or has no levels.
        if metric_name not in METRICS_METADATA or not METRICS_METADATA[metric_name].levels:
            try:
                summed_metrics[metric_name] = operation(
                    [measurements[metric_name] for measurements in measurements_list
                     if metric_name in measurements])
            except TypeError:
                log.exception("{} seems to be hierarchical but metric levels are "
                              "not specified.".format(metric_name))
                raise
        else:
            max_depth = len(METRICS_METADATA[metric_name].levels)
            summed = dict()
            for measurements in measurements_list:
                if metric_name in measurements:
                    _list_leveled_metrics(summed, measurements[metric_name], max_depth)
            _operation_on_leveled_metric(summed, operation, max_depth)
            summed_metrics[metric_name] = summed

    return summed_metrics


def _list_leveled_metrics(aggregated_metric, new_metric, max_depth, depth=0):
    """Making list of leveled metric with hierarchy preservation.
    Results will be stored in aggregated_metric (numeric leafs will be converted to arrays)
    and new_metric will be appended.
    """
    for key, value in new_metric.items():
        if depth == max_depth - 1:
            if key in aggregated_metric and type(aggregated_metric[key]) == list:
                aggregated_metric[key].append(value)
            else:
                aggregated_metric[key] = [value]
        else:
            _list_leveled_metrics(aggregated_metric[key], value, max_depth, depth + 1)


def _operation_on_leveled_metric(aggregated_metric, operation, max_depth,
                                 depth=0):
    """Performing declared operation on leveled metric. It is assumed
    that result will be stored in aggregated and on max_depth there is
    a list of values than can be aggregated using operation."""
    for key, value in aggregated_metric.items():
        if depth == max_depth - 1:
            aggregated_metric[key] = operation(value)
        else:
            _operation_on_leveled_metric(
                aggregated_metric[key], operation, max_depth, depth + 1)


def _operation_on_leveled_dicts(a, b, operation, max_depth, depth=0):
    """Performing declared operation on two leveled hierarchical metrics.
    The result will be returned as new object."""
    from wca.logger import TRACE
    operation_result = {}
    for key, value in a.items():
        if depth == max_depth - 1:
            try:
                operation_result[key] = operation(a[key], b[key])
            except ZeroDivisionError:
                log.log(TRACE, 'Merging op Division by zero. Ignoring! for key=%s', key)
        else:
            operation_result[key] = _operation_on_leveled_dicts(
                a[key], b[key], operation, max_depth, depth + 1)

    return operation_result


class BaseDerivedMetricsGenerator:
    """ Calculate derived metrics based on predefined rules:

    ipc = instructions / cycle
    ips = instructions / second
    cache_hit_ratio = cache-reference - cache-misses / cache-references
    cache_misses_per_kilo_instructions = cache_misses / (instructions/1000)
    """

    def __init__(self, get_measurements_func: Callable[[], Measurements]):
        self._prev_measurements = None
        self._prev_ts = None
        self.get_measurements_func = get_measurements_func

    def get_measurements(self) -> Measurements:
        measurements = self.get_measurements_func()
        return self._get_measurements_with_derived_metrics(measurements)

    def _get_measurements_with_derived_metrics(self, measurements):
        """Extend given measurements with some derived metrics like IPC, IPS, cache_hit_ratio.
        Extends only if those metrics are enabled in "event_names".
        """

        now = time.time()

        def available(*names):
            return all(name in measurements and name in self._prev_measurements for name in names)

        def delta(*names):
            if not available(*names):
                return 0

            calculated_delta = []
            for metric_name in names:
                if metric_name in METRICS_METADATA and METRICS_METADATA[metric_name].levels:
                    max_depth = len(METRICS_METADATA[metric_name].levels)
                    calculated_delta.append(
                        _operation_on_leveled_dicts(measurements[metric_name],
                                                    self._prev_measurements[metric_name],
                                                    sub, max_depth))
                else:
                    calculated_delta.append(
                        measurements[metric_name] - self._prev_measurements[metric_name])

            return calculated_delta

        # if specific pairs are available calculate derived metrics
        if self._prev_measurements is not None:
            time_delta = now - self._prev_ts
            self._derive(measurements, delta, available, time_delta)

        self._prev_measurements = measurements
        self._prev_ts = now

        return measurements

    def _derive(self, measurements, delta, available, time_delta):
        raise NotImplementedError


class MissingMeasurementException(Exception):
    """when metric has not been collected with success"""
    pass


def export_metrics_from_measurements(measurements: Measurements) -> List[Metric]:
    """Generate (recursively) Metric based on hierarchical measurements taking levels into
     consideration and attaching labels to those metrics based on defined levels."""
    all_metrics = []
    for metric_name, metric_node in measurements.items():
        if metric_name in METRICS_METADATA and METRICS_METADATA[metric_name].levels:
            levels = METRICS_METADATA[metric_name].levels
            max_depth = len(levels)

            def is_leaf(depth):
                return depth == max_depth

            def create_metric(node, labels):
                return [Metric.create_metric_with_metadata(
                    name=metric_name,
                    value=node,
                    labels=labels
                )]

            def recursive_create_metric(node, parent_labels=None, depth=0):
                if is_leaf(depth):
                    return create_metric(node, parent_labels)
                else:
                    try:
                        metrics = []
                        for parent_label_value, child in node.items():
                            new_parent_labels = {} if parent_labels is None else dict(parent_labels)
                            new_parent_labels[levels[depth]] = str(parent_label_value)
                            metrics.extend(
                                recursive_create_metric(child, new_parent_labels, depth + 1))
                        return metrics
                    except AttributeError as e:
                        raise Exception(
                            'found int or float when expecting hierarchy for metric for %s'
                            '- check levels definition in METRIC_METADATA!'
                            % metric_name
                        ) from e

            all_metrics.extend(recursive_create_metric(metric_node, {}))
        else:
            metric_value = metric_node
            all_metrics.append(Metric.create_metric_with_metadata(
                name=metric_name,
                value=metric_value,
            ))
    return all_metrics


def add_metric(metric_name, metric_metadata):
    setattr(MetricName, metric_name.upper(), metric_name)
    METRICS_METADATA.update({metric_name: metric_metadata})
