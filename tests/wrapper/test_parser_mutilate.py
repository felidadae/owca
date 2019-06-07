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


from io import StringIO

from wca.metrics import Metric, MetricType
from wrapper.parser_mutilate import parse


def test_parse():
    data = """#type       avg     std     min     5th    10th    90th    95th    99th
               read      801.9   155.0   304.5   643.7   661.1  1017.8  1128.2  1386.5
               update    804.6   157.8   539.4   643.4   661.2  1026.1  1136.1  1404.3
               op_q        1.0     0.0     1.0     1.0     1.0     1.1     1.1     1.1

               Total QPS = 159578.5 (1595835 / 10.0s)

               Misses = 0 (0.0%)
               Skipped TXs = 0 (0.0%)

               RX  382849511 bytes :   36.5 MB/s
               TX   67524708 bytes :    6.4 MB/s
"""

    number_of_reads = len(data.splitlines())
    input_ = StringIO(data)

    got = []
    for _ in range(number_of_reads):
        got.extend(parse(input_, '', None, {}, 'twemcache_'))
    expected = [
        Metric('twemcache_read_avg', value=801.9, labels={},
               type=MetricType.GAUGE, help="Average"),
        Metric('twemcache_read_p90', value=1017.8, labels={},
               type=MetricType.GAUGE, help="90th percentile of read latency"),
        Metric('twemcache_read_p95', value=1128.2, labels={},
               type=MetricType.GAUGE, help="95th percentile of read latency"),
        Metric('twemcache_read_p99', value=1386.5, labels={},
               type=MetricType.GAUGE, help="99th percentile of read latency"),
        Metric('twemcache_qps', value=159578.5, labels={},
               type=MetricType.GAUGE, help="QPS")]

    assert expected == got


def test_parse_scan_mode():
    data = """
    #type       avg     min     1st     5th    10th    90th    95th    99th      QPS   target
    read       76.3   346.3    21.1    23.5    24.5    34.3    38.7  2056.6   1002.0   1000"""

    number_of_reads = len(data.splitlines())
    input_ = StringIO(data)

    got = []

    for _ in range(number_of_reads):
        got.extend(parse(input_, '', None, {}, 'twemcache_'))

    expected = [
        Metric('twemcache_scan_qps', value=1002.0, labels={},
               type=MetricType.GAUGE, help="QPS"),
        Metric('twemcache_scan_read_avg', value=76.3, labels={},
               type=MetricType.GAUGE, help="Average"),
        Metric('twemcache_scan_read_p90', value=34.3, labels={},
               type=MetricType.GAUGE, help="90th percentile of read latency"),
        Metric('twemcache_scan_read_p95', value=38.7, labels={},
               type=MetricType.GAUGE, help="95th percentile of read latency"),
        Metric('twemcache_scan_read_p99', value=2056.6, labels={},
               type=MetricType.GAUGE, help="99th percentile of read latency")
    ]
    assert expected == got
