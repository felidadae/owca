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


from unittest.mock import patch

import pytest

from owca.metrics import Metric, MetricName
from owca.platforms import Platform, parse_proc_meminfo, parse_proc_stat, \
    collect_topology_information, collect_platform_information, RDTInformation
from owca.testing import create_open_mock


@pytest.mark.parametrize("raw_meminfo_output,expected", [
    ("MemTotal:       32815700 kB\n"
     "MemFree:        18245956 kB\n"
     "MemAvailable:   24963992 kB\n"
     "Buffers:         1190812 kB\n"
     "Cached:          6971960 kB\n"
     "SwapCached:            0 kB\n"
     "Active:          8808464 kB\n"
     "Inactive:        4727816 kB\n"
     "Active(anon):    5376088 kB\n",
     6406972 * 1024)

])
def test_parse_proc_meminfo(raw_meminfo_output, expected):
    assert parse_proc_meminfo(raw_meminfo_output) == expected


@pytest.mark.parametrize("raw_proc_state_output,expected", [
    ("cpu  8202889 22275 2138696 483384497 138968 853793 184852 0 0 0\n"
     "cpu0 100 100 100 100 100 100 100 0 0 0\n"
     "cpu1 100 100 100 100 100 100 100 0 0 0\n"
     "cpu2 100 100 100 100 100 100 100 0 0 0\n"
     "cpu3 100 100 100 100 100 100 100 0 0 0\n"
     "cpu4 100 100 100 100 100 100 100 0 0 0\n"
     "cpu5 100 100 100 100 100 100 100 0 0 0\n"
     "cpu6 100 100 100 100 100 100 100 0 0 0\n"
     "cpu7 100 100 100 100 100 100 100 0 0 0\n"
     "intr 768113335 20 0 0 0 0 0 0 0 1 4 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0\n",
     {0: 500, 1: 500, 2: 500, 3: 500, 4: 500, 5: 500, 6: 500, 7: 500})
])
def test_parse_proc_state(raw_proc_state_output, expected):
    assert parse_proc_stat(raw_proc_state_output) == expected


@patch('builtins.open', new=create_open_mock({
    "/sys/devices/system/cpu/cpu0/topology/physical_package_id": "0",
    "/sys/devices/system/cpu/cpu0/topology/core_id": "0",
    "/sys/devices/system/cpu/cpu1/topology/physical_package_id": "0",
    "/sys/devices/system/cpu/cpu1/topology/core_id": "0",
    "/sys/devices/system/cpu/cpu1/online": "1",
    "/sys/devices/system/cpu/cpu2/online": "0",
    "/sys/devices/system/cpu/cpu3/online": "0",
}))
@patch('os.listdir', return_value=['cpu0', 'cpuidle', 'uevent', 'nohz_full', 'hotplug',
                                   'cpu1', 'cpu2', 'possible', 'offline', 'present',
                                   'power', 'microcode', 'cpu3', 'online',
                                   'vulnerabilities', 'cpufreq', 'intel_pstate',
                                   'isolated', 'kernel_max', 'modalias'])
def test_collect_topology_information_2_cpus_in_1_core_offline_rest_online(*mocks):
    assert (2, 1, 1) == collect_topology_information()


@patch('builtins.open', new=create_open_mock({
    "/sys/devices/system/cpu/cpu0/topology/physical_package_id": "0",
    "/sys/devices/system/cpu/cpu0/topology/core_id": "0",
    "/sys/devices/system/cpu/cpu1/topology/physical_package_id": "0",
    "/sys/devices/system/cpu/cpu1/topology/core_id": "1",
    "/sys/devices/system/cpu/cpu1/online": "1",
    "/sys/devices/system/cpu/cpu2/topology/physical_package_id": "1",
    "/sys/devices/system/cpu/cpu2/topology/core_id": "0",
    "/sys/devices/system/cpu/cpu2/online": "1",
    "/sys/devices/system/cpu/cpu3/topology/physical_package_id": "1",
    "/sys/devices/system/cpu/cpu3/topology/core_id": "1",
    "/sys/devices/system/cpu/cpu3/online": "1",
}))
@patch('os.listdir', return_value=['cpu0', 'cpuidle', 'uevent', 'nohz_full', 'hotplug',
                                   'cpu1', 'cpu2', 'possible', 'offline', 'present',
                                   'power', 'microcode', 'cpu3', 'online',
                                   'vulnerabilities', 'cpufreq', 'intel_pstate',
                                   'isolated', 'kernel_max', 'modalias'])
def test_collect_topology_information_2_cores_per_socket_all_cpus_online(*mocks):
    assert (4, 4, 2) == collect_topology_information()


@patch('builtins.open', new=create_open_mock({
    "/sys/fs/resctrl/info/L3/cbm_mask": "fffff",
    "/sys/fs/resctrl/info/L3/min_cbm_bits": "2",
    "/sys/fs/resctrl/info/L3/num_closids": "16",
    "/sys/fs/resctrl/info/MB/bandwidth_gran": "10",
    "/sys/fs/resctrl/info/MB/min_bandwidth": "20",
    "/sys/fs/resctrl/info/MB/num_closids": "8",
    "/sys/fs/resctrl/schemata": "MB:0=100",
    "/proc/stat": "parsed value mocked below",
    "/proc/meminfo": "parsed value mocked below",
    "/proc/cpuinfo": "model name : intel xeon"
}))
@patch('owca.platforms.get_owca_version', return_value="0.1")
@patch('socket.gethostname', return_value="test_host")
@patch('owca.platforms.parse_proc_meminfo', return_value=1337)
@patch('owca.platforms.parse_proc_stat', return_value={0: 100, 1: 200})
@patch('owca.platforms.collect_topology_information', return_value=(2, 1, 1))
@patch('time.time', return_value=1536071557.123456)
def test_collect_platform_information(*mocks):
    assert collect_platform_information() == (
        Platform(1, 1, 2, {0: 100, 1: 200}, 1337, 1536071557.123456,
                 RDTInformation('fffff', '2', True, 8, 10, 20)),
        [
            Metric.create_metric_with_metadata(
                name=MetricName.MEM_USAGE, value=1337
            ),
            Metric.create_metric_with_metadata(
                name=MetricName.CPU_USAGE_PER_CPU, value=100, labels={"cpu": "0"}
            ),
            Metric.create_metric_with_metadata(
                name=MetricName.CPU_USAGE_PER_CPU, value=200, labels={"cpu": "1"}
            ),
        ],
        {"sockets": "1", "cores": "1", "cpus": "2", "host": "test_host",
         "owca_version": "0.1", "cpu_model": "intel xeon"}
    )
