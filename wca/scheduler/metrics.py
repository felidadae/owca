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
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List

from wca.metrics import Metric, MetricType

log = logging.getLogger(__name__)

PREFIX = 'wca_scheduler_'


class MetricName(str, Enum):
    POD_IGNORE_FILTER = PREFIX + 'pod_ignore_filter'
    POD_IGNORE_PRIORITIZE = PREFIX + 'pod_ignore_prioritize'
    FILTER = PREFIX + 'filter'
    PRIORITIZE = PREFIX + 'prioritize'
    APP_REQUESTED_RESOURCE = PREFIX + 'app_requested_resource'
    NODE_CAPACITY_RESOURCE = PREFIX + 'node_capacity_resource'
    NODE_USED_RESOURCE = PREFIX + 'node_used_resource'
    NODE_FREE_RESOURCE = PREFIX + 'node_free_resource'
    NODE_DRAM_HIT_RATIO_CAN_SCHEDULE = PREFIX + 'node_dram_hit_ratio_can_schedule'
    FIT_PREDICTED_MEMBW_FLAT_USAGE = PREFIX + 'fit_predicted_membw_flat_usage'
    BAR_REQUESTED_FRACTION = PREFIX + 'bar_requested_fraction'
    BAR_LEAST_USED_SCORE = PREFIX + 'bar_least_used_score'
    BAR_MEAN = PREFIX + 'bar_mean'
    BAR_VARIANCE = PREFIX + 'bar_variance'
    BAR_SCORE = PREFIX + 'bar_score'
    BAR_RESULT = PREFIX + 'bar_result'

    def __repr__(self):
        return repr(self.value)


def check_metric_metadata(first: Metric, second: Metric):
    assert first.help == second.help, 'improper help for %r' % first.name
    assert first.unit == second.unit, 'improper unit for %r' % first.name
    assert first.type == second.type, 'improper type for %r' % first.name
    assert first.granularity == second.granularity, 'improper granularity for %r' % first.name


@dataclass
class MetricRegistry:
    """Store metrics in prometheus way"""
    _storage: Dict[MetricName, List[Metric]] = field(default_factory=lambda: {})

    def extend(self, metrics: List[Metric]):
        for metric in metrics:
            self.add(metric)

    def add(self, metric: Metric):
        # Check if metric is already in registry.
        if metric.name in self._storage:

            # Check if there is no same metric in registry.
            metric_already_here = False
            for registered_metric in self._storage[metric.name]:
                if registered_metric.labels == metric.labels:

                    # Check if metric have same metadata.
                    check_metric_metadata(registered_metric, metric)

                    metric_already_here = True
                    # Check metric type.
                    if metric.type == MetricType.GAUGE:
                        # Gauges should be overwritten.
                        registered_metric.value = metric.value
                    elif metric.type == MetricType.COUNTER:
                        # Counters should be incremented.
                        registered_metric.value += metric.value

            # If there is no same metric, add new one.
            if not metric_already_here:
                self._storage[metric.name].append(metric)

        # There is no this kind metrics.
        else:
            self._storage[metric.name] = [metric]

    def clean(self):
        self._storage = {}

    def as_dict(self) -> [str, float]:
        """  """
        d = {}
        for name, metrics in self._storage.items():
            for metric in metrics:
                d[name+repr(metric.labels)] = metric.value
        return d

    def get_names(self) -> List[str]:
        return list(set(map(lambda m: m, list(self._storage.keys()))))

    def prometheus_exposition(self) -> str:
        metrics = []

        for _, new_metrics in self._storage.items():
            metrics.extend(new_metrics)
        # Lazy import, because we do not want to import all storage module code including
        # libc and security.
        from wca.storage import (convert_to_prometheus_exposition_format,
                                 is_convertable_to_prometheus_exposition_format)
        if is_convertable_to_prometheus_exposition_format(metrics):
            prometheus_exposition = convert_to_prometheus_exposition_format(metrics)
            return prometheus_exposition
        else:
            log.warning('[Metrics] Cannot convert metrics '
                        'to prometheus exposition format!')
            return ""
