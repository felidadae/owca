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

from wca.detectors import convert_anomalies_to_metrics
from tests.testing import anomaly, anomaly_metrics


@pytest.mark.parametrize('anomalies,tasks_labels,expected_metrics', (
    ([], {}, []),
    (
        [anomaly('t1', ['t2'])],
        {'t1': {'workload_instance': 't1_workload_instance'},
         't2': {'workload_instance': 't2_workload_instance'}},
        anomaly_metrics('t1', ['t2'],
                        {'t1': 't1_workload_instance', 't2': 't2_workload_instance'})),
    (
        [anomaly('t2', ['t1', 't3'])],
        {'t1': {'workload_instance': 't1_workload_instance'},
         't2': {'workload_instance': 't2_workload_instance'},
         't3': {'workload_instance': 't3_workload_instance'}},
        anomaly_metrics('t2', ['t1', 't3'],
                        {'t1': 't1_workload_instance', 't2': 't2_workload_instance',
                         't3': 't3_workload_instance'})
    ),
))
def test_convert_anomalies_to_metrics(anomalies, tasks_labels, expected_metrics):
    metrics_got = convert_anomalies_to_metrics(anomalies, tasks_labels)
    assert metrics_got == expected_metrics
