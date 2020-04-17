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
import logging
import statistics
from collections import defaultdict
from typing import List, Dict, BinaryIO

import os
from dataclasses import dataclass
from operator import truediv, add

from wca import perf_const as pc, platforms
from wca.metrics import Measurements, BaseDerivedMetricsGenerator, \
    _operation_on_leveled_metric, \
    MetricName, _operation_on_leveled_dicts, METRICS_METADATA
from wca.perf import _perf_event_open, _create_file_from_fd, \
    _parse_event_groups, LIBC
from wca.platforms import decode_listformat, encode_listformat

log = logging.getLogger(__name__)


@dataclass
class Event:
    """Similar to man perf list for pmu types unc_imc_0/event=0x,config1=0x/'"""
    name: str
    event: int = 0
    umask: int = 0
    config: int = 0
    config1: int = 0

    def __post_init__(self):
        """ head /sys/devices/uncore_imc_0/format/*
        ==> /sys/devices/uncore_imc_0/format/event <==
        config:0-7
        ==> /sys/devices/uncore_imc_0/format/umask <==
        config:8-15
        """
        if self.config:
            assert self.event == 0 and self.umask == 0, \
                'Event and umask should not be configured if config value is given'
        if self.event:
            self.config = self.event | (self.umask << 8)


def _create_event_attributes(pmu_type, disabled, event: Event):
    """Creates perf_event_attr structure for perf_event_open syscall"""
    attr = pc.PerfEventAttr()
    attr.size = pc.PERF_ATTR_SIZE_VER5
    attr.type = pmu_type
    attr.config = event.config
    attr.config1 = event.config1
    attr.sample_type = pc.PERF_SAMPLE_IDENTIFIER
    attr.read_format = (pc.PERF_FORMAT_GROUP |
                        pc.PERF_FORMAT_TOTAL_TIME_ENABLED |
                        pc.PERF_FORMAT_TOTAL_TIME_RUNNING |
                        pc.PERF_FORMAT_ID)

    attr.flags = pc.AttrFlags.inherit

    if disabled:
        attr.flags |= pc.AttrFlags.disabled

    return attr


def _get_measurements_for_scaling_info(scaling_factors):
    measurements = {}
    if scaling_factors:
        measurements[MetricName.PLATFORM_SCALING_UNCORE_FACTOR] = \
            statistics.mean(scaling_factors)
    else:
        measurements[MetricName.PLATFORM_SCALING_UNCORE_FACTOR_AVG] = 1.0
    return measurements


