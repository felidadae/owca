# Copyright (c) 2019 Intel Corporation
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
from unittest.mock import MagicMock, patch

from wca.nodes import Task
from wca.config import register

from wca.extra.static_allocator import StaticAllocator

from tests.tester.tester import Tester, FileCheck, MetricCheck


@patch('tests.tester.tester._delete_cgroup')
@patch('tests.tester.tester._create_cgroup')
@patch('sys.exit')
def test_tester(
        mock_sys_exit: MagicMock,
        mock_create_cgroup: MagicMock,
        mock_delete_cgroup: MagicMock):
    register(FileCheck)
    register(MetricCheck)
    register(StaticAllocator)

    mock_check = MagicMock()

    tester = Tester('tests/tester/tester_config.yaml')

    tester.testcases[0]['checks'] = [mock_check]
    tester.testcases[1]['checks'] = [mock_check]

    # Prepare first testcase.
    assert tester.get_tasks() == [Task(
        name='task1', task_id='task1', cgroup_path='/test/task1',
        labels={}, resources={}, subcgroups_paths=[]), Task(
            name='task2', task_id='task2', cgroup_path='/test/task2',
            labels={}, resources={}, subcgroups_paths=[])]

    assert mock_create_cgroup.call_count == 2

    # Do checks from first testcase. Prepare second one.
    assert tester.get_tasks() == [Task(
        name='task2', task_id='task2', cgroup_path='/test/task2',
        labels={}, resources={}, subcgroups_paths=[]), Task(
            name='task4', task_id='task4', cgroup_path='/test/task4',
            labels={}, resources={}, subcgroups_paths=[])]

    assert mock_check.check.call_count == 1
    assert mock_create_cgroup.call_count == 3
    assert mock_delete_cgroup.call_count == 1

    tester.get_tasks()

    assert mock_check.check.call_count == 2
    assert mock_create_cgroup.call_count == 3
    assert mock_delete_cgroup.call_count == 3

    mock_sys_exit.assert_called()
