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

from unittest.mock import patch, call, mock_open

import pytest

from wca.metrics import Metric
from tests.testing import create_open_mock, _is_dict_match, assert_metric, assert_subdict


def test_create_open_mock_autocreated():
    with patch('builtins.open', create_open_mock({
        '/some/path.txt': 'foo',
    })) as mocks:
        assert open('/some/path.txt').read() == 'foo'
        open('/some/path.txt', 'w').write('bar')
        mocks['/some/path.txt'].assert_has_calls(
            [call().write('bar')])


def test_create_open_mock_manually():
    my_own_mock_open = mock_open(read_data='foo')
    with patch('builtins.open', create_open_mock({
        '/some/path.txt': my_own_mock_open
    })):
        assert open('/some/path.txt').read() == 'foo'
        open('/some/path.txt', 'w').write('bar')
        my_own_mock_open.assert_has_calls(
            [call().write('bar')])


@pytest.mark.parametrize('got_dict, expected_subdict, expected_match', [
    (dict(), dict(), True),  # Empty query always match
    (dict(x=1), dict(), True),  # ditto,
    (dict(), dict(x=1), False),  # Non empty query doesn't match empty dict,
    (dict(x=2), dict(x=1), False),  # no when value is different
    (dict(x=1), dict(x=1), True),  # ok for the same
    (dict(x=1, y=2), dict(x=1), True),  # additional parameters doesn't interfere
    (dict(x=1, y=2), dict(x=1, y=2), True),  # two params exact match
    (dict(x=1, y=1, z=3), dict(x=1, y=2), False),  # two keys mismatch
    (dict(x=1, y=2, z=3), dict(x=1, y=2), True),  # two vs three keys match
])
def test_is_dict_match(got_dict, expected_subdict, expected_match):
    assert _is_dict_match(got_dict, expected_subdict) == expected_match


@pytest.mark.parametrize(
    'got_metrics, expected_metric_name, '
    'expected_metric_labels, expected_metric_value, exception_message', [
        ([Metric('foo', 2)], 'foo', None, None, None),
        ([Metric('foo', 2)], 'foo', None, 2, None),
        ([Metric('foo', 2)],
         'foo', None, 3, r"metric name='foo' value differs got=2 expected=3"),
        ([Metric('foo', 2)], 'foo', dict(), 2, None),
        ([Metric('foo', 2, labels=dict(a='b'))],
         'foo', None, 3, r"metric name='foo' value differs got=2 expected=3"),
        ([Metric('foo', 2, labels=dict(a='b'))], 'foo', None, 2, None),
        ([Metric('foo', 2, labels=dict(a='b'))], 'foo', dict(), 2, None),
        ([Metric('foo', 2, labels=dict(a='b'))], 'foo', dict(a='b'), 2, None),
        ([Metric('foo', 2, labels=dict(a='b'))], 'foo', dict(a='c'), 2, 'not found'),
    ])
def test_assert_metric(got_metrics, expected_metric_name,
                       expected_metric_labels, expected_metric_value, exception_message):
    if exception_message is not None:
        with pytest.raises(AssertionError, match=exception_message):
            assert_metric(got_metrics, expected_metric_name,
                          expected_metric_labels, expected_metric_value)
    else:
        assert_metric(got_metrics, expected_metric_name,
                      expected_metric_labels, expected_metric_value)


@pytest.mark.parametrize(
    'got_dict, expected_subdict, exception_message', [
        # proper empty or simple dicts
        (dict(), dict(), None),
        (dict(x=1), dict(), None),
        (dict(x=1), dict(), None),
        (dict(x=1, y=1), dict(x=1), None),
        # invalid flat dicts
        (dict(x=1, y=1), dict(x=1, z=2), "key 'z' not found"),
        (dict(x=1, y=1), dict(x=1, y=2), r"value differs got=1 expected=2 at key='y'"),
        # proper nested dicts
        (dict(x=1, y=dict(z=1)), dict(x=1), None),
        (dict(x=1, y=dict(z=1)), dict(x=1, y=dict()), None),
        (dict(x=1, y=dict(z=1)), dict(x=1, y=dict(z=1)), None),
        (dict(x=1, y=dict(z=1)), dict(y=dict(z=1)), None),
        # some deep value differs
        (dict(x=1, y=dict(z=1)), dict(
            x=1, y=dict(z=2)), r"value differs got=1 expected=2 at key='z'"),
        (dict(x=1, y=dict(z=1)), dict(y=dict(not_existient_key=2)), "not found"),
    ])
def test_assert_subdict(got_dict, expected_subdict, exception_message):
    if exception_message is not None:
        with pytest.raises(AssertionError, match=exception_message):
            assert_subdict(got_dict, expected_subdict)
    else:
        assert_subdict(got_dict, expected_subdict)
