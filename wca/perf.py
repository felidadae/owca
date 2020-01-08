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
from typing import List, Dict, BinaryIO, Iterable

import os
import struct
from operator import truediv, sub

from wca import logger
from wca import perf_const as pc
from wca.metrics import Measurements, MetricName, MissingMeasurementException, \
    BaseDerivedMetricsGenerator, METRICS_METADATA, _operation_on_leveled_dicts, \
    _operation_on_leveled_metric
from wca.platforms import Platform, CPUCodeName

LIBC = ctypes.CDLL('libc.so.6', use_errno=True)

log = logging.getLogger(__name__)


def _get_event_config(cpu: CPUCodeName, event_name: str) -> int:
    event, umask, cmask = pc.PREDEFINED_RAW_EVENTS[event_name][cpu]
    return event | (umask << 8) | (cmask << 24)


def _get_online_cpus() -> List[int]:
    """Return list with numbers of online cores for current machine"""
    online_cpus = []
    with open('/sys/devices/system/cpu/online', 'r') as fobj:
        online_cpus = _parse_online_cpus_string(fobj.read())
    return online_cpus


def _parse_online_cpus_string(raw_string) -> List[int]:
    """
    Parses string returned by /sys/devices/system/cpu/online
    and returns a list of online cores
    """
    parsed_cpus_info = []
    for nr in raw_string.split(','):
        if '-' not in nr:
            parsed_cpus_info.append(int(nr))
        else:
            start, end = nr.split('-')
            parsed_cpus_info.extend(range(int(start), int(end) + 1))
    return parsed_cpus_info


def _parse_event_groups(file, event_names, include_scaling_info) -> Measurements:
    """Reads event values from the event file (For single cpu)
    Returns all declared metrics in "event_names".
    """
    measurements = {}
    scaling_factors = []
    size = struct.unpack('q', file.read(8))[0]
    assert size == len(event_names)
    time_enabled = struct.unpack('q', file.read(8))[0]
    time_running = struct.unpack('q', file.read(8))[0]
    for current_event in range(0, size):
        raw_value = struct.unpack('q', file.read(8))[0]
        measurement, scaling_factor = _scale_counter_value(
            raw_value,
            time_enabled,
            time_running
        )
        measurements[event_names[current_event]] = measurement

        # 0.0 means that process was not running at this CPU at all,
        # do not take into equation to calculate scaling factor avg/max
        if scaling_factor != 0.0:
            scaling_factors.append(scaling_factor)
        # id is unused, but we still need to read the whole struct
        struct.unpack('q', file.read(8))[0]

    # we add 2 non-standard metrics based on unpacked values,
    # we need to collect scaling factors here
    if include_scaling_info:
        if scaling_factors:
            print(scaling_factors)
            measurements[MetricName.TASK_SCALING_FACTOR_AVG] = statistics.mean(scaling_factors)
            measurements[MetricName.TASK_SCALING_FACTOR_MAX] = max(scaling_factors)
        else:
            measurements[MetricName.TASK_SCALING_FACTOR_AVG] = 1.0
            measurements[MetricName.TASK_SCALING_FACTOR_MAX] = 1.0

    return measurements


def _perf_event_open(perf_event_attr, pid, cpu, group_fd, flags) -> int:
    """Wrapper on perf_event_open function using libc syscall"""
    return LIBC.syscall(pc.PERF_EVENT_OPEN_NR, perf_event_attr, pid, cpu,
                        group_fd, flags)


def _get_cgroup_fd(cgroup) -> int:
    """
    Return FD for provided cgroup
    """
    path = os.path.join('/sys/fs/cgroup/perf_event', cgroup)
    # cgroup is a directory, so we can't use fdopen on the file
    # descriptor we receive from os.open
    try:
        return os.open(path, os.O_RDONLY)
    except FileNotFoundError:
        raise MissingMeasurementException(
            'cannot initialize perf for cgroup %r - directory not found' % cgroup)


