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
from unittest.mock import MagicMock, Mock

import pytest

from tests.testing import create_json_fixture_mock
from wca.scheduler.data_providers.cluster_data_provider import (
        ClusterDataProvider, MissingBasicResources,
        Queries)
from wca.scheduler.kubeapi import Kubeapi
from wca.prometheus import Prometheus
from wca.scheduler.types import ResourceType

TEST_QUERIES = Queries()


def get_mocked_cluster_data_provider():
    mocked_kubeapi = MagicMock(spec=Kubeapi)
    mocked_kubeapi.request_kubeapi.side_effect = request_kubeapi_side_effect
    mocked_kubeapi.monitored_namespaces = ['default']

    mocked_prometheus = Mock(spec=Prometheus)
    mocked_prometheus.do_query.side_effect = do_query_side_effect

    cluster_dp = ClusterDataProvider(
            kubeapi=mocked_kubeapi,
            prometheus=mocked_prometheus,
            queries=Queries())

    return cluster_dp


def request_kubeapi_side_effect(*args):
    if args[0] == '/api/v1/nodes':
        return create_json_fixture_mock('kubeapi_nodes').json()
    # CHANGE IT
    elif args[0] == '/api/v1/namespaces/default/pods':
        return create_json_fixture_mock('kubeapi_default_ns_pods').json()


def do_query_side_effect(*args):

    if args[0] == TEST_QUERIES.NODES_PMM_MEMORY_MODE:
        return create_json_fixture_mock('prometheus_nodes_pmm_memory_mode').json()['data']['result']
    elif args[0] == TEST_QUERIES.NODE_CAPACITY_RESOURCES_QUERY_MAP[ResourceType.MEMBW_READ]:
        return create_json_fixture_mock('prometheus_membw_capacity_read').json()['data']['result']
    elif args[0] == TEST_QUERIES.NODE_CAPACITY_RESOURCES_QUERY_MAP[ResourceType.MEMBW_WRITE]:
        return create_json_fixture_mock('prometheus_membw_capacity_write').json()['data']['result']
    elif args[0] == TEST_QUERIES.NODE_CAPACITY_RESOURCES_QUERY_MAP[ResourceType.WSS]:
        return create_json_fixture_mock('prometheus_node_capacity_mem_wss').json()['data']['result']
    elif args[0] == TEST_QUERIES.APP_REQUESTED_RESOURCES_QUERY_MAP[ResourceType.CPU]:
        return create_json_fixture_mock(
                'prometheus_app_requested_cpu').json()['data']['result']
    elif args[0] == TEST_QUERIES.APP_REQUESTED_RESOURCES_QUERY_MAP[ResourceType.MEM]:
        return create_json_fixture_mock(
                'prometheus_app_requested_mem').json()['data']['result']
    elif args[0] == TEST_QUERIES.APP_REQUESTED_RESOURCES_QUERY_MAP[ResourceType.MEMBW_READ]:
        return create_json_fixture_mock(
                'prometheus_app_requested_membw_read').json()['data']['result']
    elif args[0] == TEST_QUERIES.APP_REQUESTED_RESOURCES_QUERY_MAP[ResourceType.MEMBW_WRITE]:
        return create_json_fixture_mock(
                'prometheus_app_requested_membw_write').json()['data']['result']
    elif args[0] == TEST_QUERIES.APP_REQUESTED_RESOURCES_QUERY_MAP[ResourceType.WSS]:
        return create_json_fixture_mock(
                'prometheus_app_requested_wss').json()['data']['result']
    elif args[0] == TEST_QUERIES.NODES_DRAM_HIT_RATIO:
        return create_json_fixture_mock('prometheus_nodes_dram_hit_ratio').json()['data']['result']
    else:
        return []


@pytest.mark.parametrize('resources', [
    [],
    [ResourceType.CPU],
    [ResourceType.MEM],
    [ResourceType.MEMBW_READ, ResourceType.MEMBW_WRITE]])
def test_get_nodes_capacities_raise_exception_no_cpu_or_mem(resources):
    cluster_dp = get_mocked_cluster_data_provider()

    with pytest.raises(MissingBasicResources):
        cluster_dp.get_nodes_capacities(resources)


CLUSTER_CPU_MEM_CAPACITIES = {
    'node101': {'cpu': 72.0, 'mem': 1596},
    'node102': {'cpu': 72.0, 'mem': 404},
    'node103': {'cpu': 72.0, 'mem': 201},
    'node104': {'cpu': 72.0, 'mem': 201},
    'node105': {'cpu': 72.0, 'mem': 201},
    'node200': {'cpu': 96.0, 'mem': 201},
    'node201': {'cpu': 96.0, 'mem': 201},
    'node202': {'cpu': 96.0, 'mem': 201},
    'node203': {'cpu': 96.0, 'mem': 201},
    'node37': {'cpu': 80.0, 'mem': 201},
    'node38': {'cpu': 80.0, 'mem': 404},
    'node39': {'cpu': 80.0, 'mem': 404},
    'node40': {'cpu': 80.0, 'mem': 201},
}


