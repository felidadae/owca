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


from unittest import mock
from unittest.mock import Mock, patch, mock_open

import os
import pytest
from io import BytesIO

from wca import metrics
from wca import perf
from wca import perf_const as pc
from wca.metrics import MetricName
from wca.perf import _parse_raw_event_name, _get_event_config, PerfCgroupDerivedMetricsGenerator, \
    filter_out_event_names_for_cpu, check_perf_event_count_limit
from wca.platforms import CPUCodeName, Platform


@pytest.mark.parametrize("raw_value,time_enabled,time_running,expected_value,expected_factor", [
    (300, 200, 100, 600, 2.0),
    (0, 0, 0, 0, 0),
    (200, 0, 100, 0, 0),
    (200, 100, 0, 0, 0),
    (300, 200, 200, 300, 1.0),
])
def test_scale_counter_value(raw_value, time_running, time_enabled, expected_value,
                             expected_factor):
    assert perf._scale_counter_value(raw_value, time_enabled, time_running) == (
        expected_value, expected_factor)


@patch('os.open', return_value=10)
def test_get_cgroup_fd(os_open):
    assert perf._get_cgroup_fd('a_cgroup') == 10
    os_open.assert_called_once_with('/sys/fs/cgroup/perf_event/a_cgroup',
                                    os.O_RDONLY)


@patch('os.fdopen', return_value=object)
def test_create_file_from_valid_fd(_):
    file = perf._create_file_from_fd(1)
    assert file is not None


def test_create_file_from_invalid_fd():
    with pytest.raises(perf.UnableToOpenPerfEvents):
        perf._create_file_from_fd(-1)


@pytest.mark.parametrize("disabled_flag,expected", [
    (True, pc.AttrFlags.exclude_guest | pc.AttrFlags.disabled | pc.AttrFlags.inherit),
    (False, pc.AttrFlags.exclude_guest | pc.AttrFlags.inherit)
])
def test_create_event_attributes_disabled_flag(disabled_flag, expected):
    assert perf._create_event_attributes(
        metrics.MetricName.TASK_CYCLES,
        disabled_flag,
        cpu_code_name=CPUCodeName.UNKNOWN).flags == expected


@pytest.mark.parametrize("raw_string,expected", [
    ('0-31', list(range(32))),
    ('0', [0]),
    ('0-3,6,10-12', [0, 1, 2, 3, 6, 10, 11, 12])
])
def test_parse_online_cpus_string(raw_string, expected):
    assert perf._parse_online_cpus_string(raw_string) == expected


