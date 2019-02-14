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
from owca import main
from owca.mesos import MesosTask
from owca.logger import init_logging
from owca.testing import create_open_mock


yaml_config = '''
runner: !DetectionRunner
  node: !MesosNode
  action_delay: 1.
  metrics_storage: !LogStorage
  anomalies_storage: !LogStorage
  detector: !ExampleDetector
    cycle_length: 100
'''

proc_stat = """
cpu  4969563 5965 1481345 294174407 127056 380371 128960 0 0 0
cpu0 624099 681 186848 36753242 18099 44459 30609 0 0 0
intr 412890163 14 0 0 0 0 0 0 0 1 5 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 2522290 0 4890626 5163926 3207027 12 16188 16188 0 0 0 0 0 0 0 0 0 0 0 0 0 0 6549 7034 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0
ctxt 1206169501
btime 1535705721
processes 129842
procs_running 1
procs_blocked 0
softirq 319258612 1 156213925 68555 5943686 2026935 0 1167130 98346902 0 55491478
"""  # noqa

proc_meminfo = """
MemTotal:       16265556 kB
MemFree:          403888 kB
MemAvailable:    9726904 kB
Buffers:         1546536 kB
Cached:          7372084 kB
SwapCached:            8 kB
Active:          7911668 kB
Inactive:        6780804 kB
Active(anon):    4212292 kB
Inactive(anon):  1513752 kB
Active(file):    3699376 kB
Inactive(file):  5267052 kB
Unevictable:          48 kB
Mlocked:              48 kB
SwapTotal:       8204284 kB
SwapFree:        8203772 kB
Dirty:             11972 kB
Writeback:             0 kB
AnonPages:       5773888 kB
Mapped:          1380772 kB
Shmem:           1486540 kB
Slab:             927068 kB
SReclaimable:     693440 kB
SUnreclaim:       233628 kB
KernelStack:       20720 kB
PageTables:        87524 kB
NFS_Unstable:          0 kB
Bounce:                0 kB
WritebackTmp:          0 kB
CommitLimit:    16337060 kB
Committed_AS:   15778344 kB
VmallocTotal:   34359738367 kB
VmallocUsed:           0 kB
VmallocChunk:          0 kB
HardwareCorrupted:     0 kB
AnonHugePages:         0 kB
ShmemHugePages:        0 kB
ShmemPmdMapped:        0 kB
CmaTotal:              0 kB
CmaFree:               0 kB
HugePages_Total:       0
HugePages_Free:        0
HugePages_Rsvd:        0
HugePages_Surp:        0
Hugepagesize:       2048 kB
Hugetlb:               0 kB
DirectMap4k:      472444 kB
DirectMap2M:    13000704 kB
DirectMap1G:     4194304 kB
"""

mesos_tasks_mocks = [
    MesosTask(
        name='test foo task',
        executor_pid=666,
        container_id='uniq_container_id',
        task_id='mesos_like_task_id',
        agent_id='some_mesos_agent_id',
        executor_id='some_mesos_executor_id',
        cgroup_path='/mesos/xxxx-yyy',
        labels=dict(),
        resources=dict()
    )
]


@mock.patch('sys.argv', ['owca', '-c', 'configs/see_yaml_config_variable_above.yaml',
                         '-r', 'example.external_package:ExampleDetector', '-l', 'trace'])
@mock.patch('os.rmdir')
@mock.patch('owca.config.exists', return_value=True)
@mock.patch('owca.config.open', mock.mock_open(read_data=yaml_config))
@mock.patch('owca.mesos.MesosNode.get_tasks', return_value=mesos_tasks_mocks)
@mock.patch('owca.resctrl.ResGroup.sync')
@mock.patch('owca.containers.PerfCounters')
@mock.patch('owca.runner.DetectionRunner.wait_or_finish', return_value=False)
@mock.patch('builtins.open', new=create_open_mock({
    "/proc/sys/kernel/perf_event_paranoid": "0",
    "/sys/fs/cgroup/cpu/mesos/xxxx-yyy/cpuacct.usage": "10",
    "/proc/stat": proc_stat,
    "/proc/meminfo": proc_meminfo,
    "/sys/devices/system/cpu/cpu0/topology/physical_package_id": "0",
    "/sys/devices/system/cpu/cpu0/topology/core_id": "0",
    "/sys/fs/resctrl/tasks": "666",
    "/sys/fs/resctrl/mon_data/mon_L3_00/mbm_total_bytes": "1024",
    "/sys/fs/resctrl/mon_groups/mesos-xxxx-yyy/mon_data/cpu0/mbm_total_bytes": "512",
    "/sys/fs/resctrl/mon_groups/mesos-xxxx-yyy/mon_data/cpu0/llc_occupancy": "2048",
}))
@mock.patch('os.listdir', return_value=["cpu0"])
def test_main(*mocks):
    main.main()
    # restore 'silent' logging level
    init_logging('critical', 'owca')
