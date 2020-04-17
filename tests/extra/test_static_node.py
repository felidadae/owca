# Copyright (c) 2019 Intel Corporation
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
from unittest.mock import Mock, patch

from tests.testing import mock_open
from wca.extra.static_node import StaticNode
from wca.nodes import Task


@patch('os.path.exists', Mock(return_value=True))
@patch('builtins.open', mock_open(read_data='100'))
def test_static_node():
    static_node = StaticNode(tasks=['task1'])
    assert static_node.get_tasks() == [Task(
        name='task1', task_id='task1', cgroup_path='/task1',
        labels={}, resources={}, subcgroups_paths=[]
    )]


@patch('os.path.exists', Mock(return_value=False))
@patch('builtins.open', mock_open(read_data='100'))
def test_static_node_without_cgroups():
    static_node = StaticNode(tasks=['task1'])
    assert static_node.get_tasks() == []


@patch('os.path.exists', Mock(return_value=True))
@patch('builtins.open', mock_open(read_data=''))
def test_static_node_with_cgroups_but_require_pids():
    static_node = StaticNode(tasks=['task1'], require_pids=True)
    assert static_node.get_tasks() == []


@patch('os.path.exists', Mock(return_value=True))
@patch('builtins.open', mock_open(read_data='100'))
def test_static_node_with_labels_and_resources():
    static_node = StaticNode(tasks=['task1'], default_labels=dict(foo='bar'),
                             default_resources=dict(cpu=1))
    assert static_node.get_tasks() == [Task(
        name='task1', task_id='task1', cgroup_path='/task1',
        labels={'foo': 'bar'}, resources={'cpu': 1}, subcgroups_paths=[]
    )]


@patch('os.path.exists', Mock(return_value=True))
@patch('os.path.isdir', Mock(return_value=True))
@patch('os.listdir', Mock(return_value=['task2']))
def test_static_node_with_directory():
    static_node = StaticNode(
        tasks=['task1'],
        directory='docker'  # doesn't matter because we're patch listdir
    )
    got_tasks = static_node.get_tasks()
    # Warning only the task_id checked (cgroup_path and name are ignored for __eq__)
    assert got_tasks == [
        Task(name='task1', task_id='task1', cgroup_path='/task1',
             subcgroups_paths=[], labels={}, resources={}),
        Task(name='docker/task2', task_id='docker/task2', cgroup_path='/docker/task2',
             subcgroups_paths=[], labels={}, resources={})
    ]
