# Copyright (c) 2020 Intel Corporation
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
import pytest
from tests.scheduler.data_providers.test_cluster_score_data_provider import APPS_PROFILE

from wca.scheduler.algorithms.score import _get_app_node_type, Score, Score2
from wca.scheduler.data_providers.score import NodeType
from wca.scheduler.types import CPU, MEM, MEMBW_READ, MEMBW_WRITE, WSS

SCORE_TARGET = -2.0


@pytest.mark.parametrize('apps_profile, app_name, score_target, result', [
    (APPS_PROFILE, 'memcached-mutilate-big', None, NodeType.PMEM),
    (APPS_PROFILE, 'sysbench-memory-small', None, NodeType.DRAM),
    (APPS_PROFILE, 'sysbench-memory-big', SCORE_TARGET, NodeType.DRAM),
    (APPS_PROFILE, 'sysbench-memory-small', SCORE_TARGET, NodeType.DRAM),
    (APPS_PROFILE, 'sysbench-memory-medium', SCORE_TARGET, NodeType.DRAM),
    (APPS_PROFILE, 'stress-stream-big', SCORE_TARGET, NodeType.DRAM),
    (APPS_PROFILE, 'stress-stream-medium', SCORE_TARGET, NodeType.DRAM),
    (APPS_PROFILE, 'stress-stream-small', SCORE_TARGET, NodeType.DRAM),
    (APPS_PROFILE, 'memcached-mutilate-big', SCORE_TARGET, NodeType.PMEM),
    (APPS_PROFILE, 'mysql-hammerdb-small', SCORE_TARGET, NodeType.PMEM),
    (APPS_PROFILE, 'memcached-mutilate-small', SCORE_TARGET, NodeType.PMEM),
    (APPS_PROFILE, 'redis-memtier-medium', SCORE_TARGET, NodeType.PMEM),
    (APPS_PROFILE, 'redis-memtier-small', SCORE_TARGET, NodeType.PMEM),
    (APPS_PROFILE, 'redis-memtier-big', SCORE_TARGET, NodeType.PMEM),
    (APPS_PROFILE, 'memcached-mutilate-medium', SCORE_TARGET, NodeType.PMEM),
    (APPS_PROFILE, 'specjbb-preset-big-120', SCORE_TARGET, NodeType.PMEM),
    (APPS_PROFILE, 'memcached-mutilate-big-wss', SCORE_TARGET, NodeType.PMEM),
    (APPS_PROFILE, 'specjbb-preset-small', SCORE_TARGET, NodeType.PMEM),
    (APPS_PROFILE, 'redis-memtier-big-wss', SCORE_TARGET, NodeType.PMEM),
    (APPS_PROFILE, 'specjbb-preset-medium', SCORE_TARGET, NodeType.PMEM),
    ([], '', None, NodeType.DRAM),
    ])
def test_get_app_node_type(apps_profile, app_name, score_target, result):
    assert _get_app_node_type(apps_profile, app_name, score_target) == result


@pytest.mark.parametrize('', [
    (),
    ])
def test_reschedule():
    pass


def test_normalize_capacity_to_memory():
    algorithm_instance = Score2(None)
    capacity = {CPU: 40, MEM: 20, MEMBW_WRITE: 40, MEMBW_READ: 40, WSS: 40}
    expected = {CPU: 2, MEM: 1, MEMBW_WRITE: 2, MEMBW_READ: 2, WSS: 2}
    assert algorithm_instance.normalize_capacity_to_memory(capacity) == expected


def test_calculate_apps_profile():
    algorithm_instance = Score2(None, [CPU, MEM, MEMBW_READ, MEMBW_WRITE, WSS])
    nodes_capacities = {
        'node101': {CPU: 72.0, MEM: 1596, MEMBW_READ: 57, MEMBW_WRITE: 16, WSS: 58},
        'node102': {CPU: 72.0, MEM: 201, MEMBW_READ: 256, MEMBW_WRITE: 256, WSS: 201},
    }
    apps_spec = {
        'memcached-mutilate-small': {CPU: 10, MEM: 26, MEMBW_READ: 2, MEMBW_WRITE: 2, WSS: 5},
    }
    data_provider_queried = (nodes_capacities, None, apps_spec, None)
    apps_scores  = algorithm_instance.calculate_apps_profile(data_provider_queried)
    assert round(apps_scores['memcached-mutilate-small'], 1) == -8.5


def test_calculate_apps_profile_theory():
    algorithm_instance = Score2(None, [CPU, MEM, MEMBW_READ, MEMBW_WRITE, WSS])
    nodes_capacities = {
        'node101': {CPU: 60, MEM: 1200, MEMBW_READ: 60, MEMBW_WRITE: 18, WSS: 18},
        'node102': {CPU: 72.0, MEM: 201, MEMBW_READ: 256, MEMBW_WRITE: 256, WSS: 201},
    }
    apps_spec = {
        'workload_A': {CPU: 2, MEM: 2,  MEMBW_WRITE: 0.6, MEMBW_READ: 2, WSS: 0.6},
        'workload_B': {CPU: 1, MEM: 20, MEMBW_WRITE: 0.3, MEMBW_READ: 1, WSS: 0.3},
        'workload_C': {CPU: 1, MEM: 10, MEMBW_WRITE: 0.6, MEMBW_READ: 2, WSS: 0.6},
    }
    data_provider_queried = (nodes_capacities, None, apps_spec, None)
    apps_scores = algorithm_instance.calculate_apps_profile(data_provider_queried)
    assert apps_scores == {'workload_A': -20.0, 'workload_B': -1.0, 'workload_C': -4.0}
