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


from itertools import chain

import pytest
from operator import truediv, add, sub

from wca.mesos import create_metrics, sanitize_label
from wca.metrics import (Metric, merge_measurements, MetricName,
                         METRICS_METADATA, MetricGranurality,
                         export_metrics_from_measurements, MetricMetadata,
                         MetricType, MetricUnit, MetricSource,
                         _list_leveled_metrics,
                         _operation_on_leveled_metric,
                         _operation_on_leveled_dicts)


@pytest.mark.parametrize('label_key,expected_label_key', (
        ('org.apache.ble', 'ble'),
        ('org.apache.aurora.metadata.foo', 'foo'),
        ('some.dots.found', 'some_dots_found'),
))
def test_sanitize_labels(label_key, expected_label_key):
    assert sanitize_label(label_key) == expected_label_key


@pytest.mark.parametrize('task_measurements,expected_metrics', (
        ({}, []),
        ({'cpu': 15},
         [Metric(name='cpu', value=15)]),
        ({'cpu': 15, 'ram': 30},
         [
             Metric(name='cpu', value=15),
             Metric(name='ram', value=30)
         ]),
))
def test_create_metrics(task_measurements, expected_metrics):
    got_metrics = create_metrics(task_measurements)
    assert expected_metrics == got_metrics


@pytest.mark.parametrize('measurements_list,expected_merge', (
        ([{}, {}], {}),
        ([{'m1': 3}, {'m1': 5}, {'m2': 7}], {'m1': 8, 'm2': 7}),
        ([{'m1': 8}, {'m1': 3, 'm2': 2}], {'m1': 11, 'm2': 2}),
        ([{'m1': 8}, {'m1': 3}], {'m1': 11}),
        ([{'m1': 8, 'm2': 3}, {'m1': 3, 'm2': 7}, {'m1': 3}], {'m1': 14, 'm2': 10}),
        ([{'ipc': 2}, {'ipc': 4}], {'ipc': 6}),
        ([{'ipc': 2}, {'ipc': 4}, {'m1': 2}, {'m1': 3}], {'ipc': 6, 'm1': 5}),
        ([{'task_cycles': {0: 2, 1: 5}}, {'task_cycles': {0: 4, 1: 7}}],
         {'task_cycles': {0: 6, 1: 12}}),
        ([{'task_cycles': {0: 2, 1: 5}}, {'task_cycles': {0: 4, 1: 7}}, {'m1': 8}],
         {'task_cycles': {0: 6, 1: 12}, 'm1': 8})
))
def test_merge_measurements(measurements_list, expected_merge):
    assert merge_measurements(measurements_list) == expected_merge


def test_metric_meta_exists():
    for metric_name in chain(MetricName):
        assert metric_name in METRICS_METADATA, 'missing metadata for metric %s' % metric_name


@pytest.mark.parametrize(
    'measurements, expected', [
        ({MetricName.TASK_MEM_NUMA_PAGES: {'1': 10, '2': 20}, }, 2),
        ({MetricName.TASK_CYCLES: {0: 1123}}, 1),
        ({}, 0)
    ])
def test_export_metrics_from_measurements(measurements, expected):
    result = export_metrics_from_measurements(measurements)
    assert len(result) == expected


class TestMetric(object):
    """To create and delete a test metric from metrics module structures."""

    def __enter__(self):
        MetricName.TEST_METRIC = 'test_metric'
        METRICS_METADATA['test_metric'] = MetricMetadata('Non existing metric for unit test.',
                                                         MetricType.COUNTER,
                                                         MetricUnit.NUMERIC,
                                                         MetricSource.GENERIC,
                                                         MetricGranurality.PLATFORM,
                                                         levels=['numa_node', 'container'],
                                                         enabled='no'
                                                         )

    def __exit__(self, type, value, traceback):
        """if exception was raised the metrics structeres will be cleaned up."""
        del METRICS_METADATA['test_metric']
        del MetricName.TEST_METRIC


def test_export_metrics_from_measurements_artifical_metric():
    """We currently do not have a metric which len(METRICS_METADATA[X].levels) > 1,
        so the need to add such metric in metrics structures for the test."""
    with TestMetric():
        measurements = {'test_metric': {'id0': {'stress': 0, 'dbmango': 1},
                                        'id1': {'stress': 10, 'dbmango': 20}}}
        result = export_metrics_from_measurements(measurements)
        assert len(result) == 4
        assert result[0].name == 'test_metric'
        assert 'numa_node' in result[0].labels and 'container' in result[0].labels
        assert sorted([item.value for item in result]) == [0, 1, 10, 20]  # values for metrics


@pytest.mark.parametrize(
    'aggregated_metric, new_metric, max_depth, expected', [
        # aggregated is empty, just put 20 into list
        ({},
         {0: 10},
         1,
         {0: [10]}),
        #  aggregated has 3 elements for key 0 and 20 and 2 and 3 will be added,
        ({0: {10: [100, 200, 300]}, 1: {20: [400, 500, 600]}},
         {0: {10: 400}, 1: {20: 700}},
         2,
         {0: {10: [100, 200, 300, 400]}, 1: {20: [400, 500, 600, 700]}}),
        # 3 levels
        ({0: {1: {2: [10, 20]}}},
         {0: {1: {2: 30}}},
         3,
         {0: {1: {2: [10, 20, 30]}}}),
    ])
def test_list_leveled_metrics(aggregated_metric, new_metric, max_depth, expected):
    _list_leveled_metrics(aggregated_metric, new_metric, max_depth) == expected
    assert aggregated_metric == expected


@pytest.mark.parametrize(
    'aggregated_metric, operation, max_depth, expected', [
        # 2 levels
        ({0: {10: [20, 5, 8, 2]}, 1: {20: [1, 2, 4, 3]}},
         sum,
         2,
         {0: {10: 35}, 1: {20: 10}}),
        # 3 levels
        ({0: {1: {2: [10, 20, 30]}}},
         sum,
         3,
         {0: {1: {2: 60}}})
    ])
def test_operation_on_leveled_metric(aggregated_metric, operation, max_depth, expected):
    _operation_on_leveled_metric(aggregated_metric, operation, max_depth)
    assert aggregated_metric == expected


@pytest.mark.parametrize(
    'a, b, operation, max_depth, expected', [
        # 2 levels + div
        ({0: {10: 200, 20: 120}},
         {0: {10: 2, 20: 2}},
         truediv,
         2,
         {0: {10: 100, 20: 60}}),
        # 2 levels and add
        ({0: {10: 200, 20: 120}},
         {0: {10: 2, 20: 2}},
         add,
         2,
         {0: {10: 202, 20: 122}}),
        # 2 levels and sub
        ({0: {10: 150}, 20: {10: 250}},
         {0: {10: 10}, 20: {10: 10}},
         sub,
         2,
         {0: {10: 140}, 20: {10: 240}}),
        # 1 level and div (divided by zero) - no results
        ({18: 0},
         {18: 0},
         truediv,
         1,
         {}
         )
    ])
def test_operation_on_leveled_dicts(a, b, operation, max_depth, expected):
    assert _operation_on_leveled_dicts(a, b, operation, max_depth) == expected
