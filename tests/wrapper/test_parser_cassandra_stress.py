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
from wrapper.parser_cassandra_stress import parse


def test_parse():
    input_ = StringIO(
        "Results:"
        "Op rate                   :   14,997 op/s  [WRITE: 14,997 op/s]"
        "Partition rate            :   14,997 pk/s  [WRITE: 14,997 pk/s]"
        "Row rate                  :   14,997 row/s [WRITE: 14,997 row/s]"
        "Latency mean              :    1.9 ms [WRITE: 1.9 ms]"
        "Latency median            :    0.3 ms [WRITE: 0.3 ms]"
        "Latency 95th percentile   :    0.4 ms [WRITE: 0.4 ms]"
        "Latency 99th percentile   :   74.0 ms [WRITE: 74.0 ms]"
        "Latency 99.9th percentile :  146.8 ms [WRITE: 146.8 ms]"
        "Latency max               :  160.2 ms [WRITE: 160.2 ms]"
        "Total partitions          :  1,350,028 [WRITE: 1,350,028]"
        "Total errors              :          0 [WRITE: 0]"
        "Total GC count            : 0"
        "Total GC memory           : 0.000 KiB"
        "Total GC time             :    0.0 seconds"
        "Avg GC time               :    NaN ms"
        "StdDev GC time            :    0.0 ms"
        "Total operation time      : 00:01:30"
    )
    expected = [
        Metric('cassandra_qps', value=14997, type=MetricType.GAUGE,
               help="QPS"),
        Metric('cassandra_p99', value=74.0, type=MetricType.GAUGE,
               help="99th percentile")
    ]
    assert expected == parse(input_, None, None, {}, 'cassandra_')
