
================================
Available metrics
================================

**This software is pre-production and should not be deployed to production servers.**

.. contents:: Table of Contents


Metrics sources
===============

Check out `metrics sources documentation <metrics_sources.rst>`_ for more details how metrics 
are measured and about labels/levels.

For searchable list of metrics `metrics as csv file <metrics.csv>`_ .

Legend	
======

- **Name**: is the name of metric that will be exported to Prometheus by using Prometheus 
  exposition format but also the name of the key in ``Measurements`` dict-like 
  type used in ``Detector`` and ``Allocator`` plugins,	
- **Help**: information what metric represents and some 
  details how metric was collected and known problems or limitations,	
- **Unit**: unit of the metric (usually seconds or bytes),	
- **Type**: only possible types are `gauge` and `counter` as described 
  in `Prometheus metric types <https://prometheus.io/docs/concepts/metric_types/>`_.	
- **Source**: short description about mechanics that was used to collect metric,	
  for more detailed information check out `Metric sources documenation <metric_sources.rst>`_.	
- **Enabled** - column describes if metric is enabled by default and 
  how to enable (option in ``MeasurementRunner`` responsible for configuring it. 
  Please refer to `metrics sources documentation <metrics_sources.rst>`_ for more details.)	
- **Levels/Labels** - some metrics have additional dimensions (more granularity than just ``Task`` 
  or ``Platform``) e.g. ``task_mem_numa_pages`` can be collected per NUMA node - in this case	
  this metrics have attached additional label like ``numa_node=0`` which creates new series in	
  Prometheus nomenclature and represents more granular information about source of metric. 
  When used in python API in ``Detector`` or ``Allocator`` classes this will be 
  represented by nested dicts where each level have keys corresponding to "level" (order is important).	
  For example doubly nested perf uncore metrics like: ``platform_cas_count_reads`` 
  have two levels: `socket` and `pmu_type` (which physically represents memory controller) 
  will be encoded as::	

    platform_cas_count_reads{socket=0, pmu_type=17} 12345	

  and represented in Python API as::	

    measurements = {'platform_cas_count_reads': {0: {17: 12345}}}	
Task's metrics
==============