def _scale_counter_value(raw_value, time_enabled, time_running) -> (float, float):
    """
    Scales raw counter measurement with time_enabled and time_running values,
    according to https://perf.wiki.kernel.org/index.php/Tutorial#multiplexing_and_scaling_events

    Return (scaled metric value, scaling factor)

    0 - means that no measurement was performed at all
    """
    # After the start of measurement, first few readings may contain only 0's
    if time_running == 0:
        return 0.0, 0.0
    if time_enabled == 0:
        log.warning("Event time enabled equals 0")
        return 0.0, 0.0
    if time_running != time_enabled:
        scaling_factor = float(time_enabled) / float(time_running)
        return round(float(raw_value) * scaling_factor), scaling_factor
    else:
        return float(raw_value), 1.0


def _parse_raw_event_name(event_name: str) -> (int, int):
    """Parses raw event name with the format:

        name__rEEUU
        name__rEEUUCC
        name__rEEUUCC1111111111

        where UU == umask (Unit Mask) (byte)
          and EE == event number (Event select field), (byte)
          and optionally CMASK (Counter Mask) (byte)
          and optionally config1 (5bytes, 40bits)
        EE,UU and CC are parsed as hex.

    Intel Software Developer Manual Volume 2, Chapter 18.2.1

    :returns value encoded for perf_event attr.config structure
    """
    if '__r' not in event_name:
        raise Exception('raw events name is expected to contain "__r" characters.')
    try:
        _, bits = event_name.split('__r')
        config1 = 0
        if len(bits) == 16:
            cmask = int(bits[4:6], 16)
            config1 = int(bits[6:16], 16)
        elif len(bits) == 6:
            cmask = int(bits[4:6], 16)
        elif len(bits) == 4:
            cmask = 0
        else:
            raise Exception('improper raw event_name specification (length should be 4 or 6 or 16)')
        event = int(bits[0:2], 16)
        umask = int(bits[2:4], 16)
        return event | (umask << 8) | (cmask << 24), config1
    except ValueError as e:
        raise Exception('Cannot parse raw event definition: %r: error %s' % (bits, e)) from e


def _create_event_attributes(event_name, disabled, cpu_code_name: CPUCodeName):
    """Creates perf_event_attr structure for perf_event_open syscall"""
    attr = pc.PerfEventAttr()
    attr.size = pc.PERF_ATTR_SIZE_VER5

    if event_name in pc.PREDEFINED_RAW_EVENTS:
        attr.type = pc.PerfType.PERF_TYPE_RAW
        attr.config = _get_event_config(cpu_code_name, event_name)
    elif event_name in pc.HardwareEventNameMap:
        attr.type = pc.PerfType.PERF_TYPE_HARDWARE
        attr.config = pc.HardwareEventNameMap[event_name]
    elif '__r' in event_name:
        attr.type = pc.PerfType.PERF_TYPE_RAW
        attr.config, attr.config1 = _parse_raw_event_name(event_name)
    else:
        raise Exception('Unknown event name %r' % event_name)

    log.log(logger.TRACE,
            'perf: event_attribute: name=%r type=%r config=%r',
            event_name, attr.type, attr.config)

    attr.sample_type = pc.PERF_SAMPLE_IDENTIFIER
    attr.read_format = (pc.PERF_FORMAT_GROUP |
                        pc.PERF_FORMAT_TOTAL_TIME_ENABLED |
                        pc.PERF_FORMAT_TOTAL_TIME_RUNNING |
                        pc.PERF_FORMAT_ID)

    attr.flags = pc.AttrFlags.exclude_guest | pc.AttrFlags.inherit

    if disabled:
        attr.flags |= pc.AttrFlags.disabled

    return attr


