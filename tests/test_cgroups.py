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

from unittest.mock import patch, mock_open, MagicMock, call, Mock

import pytest

from tests.testing import create_open_mock, platform_mock
from wca.allocators import AllocationConfiguration
from wca.cgroups import Cgroup, CgroupType, CgroupResource
from wca.metrics import MetricName, MissingMeasurementException
from wca.platforms import Platform


@patch('wca.cgroups.log.warning')
@patch('builtins.open', side_effect=FileNotFoundError())
def test_get_measurements_not_found_cgroup(mock_file, mock_log_warning):
    cgroup = Cgroup('/some/foo1', platform=platform_mock)
    with pytest.raises(MissingMeasurementException):
        cgroup.get_measurements()


@patch('builtins.open', create_open_mock({
    '/sys/fs/cgroup/cpu/some/foo1/cpuacct.usage': '1000000000',  # nanoseconds
    '/sys/fs/cgroup/memory/some/foo1/memory.usage_in_bytes': '101',
    '/sys/fs/cgroup/memory/some/foo1/memory.max_usage_in_bytes': '999',
    '/sys/fs/cgroup/memory/some/foo1/memory.limit_in_bytes': '2000',
    '/sys/fs/cgroup/memory/some/foo1/memory.soft_limit_in_bytes': '1500',
    '/sys/fs/cgroup/memory/some/foo1/memory.numa_stat': 'hierarchical_total=1 N0=123 N1=234',
    '/sys/fs/cgroup/memory/some/foo1/memory.stat': 'pgfault 2730362811\nfoo=1 N0=123 N1=234',
}))
def test_get_measurements():
    cgroup = Cgroup('/some/foo1', platform=platform_mock)
    measurements = cgroup.get_measurements()

    assert measurements == {MetricName.TASK_CPU_USAGE_SECONDS: 1,
                            MetricName.TASK_MEM_USAGE_BYTES: 101,
                            MetricName.TASK_MEM_MAX_USAGE_BYTES: 999,
                            MetricName.TASK_MEM_LIMIT_BYTES: 2000,
                            MetricName.TASK_MEM_SOFT_LIMIT_BYTES: 1500,
                            MetricName.TASK_MEM_PAGE_FAULTS: 2730362811,
                            MetricName.TASK_MEM_NUMA_PAGES: {'0': 123, '1': 234}}


@patch('builtins.open', mock_open(read_data='100'))
def test_cgroup_read():
    cgroup = Cgroup('/some/foo1', platform=platform_mock)
    value = cgroup._read('some_ctr_file', CgroupType.CPU)
    assert value == 100


def test_cgroup_write():
    cgroup = Cgroup('/some/foo1', platform=platform_mock)
    ctrl_file_mock = MagicMock()
    full_path = '/sys/fs/cgroup/cpu/some/foo1/some_ctrl_file'
    open_mock = create_open_mock({full_path: ctrl_file_mock})
    with patch('builtins.open', open_mock):
        cgroup._write('some_ctrl_file', 5, CgroupType.CPU)
    ctrl_file_mock.assert_called_once_with(full_path, 'wb')
    ctrl_file_mock.assert_has_calls([call().__enter__().write(b'5')])


@patch('wca.cgroups.Cgroup._read', return_value=1000)
def test_get_normalized_shares(_read_mock):
    cgroup = Cgroup('/some/foo1', platform=platform_mock,
                    allocation_configuration=AllocationConfiguration())
    assert cgroup._get_normalized_shares() == pytest.approx(1, 0.01)


@patch('builtins.open', create_open_mock({
    '/sys/fs/cgroup/cpu/some/foo1/cpu.cfs_period_us': '100000',
    '/sys/fs/cgroup/cpu/some/foo1/cpu.cfs_quota_us': '-1',
}))
def test_get_normalized_quota():
    cgroup = Cgroup('/some/foo1', platform=platform_mock,
                    allocation_configuration=AllocationConfiguration())
    assert cgroup._get_normalized_quota() == 1.0