@dataclass
class UncorePerfCounters:
    """Perf facade on perf_event_open system call to deal with uncore counters"""
    cpus: List[int]
    pmu_events: Dict[int, List[Event]]  # pmu_type to event_config
    platform: platforms.Platform  # required for cpu to socket/numa_node mapping

    def __post_init__(self):
        # all perf file descriptors, except leaders
        self._event_files: List[BinaryIO] = []
        # perf data file descriptors (only leaders) per pmu and per cpu
        self._group_event_leader_files_per_pmu: Dict[int, Dict[int, BinaryIO]] = defaultdict(
            lambda: defaultdict())
        # DO the magic and enabled everything + start counting
        self._open()

    def get_measurements(self) -> Measurements:
        """Reads, scales and aggregates event measurements"""
        measurements_per_cpu: Dict[int, Measurements] = {}
        # reversed topology (flatten the topology)
        cpu_to_socket = {}
        for socket_id, socket in self.platform.topology.items():
            for _, cpu_ids in socket.items():
                for cpu_id in cpu_ids:
                    cpu_to_socket[cpu_id] = socket_id

        measurements_per_socket = defaultdict(lambda: defaultdict(dict))
        for pmu, events in self.pmu_events.items():
            event_names = [e.name for e in events]
            for cpu, event_leader_file in self._group_event_leader_files_per_pmu[pmu].items():
                measurements_per_cpu[cpu] = _parse_event_groups(
                    event_leader_file, event_names, _get_measurements_for_scaling_info)
                for metric in measurements_per_cpu[cpu]:
                    socket = cpu_to_socket[cpu]
                    measurements_per_socket[metric][socket][pmu] = \
                        measurements_per_cpu[cpu][metric]

        return dict(measurements_per_socket)

    def cleanup(self):
        """Closes all opened file descriptors"""
        for pmu, _group_event_leader_files in self._group_event_leader_files_per_pmu.values():
            for file in _group_event_leader_files.values():
                file.close()
        for file in self._event_files:
            file.close()

    def _open_for_cpu(self, pmu: int, cpu: int, event: Event):
        """Opens file descriptor for event selected via event_name, for selected cpu"""
        group_file = self._group_event_leader_files_per_pmu.get(pmu, {}).get(cpu)
        is_group_leader = group_file is None

        # man perf_event_open cite regarding the disabled variable:
        #   When creating an event group, typically the group leader is
        #     initialized with disabled set to 1 and any child events are
        #     initialized with disabled set to 0.  Despite disabled being 0,
        #     the child events will not start until the group leader is
        #     enabled.
        # Disabled when creating new leader.
        # Enabled for children
        flags = 0  # pc.PERF_FLAG_FD_CLOEXEC
        pid = -1
        if is_group_leader:
            disabled = True
            group_fd = -1
        else:
            disabled = False
            group_fd = group_file.fileno()

        self.attr = _create_event_attributes(
            pmu,
            disabled,
            event,
        )
        pfd = _perf_event_open(perf_event_attr=ctypes.byref(self.attr),
                               pid=pid,
                               cpu=cpu,
                               group_fd=group_fd,
                               flags=flags)
        perf_event_file = _create_file_from_fd(pfd)

        if is_group_leader:
            self._group_event_leader_files_per_pmu[pmu][cpu] = perf_event_file
        else:
            self._event_files.append(perf_event_file)

    def _open(self):
        """Opens file descriptors for selected events, for all online cpus"""
        for pmu, events in self.pmu_events.items():
            for event in events:
                for cpu in self.cpus:
                    self._open_for_cpu(pmu, cpu, event)
            self._reset_and_enable_group_event_leaders(pmu)

    def _reset_and_enable_group_event_leaders(self, pmu):
        for group_event_leader_file in self._group_event_leader_files_per_pmu[pmu].values():
            if LIBC.ioctl(group_event_leader_file.fileno(), pc.PERF_EVENT_IOC_RESET, 0) < 0:
                raise OSError("Cannot reset perf counts")
            if LIBC.ioctl(group_event_leader_file.fileno(), pc.PERF_EVENT_IOC_ENABLE, 0) < 0:
                raise OSError("Cannot enable perf counts")


UNCORE_IMC_EVENTS = {
    # https://github.com/opcm/pcm/blob/816dec444453c0e1253029e7faecfe1e024a071c/cpucounters.cpp#L3549
    MetricName.PLATFORM_PMM_BANDWIDTH_READS:
        Event(name=MetricName.PLATFORM_PMM_BANDWIDTH_READS, event=0xe3),
    MetricName.PLATFORM_PMM_BANDWIDTH_WRITES:
        Event(name=MetricName.PLATFORM_PMM_BANDWIDTH_WRITES, event=0xe7),
    MetricName.PLATFORM_CAS_COUNT_READS:
        Event(name=MetricName.PLATFORM_CAS_COUNT_READS, event=0x04, umask=0x3),  # * 64 to get bytes
    MetricName.PLATFORM_CAS_COUNT_WRITES:
        Event(name=MetricName.PLATFORM_CAS_COUNT_WRITES,
              event=0x04, umask=0xc),  # * 64 to get bytes
    MetricName.PLATFORM_RPQ_OCCUPANCY:
        Event(name=MetricName.PLATFORM_RPQ_OCCUPANCY, event=0x80),
    MetricName.PLATFORM_RPQ_INSERTS:
        Event(name=MetricName.PLATFORM_RPQ_INSERTS, event=0x10),
    MetricName.PLATFORM_IMC_CLOCKTICKS:
        Event(name=MetricName.PLATFORM_IMC_CLOCKTICKS, event=0x0)
}

