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


import ctypes

from wca.metrics import MetricName
from wca.platforms import CPUCodeName

# x86 specific, from arch/x86/include/generated/uapi/asm/unistd_64.h
PERF_EVENT_OPEN_NR = 298

# as defined in include/uapi/linux/perf_event.h
PERF_ATTR_SIZE_VER5 = 0x70

PERF_EVENT_IOC_ENABLE = 0x2400
PERF_EVENT_IOC_DISABLE = 0x2401
PERF_EVENT_IOC_REFRESH = 0x2402
PERF_EVENT_IOC_RESET = 0x2403

PERF_FLAG_FD_NO_GROUP = 1 << 0
PERF_FLAG_FD_OUTPUT = 1 << 1
PERF_FLAG_PID_CGROUP = 1 << 2
PERF_FLAG_FD_CLOEXEC = 1 << 3

PERF_FORMAT_GROUP = 1 << 3

PERF_FORMAT_TOTAL_TIME_ENABLED = 1 << 0
PERF_FORMAT_TOTAL_TIME_RUNNING = 1 << 1
PERF_FORMAT_ID = 1 << 2

PERF_SAMPLE_IDENTIFIER = 1 << 16


class ReadFormat(ctypes.Structure):
    _fields_ = [('value', ctypes.c_ulong),
                ('time_enabled', ctypes.c_ulong),
                ('time_running', ctypes.c_ulong),
                ('id', ctypes.c_ulong)]


class PerfEventAttr(ctypes.Structure):
    _fields_ = [('type', ctypes.c_uint),
                ('size', ctypes.c_uint),
                ('config', ctypes.c_ulong),
                ('sample_period', ctypes.c_ulong),
                ('sample_type', ctypes.c_ulong),
                ('read_format', ctypes.c_ulong),
                ('flags', ctypes.c_ulong),
                ('wakeup_events', ctypes.c_uint),  # union {wakeup_events, wakeup_watermark}
                ('bp_type', ctypes.c_uint),  # bp_type
                ('config1', ctypes.c_ulong),  # union {bp_addr, kprobe_func, kprobe_path, config1}
                ('config2', ctypes.c_ulong),  # union {bp_len, kprobe_addr, probe_offset, config2}
                ('branch_sample_type', ctypes.c_ulong),
                ('sample_regs_user', ctypes.c_uint),  # sample_regs_user
                ('sample_stack_user', ctypes.c_int),  # sample_stack_user
                ('IGNORE9', ctypes.c_ulong),  # TODO: check me for 3.10 vs 5.15
                ('IGNORE10', ctypes.c_uint),
                ('IGNORE11', ctypes.c_uint),
                ]


class EventType:
    EVTYPE_GENERIC = 0
    EVTYPE_PEBS = 1  # Basic PEBS event
    EVTYPE_PEBS_LL = 2  # PEBS event with load latency info
    EVTYPE_IBS = 3


class EventTypeConfig:
    PERF_COUNT_HW_CPU_CYCLES = 0
    PERF_COUNT_HW_INSTRUCTIONS = 1
    PERF_COUNT_HW_CACHE_REFERENCES = 2
    PERF_COUNT_HW_CACHE_MISSES = 3
    PERF_COUNT_HW_BRANCH_INSTRUCTIONS = 4
    PERF_COUNT_HW_BRANCH_MISSES = 5
    PERF_COUNT_HW_BUS_CYCLES = 6
    PERF_COUNT_HW_STALLED_CYCLES_FRONTEND = 7
    PERF_COUNT_HW_STALLED_CYCLES_BACKEND = 8
    PERF_COUNT_HW_REF_CPU_CYCLES = 9


HardwareEventNameMap = {
    MetricName.TASK_CYCLES: EventTypeConfig.PERF_COUNT_HW_CPU_CYCLES,
    MetricName.TASK_INSTRUCTIONS: EventTypeConfig.PERF_COUNT_HW_INSTRUCTIONS,
    MetricName.TASK_CACHE_MISSES: EventTypeConfig.PERF_COUNT_HW_CACHE_MISSES,
    MetricName.TASK_CACHE_REFERENCES: EventTypeConfig.PERF_COUNT_HW_CACHE_REFERENCES,
}

# According SDM-vol-3b 19-48
PREDEFINED_RAW_EVENTS = {
    # CPUCodeName: tuple(event_id, event_mask, counter_mask)
    MetricName.TASK_STALLED_MEM_LOADS: {
        CPUCodeName.SKYLAKE: (0xA3, 0x14, 20),
        CPUCodeName.BROADWELL: (0xA3, 0x06, 6)
    },
    MetricName.TASK_OFFCORE_REQUESTS_L3_MISS_DEMAND_DATA_RD: {
        CPUCodeName.SKYLAKE: (0x60, 0x10, 0),
    },
    MetricName.TASK_OFFCORE_REQUESTS_OUTSTANDING_L3_MISS_DEMAND_DATA_RD: {
        CPUCodeName.SKYLAKE: (0xB0, 0x10, 0),
    },
    MetricName.TASK_MEM_LOAD_RETIRED_LOCAL_PMM: {
        CPUCodeName.SKYLAKE: (0xd1, 0x80, 0),
        CPUCodeName.CASCADE_LAKE: (0xd1, 0x80, 0),
    },
    MetricName.TASK_MEM_INST_RETIRED_LOADS: {
        CPUCodeName.SKYLAKE: (0xd0, 0x81, 0),
        CPUCodeName.CASCADE_LAKE: (0xd0, 0x81, 0),
    },
    MetricName.TASK_MEM_INST_RETIRED_STORES: {
        CPUCodeName.SKYLAKE: (0xd0, 0x82, 0),
        CPUCodeName.CASCADE_LAKE: (0xd0, 0x82, 0),
    },
    MetricName.TASK_DTLB_LOAD_MISSES: {
        CPUCodeName.SKYLAKE: (0x08, 0x0e, 0),
        CPUCodeName.CASCADE_LAKE: (0x08, 0x0e, 0),
    },
}


class PerfType:
    """
    Enum taken from kernels tools/include/uapi/linux/perf_event.h:
    perf_type_id
    """
    PERF_TYPE_HARDWARE = 0
    PERF_TYPE_SOFTWARE = 1
    PERF_TYPE_TRACEPOINT = 2
    PERF_TYPE_HW_CACHE = 3
    PERF_TYPE_RAW = 4
    PERF_TYPE_BREAKPOINT = 5


class AttrFlags:
    disabled = 1 << 0
    inherit = 1 << 1
    pinned = 1 << 2
    exclusive = 1 << 3
    exclude_user = 1 << 4
    exclude_kernel = 1 << 5
    exclude_hv = 1 << 6
    exclude_idle = 1 << 7
    mmap = 1 << 8
    comm = 1 << 9
    freq = 1 << 10
    inherit_stat = 1 << 11
    enable_on_exec = 1 << 12
    task = 1 << 13
    watermark = 1 << 14
    precise_ip_lo = 1 << 15
    precise_ip_hi = 1 << 16
    mmap_data = 1 << 17
    sample_id_all = 1 << 18
    exclude_host = 1 << 19
    exclude_guest = 1 << 20
    exclude_callchain_kernel = 1 << 21
    exclude_callchain_user = 1 << 22
    mmap2 = 1 << 23
    comm_exec = 1 << 24
    use_clockid = 1 << 25
    context_switch = 1 << 26
    write_backward = 1 << 27
    namespaces = 1 << 28