CLUSTER_MEMBW_CAPACITIES = {
    'node101': {'membw_read': 255999960000, 'membw_write': 255999960000},
    'node102': {'membw_read': 255999960000, 'membw_write': 255999960000},
    'node103': {},
    'node104': {},
    'node105': {},
    'node200': {},
    'node201': {},
    'node202': {},
    'node203': {},
    'node37': {'membw_read': 54400000000, 'membw_write': 14800000000},
    'node38': {'membw_read': 255999960000, 'membw_write': 255999960000},
    'node39': {'membw_read': 255999960000, 'membw_write': 255999960000},
    'node40': {'membw_read': 33200000000, 'membw_write': 12000000000},
}

CLUSTER_CAPACITIES = {}

for node in CLUSTER_CPU_MEM_CAPACITIES:
    if node in CLUSTER_MEMBW_CAPACITIES:
        CLUSTER_CAPACITIES[node] = {
                **CLUSTER_CPU_MEM_CAPACITIES[node],
                **CLUSTER_MEMBW_CAPACITIES[node]}
    else:
        CLUSTER_CAPACITIES[node] = CLUSTER_CPU_MEM_CAPACITIES[node]


@pytest.mark.parametrize('resources, nodes_capacities', [
    ([ResourceType.CPU, ResourceType.MEM], CLUSTER_CPU_MEM_CAPACITIES),
    ([ResourceType.CPU, ResourceType.MEM, ResourceType.MEMBW_READ,
        ResourceType.MEMBW_WRITE], CLUSTER_CAPACITIES),
    ])
def test_get_nodes_capacities(resources, nodes_capacities):
    cluster_dp = get_mocked_cluster_data_provider()
    cp = cluster_dp.get_nodes_capacities(resources)

    for node in nodes_capacities:
        assert len(nodes_capacities[node]) == len(cp[node])


CLUSTER_APP_COUNT = ({
    'node101': {'memcached-mutilate-big': ['memcached-mutilate-big-0'],
                'memcached-mutilate-big-wss': ['memcached-mutilate-big-wss-1'],
                'redis-memtier-big': ['redis-memtier-big-0'],
                'redis-memtier-big-wss': ['redis-memtier-big-wss-0'],
                'specjbb-preset-big-120': ['specjbb-preset-big-120-0']},
    'node102': {'memcached-mutilate-big': ['memcached-mutilate-big-1'],
                'specjbb-preset-small': ['specjbb-preset-small-0'],
                'sysbench-memory-big': ['sysbench-memory-big-0']},
    'node103': {'memcached-mutilate-medium': ['memcached-mutilate-medium-0'],
                'stress-stream-medium': ['stress-stream-medium-1']},
    'node104': {'memcached-mutilate-small': ['memcached-mutilate-small-1'],
                'specjbb-preset-medium': ['specjbb-preset-medium-1']},
    'node105': {'memcached-mutilate-medium': ['memcached-mutilate-medium-1'],
                'sysbench-memory-medium': ['sysbench-memory-medium-0'],
                'sysbench-memory-small': ['sysbench-memory-small-1']},
    'node200': {'memcached-mutilate-small': ['memcached-mutilate-small-0'],
                'redis-memtier-small': ['redis-memtier-small-1'],
                'stress-stream-big': ['stress-stream-big-0'],
                'stress-stream-small': ['stress-stream-small-0'],
                'sysbench-memory-medium': ['sysbench-memory-medium-1']},
    'node201': {'redis-memtier-big-wss': ['redis-memtier-big-wss-1']},
    'node202': {'redis-memtier-medium': ['redis-memtier-medium-0'],
                'specjbb-preset-medium': ['specjbb-preset-medium-0'],
                'specjbb-preset-small': ['specjbb-preset-small-1'],
                'stress-stream-small': ['stress-stream-small-1'],
                'sysbench-memory-small': ['sysbench-memory-small-0']},
    'node203': {'redis-memtier-small': ['redis-memtier-small-0'],
                'specjbb-preset-big-60': ['specjbb-preset-big-60-0']},
    'node37': {'mysql-hammerdb-small': ['mysql-hammerdb-small-1'],
               'sysbench-memory-big': ['sysbench-memory-big-1']},
    'node38': {'memcached-mutilate-big-wss': ['memcached-mutilate-big-wss-0'],
               'specjbb-preset-big-120': ['specjbb-preset-big-120-1']},
    'node39': {'mysql-hammerdb-small': ['mysql-hammerdb-small-0'],
               'redis-memtier-big': ['redis-memtier-big-1'],
               'stress-stream-big': ['stress-stream-big-1'],
               'stress-stream-medium': ['stress-stream-medium-0']},
    'node40': {'redis-memtier-medium': ['redis-memtier-medium-1'],
               'specjbb-preset-big-60': ['specjbb-preset-big-60-1']}}, {})


