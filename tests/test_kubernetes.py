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
from unittest.mock import patch, Mock

from owca.kubernetes import KubernetesNode, KubernetesTask, find_resources
from owca.testing import relative_module_path


def create_json_fixture_mock(name, status_code=200):
    """ Helper function to shorten the notation. """
    return Mock(json=Mock(
        return_value=json.load(open(relative_module_path(__file__, 'fixtures/' + name + '.json'))),
        status_code=status_code))


@patch('requests.get', return_value=create_json_fixture_mock('kubernetes_get_state', 200))
def test_get_tasks(get_mock):
    node = KubernetesNode()
    tasks = node.get_tasks()
    assert len(tasks) == 2

    task = tasks[0]
    assert task == KubernetesTask(name='test',
                                  task_id='4d6a81df-3448-11e9-8e1d-246e96663c22',
                                  qos='burstable',
                                  labels={'exampleKey': 'value'},
                                  resources={'requests_cpu': 0.25, 'requests_memory': 64*1024**2},
                                  cgroup_path='/kubepods/4d6a81df-3448-11e9-8e1d-246e96663c22/podBurstable/',
                                  subcgroups_paths=['/kubepods/burstable/pod4d6a81df-3448-11e9-8e1d-246e96663c22/eb9c378219b6a4efc034ea8898b19faa0e27c7b20b8eb254fda361cceacf8e90'])

    task = tasks[1]
    assert task == KubernetesTask(name='test2',
                                  task_id='567975a0-3448-11e9-8e1d-246e96663c22',
                                  qos='besteffort',
                                  labels={},
                                  resources={},
                                  cgroup_path='/kubepods/567975a0-3448-11e9-8e1d-246e96663c22/podBestEffort/',
                                  subcgroups_paths=['/kubepods/besteffort/pod567975a0-3448-11e9-8e1d-246e96663c22/e90bbbb3b060baa1d354cd9b26f353d66fbb08d785abd32f4f6ec52ac843a2e7'])


def test_find_resources_empty():
    container_spec = [{'image': 'redis',
        'imagePullPolicy': 'Always',
        'name': 'redis',
        'resources': {},
        'terminationMessagePath': '/dev/termination-log',
        'terminationMessagePolicy': 'File',
        'volumeMounts': [{'mountPath': '/var/run/secrets/kubernetes.io/serviceaccount',
                                'name': 'default-token-ktvvz',
                                'readOnly': True}]}]
    assert {} == find_resources(container_spec)


def test_find_resources_with_requests_and_limits():
    container_spec = [{'image': 'redis',
        'imagePullPolicy': 'Always',
        'name': 'redis',
        'resources': {'limits': {'cpu': '250m', 'memory': '64Mi'},
                         'requests': {'cpu': '250m', 'memory': '64MB'}},
        'terminationMessagePath': '/dev/termination-log',
        'terminationMessagePolicy': 'File',
        'volumeMounts': [{'mountPath': '/var/run/secrets/kubernetes.io/serviceaccount',
                          'name': 'default-token-ktvvz',
                          'readOnly': True}]}]
    assert {'limits_cpu': 0.25, 'limits_memory': 64*1024**2, 'requests_cpu': 0.25, 'requests_memory': 64*1000**2} == find_resources(container_spec)


def test_find_resources_multiple_containers():
    container_spec = [{'image': 'redis',
        'imagePullPolicy': 'Always',
        'name': 'redis',
        'resources': {'requests': {'cpu': '250m', 'memory': '67108864'}},
        'terminationMessagePath': '/dev/termination-log',
        'terminationMessagePolicy': 'File',
        'volumeMounts': [{'mountPath': '/var/run/secrets/kubernetes.io/serviceaccount',
                          'name': 'default-token-ktvvz',
                          'readOnly': True}]},
    {'image': 'memcached',
        'imagePullPolicy': 'Always',
        'name': 'memcached',
        'resources': {'requests': {'cpu': '100m', 'memory': '32MB'}},
        'terminationMessagePath': '/dev/termination-log',
        'terminationMessagePolicy': 'File',
        'volumeMounts': [{'mountPath': '/var/run/secrets/kubernetes.io/serviceaccount',
                          'name': 'default-token-ktvvz',
                          'readOnly': True}]}]
    assert {'requests_cpu': 0.35, 'requests_memory': 67108864 + 32 * 1000 ** 2} == find_resources(container_spec)

