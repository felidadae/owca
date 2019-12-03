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
import requests

from wca.config import ValidationError
from wca.mesos import MesosNode, MesosTask
from wca.nodes import TaskSynchronizationException
from tests.testing import create_json_fixture_mock, create_open_mock


@patch('requests.post', return_value=create_json_fixture_mock('mesos_get_state', __file__))
@patch('wca.mesos.find_cgroup', return_value='mesos/120-123')
def test_get_tasks(find_cgroup_mock, post_mock):
    node = MesosNode()
    tasks = set(node.get_tasks())  # Wrap with set to make sure that hash is implemented.
    assert len(tasks) == 1

    task = tasks.pop()

    assert task == MesosTask(
        agent_id='e88fac89-2398-4e75-93f3-88cf4c35ec03-S9',
        cgroup_path='mesos/120-123',
        subcgroups_paths=[],
        container_id='ceab3bec-9282-43aa-b05f-095736cc169e',
        executor_id='thermos-root-staging14-cassandra--9043-0-9ee9fbf1-b51b-4bb3-9748-6a4327fd7e0e',
        executor_pid=32620,
        labels={'aurora_tier': 'preemptible',
                'env_uniq_id': '14',
                'name': 'cassandra--9043',
                'workload_uniq_id': '9043',
                'application': 'cassandra',
                'load_generator': 'ycsb'},
        name='root/staging14/cassandra--9043',
        task_id='root-staging14-cassandra--9043-0-9ee9fbf1-b51b-4bb3-9748-6a4327fd7e0e',
        resources={'mem': 2048.0 * 1000 ** 2, 'cpus': 8.0, 'disk': 10240.0 * 1000 ** 2}
    )


@patch('requests.post', return_value=create_json_fixture_mock('mesos_get_state', __file__))
@patch('builtins.open', new=create_open_mock({
    "/proc/32620/cgroup": "2:cpuacct,cpu:/",
}))
def test_get_tasks_with_wrong_cgroup(post_mock):
    node = MesosNode()
    tasks = set(node.get_tasks())  # Wrap with set to make sure that hash is implemented.
    assert len(tasks) == 0


@pytest.mark.parametrize(
    "json_mock", [create_json_fixture_mock('missing_executor_pid_in_mesos_response', __file__),
                  create_json_fixture_mock('missing_statuses_in_mesos_response', __file__),
                  create_json_fixture_mock('empty_statuses_in_mesos_response', __file__)])
def test_not_enough_data_in_response(json_mock):
    """MesosNode get_tasks should return none tasks as vital data in mesos response is missing."""
    with patch('requests.post', return_value=json_mock):
        node = MesosNode()
        tasks = node.get_tasks()
        assert len(tasks) == 0


@patch('wca.mesos.find_cgroup', return_value='mesos/120-123')
@pytest.mark.parametrize(
    "json_mock", [create_json_fixture_mock('mesos_invalid_response', __file__)])
def test_invalid_data_in_response(find_cgroup_mock, json_mock):
    with patch('requests.post', return_value=json_mock):
        node = MesosNode()
        with pytest.raises(ValidationError):
            node.get_tasks()


@patch('requests.post', side_effect=requests.exceptions.ConnectionError())
def test_get_tasks_synchronization_error(request):
    node = MesosNode()
    with pytest.raises(TaskSynchronizationException):
        node.get_tasks()
