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
from copy import deepcopy
from typing import Tuple, List

from wca.metrics import Metric
from wca.scheduler.algorithms import DataMissingException, RescheduleResult
from wca.scheduler.algorithms.base import (
    BaseAlgorithm, sum_resources, used_free_requested,
    QueryDataProviderInfo, enough_resources_on_node, DEFAULT_DIMENSIONS)
from wca.scheduler.data_providers import DataProvider
from wca.scheduler.types import ResourceType

log = logging.getLogger(__name__)


def app_fits(node_name, app_name, dimensions, nodes_capacities,
             assigned_apps, apps_spec) -> Tuple[bool, str, List[Metric]]:
    # Current node context: used and free currently
    used, free, requested, capacity, membw_read_write_ratio, metrics = \
        used_free_requested(node_name, app_name, dimensions,
                            nodes_capacities, assigned_apps, apps_spec)
    metrics.extend(metrics)

    # SUBTRACT: "free" after simulated assignment of requested
    try:
        requested_and_used = sum_resources(requested, used)
    except ValueError as e:
        msg = 'cannot sum app=%s requested=%s and node=%s used=%s: %s' % (
            app_name, requested, node_name, used, e)
        log.error(msg)
        raise DataMissingException(msg) from e

    fits, broken_capacities, free = enough_resources_on_node(
        capacity, requested_and_used, membw_read_write_ratio)
    if fits:
        log.debug('[Filter][app=%s][node=%s] ok free_after_bind=%r',
                  app_name, node_name, free)
        message = ''
    else:
        broken_capacities_str = \
            ','.join(['({}: {})'.format(r, v) for r, v in broken_capacities.items()])
        log.debug('[Filter][app=%s][node=%s] broken capacities: missing %r',
                  app_name, node_name, broken_capacities_str)
        message = 'Could not fit node for dimensions: missing {}.'.format(
            broken_capacities_str)

    return fits, message, metrics


class Fit(BaseAlgorithm):
    """Filter all nodes where the scheduled app does not fit.
       Supporting any number of dimensions.
       Treats MEMBW_READ and MEMBW_WRITE differently than other dimensions."""

    def __init__(self, data_provider: DataProvider,
                 dimensions: List[ResourceType] = DEFAULT_DIMENSIONS,
                 max_node_score: float = 10.0,
                 alias: str = None,
                 cpu_scale_factor: float = 1.0):
        BaseAlgorithm.__init__(self, data_provider, dimensions, max_node_score, alias)
        self.cpu_scale_factor = cpu_scale_factor
        self.pmem_nodes = self.data_provider.get_pmem_nodes()

    def app_fit_node(self, node_name, app_name, data_provider_queried) -> Tuple[bool, str]:
        nodes_capacities, assigned_apps, apps_spec, _ = data_provider_queried

        # Scaling factor for cpu
        new_nodes_capacities = deepcopy(nodes_capacities)
        for node in nodes_capacities:
            if node in self.pmem_nodes:
                new_nodes_capacities[node][ResourceType.CPU] = \
                    nodes_capacities[node][ResourceType.CPU] * self.cpu_scale_factor

        fits, message, metrics = app_fits(
            node_name, app_name, self.dimensions,
            new_nodes_capacities, assigned_apps, apps_spec)
        self.metrics.extend(metrics)
        return fits, message

    def priority_for_node(self, node_name: str, app_name: str,
                          data_provider_queried: Tuple) -> float:
        """no prioritization method for FitGeneric"""
        return 0.0

    def reschedule_with_metrics(self, data_provider_queried: QueryDataProviderInfo,
                                ) -> Tuple[RescheduleResult, List[Metric]]:
        return {}, []