def _create_file_from_fd(pfd):
    """Validates file description and creates a file-like object"""
    # -1 is returned on error: http://man7.org/linux/man-pages/man2/open.2.html#RETURN_VALUE
    if pfd == -1:
        INVALID_ARG_ERRNO = 22
        errno = ctypes.get_errno()
        if errno == INVALID_ARG_ERRNO:
            raise UnableToOpenPerfEvents('Invalid perf event file descriptor: {}, {}. '
                                         'For cgroup based perf counters it may indicate there is '
                                         'no enough hardware counters for measure all metrics!'
                                         'If traceback shows problem in perf_uncore '
                                         'it could be problem with PERF_FORMAT_GROUP in'
                                         'perf_event_attr structure for perf_event_open syscall.'
                                         'Older kernel cannot handle with extended format group.'
                                         'Kernel cannot be 3.10.0-862.el7.x86_64 or lower.'
                                         ''.format(errno, os.strerror(errno)))
        else:
            raise UnableToOpenPerfEvents('Invalid perf event file descriptor: {}, {}.'
                                         .format(errno, os.strerror(errno)))
    return os.fdopen(pfd, 'rb')


class PerfCounters:
    """Perf facade on perf_event_open system call"""

    def __init__(
            self,
            cgroup_path: str,
            event_names: Iterable[MetricName],
            platform: Platform,
            aggregate_for_all_cpus_with_sum: bool = True
    ):
        # Provide cgroup_path with leading '/'
        assert cgroup_path.startswith('/')
        # cgroup path without leading '/'
        relative_cgroup_path = cgroup_path[1:]
        self._cgroup_fd: int = _get_cgroup_fd(relative_cgroup_path)

        # all perf file descriptors, except leaders
        self._event_files: List[BinaryIO] = []
        # perf data file descriptors (only leaders) per cpu
        self._group_event_leader_files: Dict[int, BinaryIO] = {}

        self._platform = platform

        self._aggregate_for_all_cpus_with_sum = aggregate_for_all_cpus_with_sum

        # keep event names for output information
        self._event_names: List[MetricName] = event_names

        # DO the magic and enabled everything + start counting
        self._open()

    def cleanup(self):
        """Closes all opened file descriptors"""
        for file in self._group_event_leader_files.values():
            file.close()
        for file in self._event_files:
            file.close()
        # _cgroup_fd is an int, thus we need to close it with os.close
        os.close(self._cgroup_fd)

    def _open_for_cpu(self, cpu, event_name):
        """Opens file descriptor for event selected via event_name, for selected cpu"""
        group_file = self._group_event_leader_files.get(cpu)
        is_group_leader = group_file is None

        # man perf_event_open cite regarding the disabled variable:
        #   When creating an event group, typically the group leader is
        #     initialized with disabled set to 1 and any child events are
        #     initialized with disabled set to 0.  Despite disabled being 0,
        #     the child events will not start until the group leader is
        #     enabled.
        # Disabled when creating new leader.
        # Enabled for children

        # man perf_event_open cite regarding group_fd variable:
        #       The cgroup is identified by passing a file descriptor opened
        #       on its directory in the cgroupfs filesystem.  For instance, if
        #       the cgroup to monitor is called test, then a file descriptor
        #       opened on /dev/cgroup/test (assuming cgroupfs is mounted on
        #       /dev/cgroup) must be passed as the pid parameter.  cgroup
        #       monitoring is available only for system-wide events and may
        #       therefore require extra permissions.
        if is_group_leader:
            disabled = True
            pid = self._cgroup_fd
            flags = pc.PERF_FLAG_PID_CGROUP | pc.PERF_FLAG_FD_CLOEXEC
            group_fd = -1
        else:
            disabled = False
            pid = -1
            flags = pc.PERF_FLAG_FD_CLOEXEC
            group_fd = group_file.fileno()

        attr = _create_event_attributes(event_name, disabled=disabled,
                                        cpu_code_name=self._platform.cpu_codename)

        if attr is None:
            # Unsupported event path.
            return None

        self.attr = attr

        pfd = _perf_event_open(perf_event_attr=ctypes.byref(self.attr),
                               pid=pid,
                               cpu=cpu,
                               group_fd=group_fd,
                               flags=flags)
        perf_event_file = _create_file_from_fd(pfd)

        if is_group_leader:
            self._group_event_leader_files[cpu] = perf_event_file
        else:
            self._event_files.append(perf_event_file)

    def _open(self):
        """Opens file descriptors for selected events, for all online cpus"""
        for event_name in self._event_names:
            for cpu in _get_online_cpus():
                self._open_for_cpu(cpu, event_name)
        self._reset_and_enable_group_event_leaders()

    def _reset_and_enable_group_event_leaders(self):
        for group_event_leader_file in self._group_event_leader_files.values():
            if LIBC.ioctl(group_event_leader_file.fileno(), pc.PERF_EVENT_IOC_RESET, 0) < 0:
                raise OSError("Cannot reset perf counts")
            if LIBC.ioctl(group_event_leader_file.fileno(), pc.PERF_EVENT_IOC_ENABLE, 0) < 0:
                raise OSError("Cannot enable perf counts")

    def get_measurements(self) -> Measurements:
        """Reads, scales and aggregates event measurements."""

        # Measurements:
        # levels: ['metric_name', 'cpu']
        per_metric_per_cpu = {}
        # levels: ['metric_name'] - Aggregated values (sum for all cpus)
        per_metric = defaultdict(float)

        max_values_for_all_cpus = []
        avg_values_for_all_cpus = []

        for cpu, event_leader_file in self._group_event_leader_files.items():
            per_cpu = _parse_event_groups(
                event_leader_file, self._event_names, include_scaling_info=True)
            for metric_name, metric_value in per_cpu.items():
                # not aggregated  version
                per_metric_per_cpu.setdefault(metric_name, {})
                per_metric_per_cpu[metric_name][cpu] = metric_value
                # sum (aggregate operation)
                per_metric[metric_name] += metric_value
            max_values_for_all_cpus.append(per_cpu[MetricName.TASK_SCALING_FACTOR_MAX])
            avg_values_for_all_cpus.append(per_cpu[MetricName.TASK_SCALING_FACTOR_AVG])

        if self._aggregate_for_all_cpus_with_sum \
                and avg_values_for_all_cpus and max_values_for_all_cpus:
            # average for all metric of averages for cpus
            per_metric[MetricName.TASK_SCALING_FACTOR_AVG] = statistics.mean(
                avg_values_for_all_cpus)
            # max of max
            per_metric[MetricName.TASK_SCALING_FACTOR_MAX] = max(max_values_for_all_cpus)
            return dict(per_metric)
        else:
            # no aggreated values
            return per_metric_per_cpu


