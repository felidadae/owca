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

from tests.testing import create_open_mock, relative_module_path, _is_dict_match, assert_metric
from wca.metrics import MetricName
from wca.platforms import Platform, CPUCodeName, parse_proc_stat, \
    parse_proc_meminfo, _parse_cpuinfo, parse_proc_vmstat
from wca.platforms import collect_topology_information, collect_platform_information, \
    RDTInformation, decode_listformat, parse_node_cpus, parse_node_meminfo, encode_listformat, \
    parse_node_distances


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


@patch('builtins.open', new=create_open_mock({
    "/proc/vmstat": open(relative_module_path(__file__, 'fixtures/proc-vmstat.txt')).read(),
}))
def test_parse_proc_vmstat(*mocks):
    assert parse_proc_vmstat() == {
        MetricName.PLATFORM_VMSTAT_NUMA_HINT_FAULTS: 97909,
        MetricName.PLATFORM_VMSTAT_NUMA_HINT_FAULTS_LOCAL: 97909,
        MetricName.PLATFORM_VMSTAT_NUMA_PAGES_MIGRATED: 14266,
        MetricName.PLATFORM_VMSTAT_PGFAULTS: 2911936,
        MetricName.PLATFORM_VMSTAT_PGMIGRATE_FAIL: 5633,
        MetricName.PLATFORM_VMSTAT_PGMIGRATE_SUCCESS: 14266
    }


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


@pytest.mark.parametrize("filename,expected_cpus,expected_cpu", [
    ('fixtures/procinfo_1socket_4cores_8cpus.txt', 8, {
        'model name': 'Intel(R) Core(TM) i7-4790 CPU @ 3.60GHz',
        'microcode': '0x25',
        'cpu MHz': '800.024',
        'cache size': '8192 KB'
    }),
    ('fixtures/procinfo_2sockets_ht.txt', 72, {}),
    ('fixtures/procinfo_2sockets_noht.txt', 28, {}),
])
def test_parse_cpu_info(filename, expected_cpus, expected_cpu):
    with patch('builtins.open',
               new=create_open_mock(
                   {"/proc/cpuinfo": open(relative_module_path(__file__, filename)).read()})
               ):
        got_data = _parse_cpuinfo()
        assert len(got_data) == expected_cpus
        assert _is_dict_match(got_data[0], expected_cpu), 'some keys do not match!'


@pytest.mark.parametrize("filename,expected_cpus,expected_cores,expected_sockets", [
    ('fixtures/procinfo_1socket_4cores_8cpus.txt', 8, 4, 1),
    ('fixtures/procinfo_2sockets_ht.txt', 72, 36, 2),
    ('fixtures/procinfo_2sockets_noht.txt', 28, 28, 2),
])
def test_collect_topology_information(filename, expected_cpus, expected_cores,
                                      expected_sockets):
    with patch('builtins.open',
               new=create_open_mock(
                   {"/proc/cpuinfo": open(relative_module_path(__file__, filename)).read()})
               ):
        cpuinfo = _parse_cpuinfo()
        got_cpus, got_cores, got_sockets, got_topology = collect_topology_information(cpuinfo)
        assert got_cpus == expected_cpus
        assert got_cores == expected_cores
        assert got_sockets == expected_sockets


@patch('builtins.open', new=create_open_mock({
    "/sys/devices/system/node/node0/cpulist": "1-2,6-8",
    "/sys/devices/system/node/node1/cpulist": "3,4,5-6",
}))
@patch('os.listdir', return_value=['node0', 'node1', 'ble', 'cpu'])
def test_parse_node_cpus(*mocks):
    node_cpus = parse_node_cpus()
    assert node_cpus == {0: {1, 2, 6, 7, 8}, 1: {3, 4, 5, 6}}


@patch('builtins.open', new=create_open_mock({
    "/sys/devices/system/node/node0/distance": "10 21",
    "/sys/devices/system/node/node1/distance": "21 10",
}))
@patch('os.listdir', return_value=['node0', 'node1', 'ble', 'cpu'])
def test_parse_node_distances(*mocks):
    node_distances = parse_node_distances()
    assert node_distances == {0: {0: 10, 1: 21}, 1: {0: 21, 1: 10}}


