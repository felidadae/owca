# Copyright (C) 2019 Intel Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions
# and limitations under the License.
#
#
# SPDX-License-Identifier: Apache-2.0

from requests import get
from time import time

import logging
import os
import pytest

_PROMETHEUS_QUERY_PATH = "/api/v1/query"
_PROMETHEUS_QUERY_RANGE_PATH = "/api/v1/query_range"
_PROMETHEUS_URL_TPL = '{prometheus}{path}?query={name}'
_PROMETHEUS_TIME_TPL = '&start={start}&end={end}&step=1s'
_PROMETHEUS_TAG_TPL = '{key}="{value}"'


def _build_prometheus_url(prometheus, name, tags=None, window_size=None, event_time=None):
    tags = tags or dict()
    path = _PROMETHEUS_QUERY_PATH
    time_range = ''

    # Some variables need to be overwritten for range queries.
    if window_size and event_time:
        offset = window_size / 2
        time_range = _PROMETHEUS_TIME_TPL.format(
            start=event_time - offset,
            end=event_time + offset)
        path = _PROMETHEUS_QUERY_RANGE_PATH

    url = _PROMETHEUS_URL_TPL.format(
        prometheus=prometheus,
        path=path,
        name=name,
    )

    # Prepare additional tags for query.
    query_tags = []
    for k, v in tags.items():
        query_tags.append(_PROMETHEUS_TAG_TPL.format(key=k, value=v))
    query_tags_str = ','.join(query_tags)

    # Build final URL from all the components.
    url = ''.join([url, "{", query_tags_str, "}", time_range])

    return url


def _fetch_metrics(url):
    response = get(url)
    response.raise_for_status()
    return response.json()


@pytest.mark.parametrize('workload_name', [
    'cassandra_stress',
    'stress_ng',
    'cassandra_ycsb',
    'specjbb',
    'twemcache_rpc_perf',
    'redis_rpc_perf',
    'twemcache_mutilate'
])
def test_wca_metrics(workload_name):
    test_wca(workload_name, ['sli', 'task_cycles'])


@pytest.mark.parametrize('workload_name', [
    'memcached-mutilate',
    'redis-memtier',
    'sysbench-memory',
    'stress'
])
def test_wca_metrics_kustomize(workload_name):
    test_wca(workload_name, ['apm__sli', 'task_cycles'])


def test_wca(workload_name, metrics):
    assert 'PROMETHEUS' in os.environ, 'prometheus host to connect'
    assert 'BUILD_NUMBER' in os.environ
    assert 'BUILD_COMMIT' in os.environ
    assert ('KUBERNETES_HOST' in os.environ) or ('MESOS_AGENT' in os.environ)

    prometheus = os.environ['PROMETHEUS']
    build_number = int(os.environ['BUILD_NUMBER'])
    build_commit = os.environ['BUILD_COMMIT']

    if os.environ.get('KUBERNETES_HOST'):
        env_uniq_id = os.environ['KUBERNETES_HOST'].split('.')[3]
    else:
        env_uniq_id = os.environ['MESOS_AGENT'].split('.')[3]

    tags = dict(build_number=build_number,
                build_commit=build_commit,
                workload_name=workload_name,
                env_uniq_id=env_uniq_id)

    logging.info('testing for: BUILD_NUMBER=%r, BUILD_COMMIT=%r, ENV_UNIQ_ID=%r',
                 build_number, build_commit, env_uniq_id)

    for metric in metrics:
        metric_query = _build_prometheus_url(prometheus, metric,
                                             tags, 1800, time())
        fetched_metric = _fetch_metrics(metric_query)
        assert len(fetched_metric['data']['result']) > 0, \
            'queried prometheus for {} metrics produced by workload ' \
            '{} and did not received any'.format(metric, workload_name)