class UnableToOpenPerfEvents(Exception):
    pass


class PerfCgroupDerivedMetricsGenerator(BaseDerivedMetricsGenerator):
    def _derive(self, measurements, delta, available, time_delta):

        def rate(value):
            return float(value) / time_delta

        if available(MetricName.TASK_INSTRUCTIONS, MetricName.TASK_CYCLES):
            inst_delta, cycles_delta = delta(MetricName.TASK_INSTRUCTIONS, MetricName.TASK_CYCLES)
            max_depth = len(METRICS_METADATA[MetricName.TASK_INSTRUCTIONS].levels)

            if max_depth == 0:
                if cycles_delta > 0:
                    measurements[MetricName.TASK_IPC] = float(inst_delta) / cycles_delta
                if time_delta > 0:
                    measurements[MetricName.TASK_IPS] = rate(inst_delta)
            else:
                # leveled calculations
                ipc = _operation_on_leveled_dicts(inst_delta, cycles_delta, truediv, max_depth)
                measurements[MetricName.TASK_IPC] = ipc
                if time_delta > 0:
                    _operation_on_leveled_metric(inst_delta, rate, max_depth)
                    measurements[MetricName.TASK_IPS] = inst_delta

        if available(MetricName.TASK_INSTRUCTIONS, MetricName.TASK_CACHE_MISSES):
            inst_delta, cache_misses_delta = delta(MetricName.TASK_INSTRUCTIONS,
                                                   MetricName.TASK_CACHE_MISSES)

            max_depth = len(METRICS_METADATA[MetricName.TASK_CACHE_MISSES].levels)

            def times1000(x):
                return x * 1000

            if max_depth == 0:
                mpki = times1000(float(cache_misses_delta) / inst_delta)
                measurements[MetricName.TASK_CACHE_MISSES_PER_KILO_INSTRUCTIONS] = mpki
            else:
                # leveled calculations
                divided = _operation_on_leveled_dicts(
                    cache_misses_delta, inst_delta, truediv, max_depth)

                _operation_on_leveled_metric(divided, times1000, max_depth)
                measurements[MetricName.TASK_CACHE_MISSES_PER_KILO_INSTRUCTIONS] = divided

        if available(MetricName.TASK_CACHE_REFERENCES, MetricName.TASK_CACHE_MISSES):
            cache_ref_delta, cache_misses_delta = delta(MetricName.TASK_CACHE_REFERENCES,
                                                        MetricName.TASK_CACHE_MISSES)
            max_depth = len(METRICS_METADATA[MetricName.TASK_CACHE_MISSES].levels)
            if max_depth == 0:
                cache_hits = cache_ref_delta - cache_misses_delta
                cache_hit_ratio = float(cache_hits) / cache_ref_delta
                measurements[MetricName.TASK_CACHE_HIT_RATIO] = cache_hit_ratio
            else:
                # leveled calculations
                cache_hits_count = _operation_on_leveled_dicts(
                    cache_ref_delta, cache_misses_delta, sub, max_depth)
                cache_hit_ratio = _operation_on_leveled_dicts(cache_hits_count, cache_ref_delta,
                                                              truediv, max_depth)
                measurements[MetricName.TASK_CACHE_HIT_RATIO] = cache_hit_ratio