@patch('builtins.open', new=create_open_mock({
    "/sys/fs/resctrl/info/L3/cbm_mask": "fffff",
    "/sys/fs/resctrl/info/L3/min_cbm_bits": "2",
    "/sys/fs/resctrl/info/L3/num_closids": "16",
    "/sys/fs/resctrl/info/MB/bandwidth_gran": "10",
    "/sys/fs/resctrl/info/MB/min_bandwidth": "20",
    "/sys/fs/resctrl/info/MB/num_closids": "8",
    "/sys/fs/resctrl/schemata": "MB:0=100\nL3:0=fffff",
    "/proc/stat": "parsed value mocked below",
    "/proc/meminfo": "parsed value mocked below",
    "/proc/cpuinfo": "model name : intel xeon"
}))
@patch('wca.platforms.os.path.exists', side_effect=lambda path: path in [
    '/sys/fs/resctrl/mon_data/mon_L3_00/llc_occupancy',
    '/sys/fs/resctrl/mon_data/mon_L3_00/mbm_total_bytes'
])
@patch('wca.platforms.get_wca_version', return_value="0.1")
@patch('socket.gethostname', return_value="test_host")
@patch('wca.platforms.parse_proc_meminfo', return_value=1337)
@patch('wca.platforms.read_proc_meminfo', return_value='does not matter, because parse is mocked')
@patch('wca.platforms.parse_proc_stat', return_value={0: 100, 1: 200})
@patch('wca.platforms.parse_node_cpus', return_value={})
@patch('wca.platforms.parse_proc_vmstat',
       return_value={MetricName.PLATFORM_VMSTAT_NUMA_PAGES_MIGRATED: 5})
@patch('wca.platforms.parse_node_distances', return_value={})
@patch('wca.platforms.parse_node_meminfo', return_value=[{0: 1}, {0: 2}])
@patch('wca.platforms.get_numa_nodes_count', return_value=1)
@patch('wca.platforms.collect_topology_information', return_value=(2, 1, 1, {}))
@patch('wca.platforms.read_proc_stat', return_value='noop, because above parse is mocked')
@patch('wca.platforms.collect_topology_information', return_value=(2, 1, 1))
@patch('wca.platforms._parse_cpuinfo', return_value=[
    {'model': 0x5E, 'model name': 'intel xeon', 'stepping': 1}])
@patch('wca.platforms.get_platform_static_information', return_value={})
@patch('time.time', return_value=1536071557.123456)
def test_collect_platform_information(*mocks):
    got_platform, got_metrics, got_labels = collect_platform_information(
        include_optional_labels=True
    )

    assert got_platform == Platform(
        sockets=1,
        cores=1,
        cpus=2,
        numa_nodes=1,
        topology={},
        cpu_model='intel xeon',
        cpu_model_number=0x5E,
        cpu_codename=CPUCodeName.SKYLAKE,
        timestamp=1536071557.123456,  # timestamp,
        node_cpus={},
        node_distances={},
        rdt_information=RDTInformation(True, True, True, True, 'fffff', '2', 8, 10, 20),
        measurements={MetricName.PLATFORM_CPU_USAGE: {0: 100, 1: 200},
                      MetricName.PLATFORM_MEM_USAGE_BYTES: 1337,
                      MetricName.PLATFORM_MEM_NUMA_FREE_BYTES: {0: 1},
                      MetricName.PLATFORM_MEM_NUMA_USED_BYTES: {0: 2},
                      MetricName.PLATFORM_VMSTAT_NUMA_PAGES_MIGRATED: 5,
                      },
        swap_enabled=False
    )

    assert_metric(got_metrics, MetricName.PLATFORM_MEM_USAGE_BYTES, expected_metric_value=1337)
    assert_metric(got_metrics, MetricName.PLATFORM_CPU_USAGE, {'cpu': '0'},
                  expected_metric_value=100)
    assert_metric(got_metrics, MetricName.PLATFORM_TOPOLOGY_CORES, expected_metric_value=1)
    assert_metric(got_metrics, MetricName.PLATFORM_VMSTAT_NUMA_PAGES_MIGRATED,
                  expected_metric_value=5)
    assert got_labels == {"sockets": "1", "cores": "1", "cpus": "2", "host": "test_host",
                          "wca_version": "0.1", "cpu_model": "intel xeon"}


@pytest.mark.parametrize(
    'raw_cpulist, expected_cpus', [
        ('1,2,3-4,10-11', {1, 2, 3, 4, 10, 11}),
        ('1-2', {1, 2}),
        ('5,1-2', {1, 2, 5}),
        ('1,  2', {1, 2}),
        ('5,1- 2', {1, 2, 5}),
    ])
def test_decode_listform(raw_cpulist, expected_cpus):
    got_cpus = decode_listformat(raw_cpulist)
    assert got_cpus == expected_cpus


@pytest.mark.parametrize(
    'intset, expected_encoded', [
        ({1, 2, 3, 4, 10, 11}, '1,2,3,4,10,11'),
        ({1, 2}, '1,2'),
        ({2, 1}, '1,2'),
        ({}, ''),
    ])
def test_encode_listformat(intset, expected_encoded):
    got_encoded = encode_listformat(intset)
    assert got_encoded == expected_encoded


@patch('builtins.open', new=create_open_mock(
    {'/sys/devices/system/node/node0/meminfo': open(
        relative_module_path(__file__, 'fixtures/sys-devices-system-nodex-meminfo.txt')).read()})
       )
@patch('os.listdir', return_value=['node0'])
def test_parse_node_meminfo(*mocks):
    expected_node_free, expected_node_used = parse_node_meminfo()
    assert expected_node_free == {0: 454466117632}
    assert expected_node_used == {0: 77696421888}
