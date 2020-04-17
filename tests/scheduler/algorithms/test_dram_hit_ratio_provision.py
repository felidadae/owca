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

import pytest

from wca.metrics import Metric, MetricType
from wca.scheduler.algorithms.base import DEFAULT_DIMENSIONS
from tests.scheduler.data_providers.test_cluster_data_provider import (
    get_mocked_cluster_data_provider)
from wca.scheduler.algorithms.dram_hit_ratio_provision import DramHitRatioProvision
from wca.scheduler.metrics import MetricName


@pytest.mark.parametrize('node_name, app_name, expected_output', [
    ('node101', '', (False, 'Could not fit node because of dram hit ratio violation.')),
    ('node37', '', (True, ''))
])
def test_app_fit_node(node_name, app_name, expected_output):
    algorithm = DramHitRatioProvision(data_provider=get_mocked_cluster_data_provider(),
                                      dimensions=DEFAULT_DIMENSIONS,
                                      threshold=0.995)
    assert algorithm.app_fit_node(node_name, app_name, None) == expected_output
    assert algorithm.metrics._storage[MetricName.NODE_DRAM_HIT_RATIO_CAN_SCHEDULE] == \
        [Metric(name=MetricName.NODE_DRAM_HIT_RATIO_CAN_SCHEDULE,
                value=int(expected_output[0]),
                labels=dict(node=node_name),
                type=MetricType.GAUGE)]
