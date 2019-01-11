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


import json

from owca.mesos import MesosNode, MesosTask
from unittest.mock import patch, Mock
from owca.testing import relative_module_path


@patch('requests.post', return_value=Mock(
    json=Mock(
        return_value=json.load(
            open(relative_module_path(__file__, 'fixtures/mesos_get_state.json'))),
        status_code=200)))
@patch('owca.mesos.find_cgroup', return_value='mesos/120-123')
def test_get_tasks(find_cgroup_mock, post_mock):
    node = MesosNode()
    tasks = node.get_tasks()
    assert len(tasks) == 1

    task = tasks[0]
    assert task == MesosTask(
        agent_id='e88fac89-2398-4e75-93f3-88cf4c35ec03-S9',
        cgroup_path='mesos/120-123',
        container_id='ceab3bec-9282-43aa-b05f-095736cc169e',
        executor_id='thermos-root-staging14-cassandra--9043-0-9ee9fbf1-b51b-4bb3-9748-6a4327fd7e0e',
        executor_pid=32620,
        labels={'org.apache.aurora.tier': 'preemptible',
                'org.apache.aurora.metadata.env_uniq_id': '14',
                'org.apache.aurora.metadata.name': 'cassandra--9043',
                'org.apache.aurora.metadata.workload_uniq_id': '9043',
                'org.apache.aurora.metadata.application': 'cassandra',
                'org.apache.aurora.metadata.load_generator': 'ycsb'},
        name='root/staging14/cassandra--9043',
        task_id='root-staging14-cassandra--9043-0-9ee9fbf1-b51b-4bb3-9748-6a4327fd7e0e',
        resources={'mem': 2048.0, 'cpus': 8.0, 'disk': 10240.0}
    )


@patch('requests.post', return_value=Mock(
    json=Mock(
        return_value=json.load(
            open(relative_module_path(__file__,
                                      'fixtures/missing_executor_pid_in_mesos_response.json'))),
        status_code=200)))
def test_missing_executor_pid(post):
    node = MesosNode()
    tasks = node.get_tasks()

    assert len(tasks) == 0


def test_missing_statuses():
    mesos_json_response = json.load(
        open(relative_module_path(__file__,
                                  'fixtures/missing_executor_pid_in_mesos_response.json')))
    for task in mesos_json_response['get_state']['get_tasks']['launched_tasks']:
        del task['statuses']
    with patch('requests.post',
               return_value=Mock(json=Mock(return_value=mesos_json_response),
                                 status_code=200)):
        node = MesosNode()
        tasks = node.get_tasks()
        assert len(tasks) == 0

    for task in mesos_json_response['get_state']['get_tasks']['launched_tasks']:
        task['statuses'] = []
    with patch('requests.post',
               return_value=Mock(json=Mock(return_value=mesos_json_response),
                                 status_code=200)):
        node = MesosNode()
        tasks = node.get_tasks()
        assert len(tasks) == 0
