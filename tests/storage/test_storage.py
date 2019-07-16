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


import pytest
from unittest import mock

from wca.metrics import Metric, MetricType
import wca.storage as storage


@pytest.fixture
def sample_metrics():
    return [
        Metric(name='average_latency_miliseconds', value=8,
               labels={'user': 'felidadae', 'node': 'slave_1'},
               type=MetricType.COUNTER, help='latency measured in miliseconds'),
        Metric(name='percentile_99th_miliseconds', value=89,
               labels={'user': 'felidadae', 'node': 'slave_1'},
               type=MetricType.COUNTER, help='99th percentile in miliseconds')
    ]


@pytest.fixture
def sample_metrics_with_quote():
    """for testing for proper escaping"""
    return [
        Metric(name='average_latency_miliseconds', value=8,
               labels={'user': 'felidadae', 'node': 'slave_1 called "brave heart"'},  # quoted
               type=MetricType.COUNTER, help='latency measured in miliseconds'),
    ]


@pytest.fixture
def sample_metrics_with_float_value():
    """for testing for proper float representation"""
    return [
        Metric(name='average_latency_miliseconds', value=8.223,
               labels={'user': 'felidadae', 'node': 'slave_1'},
               type=MetricType.COUNTER, help='latency measured in miliseconds'),
    ]


# PEC <- prometheus exposition format
@pytest.fixture
def sample_metrics_unconvertable_to_PEF():
    """for testing for proper float representation"""
    return [
        Metric(name='latency-miliseconds', value=8.223,
               labels={'user': 'felidadae', 'node': 'slave_1'},
               type=MetricType.COUNTER, help='latency measured in miliseconds'),
    ]


@mock.patch('time.time', return_value=1531729598.001)
def test_convert_to_prometheus_exposition_format(mock_get_current_time, sample_metrics,
                                                 sample_metrics_with_quote,
                                                 sample_metrics_with_float_value):
    timestamp = storage.get_current_time()
    msg = storage.convert_to_prometheus_exposition_format(sample_metrics, timestamp)
    assert(
        msg == (
            '# HELP average_latency_miliseconds latency measured in miliseconds\n'
            '# TYPE average_latency_miliseconds counter\n'
            'average_latency_miliseconds{node="slave_1",user="felidadae"} 8 1531729598001\n'
            '\n'
            '# HELP percentile_99th_miliseconds 99th percentile in miliseconds\n'
            '# TYPE percentile_99th_miliseconds counter\n'
            'percentile_99th_miliseconds{node="slave_1",user="felidadae"} 89 1531729598001\n'
            '\n'
        )
    )

    msg = storage.convert_to_prometheus_exposition_format(sample_metrics_with_quote, timestamp)
    assert(
        msg == (
            '# HELP average_latency_miliseconds latency measured in miliseconds\n'
            '# TYPE average_latency_miliseconds counter\n'
            'average_latency_miliseconds'  # next string the same line
            '{node="slave_1 called \\"brave heart\\"",user="felidadae"} 8 1531729598001\n'
            '\n'
        )
    )

    msg = storage.convert_to_prometheus_exposition_format(sample_metrics_with_quote)
    assert(
        msg == (
            '# HELP average_latency_miliseconds latency measured in miliseconds\n'
            '# TYPE average_latency_miliseconds counter\n'
            'average_latency_miliseconds'  # next string the same line
            '{node="slave_1 called \\"brave heart\\"",user="felidadae"} 8\n'
            '\n'
        )
    )

    msg = storage.convert_to_prometheus_exposition_format(sample_metrics_with_float_value,
                                                          timestamp)
    assert(
        msg == (
            '# HELP average_latency_miliseconds latency measured in miliseconds\n'
            '# TYPE average_latency_miliseconds counter\n'
            'average_latency_miliseconds'  # next string the same line
            '{node="slave_1",user="felidadae"} 8.223 1531729598001\n'
            '\n'
        )
    )


@mock.patch('wca.storage.check_kafka_dependency', return_value=None)
@mock.patch('wca.storage.create_kafka_consumer',
            return_value=mock.Mock(flush=mock.Mock(return_value=1)))
def test_when_brocker_unavailable(mock_fun, mock_producer, sample_metrics):
    kafka_storage = storage.KafkaStorage(brokers_ips=["whatever because is ignored"], topic='some')
    with pytest.raises(storage.FailedDeliveryException, match="Maximum timeout"):
        kafka_storage.store(sample_metrics)
    kafka_storage.producer.flush.assert_called_once()


def test_is_convertable_to_prometheus_exposition_format(
        sample_metrics,
        sample_metrics_with_float_value,
        sample_metrics_unconvertable_to_PEF):
    metric_nPEF = sample_metrics_unconvertable_to_PEF
    is_convertable = storage.is_convertable_to_prometheus_exposition_format

    assert (True, "") == is_convertable(sample_metrics)
    assert (True, "") == is_convertable(sample_metrics_with_float_value)
    assert (False, "Wrong metric name latency-miliseconds.") == is_convertable(metric_nPEF)


@pytest.fixture
def sample_metrics_mixed():
    return [
        Metric(name='bar', value=89, type=None, help='bar-help'),
        Metric(name='foo', value=1, labels=dict(a='3'),
               type=MetricType.COUNTER, help='foo-help'),
        Metric(name='foo', value=1, labels=dict(a='20'),
               type=MetricType.COUNTER, help='foo-help'),
        Metric(name='foo', value=1, labels=dict(a='1'),
               type=MetricType.COUNTER, help='foo-help'),
        Metric(name='bar2', value=89),
    ]


def test_grouping_metrics_by_metadata(sample_metrics_mixed):

    got_grouped = storage.group_metrics_by_name(sample_metrics_mixed)

    expected_grouped = [
        ('bar', [
            Metric(name='bar', value=89, type=None, help='bar-help'),
        ]),
        ('bar2', [
            Metric(name='bar2', value=89),
        ]),
        ('foo', [
            Metric(name='foo', value=1, labels=dict(a='1'),
                   type=MetricType.COUNTER, help='foo-help'),
            Metric(name='foo', value=1, labels=dict(a='3'),
                   type=MetricType.COUNTER, help='foo-help'),
            Metric(name='foo', value=1, labels=dict(a='20'),
                   type=MetricType.COUNTER, help='foo-help'),
        ]),
    ]

    assert got_grouped == expected_grouped


@mock.patch('wca.storage.get_current_time', return_value='1531729598000')
def test_convert_to_prometheus_exposition_format_grouped_case(
        mock_get_current_time, sample_metrics_mixed
):
    msg = storage.convert_to_prometheus_exposition_format(sample_metrics_mixed,
                                                          storage.get_current_time())
    assert msg == '''# HELP bar bar-help
bar 89 1531729598000

bar2 89 1531729598000

# HELP foo foo-help
# TYPE foo counter
foo{a="1"} 1 1531729598000
foo{a="3"} 1 1531729598000
foo{a="20"} 1 1531729598000

'''
