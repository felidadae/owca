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
from unittest.mock import patch, Mock, call
from io import StringIO

from wca.metrics import Metric
from wca.storage import FailedDeliveryException
from wrapper.parser import (default_parse, kafka_store_with_retry,
                            DEFAULT_REGEXP, MAX_ATTEMPTS, readline_with_check)


@pytest.mark.parametrize("input,separator,expected", [
    (StringIO("x=4 y=5 \n"
              "x=2 y=6"), None,
     [Metric("mp_x", 4.0), Metric("mp_y", 5.0)]),
    (StringIO("x=4 y=5 \n"
              "z=2 w=6 \n"
              "---"), "---",
     [Metric("mp_x", 4.0), Metric("mp_y", 5.0),
      Metric("mp_z", 2.0), Metric("mp_w", 6.0)]),
    (StringIO("Metrics: x=4.5 y=5.4 \n"
              "z=1.337,w=6.66 \n"
              "---"), "---",
     [Metric("mp_x", 4.5),
      Metric("mp_y", 5.4),
      Metric("mp_z", 1.337),
      Metric("mp_w", 6.66)]),
])
def test_default_parse(input, separator, expected):
    assert default_parse(input, DEFAULT_REGEXP, separator, metric_name_prefix='mp_') == expected


def test_default_parse_no_source_no_separator():
    with pytest.raises(StopIteration):
        default_parse(input=StringIO(''), regexp=DEFAULT_REGEXP, separator=None)


def test_default_parse_no_source_separator():
    with pytest.raises(StopIteration):
        default_parse(input=StringIO("x=4 y=5 \n"
                                     "z=2 w=5\n"
                                     # last line is an empty string, which should raise the
                                     # exception
                                     ""), regexp=DEFAULT_REGEXP, separator="---")


def test_readline_with_check():
    with pytest.raises(StopIteration):
        readline_with_check(input=StringIO(""))
    line = "content_of_line"
    assert line == readline_with_check(input=StringIO(line))


@patch('time.sleep')
def test_kafka_store_with_retry_failure(sleep_mock):
    kafka_mock = Mock()
    kafka_mock.store = Mock(side_effect=[FailedDeliveryException] * MAX_ATTEMPTS)
    with pytest.raises(FailedDeliveryException):
        kafka_store_with_retry(kafka_mock, Mock())
    sleep_mock.assert_has_calls([call(1), call(2), call(4), call(8)])


@patch('time.sleep')
def test_kafka_store_with_retry_success(sleep_mock):
    kafka_mock = Mock()
    kafka_mock.store = Mock(
        side_effect=[FailedDeliveryException, FailedDeliveryException, Mock()])
    kafka_store_with_retry(kafka_mock, Mock())
    sleep_mock.assert_has_calls([call(1), call(2)])
    # No other assert can be made, test should not throw an exception
