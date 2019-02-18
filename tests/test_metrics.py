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

from owca.mesos import create_metrics, sanitize_mesos_label
from owca.metrics import Metric, sum_measurements


@pytest.mark.parametrize('label_key,expected_label_key', (
    ('org.apache.ble', 'ble'),
    ('org.apache.aurora.metadata.foo', 'foo'),
    ('some.dots.found', 'some_dots_found'),
))
def test_sanitize_labels(label_key, expected_label_key):
    assert sanitize_mesos_label(label_key) == expected_label_key


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

@pytest.mark.parametrize('measurements_list,expected_sum,expected_ignored', (
    ([{'m1': 8}, {'m1': 3}], {'m1': 11}, []),
    ([{'m1': 8}, {'m1': 3, 'm2': 2}], {'m1': 11}, ['m2']),
    ([{'m1': 8}, {'m1': 3}, {'m1': 3}], {'m1': 14}, []),
    ([{'m1': 8, 'm2': 3}, {'m1': 3, 'm2': 7}, {'m1': 3}], {'m1': 14}, ['m2']),
))
def test_sum_measurements(measurements_list, expected_sum, expected_ignored):
    assert sum_measurements(measurements_list) == (expected_sum, expected_ignored)