@pytest.mark.parametrize('apps_count', [
    (CLUSTER_APP_COUNT),
    ])
def test_get_apps_counts(apps_count):
    cluster_dp = get_mocked_cluster_data_provider()
    assert apps_count == cluster_dp.get_apps_counts()


APP_REQUESTED_CPU_MEM = {
    'memcached-mutilate-big-wss': {'cpu': 10, 'mem': 91000000000},
    'memcached-mutilate-medium': {'cpu': 10, 'mem': 51000000000},
    'redis-memtier-big': {'cpu': 3, 'mem': 70000000000},
    'redis-memtier-big-wss': {'cpu': 3, 'mem': 75000000000},
    'redis-memtier-medium': {'cpu': 3, 'mem': 11000000000},
    'redis-memtier-small': {'cpu': 3, 'mem': 10000000000},
    'specjbb-preset-medium': {'cpu': 9, 'mem': 26000000000},
    'sysbench-memory-big': {'cpu': 4, 'mem': 10000000000},
    'sysbench-memory-medium': {'cpu': 3, 'mem': 4000000000},
    'sysbench-memory-small': {'cpu': 2, 'mem': 2000000000}
}


APP_REQUESTED_MEMBW = {
    'memcached-mutilate-big-wss': {'membw_read': 2622597731, 'membw_write': 2805136872},
    'memcached-mutilate-medium': {'membw_read': 2839845719, 'membw_write': 2634252554},
    'redis-memtier-big': {'membw_read': 1627937868, 'membw_write': 1085064491},
    'redis-memtier-big-wss': {'membw_read': 1980646146, 'membw_write': 3163513620},
    'redis-memtier-medium': {'membw_read': 1591126817, 'membw_write': 1049019197},
    'redis-memtier-small': {'membw_read': 1393914170, 'membw_write': 1039516290},
    'specjbb-preset-medium': {'membw_read': 3411658124, 'membw_write': 1192782848},
    'sysbench-memory-big': {'membw_read': 115604853, 'membw_write': 14738247436},
    'sysbench-memory-medium': {'membw_read': 35819087, 'membw_write': 10940491266},
    'sysbench-memory-small': {'membw_read': 19041364, 'membw_write': 5890534725}
}

APP_REQUESTED_CPU_MEM_MEMBW = {app: {**APP_REQUESTED_CPU_MEM[app], **APP_REQUESTED_MEMBW[app]}
                               for app in APP_REQUESTED_CPU_MEM}

APP_REQUESTED_WSS = {
    'memcached-mutilate-big-wss': {'wss': 10686448000},
    'memcached-mutilate-medium': {'wss': 7230696000},
    'redis-memtier-big': {'wss': 3525264000},
    'redis-memtier-big-wss': {'wss': 4841892000},
    'redis-memtier-medium': {'wss': 2503720000},
    'redis-memtier-small': {'wss': 1967084000},
    'specjbb-preset-medium': {'wss': 12415120000},
    'sysbench-memory-big': {'wss': 8396076000},
    'sysbench-memory-medium': {'wss': 2104676000},
    'sysbench-memory-small': {'wss': 1056096000}
}

APP_REQUESTED_ALL_RESOURCES = {app: {**APP_REQUESTED_CPU_MEM_MEMBW[app], **APP_REQUESTED_WSS[app]}
                               for app in APP_REQUESTED_CPU_MEM}


@pytest.mark.parametrize('resource_types, resources', [
    ([ResourceType.CPU, ResourceType.MEM], APP_REQUESTED_CPU_MEM),
    ([ResourceType.MEMBW_READ, ResourceType.MEMBW_WRITE], APP_REQUESTED_MEMBW),
    ([ResourceType.CPU, ResourceType.MEM, ResourceType.MEMBW_READ, ResourceType.MEMBW_WRITE],
        APP_REQUESTED_CPU_MEM_MEMBW),
    ([ResourceType.WSS], APP_REQUESTED_WSS),
    ([ResourceType.CPU, ResourceType.MEM, ResourceType.MEMBW_READ, ResourceType.MEMBW_WRITE,
      ResourceType.WSS], APP_REQUESTED_ALL_RESOURCES),
    ])
def test_get_apps_requested_resources(resource_types, resources):
    cluster_dp = get_mocked_cluster_data_provider()
    result = cluster_dp.get_apps_requested_resources(resource_types)
    # Check only keys.
    # Values are skipped due to big effort for keeping test fixtures consistent each other.
    for resource in resources:
        assert resource in result


def test_get_dram_hit_ratio():
    cluster_dp = get_mocked_cluster_data_provider()
    expected_output = {
        'node101': 0.9941095705596056,
        'node102': 1.0,
        'node103': 1.0,
        'node104': 1.0,
        'node105': 1.0,
        'node200': 1.0,
        'node202': 1.0,
        'node203': 1.0,
        'node37': 1.0,
        'node38': 1.0,
        'node39': 1.0,
        'node40': 1.0}
    assert cluster_dp.get_dram_hit_ratio() == expected_output