@pytest.mark.parametrize("file,event_names,expected", [
    (BytesIO(b"\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
             b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x4a\x16\x00\x00\x00\x00\x00\x00"),
     [metrics.MetricName.TASK_CYCLES],
     {metrics.MetricName.TASK_CYCLES: 0,
      metrics.MetricName.TASK_SCALING_FACTOR_AVG: 1.0,
      metrics.MetricName.TASK_SCALING_FACTOR_MAX: 1.0}
     ),
    # case with no scaling
    (BytesIO(b"\x03\x00\x00\x00\x00\x00\x00\x00\x26\xe7\xea\x29\x01\x00\x00\x00\x26\xe7\xea\x29"
             b"\x01\x00\x00\x00\xa6\x6e\x1a\x9d\x08\x00\x00\x00\x1d\x17\x00\x00\x00\x00\x00\x00"
             b"\xc8\xfd\x08\x88\x04\x00\x00\x00\x1e\x17\x00\x00\x00\x00\x00\x00\x18\xc8\x43\x00"
             b"\x00\x00\x00\x00\x1f\x17\x00\x00\x00\x00\x00\x00"),
     [metrics.MetricName.TASK_INSTRUCTIONS, metrics.MetricName.TASK_CYCLES,
      metrics.MetricName.TASK_CACHE_MISSES],
     {metrics.MetricName.TASK_INSTRUCTIONS: 36995493542,
      metrics.MetricName.TASK_CYCLES: 19462159816,
      metrics.MetricName.TASK_CACHE_MISSES: 4442136,
      metrics.MetricName.TASK_SCALING_FACTOR_AVG: 1.0,
      metrics.MetricName.TASK_SCALING_FACTOR_MAX: 1.0}
     ),
    # case with 50% scaling factor
    (BytesIO(b"\x03\x00\x00\x00\x00\x00\x00\x00\xb2\xef\xff\x29\x01\x00\x00\x00\x07\x13\x08\x95"
             b"\x00\x00\x00\x00\x86\xb2\xf1\x4b\x04\x00\x00\x00\x5d\x19\x00\x00\x00\x00\x00\x00"
             b"\xbe\x74\x5f\x43\x02\x00\x00\x00\x5e\x19\x00\x00\x00\x00\x00\x00\xf0\xa5\x15\x00"
             b"\x00\x00\x00\x00\x5f\x19\x00\x00\x00\x00\x00\x00"),
     [metrics.MetricName.TASK_INSTRUCTIONS, metrics.MetricName.TASK_CYCLES,
      metrics.MetricName.TASK_CACHE_MISSES],
     {metrics.MetricName.TASK_INSTRUCTIONS: 36900158682,
      metrics.MetricName.TASK_CYCLES: 19436397211,
      metrics.MetricName.TASK_CACHE_MISSES: 2836869,
      # TODO: assert for 2.0 with some margin
      metrics.MetricName.TASK_SCALING_FACTOR_AVG: 1.9995750600302817,
      metrics.MetricName.TASK_SCALING_FACTOR_MAX: 1.9995750600302817}
     )
])
def test_parse_event_groups(file, event_names, expected):
    assert perf._parse_event_groups(file, event_names, include_scaling_info=True) == expected


@patch('wca.perf._get_cgroup_fd')
@patch('wca.perf.PerfCounters._open')
def test_perf_counters_init(_open_mock, _get_cgroup_fd_mock):
    platform_mock = Mock(Spec=Platform, cpu_model='intel xeon', cpu_codename=CPUCodeName.SKYLAKE)
    prf = perf.PerfCounters('/mycgroup', [metrics.MetricName.TASK_CYCLES], platform_mock)
    assert prf._group_event_leader_files == {}
    _get_cgroup_fd_mock.assert_called_once()
    _open_mock.assert_called_once()


@patch('builtins.open')
@patch('wca.perf._parse_online_cpus_string', return_value=[0])
def test_get_online_cpus(_parse_online_cpu_string_mock, open_mock):
    assert perf._get_online_cpus() == [0]
    open_mock.assert_called_with('/sys/devices/system/cpu/online', 'r')


@patch('wca.perf._parse_event_groups', return_value={
    metrics.MetricName.TASK_CYCLES: 2,
    metrics.MetricName.TASK_INSTRUCTIONS: 4,
    metrics.MetricName.TASK_SCALING_FACTOR_MAX: 3,
    metrics.MetricName.TASK_SCALING_FACTOR_AVG: 2})
@patch('wca.perf._get_cgroup_fd')
@patch('wca.perf.PerfCounters._open')
def test_read_metrics_non_aggregated(*args):
    platform_mock = Mock(Spec=Platform, cpu_model='intel xeon', cpu_codename=CPUCodeName.SKYLAKE)
    prf = perf.PerfCounters('/mycgroup', [metrics.MetricName.TASK_CYCLES],
                            platform_mock, aggregate_for_all_cpus_with_sum=False)
    prf._group_event_leader_files[0] = {0: mock_open()}
    assert prf.get_measurements() == {metrics.MetricName.TASK_CYCLES: {0: 2},
                                      metrics.MetricName.TASK_INSTRUCTIONS: {0: 4},
                                      metrics.MetricName.TASK_SCALING_FACTOR_AVG: {0: 2},
                                      metrics.MetricName.TASK_SCALING_FACTOR_MAX: {0: 3}}


@patch('wca.perf._parse_event_groups', return_value={
    metrics.MetricName.TASK_CYCLES: 2,
    metrics.MetricName.TASK_INSTRUCTIONS: 4,
    metrics.MetricName.TASK_SCALING_FACTOR_MAX: 3,
    metrics.MetricName.TASK_SCALING_FACTOR_AVG: 2})
@patch('wca.perf._get_cgroup_fd')
@patch('wca.perf.PerfCounters._open')
def test_read_metrics_aggregated(*args):
    platform_mock = Mock(Spec=Platform, cpu_model='intel xeon', cpu_codename=CPUCodeName.SKYLAKE)
    prf = perf.PerfCounters('/mycgroup', [metrics.MetricName.TASK_CYCLES],
                            platform_mock, aggregate_for_all_cpus_with_sum=True)
    prf._group_event_leader_files[0] = {0: mock_open()}
    assert prf.get_measurements() == {metrics.MetricName.TASK_CYCLES: 2,
                                      metrics.MetricName.TASK_INSTRUCTIONS: 4,
                                      metrics.MetricName.TASK_SCALING_FACTOR_AVG: 2,
                                      metrics.MetricName.TASK_SCALING_FACTOR_MAX: 3}


@patch('wca.perf.LIBC.ioctl', return_value=1)
@patch('wca.perf._get_cgroup_fd')
@patch('wca.perf.PerfCounters._open')
def test_reset_and_enable_group_event_leaders(_open_mock, _get_cgroup_fd_mock, ioctl_mock):
    platform_mock = Mock(Spec=Platform, cpu_model='intel xeon', cpu_codename=CPUCodeName.SKYLAKE)
    prf = perf.PerfCounters('/mycgroup', [metrics.MetricName.TASK_CYCLES], platform_mock)
    # cpu0 group event leader mock
    prf._group_event_leader_files = {0: Mock()}
    prf._reset_and_enable_group_event_leaders()
    ioctl_mock.assert_has_calls([mock.ANY] * 2)


@patch('wca.perf.LIBC.ioctl', return_value=-1)
@patch('wca.perf._get_cgroup_fd')
@patch('wca.perf.PerfCounters._open')
def test_reset_and_enable_group_event_leaders_reset_fail(
        _open_mock, _get_cgroup_fd_mock, ioctl_mock
):
    platform_mock = Mock(Spec=Platform, cpu_model='intel xeon', cpu_codename=CPUCodeName.SKYLAKE)
    prf = perf.PerfCounters('/mycgroup', [metrics.MetricName.TASK_CYCLES], platform_mock)
    # cpu0 group event leader mock
    prf._group_event_leader_files = {0: Mock()}
    with pytest.raises(OSError, match="Cannot reset perf counts"):
        prf._reset_and_enable_group_event_leaders()


@patch('wca.perf.LIBC.ioctl', side_effect=[1, -1])
@patch('wca.perf._get_cgroup_fd')
@patch('wca.perf.PerfCounters._open')
def test_reset_and_enable_group_event_leaders_enable_fail(
        _open_mock, _get_cgroup_fd_mock, ioctl_mock
):
    platform_mock = Mock(Spec=Platform, cpu_model='intel xeon', cpu_codename=CPUCodeName.SKYLAKE)
    prf = perf.PerfCounters('/mycgroup', [metrics.MetricName.TASK_CYCLES], platform_mock)
    # cpu0 group event leader mock
    prf._group_event_leader_files = {0: Mock()}
    with pytest.raises(OSError, match="Cannot enable perf counts"):
        prf._reset_and_enable_group_event_leaders()


@patch('os.close')
@patch('wca.perf._get_cgroup_fd', return_value=10)
@patch('wca.perf.PerfCounters._open')
def test_cleanup(_open_mock, _get_cgroup_fd_mock, os_close_mock):
    platform_mock = Mock(Spec=Platform, cpu_model='intel xeon', cpu_codename=CPUCodeName.SKYLAKE)
    prf = perf.PerfCounters('/mycgroup', [metrics.MetricName.TASK_CYCLES], platform_mock)
    file_descriptor_mock = Mock()
    file_descriptor_mock.close = Mock()
    prf._group_event_leader_files = {'mock1': file_descriptor_mock, 'mock2': file_descriptor_mock}
    prf._event_files = [file_descriptor_mock] * 3
    prf.cleanup()
    os_close_mock.assert_called_once_with(10)
    file_descriptor_mock.close.assert_has_calls(
        [mock.call()] * (len(prf._event_files)
                         + len(prf._group_event_leader_files)))


@patch('wca.perf._get_cgroup_fd', return_value=10)
@patch('wca.perf.PerfCounters._open')
def test_open_for_cpu_wrong_arg(_open_mock, _get_cgroup_fd_mock):
    platform_mock = Mock(Spec=Platform, cpu_model='intel xeon', cpu_codename=CPUCodeName.SKYLAKE)
    prf = perf.PerfCounters('/mycgroup', [], platform_mock)
    # let's check non-existent type of measurement
    with pytest.raises(Exception, match='Unknown event name'):
        prf._open_for_cpu(0, 'invalid_event_name')


@patch('os.fdopen')
@patch('wca.perf._perf_event_open', return_value=5)
@patch('wca.perf._get_cgroup_fd', return_value=10)
@patch('wca.perf.PerfCounters._open')
def test_open_for_cpu(_open_mock, _get_cgroup_fd_mock,
                      _perf_event_open_mock, fdopen_mock):
    platform_mock = Mock(Spec=Platform, cpu_model='intel xeon', cpu_codename=CPUCodeName.SKYLAKE)
    prf = perf.PerfCounters('/mycgroup', [metrics.MetricName.TASK_CYCLES], platform_mock)
    prf._open_for_cpu(0, metrics.MetricName.TASK_CYCLES)
    assert prf._group_event_leader_files == {0: mock.ANY}
    assert prf._event_files == []
    # perf_event_open call for the event group leader
    _perf_event_open_mock.assert_called_once_with(
        perf_event_attr=mock.ANY,
        pid=10,
        cpu=0,
        group_fd=-1,
        flags=pc.PERF_FLAG_PID_CGROUP | pc.PERF_FLAG_FD_CLOEXEC
    )
    fdopen_mock.assert_called_once_with(5, 'rb')


@patch('os.fdopen', side_effect=[Mock(fileno=Mock(return_value=5)),
                                 Mock(fileno=Mock(return_value=6))])
@patch('wca.perf._perf_event_open', return_value=5)
@patch('wca.perf._get_cgroup_fd', return_value=10)
@patch('wca.perf.PerfCounters._open')
def test_open_for_cpu_with_existing_event_group_leader(_open_mock,
                                                       _get_cgroup_fd_mock,
                                                       _perf_event_open_mock, fdopen_mock):
    platform_mock = Mock(Spec=Platform, cpu_model='intel xeon', cpu_codename=CPUCodeName.SKYLAKE)
    prf = perf.PerfCounters('/mycgroup', [metrics.MetricName.TASK_CYCLES], platform_mock)
    # Create event group leader
    prf._open_for_cpu(0, metrics.MetricName.TASK_CYCLES)
    # Create non leading event
    prf._open_for_cpu(0, metrics.MetricName.TASK_INSTRUCTIONS)
    assert prf._group_event_leader_files[0].fileno() == 5
    assert prf._event_files[0].fileno() == 6
    # perf_event_open call for non leading event
    _perf_event_open_mock.assert_called_with(perf_event_attr=mock.ANY,
                                             pid=-1,
                                             cpu=0,
                                             group_fd=5,
                                             flags=pc.PERF_FLAG_FD_CLOEXEC)


@patch('wca.perf._get_cgroup_fd')
@patch('wca.perf.PerfCounters._open')
def test_get_measurements_zero_values_zero_cpus(_open_mock, _get_cgroup_fd_mock):
    platform_mock = Mock(Spec=Platform, cpu_codename=CPUCodeName.SKYLAKE)
    prf = perf.PerfCounters('/mycgroup', [], platform_mock)
    prf._group_event_leaders = {}
    assert prf.get_measurements() == {}


@patch('wca.perf._get_cgroup_fd')
@patch('wca.perf.PerfCounters._open')
def test_get_measurements_zero_values_one_cpu(_open_mock, _get_cgroup_fd_mock):
    platform_mock = Mock(Spec=Platform, cpu_codename=CPUCodeName.SKYLAKE)
    prf = perf.PerfCounters('/mycgroup', [], platform_mock)
    # File descriptor mock for single cpu
    prf._group_event_leaders = {0: Mock()}
    assert prf.get_measurements() == {}


@pytest.mark.parametrize('event_name, expected_attr_config', [
    ('some__r000000', 0),
    ('some__r000001', 0x01000000),
    ('some__r0000ff', 0xff000000),
    ('some__r0302', 0x00000203),
    ('some__r0302ff', 0xff000203),
    ('some__rc000', 0x000000c0),  # example of Instruction Retired

])
def test_parse_raw_event_name(event_name, expected_attr_config):
    got_attr_config, _ = _parse_raw_event_name(event_name)
    assert got_attr_config == expected_attr_config


@pytest.mark.parametrize('event_name, expected_match', [
    ('som', 'contain'),
    ('some__r00000100', 'length'),
    ('some__r0000xx', 'invalid literal'),
    ('some__rxx02', 'invalid literal'),

])
def test_parse_raw_event_name_invalid(event_name, expected_match):
    with pytest.raises(Exception, match=expected_match):
        _parse_raw_event_name(event_name)


@pytest.mark.parametrize('cpu, event_name, expected_config', [
    (CPUCodeName.SKYLAKE, MetricName.TASK_STALLED_MEM_LOADS, 0x140014A3),
    (CPUCodeName.BROADWELL, MetricName.TASK_STALLED_MEM_LOADS, 0x60006A3),
    (CPUCodeName.SKYLAKE, MetricName.TASK_OFFCORE_REQUESTS_L3_MISS_DEMAND_DATA_RD, 0x00001060),
    (CPUCodeName.SKYLAKE,
     MetricName.TASK_OFFCORE_REQUESTS_OUTSTANDING_L3_MISS_DEMAND_DATA_RD, 0x000010B0),
])
def test_get_event_config(cpu, event_name, expected_config):
    assert expected_config == _get_event_config(cpu, event_name)


def test_derived_metrics_flat():
    def gm_func():
        return {
            MetricName.TASK_INSTRUCTIONS: 1000,
            MetricName.TASK_CYCLES: 5,
            MetricName.TASK_CACHE_MISSES: 10000,
            MetricName.TASK_CACHE_REFERENCES: 50000,
        }

    derived_metrics_generator = PerfCgroupDerivedMetricsGenerator(
        get_measurements_func=gm_func)

    # First run, does not have enough information to generate those metrics.

    with patch('time.time', return_value=1):
        measurements = derived_metrics_generator.get_measurements()
    assert MetricName.TASK_IPC not in measurements
    assert MetricName.TASK_IPS not in measurements
    assert MetricName.TASK_CACHE_HIT_RATIO not in measurements
    assert MetricName.TASK_CACHE_MISSES_PER_KILO_INSTRUCTIONS not in measurements

    # 5 seconds later
    def gm_func_2():
        return {
            MetricName.TASK_INSTRUCTIONS: 11000,  # 10k more
            MetricName.TASK_CYCLES: 15,  # 10 more
            MetricName.TASK_CACHE_MISSES: 20000,  # 10k more
            MetricName.TASK_CACHE_REFERENCES: 100000,  # 50k more
        }

    derived_metrics_generator.get_measurements_func = gm_func_2
    with patch('time.time', return_value=6):
        measurements = derived_metrics_generator.get_measurements()
    assert MetricName.TASK_IPC in measurements
    assert MetricName.TASK_IPS in measurements
    assert MetricName.TASK_CACHE_HIT_RATIO in measurements
    assert MetricName.TASK_CACHE_MISSES_PER_KILO_INSTRUCTIONS in measurements

    assert measurements[MetricName.TASK_IPC] == 10000 / 10
    assert measurements[MetricName.TASK_IPS] == 10000 / 5

    # Assuming cache misses increase is 10k over all 50k cache references
    # Cache hit ratio should be 40k / 50k = 80%
    assert measurements[MetricName.TASK_CACHE_HIT_RATIO] == 0.8

    # 10000 / (10k/1000) = 10000 / 10
    assert measurements[MetricName.TASK_CACHE_MISSES_PER_KILO_INSTRUCTIONS] == 1000


@pytest.mark.parametrize('event_names, cpu_codename, expected', [
    (['task_cycles', 'task_instructions', 'task_cache_misses', 'task_cache_references'],
     CPUCodeName.SKYLAKE,
     ['task_cache_misses', 'task_cache_references', 'task_cycles', 'task_instructions']),
    (['__r1234', 'task_instructions', 'task_cycles', 'task_cache_references'],
     CPUCodeName.SKYLAKE,
     ['task_instructions', 'task_cache_references', 'task_cycles', '__r1234']),
    ([MetricName.TASK_OFFCORE_REQUESTS_OUTSTANDING_L3_MISS_DEMAND_DATA_RD, 'task_instructions',
      'task_cache_misses', 'task_cache_references'],
     CPUCodeName.SKYLAKE,
     ['task_cache_misses', 'task_cache_references',
      MetricName.TASK_OFFCORE_REQUESTS_OUTSTANDING_L3_MISS_DEMAND_DATA_RD, 'task_instructions']),
    ([MetricName.TASK_OFFCORE_REQUESTS_OUTSTANDING_L3_MISS_DEMAND_DATA_RD, 'task_instructions',
      'task_cache_misses', MetricName.TASK_OFFCORE_REQUESTS_OUTSTANDING_L3_MISS_DEMAND_DATA_RD],
     CPUCodeName.SKYLAKE,
     ['task_cache_misses', MetricName.TASK_OFFCORE_REQUESTS_OUTSTANDING_L3_MISS_DEMAND_DATA_RD,
      MetricName.TASK_OFFCORE_REQUESTS_OUTSTANDING_L3_MISS_DEMAND_DATA_RD, 'task_instructions']),
])
def test_parse_event_names(event_names, cpu_codename, expected):
    parsed_event_names = filter_out_event_names_for_cpu(event_names, cpu_codename)
    assert set(parsed_event_names) == set(expected)


@pytest.mark.parametrize('event_names, cpu_codename', [
    (
            ['task_cycles', 'task_instructions', 'task_cache_misses', 'false_metric'],
            CPUCodeName.SKYLAKE),
    (
            ['__r1234', 'task_instructions', 'false_metric', 'task_cache_references'],
            CPUCodeName.SKYLAKE),
    ([MetricName.TASK_OFFCORE_REQUESTS_OUTSTANDING_L3_MISS_DEMAND_DATA_RD, 'task_instructions',
      'false_metric', 'task_cache_references'], CPUCodeName.SKYLAKE),
    ([MetricName.TASK_OFFCORE_REQUESTS_OUTSTANDING_L3_MISS_DEMAND_DATA_RD, 'false_metric',
      'task_cache_misses', MetricName.TASK_OFFCORE_REQUESTS_OUTSTANDING_L3_MISS_DEMAND_DATA_RD],
     CPUCodeName.SKYLAKE)])
def test_exception_parse_event_names(event_names, cpu_codename):
    with pytest.raises(Exception):
        filter_out_event_names_for_cpu(event_names, cpu_codename)


@pytest.mark.parametrize('event_names, cpus, cores, expected', [
    # for HT enabled 5 is too much
    (['e1', 'e2', 'e3', 'e4', 'e5'], 8, 4, False),
    # for HT disabled 8 is ok
    (['e1', 'e2', 'e3', 'e4', 'e5', 'e6', 'e7', 'e8'], 16, 16, True),
    # for HT disabled 9 is too much
    (['e1', 'e2', 'e3', 'e4', 'e5', 'e6', 'e7', 'e8', 'e9'], 16, 16, False),
    # fixed counters are not taken into consideration
    (['task_cycles', 'task_instructions', 'e1', 'e2', 'e3', 'e4'], 4, 8, True),
    # fixed counters are not taken into consideration
    (['task_cycles', 'task_instructions', 'e1', 'e2', 'e3', 'e4',
      'e5', 'e6', 'e7', 'e8'], 8, 8, True),
    # HD=disabled fixed counters are not taken into consideration
    (['task_cycles', 'task_instructions', 'e1', 'e2', 'e3', 'e4', 'e5'], 8, 4, False),
])
def test_check_out_perf_event_names(event_names, cpus, cores, expected):
    got = check_perf_event_count_limit(event_names, cpus, cores)
    assert expected == got