def check_perf_event_count_limit(
        event_names: List[str], platform_cpus: int, platform_cores: int) -> bool:
    """Check there is enough perf event programmable counters to schedule all of them
    at the same time (implementation we used in perf.py)

    Note: Excludes fixed counters from check.

    8 with no HT and 4 for HT excluding fixed counters and check if there is enough
    counters to measure generic events.
    Validated for BDX, SKX and CLX (cpuid -1 -l 0xa)

    return False and logs errors if there is a problem.
    else return True
    """
    number_of_events = len([e for e in event_names if e not in
                            [MetricName.TASK_INSTRUCTIONS, MetricName.TASK_CYCLES]])
    ht_enabled = (platform_cpus != platform_cores)
    max_number_of_events = 4 if ht_enabled else 8
    log.debug('HT state: %s, assuming number of available HW counters: %i (required=%i)',
              ht_enabled, max_number_of_events, number_of_events)
    if number_of_events > max_number_of_events:
        log.error('Not enough hardware counters to measure %i programmable events '
                  '(available is %s!)', number_of_events, max_number_of_events)
        return False
    # Everything is ok
    return True


def filter_out_event_names_for_cpu(
        event_names: List[str], cpu_codename: CPUCodeName) -> List[MetricName]:
    """Filter out events that cannot be collected on given cpu."""

    filtered_event_names = []

    for event_name in event_names:
        if event_name in pc.HardwareEventNameMap:
            # Universal metrics that works on all cpus.
            filtered_event_names.append(event_name)
        elif event_name in pc.PREDEFINED_RAW_EVENTS:
            if cpu_codename in pc.PREDEFINED_RAW_EVENTS[event_name]:
                filtered_event_names.append(event_name)
            else:
                log.warning('Event %r not supported for %s!', event_name, cpu_codename.value)
                continue
        elif '__r' in event_name:
            # Pass all raw events.
            filtered_event_names.append(event_name)
        else:
            raise Exception('Unknown event name %r!' % event_name)

    return filtered_event_names
