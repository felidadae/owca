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


from io import TextIOWrapper
import logging
from typing import List, Dict
import re

from wca.metrics import Metric, MetricType
from wrapper import wrapper_main
from wrapper.parser import readline_with_check

log = logging.getLogger(__name__)


def parse(input: TextIOWrapper, regexp: str, separator: str = None,
          labels: Dict[str, str] = {}, metric_name_prefix: str = '') -> List[Metric]:
    """Custom parse function for rpc-perf.
        2018-09-13 08:15:43.404 INFO  [rpc-perf] -----
        2018-09-13 08:15:43.404 INFO  [rpc-perf] Window: 155
        2018-09-13 08:15:43.404 INFO  [rpc-perf] Connections: Ok: 0 Error: 0 Timeout: 0 Open: 80
        2018-09-13 08:15:43.404 INFO  [rpc-perf] Sockets: Create: 0 Close: 0 Read: 31601 Write:
        15795 Flush: 0
        2018-09-13 08:15:43.404 INFO  [rpc-perf] Requests: Sent: 15795 Prepared: 16384 In-Flight: 40
        2018-09-13 08:15:43.404 INFO  [rpc-perf] Responses: Ok: 15793 Error: 0 Timeout: 0 Hit: 3144
        Miss: 6960
        2018-09-13 08:15:43.404 INFO  [rpc-perf] Rate: 15823.74 rps Success: 100.00 % Hit Rate:
        31.12 %
        2018-09-13 08:15:43.404 INFO  [rpc-perf] Percentiles: Response OK (us): min: 47 p50: 389
        p90: 775 p99:86436 p999: 89120 p9999: 89657 max: 89657
    """

    new_metrics = []

    new_line = readline_with_check(input)

    if "[rpc-perf] Percentiles:" in new_line:
        percentiles = dict(re.findall(r'(?P<name>min|max|p\d*): (?P<value>\d+)', new_line))
        p9999 = float(percentiles['p9999'])
        p999 = float(percentiles['p999'])
        p99 = float(percentiles['p99'])
        p90 = float(percentiles['p90'])
        p50 = float(percentiles['p50'])
        min = float(percentiles['min'])
        max = float(percentiles['max'])
        new_metrics.append(Metric(metric_name_prefix + 'p9999', p9999,
                                  type=MetricType.GAUGE, labels=labels,
                                  help="99.99th percentile of latency in rpc-perf"))
        new_metrics.append(Metric(metric_name_prefix + 'p999', p999,
                                  type=MetricType.GAUGE, labels=labels,
                                  help="99.9th percentile of latency in rpc-perf"))
        new_metrics.append(Metric(metric_name_prefix + 'p99', p99,
                                  type=MetricType.GAUGE, labels=labels,
                                  help="99th percentile of latency in rpc-perf"))
        new_metrics.append(Metric(metric_name_prefix + 'p90', p90,
                                  type=MetricType.GAUGE, labels=labels,
                                  help="90th percentile of latency in rpc-perf"))
        new_metrics.append(Metric(metric_name_prefix + 'p50', p50,
                                  type=MetricType.GAUGE, labels=labels,
                                  help="50th percentile of latency in rpc-perf"))
        new_metrics.append(Metric(metric_name_prefix + 'min', min,
                                  type=MetricType.GAUGE, labels=labels,
                                  help="min of latency in rpc-perf"))
        new_metrics.append(Metric(metric_name_prefix + 'max', max,
                                  type=MetricType.GAUGE, labels=labels,
                                  help="max of latency in rpc-perf"))

    if "[rpc-perf] Rate:" in new_line:
        statistic = \
            dict(re.findall(r'(?P<name>Hit Rate|Success|Rate): (?P<value>\d+.\d+)', new_line))
        hit_rate = float(statistic['Hit Rate'])
        success = float(statistic['Success'])
        rate = float(statistic['Rate'])
        new_metrics.append(Metric(metric_name_prefix + 'hit_rate', hit_rate,
                                  type=MetricType.GAUGE, labels=labels,
                                  help="Hit rate in rpc-perf"))
        new_metrics.append(Metric(metric_name_prefix + 'success', success,
                                  type=MetricType.GAUGE, labels=labels,
                                  help="Success responses in rpc-perf"))
        new_metrics.append(Metric(metric_name_prefix + 'rate', rate,
                                  type=MetricType.GAUGE, labels=labels,
                                  help="Rate in rpc-perf"))

    return new_metrics


if __name__ == "__main__":
    wrapper_main.main(parse)