UNCORE_UPI_EVENTS = {
    MetricName.PLATFORM_UPI_RXL_FLITS:
        Event(name=MetricName.PLATFORM_UPI_RXL_FLITS, event=0x3, umask=0xf),
    MetricName.PLATFORM_UPI_TXL_FLITS:
        Event(name=MetricName.PLATFORM_UPI_TXL_FLITS, event=0x2, umask=0xf),
}


class PMUNotAvailable(Exception):
    pass


class UncoreEventConfigError(Exception):
    pass


def _discover_pmu_uncore_config(events, dir_prefix):
    """Detect available uncore PMUS and their types and CPUS, that events should be assigned to.
    Can raise PMUNotAvailable exception if the is not cpusmask set for this PMU.
    Returns configuration that can be used to program perf_event subsystem to collect given
    events.
    """
    base_path = '/sys/devices'
    pmus = [d for d in os.listdir(base_path) if d.startswith(dir_prefix)]
    pmu_types = [int(open(os.path.join(base_path, imc, 'type')).read().rstrip()) for imc in pmus]
    pmu_cpus_set = set(
        [open(os.path.join(base_path, imc, 'cpumask')).read().rstrip() for imc in pmus])
    if len(pmu_cpus_set) == 0:
        raise PMUNotAvailable('there is no PMU types available for "%s" device (in /sys/devices)'
                              % dir_prefix[:-1])
    assert len(pmu_cpus_set) == 1
    pmu_cpus_csv = list(pmu_cpus_set)[0]
    cpus = list(decode_listformat(pmu_cpus_csv))
    pmu_events = {pmu: events for pmu in pmu_types}
    log.debug('discovered uncore pmus types for "%s": %r with cpus=%r',
              dir_prefix[:-1], pmu_types, encode_listformat(cpus))
    return cpus, pmu_events


