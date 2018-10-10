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

from unittest.mock import patch, mock_open, MagicMock, call

import pytest

from owca.metrics import MetricName
from owca.allocators import AllocationConfiguration
from owca.cgroups import Cgroup
from owca.testing import create_open_mock


@patch('builtins.open', mock_open(read_data='100'))
def test_get_measurements():
    cgroup = Cgroup('/some/foo1', platform_cpus=1)
    measurements = cgroup.get_measurements()
    assert measurements == {MetricName.CPU_USAGE_PER_TASK: 100}


@patch('builtins.open', mock_open(read_data='100'))
def test_cgroup_read():
    cgroup = Cgroup('/some/foo1', platform_cpus=1)
    value = cgroup._read('some_ctr_file')
    assert value == 100


def test_cgroup_write():
    cgroup = Cgroup('/some/foo1', platform_cpus=1)
    ctrl_file_mock = MagicMock()
    full_path = '/sys/fs/cgroup/cpu/some/foo1/some_ctrl_file'
    open_mock = create_open_mock({full_path: ctrl_file_mock})
    with patch('builtins.open', open_mock):
        cgroup._write('some_ctrl_file', 5)
    ctrl_file_mock.assert_called_once_with(full_path, 'wb')
    ctrl_file_mock.assert_has_calls([call().__enter__().write(b'5')])


@patch('owca.containers.Cgroup._read', return_value=1000)
def test_get_normalized_shares(_read_mock):
    cgroup = Cgroup('/some/foo1', platform_cpus=1,
                    allocation_configuration=AllocationConfiguration())
    assert cgroup._get_normalized_shares() == pytest.approx(0.1, 0.01)


@patch('builtins.open', create_open_mock({
    '/sys/fs/cgroup/cpu/some/foo1/cpu.cfs_period_us': '100000',
    '/sys/fs/cgroup/cpu/some/foo1/cpu.cfs_quota_us': '-1',
}))
def test_get_normalized_quota():
    cgroup = Cgroup('/some/foo1', platform_cpus=1,
                    allocation_configuration=AllocationConfiguration())
    assert cgroup._get_normalized_quota() == float('inf')


@patch('builtins.open', create_open_mock({
    '/sys/fs/cgroup/cpu/some/foo1/tasks': '101\n102',
    '/sys/fs/cgroup/cpu/foo2/tasks': '',
}))
def test_cgroup_get_tasks():
    assert Cgroup('/some/foo1', platform_cpus=1).get_tasks() == [101, 102]
    assert Cgroup('/foo2', platform_cpus=1).get_tasks() == []