@patch('builtins.open', create_open_mock({
    '/sys/fs/cgroup/cpu/some/foo1/tasks': '101\n102',
    '/sys/fs/cgroup/cpu/foo2/tasks': '',
}))
def test_cgroup_get_pids():
    assert Cgroup('/some/foo1', platform=platform_mock).get_pids() == ['101', '102']
    assert Cgroup('/foo2', platform=platform_mock).get_pids() == []


@pytest.mark.parametrize(
    'normalized_shares, allocation_configuration, expected_shares_write', [
        (0., AllocationConfiguration(), 2),
        (1., AllocationConfiguration(), 1000),  # based on cpu_shares_unit (default 1000)
        (1., AllocationConfiguration(cpu_shares_unit=10000), 10000),
        (2., AllocationConfiguration(cpu_shares_unit=10000), 20000),
    ]
)
def test_set_normalized_shares(normalized_shares, allocation_configuration, expected_shares_write):
    with patch('wca.cgroups.Cgroup._write') as write_mock:
        cgroup = Cgroup('/some/foo1', platform=platform_mock,
                        allocation_configuration=allocation_configuration)
        cgroup.set_shares(normalized_shares)
        write_mock.assert_called_with(
            CgroupResource.CPU_SHARES, expected_shares_write, CgroupType.CPU)


@pytest.mark.parametrize(
    'normalized_quota, cpu_quota_period, platforms_cpu, initial_period_value, '
    'expected_period_write, expected_quota_write', [
        (0., 2000, 1, 1000,
         2000, 1000),
        (1., 2000, 1, 1000,
         2000, -1),
        (2., 1000, 1, 1000,
         None, -1),
        (1., 1000, 8, 1000,
         None, -1),
        (.5, 1000, 8, 1000,
         None, 4000),
        (.25, 10000, 8, 1000,
         None, 20000),
    ]
)
def test_set_normalized_quota(normalized_quota, cpu_quota_period, platforms_cpu,
                              initial_period_value, expected_period_write, expected_quota_write):
    platform_mock = Mock(
        spec=Platform,
        cpus=platforms_cpu,
    )
    with patch('wca.cgroups.Cgroup._read', return_value=initial_period_value):
        with patch('wca.cgroups.Cgroup._write') as write_mock:
            cgroup = Cgroup('/some/foo1', platform=platform_mock,
                            allocation_configuration=AllocationConfiguration(
                                cpu_quota_period=cpu_quota_period))
            cgroup.set_quota(normalized_quota)
            write_mock.assert_has_calls(
                [call(CgroupResource.CPU_QUOTA, expected_quota_write, CgroupType.CPU)])
            if expected_period_write:
                write_mock.assert_has_calls(
                    [call(CgroupResource.CPU_PERIOD, expected_period_write, CgroupType.CPU)])


# two numa nodes 0->0,1 and 1->2,3
_test_node_cpus = {0: {0, 1}, 1: {2, 3}}


@pytest.mark.parametrize(
    'cpus, mems, node_cpus,'
    'expected_cpus_write, expected_mems_write', [
        ({0, 1, 2, 3, 4}, {0}, _test_node_cpus,
         '0,1,2,3,4', '0'),
        ({0, 1}, {0, 1}, _test_node_cpus,
         '0,1', '0,1'),
        ({1, 3}, {0}, _test_node_cpus,
         '1,3', '0'),
    ]
)
def test_set_cpuset(
        cpus, mems, node_cpus, expected_cpus_write, expected_mems_write):
    platform_mock = Mock(
        spec=Platform,
        node_cpus=node_cpus,
    )
    with patch('wca.cgroups.Cgroup._write') as write_mock:
        cgroup = Cgroup('/some/foo1', platform=platform_mock)
        cgroup.set_cpuset_cpus(cpus)
        write_mock.assert_has_calls(
            [call(CgroupResource.CPUSET_CPUS, expected_cpus_write, CgroupType.CPUSET)])

        cgroup.set_cpuset_mems(mems)
        write_mock.assert_has_calls(
            [call(CgroupResource.CPUSET_MEMS, expected_mems_write, CgroupType.CPUSET)])