.. csv-table::
	:header: "Name", "Help", "Enabled", "Unit", "Type", "Source", "Levels/Labels"
	:widths: 5, 5, 5, 5, 5, 5, 5 

	"task_instructions", "Hardware PMU counter for number of instructions (PERF_COUNT_HW_INSTRUCTIONS). Fixed counter. Predefined perf PERF_TYPE_HARDWARE. Please man perf_event_open for more details.", "no (event_names)", "numeric",  "counter", "perf subsystem with cgroups", ""
	"task_cycles", "Hardware PMU counter for number of cycles (PERF_COUNT_HW_CPU_CYCLES). Fixed counter. Predefined perf PERF_TYPE_HARDWARE. Please man perf_event_open for more details.", "no (event_names)", "numeric",  "counter", "perf subsystem with cgroups", ""
	"task_cache_misses", "Hardware PMU counter for cache-misses (PERF_COUNT_HW_CACHE_MISSES).Predefined perf PERF_TYPE_HARDWARE. Please man perf_event_open for more details.", "no (event_names)", "numeric",  "counter", "perf subsystem with cgroups", ""
	"task_cache_references", "Hardware PMU counter for number of cache references (PERF_COUNT_HW_CACHE_REFERENCES).Predefined perf PERF_TYPE_HARDWARE. Please man perf_event_open for more details.", "no (event_names)", "numeric",  "counter", "perf subsystem with cgroups", ""
	"task_stalled_mem_loads", "Execution stalls while memory subsystem has an outstanding load.CYCLE_ACTIVITY.STALLS_MEM_ANYIntel SDM October 2019 19-24 Vol. 3B, Table 19-3", "no (event_names)", "numeric",  "counter", "perf subsystem with cgroups", ""
	"task_offcore_requests_l3_miss_demand_data_rd", "Increment each cycle of the number of offcore outstanding demand data read requests from SQ that missed L3.Counts number of Offcore outstanding Demand Data Read requests that miss L3 cache in the superQ every cycle.OFFCORE_REQUESTS_OUTSTANDING.L3_MISS_DEMAND_DATA_RDIntel SDM October 2019 19-24 Vol. 3B, Table 19-3", "no (event_names)", "numeric",  "counter", "perf subsystem with cgroups", ""
	"task_offcore_requests_demand_data_rd", "Counts the Demand Data Read requests sent to uncore. OFFCORE_REQUESTS.DEMAND_DATA_RD Intel SDM October 2019 19-24 Vol. 3B, Table 19-3", "no (event_names)", "numeric",  "counter", "perf subsystem with cgroups", ""
	"task_offcore_requests_demand_rfo", "Demand RFO read requests sent to uncore, including regular RFOs, locks, ItoM. OFFCORE_REQUESTS.DEMAND_RFO Intel SDM October 2019 19-24 Vol. 3B, Table 19-3", "no (event_names)", "numeric",  "counter", "perf subsystem with cgroups", ""
	"task_offcore_requests_outstanding_l3_miss_demand_data_rd", "Demand Data Read requests who miss L3 cache. OFFCORE_REQUESTS.L3_MISS_DEMAND_DATA_RD.Intel SDM October 2019 19-24 Vol. 3B, Table 19-3", "no (event_names)", "numeric",  "counter", "perf subsystem with cgroups", ""
	"task_mem_load_retired_local_pmm", "Retired load instructions with local Intel® Optane™ DC persistent memory as the data source and the datarequest missed L3 (AppDirect or Memory Mode), and DRAM cache (Memory Mode). MEM_LOAD_RETIRED.LOCAL_PMM (Mnemonic) For CLX, Intel SDM October 2019 19-24 Vol. 3B, Table 19-4", "no (event_names)", "numeric",  "counter", "perf subsystem with cgroups", ""
	"task_mem_load_retired_local_dram", "Retired load instructions which data sources missed L3 but serviced from local DRAM.MEM_LOAD_L3_MISS_RETIRED.LOCAL_DRAM Intel SDM October 2019 Chapters 19-24 Vol. 3B Table 19-3", "no (event_names)", "numeric",  "counter", "perf subsystem with cgroups", ""
	"task_mem_load_retired_remote_dram", "Retired load instructions which data sources missed L3 but serviced from remote dram. MEM_LOAD_L3_MISS_RETIRED.REMOTE_DRAMIntel SDM October 2019 Chapters 19-24 Vol. 3B Table 19-3", "no (event_names)", "numeric",  "counter", "perf subsystem with cgroups", ""
	"task_mem_inst_retired_loads", "MEM_INST_RETIRED.ALL_LOADS All retired load instructions. Intel SDM October 2019 Chapters 19-24 Vol. 3B Table 19-3", "no (event_names)", "numeric",  "counter", "perf subsystem with cgroups", ""
	"task_mem_inst_retired_stores", "MEM_INST_RETIRED.ALL_STORES All retired store instructions. Intel SDM October 2019 Chapters 19-24 Vol. 3B Table 19-3", "no (event_names)", "numeric",  "counter", "perf subsystem with cgroups", ""
	"task_dtlb_load_misses", "DTLB_LOAD_MISSES.WALK_COMPLETEDCounts demand data loads that caused a completedpage walk of any page size (4K/2M/4M/1G). This impliesit missed in all TLB levels. The page walk can end withor without a faultIntel SDM October 2019 Chapters 19-24 Vol. 3B Table 19-3", "no (event_names)", "numeric",  "counter", "perf subsystem with cgroups", ""
	"task_scaling_factor_avg", "Perf subsystem metric scaling factor, averaged value of all events and cpus (value 1.0 is the best, meaning that there is no scaling at all for any metric).", "auto (depending on event_names)", "numeric",  "gauge", "perf subsystem with cgroups", ""
	"task_scaling_factor_max", "Perf subsystem metric scaling factor, maximum value of all events and cpus (value 1.0 is the best, meaning that there is no scaling at all for any metric).", "auto (depending on event_names)", "numeric",  "gauge", "perf subsystem with cgroups", ""
	"task_ips", "Instructions per second.", "no (enable_derived_metrics)", "numeric",  "gauge", "derived from perf subsystem with cgroups", ""
	"task_ipc", "Instructions per cycle.", "no (enable_derived_metrics)", "numeric",  "gauge", "derived from perf subsystem with cgroups", ""
	"task_cache_hit_ratio", "Cache hit ratio, based on cache-misses and cache-references.", "no (enable_derived_metrics)", "numeric",  "gauge", "derived from perf subsystem with cgroups", ""
	"task_cache_misses_per_kilo_instructions", "Cache misses per kilo instructions.", "no (enable_derived_metrics)", "numeric",  "gauge", "derived from perf subsystem with cgroups", ""
	"task_llc_occupancy_bytes", "LLC occupancy from resctrl filesystem based on Intel RDT technology.", "auto (rdt_enabled)", "bytes",  "gauge", "resctrl filesystem", ""
	"task_mem_bandwidth_bytes", "Total memory bandwidth using Memory Bandwidth Monitoring.", "auto (rdt_enabled)", "bytes",  "counter", "resctrl filesystem", ""
	"task_mem_bandwidth_local_bytes", "Total local memory bandwidth using Memory Bandwidth Monitoring.", "auto (rdt_enabled)", "bytes",  "counter", "resctrl filesystem", ""
	"task_mem_bandwidth_remote_bytes", "Total remote memory bandwidth using Memory Bandwidth Monitoring.", "auto (rdt_enabled)", "bytes",  "counter", "resctrl filesystem", ""
	"task_cpu_usage_seconds", "Time taken by task based on cpuacct.usage (total kernel and user space).", "yes", "seconds",  "counter", "cgroup filesystem", ""
	"task_mem_usage_bytes", "Memory usage_in_bytes per tasks returned from cgroup memory subsystem.", "yes", "bytes",  "gauge", "cgroup filesystem", ""
	"task_mem_max_usage_bytes", "Memory max_usage_in_bytes per tasks returned from cgroup memory subsystem.", "yes", "bytes",  "gauge", "cgroup filesystem", ""
	"task_mem_limit_bytes", "Memory limit_in_bytes per tasks returned from cgroup memory subsystem.", "yes", "bytes",  "gauge", "cgroup filesystem", ""
	"task_mem_soft_limit_bytes", "Memory soft_limit_in_bytes per tasks returned from cgroup memory subsystem.", "yes", "bytes",  "gauge", "cgroup filesystem", ""
	"task_mem_numa_pages", "Number of used pages per NUMA node(key: hierarchical_total is used if available or justtotal with warning), from cgroup memory controller from memory.numa_stat file.", "yes", "numeric",  "gauge", "cgroup filesystem", "numa_node"
	"task_mem_page_faults", "Number of page faults for task.", "yes", "numeric",  "counter", "cgroup filesystem", ""
	"task_wss_referenced_bytes", "Task referenced bytes during last measurements cycle based on /proc/smaps Referenced field, with /proc/PIDs/clear_refs set to 1 accordinn wss_reset_interval.Warning: this is intrusive collection, because can influence kernel page reclaim policy and add latency.Refer to https://github.com/brendangregg/wss#wsspl-referenced-page-flag for more details.", "yes", "bytes",  "gauge", "/procs/PIDS/smaps", ""
	"task_requested_cpus", "Tasks resources cpus initial requests.", "yes", "numeric",  "gauge", "orchestrator", ""
	"task_requested_mem_bytes", "Tasks resources memory initial requests.", "yes", "bytes",  "gauge", "orchestrator", ""
	"task_last_seen", "Time the task was last seen.", "yes", "timestamp",  "counter", "internal", ""
	"task_up", "Always returns 1 for running task.", "yes", "numeric",  "counter", "internal", ""
	"task_subcontainers", "Returns number of Kubernetes Pod Containers or 0 for others.", "yes", "numeric",  "gauge", "internal", ""