class UncoreDerivedMetricsGenerator(BaseDerivedMetricsGenerator):

    def _derive(self, measurements, delta, available, time_delta):
        # each CAS operation is 64bytes long
        SCALE = 64

        def rate(value):
            return value * SCALE / time_delta

        max_depth = len(METRICS_METADATA[MetricName.PLATFORM_PMM_BANDWIDTH_WRITES].levels)
        # both CAS and PMM should have the same level and it derived metrics
        # levels are cpu and pmu
        assert max_depth == len(METRICS_METADATA[MetricName.PLATFORM_CAS_COUNT_READS].levels)
        assert max_depth == len(
            METRICS_METADATA[MetricName.PLATFORM_PMM_TOTAL_BYTES_PER_SECOND].levels)

        # DRAM
        if available(MetricName.PLATFORM_CAS_COUNT_READS, MetricName.PLATFORM_CAS_COUNT_WRITES):
            dram_read, dram_write = delta(MetricName.PLATFORM_CAS_COUNT_READS,
                                          MetricName.PLATFORM_CAS_COUNT_WRITES)

            # DRAM R/W bps
            _operation_on_leveled_metric(dram_read, rate, max_depth)
            measurements[MetricName.PLATFORM_DRAM_READS_BYTES_PER_SECOND] = dram_read

            _operation_on_leveled_metric(dram_write, rate, max_depth)
            measurements[MetricName.PLATFORM_DRAM_WRITES_BYTES_PER_SECOND] = dram_write

            # DRAM total bps
            total_dram_bps = _operation_on_leveled_dicts(
                dram_read,
                dram_write,
                add, max_depth)
            measurements[MetricName.PLATFORM_DRAM_TOTAL_BYTES_PER_SECOND] = total_dram_bps
        else:
            log.debug('dram metrics not available!')

        # PMM
        if available(MetricName.PLATFORM_PMM_BANDWIDTH_WRITES,
                     MetricName.PLATFORM_PMM_BANDWIDTH_READS):
            pmm_read, pmm_write = delta(MetricName.PLATFORM_PMM_BANDWIDTH_READS,
                                        MetricName.PLATFORM_PMM_BANDWIDTH_WRITES)

            # PMM R/W bps
            _operation_on_leveled_metric(pmm_read, rate, max_depth)
            measurements[MetricName.PLATFORM_PMM_READS_BYTES_PER_SECOND] = pmm_read

            _operation_on_leveled_metric(pmm_write, rate, max_depth)
            measurements[MetricName.PLATFORM_PMM_WRITES_BYTES_PER_SECOND] = pmm_write

            # PMM total bps
            total_pmm_bps = _operation_on_leveled_dicts(
                pmm_read,
                pmm_write,
                add,
                max_depth)
            measurements[MetricName.PLATFORM_PMM_TOTAL_BYTES_PER_SECOND] = total_pmm_bps

            # DRAM HIT = dram_bps / total_dram_and_pmm_bps
            total_dram_and_pmm_bps = _operation_on_leveled_dicts(
                total_pmm_bps,
                total_dram_bps,
                add,
                max_depth)
            dram_hit = _operation_on_leveled_dicts(
                measurements[MetricName.PLATFORM_DRAM_TOTAL_BYTES_PER_SECOND],
                total_dram_and_pmm_bps,
                truediv, max_depth)
            measurements[MetricName.PLATFORM_DRAM_HIT_RATIO] = dram_hit
        else:
            log.debug('pmm metrics not available!')

        # UPI bandwidth
        if available(MetricName.PLATFORM_UPI_RXL_FLITS, MetricName.PLATFORM_UPI_TXL_FLITS):
            """
            based on "2.6.3 Intel® UPI LL Performance Monitoring Events" chapter from
            "Intel® Xeon® Processor Scalable Memory Family Uncore Performance Monitoring"
            document June/2017

            Extract from above document:
            * Of particular interest, total link utilization may be calculated by capturing and
            subtracting transmitted/received idle flits from Intel® UPI clocks.
            Many of these events can be further broken down by message class, including link
            utilization.
            * A quick illustration on calculating UPI Bandwidth. Here are two basic examples. The
            first is a typical DRd (data read) packet and the other is an IntLogical (logically
            addressed interrupt) packet. The point is , in both these cases, the number of flits
            sent are the same even in the rare case a full cacheline’s worth of data isn’t
            transmitted. When measuring the amount of bandwidth consumed by transmission of
            the data (i.e. NOT including the header), it should be .ALL_DATA / 9 * 64B. .
            """
            rxl_flits, txl_flits = delta(MetricName.PLATFORM_UPI_RXL_FLITS,
                                         MetricName.PLATFORM_UPI_TXL_FLITS)

            def rate_for_upi(value):
                return value / time_delta / 9 * 64

            max_depth = len(METRICS_METADATA[MetricName.PLATFORM_UPI_TXL_FLITS].levels)
            bandwidth = _operation_on_leveled_dicts(rxl_flits, txl_flits, lambda x, y: x + y,
                                                    max_depth)
            _operation_on_leveled_metric(bandwidth, rate_for_upi, max_depth)
            measurements[MetricName.PLATFORM_UPI_BANDWIDTH_BYTES_PER_SECOND] = bandwidth
        else:
            log.debug('upi metrics not available!')

        # IMC RPQ
        if available(MetricName.PLATFORM_RPQ_INSERTS,
                     MetricName.PLATFORM_RPQ_OCCUPANCY,
                     MetricName.PLATFORM_IMC_CLOCKTICKS):
            measurements[MetricName.PLATFORM_RPQ_READ_LATENCY_SECONDS] = {}
            for socket in measurements[MetricName.PLATFORM_RPQ_OCCUPANCY]:
                number_of_channels = len(measurements[MetricName.PLATFORM_RPQ_OCCUPANCY][socket])
                occupancy = 0
                inserts = 0
                clockticks = 0
                for channel in measurements[MetricName.PLATFORM_RPQ_OCCUPANCY][socket]:
                    occupancy += \
                        measurements[MetricName.PLATFORM_RPQ_OCCUPANCY][socket][channel]
                    inserts += \
                        measurements[MetricName.PLATFORM_RPQ_INSERTS][socket][channel]
                    clockticks += \
                        measurements[MetricName.PLATFORM_IMC_CLOCKTICKS][socket][channel]
                rpq_read_latency = (occupancy / inserts) / \
                                   (clockticks / number_of_channels)
                measurements[MetricName.PLATFORM_RPQ_READ_LATENCY_SECONDS].update(
                    {socket: rpq_read_latency})
        else:
            log.debug('imc metrics not available!')
