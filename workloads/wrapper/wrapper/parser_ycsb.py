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
    """Custom parse function for YCSB.
    Parses lines similar to (added new line characters to improve readibility):
        2018-08-22 17:33:25:811 581 sec: 581117 operations;
        975 current ops/sec;
        est completion in 2 hours 36 minutes
        [READ: Count=462, Max=554, Min=273, Avg=393.39, 90=457,
        99=525, 99.9=554, 99.99=554] [UPDATE: Count=513, Max=699,
        Min=254, Avg=383.83, 90=441, 99=512, 99.9=589, 99.99=699] # noqa
    """
    new_metrics = []

    new_line = readline_with_check(input)

    if "operations" in new_line:
        operations_and_ops = \
            re.search(r'(?P<operations>\d+) operations;', new_line).groupdict()
        operations = float(operations_and_ops['operations'])
        new_metrics.append(Metric(metric_name_prefix + 'operations', operations,
                                  type=MetricType.GAUGE, labels=labels,
                                  help="Done operations in Cassandra"))

    if "current ops" in new_line:
        operations_and_ops = \
            re.search(r'(?P<ops_per_sec>\d+(\.\d+)?) current ops\/sec', new_line).groupdict()
        ops_per_sec = float(operations_and_ops['ops_per_sec'])
        new_metrics.append(Metric(metric_name_prefix + 'ops_per_sec', ops_per_sec,
                                  type=MetricType.GAUGE, labels=labels,
                                  help="Ops per sec Cassandra"))

    if "READ" in new_line:
        read = re.search(r'\[READ.*?99\.99=(\d+).*?\]', new_line)
        p9999 = float(read.group(1))
        new_metrics.append(Metric(metric_name_prefix + 'read_p9999', p9999,
                                  type=MetricType.GAUGE, labels=labels,
                                  help="99.99th percentile of read latency in Cassandra"))
    if "UPDATE" in new_line:
        update = re.search(r'\[UPDATE.*?99\.99=(\d+).*?\]', new_line)
        p9999 = float(update.group(1))
        new_metrics.append(Metric(metric_name_prefix + 'update_p9999', p9999,
                                  type=MetricType.GAUGE, labels=labels,
                                  help="99.99th percentile of update latency in Cassandra"))

    return new_metrics


if __name__ == "__main__":
    wrapper_main.main(parse)