Platform's metrics
==================

.. csv-table::
	:header: "Name", "Help", "Enabled", "Unit", "Type", "Source", "Levels/Labels"
	:widths: 5, 5, 5, 5, 5, 5, 5 

	"platform_topology_cores", "Platform information about number of physical cores", "yes", "numeric",  "gauge", "internal", ""
	"platform_topology_cpus", "Platform information about number of logical cpus", "yes", "numeric",  "gauge", "internal", ""
	"platform_topology_sockets", "Platform information about number of sockets", "yes", "numeric",  "gauge", "internal", ""
	"platform_dimm_count", "Number of RAM DIMM (all types memory modules)", "no (gather_hw_mm_topology)", "numeric",  "gauge", "dmidecode binary output", "dimm_type"
	"platform_dimm_total_size_bytes", "Total RAM size (all types memory modules)", "no (gather_hw_mm_topology)", "bytes",  "gauge", "dmidecode binary output", "dimm_type"
	"platform_mem_mode_size_bytes", "Size of RAM (Persistent memory) configured in memory mode.", "no (gather_hw_mm_topology)", "numeric",  "gauge", "ipmctl binary output", ""
	"platform_dimm_speed_bytes_per_second", "Total platform DRAM speed", "no (gather_hw_mm_topology)", "bytes_per_second",  "gauge", "dmidecode binary output", ""
	"platform_cpu_usage", "Logical CPU usage in 1/USER_HZ (usually 10ms).Calculated using values based on /proc/stat.", "yes", "numeric",  "counter", "/proc filesystem", "cpu"
	"platform_mem_usage_bytes", "Total memory used by platform in bytes based on /proc/meminfo and uses heuristic based on linux free tool (total - free - buffers - cache).", "yes", "bytes",  "gauge", "/proc filesystem", ""
	"platform_mem_numa_free_bytes", "NUMA memory free per NUMA node based on /sys/devices/system/node/* (MemFree:)", "yes", "bytes",  "gauge", "/sys filesystem", "numa_node"
	"platform_mem_numa_used_bytes", "NUMA memory free per NUMA used based on /sys/devices/system/node/* (MemUsed:)", "yes", "bytes",  "gauge", "/sys filesystem", "numa_node"
	"platform_vmstat_numa_pages_migrated", "Virtual Memory stats based on /proc/vmstat for number of migrates pages (autonuma)", "yes", "numeric",  "counter", "/proc filesystem", ""
	"platform_vmstat_pgmigrate_success", "Virtual Memory stats based on /proc/vmstat for number of migrates pages (succeed)", "yes", "numeric",  "counter", "/proc filesystem", ""
	"platform_vmstat_pgmigrate_fail", "Virtual Memory stats based on /proc/vmstat for number of migrates pages (failed)", "yes", "numeric",  "counter", "/proc filesystem", ""
	"platform_vmstat_numa_hint_faults", "Virtual Memory stats based on /proc/vmstat for pgfaults for migration hints", "yes", "numeric",  "counter", "/proc filesystem", ""
	"platform_vmstat_numa_hint_faults_local", "Virtual Memory stats based on /proc/vmstat: pgfaults for migration hints (local)", "yes", "numeric",  "counter", "/proc filesystem", ""
	"platform_vmstat_pgfaults", "Virtual Memory stats based on /proc/vmstat:number of page faults", "yes", "numeric",  "counter", "/proc filesystem", ""
	"platform_pmm_bandwidth_reads", "Persistent memory module number of reads.", "no (uncore_event_names)", "numeric",  "counter", "perf subsystem with dynamic PMUs (uncore)", "socket, pmu_type"
	"platform_pmm_bandwidth_writes", "Persistent memory module number of writes.", "no (uncore_event_names)", "numeric",  "counter", "perf subsystem with dynamic PMUs (uncore)", "socket, pmu_type"
	"platform_cas_count_reads", "Column adress select number of reads", "no (uncore_event_names)", "numeric",  "counter", "perf subsystem with dynamic PMUs (uncore)", "socket, pmu_type"
	"platform_cas_count_writes", "Column adress select number of writes", "no (uncore_event_names)", "numeric",  "counter", "perf subsystem with dynamic PMUs (uncore)", "socket, pmu_type"
	"platform_upi_rxl_flits", "TBD", "no (uncore_event_names)", "numeric",  "counter", "perf subsystem with dynamic PMUs (uncore)", "socket, pmu_type"
	"platform_upi_txl_flits", "TBD", "no (uncore_event_names)", "numeric",  "counter", "perf subsystem with dynamic PMUs (uncore)", "socket, pmu_type"
	"platform_rpq_occupancy", "Pending queue occupancy", "no (uncore_event_names)", "numeric",  "gauge", "perf subsystem with dynamic PMUs (uncore)", "socket, pmu_type"
	"platform_rpq_inserts", "Pending queue allocations", "no (uncore_event_names)", "numeric",  "gauge", "perf subsystem with dynamic PMUs (uncore)", "socket, pmu_type"
	"platform_imc_clockticks", "IMC clockticks", "no (uncore_event_names)", "numeric",  "counter", "perf subsystem with dynamic PMUs (uncore)", "socket, pmu_type"
	"platform_rpq_read_latency_seconds", "Read latency", "no (uncore_event_names: platform_imc_clockticks, platform_rpq_occupancy, platform_rpq_inserts and set enable_derived_metrics)", "seconds",  "gauge", "derived from perf uncore", "socket"
	"platform_pmm_reads_bytes_per_second", "TBD", "no (uncore_event_names: platform_pmm_bandwidth_reads and set enable_derived_metrics)", "numeric",  "gauge", "derived from perf uncore", "socket, pmu_type"
	"platform_pmm_writes_bytes_per_second", "TBD", "no (uncore_event_names: platform_pmm_bandwidth_writes and set enable_derived_metrics)", "numeric",  "gauge", "derived from perf uncore", "socket, pmu_type"
	"platform_pmm_total_bytes_per_second", "TBD", "no (uncore_event_names: platform_pmm_bandwidth_reads, platform_pmm_bandwidth_writes and set enable_derived_metrics)", "numeric",  "gauge", "derived from perf uncore", "socket, pmu_type"
	"platform_dram_reads_bytes_per_second", "TBD", "no (uncore_event_names: platform_cas_count_reads and set enable_derived_metrics)", "numeric",  "gauge", "derived from perf uncore", "socket, pmu_type"
	"platform_dram_writes_bytes_per_second", "TBD", "no (uncore_event_names: platform_cas_count_writes and set enable_derived_metrics)", "numeric",  "gauge", "derived from perf uncore", "socket, pmu_type"
	"platform_dram_total_bytes_per_second", "TBD", "no (uncore_event_names: platform_cas_count_reads, platform_cas_count_writes and set enable_derived_metrics)", "numeric",  "gauge", "derived from perf uncore", "socket, pmu_type"
	"platform_dram_hit_ratio", "TBD", "no (uncore_event_names: platform_cas_count_reads, platform_cas_count_writes and set enable_derived_metrics)", "numeric",  "gauge", "derived from perf uncore", "socket, pmu_type"
	"platform_upi_bandwidth_bytes_per_second", "TBD", "no (uncore_event_names: platform_upi_txl_flits, platform_upi_rxl_flits and set enable_derived_metrics)", "numeric",  "counter", "derived from perf uncore", "socket, pmu_type"
	"platform_scaling_uncore_factor", "Perf uncore subsystem metric scaling factor(value 1.0 is the best, meaning that there is no scaling at all for any uncore metric)", "auto, (depending on uncore_event_names)", "numeric",  "gauge", "perf subsystem with dynamic PMUs (uncore)", "socket, pmu_type"
	"platform_zoneinfo", "Dynamic metric with many keys based on fields from /proc/zoneinfo grouped by numa_node and zone (only Normal zone)", "yes (zoneinfo option)", "numeric",  "gauge", "/proc filesystem", "numa_node, zone, key"
	"platform_last_seen", "Timestamp the information about platform was last collected", "yes", "timestamp",  "counter", "internal", ""
	"platform_capacity_per_nvdimm_bytes", "Platform capacity per NVDIMM", "yes", "bytes",  "gauge", "internal", ""
	"platform_avg_power_per_nvdimm_watts", "Average power used by NVDIMM on the platform", "yes", "watts",  "gauge", "internal", ""
	"platform_nvdimm_read_bandwidth_bytes_per_second", "Theoretical reads bandwidth per platform", "yes", "bytes_per_second",  "gauge", "internal", "socket"
	"platform_nvdimm_write_bandwidth_bytes_per_second", "Theoretical writes bandwidth per platform", "yes", "bytes_per_second",  "gauge", "internal", "socket"



Internal metrics
================

.. csv-table::
	:header: "Name", "Help", "Enabled", "Unit", "Type", "Source", "Levels/Labels"
	:widths: 5, 5, 5, 5, 5, 5, 5 

	"wca_up", "Health check for WCA returning timestamps of last iteration", "yes", "timestamp",  "counter", "internal", ""
	"wca_information", "Special metric to cover some meta information like wca_version or cpu_model or platform topology (to be used instead of include_optional_labels)", "yes", "numeric",  "gauge", "internal", ""
	"wca_tasks", "Number of discovered tasks", "yes", "numeric",  "gauge", "internal", ""
	"wca_mem_usage_bytes", "Memory usage by WCA itself (getrusage for self and children).", "yes", "bytes",  "gauge", "internal", ""
	"wca_duration_seconds", "Internal WCA function call duration metric for profiling", "yes", "numeric",  "gauge", "internal", ""
	"wca_duration_seconds_avg", "Internal WCA function call duration metric for profiling (average from last restart)", "yes", "numeric",  "gauge", "internal", ""

