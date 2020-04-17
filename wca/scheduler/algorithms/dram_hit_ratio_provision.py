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

import logging
from typing import Tuple, List

from wca.scheduler.data_providers import DataProvider
from wca.metrics import Metric, MetricType
from wca.scheduler.algorithms.base import BaseAlgorithm, QueryDataProviderInfo
from wca.scheduler.metrics import MetricName
from wca.scheduler.types import NodeName
from wca.scheduler.types import ResourceType

log = logging.getLogger(__name__)


class DramHitRatioProvision(BaseAlgorithm):
    """Determines whether dram hit ratio had been violated on given node"""

    def __init__(self, data_provider: DataProvider,
                 dimensions: List[ResourceType],
                 max_node_score: float = 10.,
                 alias: str = None,
                 threshold: float = 0.97):
        BaseAlgorithm.__init__(self, data_provider=data_provider, dimensions=dimensions,
                               alias=alias, max_node_score=max_node_score)
        self.threshold = threshold

    def app_fit_node(self, node_name: NodeName, app_name: str,
                     data_provider_queried: QueryDataProviderInfo) -> Tuple[bool, str]:
        metrics = []

        dram_hit_ratio = self.data_provider.get_dram_hit_ratio()
        ratio_below_threshold = float(dram_hit_ratio[node_name]) < self.threshold

        metrics.append(
            Metric(name=MetricName.NODE_DRAM_HIT_RATIO_CAN_SCHEDULE,
                   value=int(not ratio_below_threshold),
                   labels=dict(node=node_name),
                   type=MetricType.GAUGE))
        self.metrics.extend(metrics)

        if not ratio_below_threshold:
            log.debug('[Filter][app=%s][node=%s] ok', app_name, node_name)
            return True, ''
        else:
            return False, 'Could not fit node because of dram hit ratio violation.'

    def priority_for_node(self, node_name: str, app_name: str,
                          data_provider_queried: QueryDataProviderInfo) -> float:
        """no prioritization method for DramHitRatioProvision"""
        return 0.0
