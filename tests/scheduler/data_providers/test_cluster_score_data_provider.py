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

from tests.testing import create_json_fixture_mock
from tests.scheduler.data_providers.test_cluster_data_provider import (
        do_query_side_effect as do_query_side_effect_cluster_dp,
        request_kubeapi_side_effect)

from wca.scheduler.data_providers.score.cluster import ClusterScoreDataProvider
from wca.scheduler.kubeapi import Kubeapi
from wca.scheduler.prometheus import Prometheus


def get_mocked_cluster_data_provider():
    mocked_kubeapi = MagicMock(spec=Kubeapi)
    mocked_kubeapi.monitored_namespaces = ['default']
    mocked_kubeapi.request_kubeapi.side_effect = request_kubeapi_side_effect

    mocked_prometheus = Mock(spec=Prometheus)
    mocked_prometheus.do_query.side_effect = do_query_side_effect

    cluster_dp = ClusterScoreDataProvider(
            kubeapi=mocked_kubeapi,
            prometheus=mocked_prometheus)

    return cluster_dp


def do_query_side_effect(*args, **kwargs):
    if args[0] == ClusterScoreDataProvider.app_profiles_query:
        return create_json_fixture_mock('prometheus_app_profile').json()['data']['result']
    elif args[0] == ClusterScoreDataProvider.node_type_query:
        return create_json_fixture_mock('prometheus_node_type').json()['data']['result']
    else:
        return do_query_side_effect_cluster_dp(*args)


APPS_PROFILE = {
        'memcached-mutilate-big': -0.15827586206896552,
        'memcached-mutilate-big-wss': -1.2382758620689656,
        'memcached-mutilate-medium': -0.6069458128078817,
        'memcached-mutilate-small': -0.4119297494110088,
        'mysql-hammerdb-small': -0.16182266009852214,
        'redis-memtier-big': -0.5262368815592204,
        'redis-memtier-big-wss': -1.532769329620904,
        'redis-memtier-medium': -0.5187192118226601,
        'redis-memtier-small': -0.5261083743842364,
        'specjbb-preset-big-120': -1.1172413793103446,
        'specjbb-preset-medium': -1.7359605911330047,
        'specjbb-preset-small': -1.2834975369458126,
        'stress-stream-big': -11.66708609980724,
        'stress-stream-medium': -11.55591133004926,
        'stress-stream-small': -8.531109445277362,
        'sysbench-memory-big': -10.901103019918613,
        'sysbench-memory-medium': -16.144356393231956,
        'sysbench-memory-small': -16.412615121010923
}


def test_get_app_profiles(expected_apps_profile=APPS_PROFILE):
    dp = get_mocked_cluster_data_provider()
    assert dp.get_apps_profile() == expected_apps_profile


NODE_TYPES = {
        'node101': 'pmem',
        'node102': 'dram',
        'node103': 'dram',
        'node104': 'dram',
        'node105': 'dram',
        'node200': 'dram',
        'node201': 'dram',
        'node202': 'dram',
        'node203': 'dram',
        'node37': 'dram',
        'node38': 'dram',
        'node39': 'dram',
        'node40': 'dram'
}


def test_get_nodes_profiles():
    dp = get_mocked_cluster_data_provider()
    assert dp.get_nodes_type() == NODE_TYPES
