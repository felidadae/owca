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
from unittest.mock import patch

from wca import profiling
from tests.testing import assert_metric


def test_profiler():
    counter = 0

    def time_side_effect():
        nonlocal counter
        counter += 2  # every call takes 2 seconds
        return counter

    profiler = profiling.Profiler()

    def some_function():
        pass

    some_function = profiler.profile_duration(name='new_name')(some_function)

    metrics = profiler.get_metrics()
    # There are no metrics before call function
    assert metrics == []

    with patch('time.time', side_effect=time_side_effect):
        for _ in range(5):
            some_function()

    # Two different calls with different times - average should be 2.
    profiler.register_duration('other_function', 1)
    profiler.register_duration('other_function', 3)

    metrics = profiler.get_metrics()

    assert_metric(metrics, 'wca_duration_seconds', {'function': 'new_name'},
                  expected_metric_value=2.)
    assert_metric(metrics, 'wca_duration_seconds_avg', {'function': 'new_name'},
                  expected_metric_value=2.)

    assert_metric(metrics, 'wca_duration_seconds', {'function': 'other_function'},
                  expected_metric_value=3.)
    assert_metric(metrics, 'wca_duration_seconds_avg', {'function': 'other_function'},
                  expected_metric_value=2.)
