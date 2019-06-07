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
from typing import List, Dict
import re
from wca.metrics import Metric, MetricType
from wrapper import wrapper_main
from wrapper.parser import readline_with_check

EOF_line = "Stop-Mutilate-Now"


def parse(input: TextIOWrapper, regexp: str, separator: str = None,
          labels: Dict[str, str] = {}, metric_name_prefix: str = '') -> List[Metric]:
    """Custom parse function for mutilate
        -for scan mode
        #type       avg     min     1st     5th    10th    90th    95th    99th      QPS   target
        read       76.3   346.3    21.1    23.5    24.5    34.3    38.7  2056.6   1002.0     1000


        -for Q mode (run with -Q)
        #type       avg     std     min     5th    10th    90th    95th    99th
        read      801.9   155.0   304.5   643.7   661.1  1017.8  1128.2  1386.5
        update    804.6   157.8   539.4   643.4   661.2  1026.1  1136.1  1404.3
        op_q        1.0     0.0     1.0     1.0     1.0     1.1     1.1     1.1

        Total QPS = 159578.5 (1595835 / 10.0s)

        Misses = 0 (0.0%)
        Skipped TXs = 0 (0.0%)

        RX  382849511 bytes :   36.5 MB/s
        TX   67524708 bytes :    6.4 MB/s
    """
    SCAN_MODE_COLUMNS = 11
    new_metrics = []
    new_line = readline_with_check(input, EOF_line)
    line = new_line.split()
    scan_prefix = 'scan_'
    if "read" in line:
        if len(line) != SCAN_MODE_COLUMNS:
            scan_prefix = ''
        else:
            qps = float(line[9])
            new_metrics.append(Metric(
                metric_name_prefix + scan_prefix + 'qps', qps,
                type=MetricType.GAUGE, labels=labels, help="QPS"
            ))

        avg = float(line[1])
        new_metrics.append(
            Metric(metric_name_prefix + scan_prefix + 'read_avg', avg,
                   type=MetricType.GAUGE, labels=labels,
                   help="Average"))

        p90 = float(line[6])
        new_metrics.append(
            Metric(metric_name_prefix + scan_prefix + 'read_p90', p90,
                   type=MetricType.GAUGE, labels=labels,
                   help="90th percentile of read latency"))

        p95 = float(line[7])
        new_metrics.append(
            Metric(metric_name_prefix + scan_prefix + 'read_p95', p95,
                   type=MetricType.GAUGE, labels=labels,
                   help="95th percentile of read latency"))

        p99 = float(line[8])
        new_metrics.append(
            Metric(metric_name_prefix + scan_prefix + 'read_p99', p99,
                   type=MetricType.GAUGE, labels=labels,
                   help="99th percentile of read latency"))

    if "Total QPS" in new_line:
        read_qps = re.search(r'Total QPS = ([0-9]*\.[0-9])', new_line)
        if read_qps is not None:
            qps = float(read_qps.group(1))
            new_metrics.append(Metric(
                metric_name_prefix + 'qps', qps, type=MetricType.GAUGE,
                labels=labels, help="QPS"))
    return new_metrics


if __name__ == "__main__":
    wrapper_main.main(parse)
