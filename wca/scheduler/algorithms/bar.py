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
from typing import Tuple, Dict, Any, Iterable

from wca.metrics import Metric, MetricType
from wca.logger import TRACE

from wca.scheduler.algorithms import used_resources_on_node, \
    calculate_read_write_ratio, substract_resources, divide_resources, sum_resources
from wca.scheduler.algorithms.fit import FitGeneric
from wca.scheduler.data_providers import DataProvider
from wca.scheduler.metrics import MetricName
from wca.scheduler.types import ResourceType as rt

log = logging.getLogger(__name__)


class BARGeneric(FitGeneric):
    def __init__(self, data_provider: DataProvider,
                 dimensions: Iterable[rt] = (rt.CPU, rt.MEM, rt.MEMBW_READ, rt.MEMBW_WRITE),
                 max_node_score: int = 1000,
                 least_used_weights: Dict[rt, float] = None,
                 bar_weights: Dict[rt, float] = None,
                 least_used_weight = 1,
                 alias=None
                 ):
        FitGeneric.__init__(self, data_provider, dimensions, alias=alias)
        if least_used_weights is None:
            self.least_used_weights = {dim: 1 for dim in self.dimensions}
            self.least_used_weights[rt.MEMBW_FLAT] = 1
        else:
            self.least_used_weights = least_used_weights
        self.max_node_score = max_node_score
        self.least_used_weight = least_used_weight
        self.bar_weights = bar_weights or {}


    def __str__(self):
        if self.alias:
            return super().__str__()
        return '%s(%d,luw=%.2f)' % (self.__class__.__name__, len(self.dimensions),
                                    self.least_used_weight)

    def priority_for_node(self, node_name: str, app_name: str,
                          data_provider_queried: Tuple[Any]) -> int:
        nodes_capacities, assigned_apps_counts, apps_spec = data_provider_queried

        used, free, requested = \
            used_free_requested(node_name, app_name, self.dimensions,
                                nodes_capacities, assigned_apps_counts, apps_spec)
        capacity = nodes_capacities[node_name]
        membw_read_write_ratio = calculate_read_write_ratio(capacity)

        # Metrics: resources: node_used, node_free and app_requested
        for resource in used:
            self.metrics.add(
                    Metric(name=MetricName.NODE_USED_RESOURCE,
                           value=used[resource],
                           labels=dict(node=node_name, resource=resource),
                           type=MetricType.GAUGE,))

        for resource in free:
            self.metrics.add(
                Metric(name=MetricName.NODE_FREE_RESOURCE,
                       value=free[resource],
                       labels=dict(node=node_name, resource=resource),
                       type=MetricType.GAUGE,))

        for resource in requested:
            self.metrics.add(
                Metric(name=MetricName.APP_REQUESTED_RESOURCE,
                       value=requested[resource],
                       labels=dict(resource=resource, app=app_name),
                       type=MetricType.GAUGE,))

        # ---
        # Least used.
        # ---

        # Requested fraction
        log.log(TRACE, "[Prioritize][app=%s][node=%s][least_used] Requested %s Free %s Used %s Capacity %s",
                app_name, node_name, dict(requested), free, used, nodes_capacities[node_name])
        requested_fraction = divide_resources(sum_resources(requested, used), capacity, membw_read_write_ratio)
        for resource, fraction in requested_fraction.items():
            self.metrics.add(
                    Metric(name=MetricName.BAR_REQUESTED_FRACTION,
                           value=fraction, labels=dict(app=app_name, resource=resource),
                           type=MetricType.GAUGE))
        log.log(TRACE, "[Prioritize][app=%s][node=%s][least_used] (requested+used) fraction ((requested+used)/capacity): %s",
                app_name, node_name, requested_fraction)

        weights = self.least_used_weights
        weights_sum = sum([weight for weight in weights.values()])
        free_fraction = {dim: 1.0-fraction for dim, fraction in requested_fraction.items()}
        log.log(TRACE, "[Prioritize][app=%s][node=%s][least_used] free fraction (after new scheduling new pod) (1-requested_fraction): %s",
                app_name, node_name, free_fraction)
        log.log(TRACE, "[Prioritize][app=%s][node=%s][least_used] free fraction linear sum: %s",
                app_name, node_name, sum(free_fraction.values()))
        least_used_score = \
            sum([free_fraction*weights[dim] for dim, free_fraction in free_fraction.items()]) \
            / weights_sum
        log.log(TRACE, "[Prioritize][app=%s][node=%s][least_used] Least used score (weighted linear sum of free_fraction): %s",
                app_name, node_name, least_used_score)
        self.metrics.add(
                Metric(name=MetricName.BAR_LEAST_USED_SCORE,
                       value=least_used_score, labels=dict(app=app_name, node=node_name),
                       type=MetricType.GAUGE))

        # ---
        # Bar
        # ---

        # Mean
        # priority according to variance of dimensions
        mean = sum([v for v in requested_fraction.values()])/len(requested_fraction)
        log.log(TRACE, "[Prioritize][app=%s][node=%s][bar] Mean: %s", app_name, node_name, mean)
        self.metrics.add(
            Metric(name=MetricName.BAR_MEAN,
                   value=mean, labels=dict(app=app_name, node=node_name),
                   type=MetricType.GAUGE))

        # Variance
        if len(requested_fraction) > 2:
            variance = sum([((fraction - mean)*(fraction - mean)) * self.bar_weights.get(rt, 1)
                            for rt, fraction in requested_fraction.items()]) \
                       / len(requested_fraction)
        elif len(requested_fraction) == 2:
            values = list(requested_fraction.values())
            variance = abs(values[0] - values[1])
        else:
            variance = 0
        log.log(TRACE, "[Prioritize][app=%s][node=%s][bar] Variance(weighted quadratic sum of requested_fraction-mean): %s", app_name, node_name, variance)
        self.metrics.add(
            Metric(name=MetricName.BAR_VARIANCE,
                   value=variance, labels=dict(app=app_name, node=node_name),
                   type=MetricType.GAUGE))

        bar_score = (1.0-variance)
        log.log(TRACE, "[Prioritize][app=%s][node=%s][bar] Bar score: %s", app_name, node_name, bar_score)
        self.metrics.add(
                Metric(name=MetricName.BAR_SCORE,
                       value=bar_score, labels=dict(app=app_name, node=node_name),
                       type=MetricType.GAUGE))

        # ---
        # Putting together Least-used and BAR.
        # ---

        scores_sum = least_used_score * self.least_used_weight + bar_score
        log.log(TRACE, "[Prioritize][app=%s][node=%s] scores_sum(least_used_weight=%s): %s", app_name, node_name, self.least_used_weight, scores_sum)

        result = int(scores_sum * self.max_node_score / 2.0)
        log.log(TRACE, "[Prioritize][app=%s][node=%s] Result(max_node_score=%s): %s", app_name, node_name, self.max_node_score, result)
        self.metrics.add(
                Metric(name=MetricName.BAR_RESULT,
                       value=result, labels=dict(app=app_name, node=node_name),
                       type=MetricType.GAUGE))

        return result


def used_free_requested(
        node_name, app_name, dimensions,
        nodes_capacities, assigned_apps_counts, apps_spec):
    """Helper function not making any new calculations."""
    membw_read_write_ratio = calculate_read_write_ratio(nodes_capacities[node_name])
    used = used_resources_on_node(dimensions, assigned_apps_counts[node_name], apps_spec)
    free = substract_resources(nodes_capacities[node_name], used, membw_read_write_ratio)
    requested = apps_spec[app_name]
    return used, free, requested


# from random import randint, seed
# from datetime import datetime
# seed(datetime.now())
# return randint(1, 100)
