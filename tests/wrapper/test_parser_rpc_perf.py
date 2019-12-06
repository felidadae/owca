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


from unittest.mock import patch

from io import StringIO

from wca.metrics import Metric, MetricType
from wrapper.parser_rpc_perf import parse


@patch('builtins.print')
def test_parse(mock_print):
    input_ = StringIO(
        "2018-09-13 08:15:43.404 INFO  [rpc-perf] -----"
        "2018-09-13 08:15:43.404 INFO  [rpc-perf] Window: 155"
        "2018-09-13 08:15:43.404 INFO  [rpc-perf] Connections: Ok: 0 Error: 0 Timeout: 0 Open: 80"
        "2018-09-13 08:15:43.404 INFO  [rpc-perf] Sockets: Create: 0 Close: 0 Read: 31601 Write: " +
        "15795 Flush: 0"
        "2018-09-13 08:15:43.404 INFO  [rpc-perf] Requests: Sent: 15795 Prepared: 16384 " +
        "In-Flight: 40"
        "2018-09-13 08:15:43.404 INFO  [rpc-perf] Responses: Ok: 15793 Error: 0 Timeout: 0 Hit: " +
        "3144 Miss: 6960"
        "2018-09-13 08:15:43.404 INFO  [rpc-perf] Rate: 15823.74 rps Success: 100.00 % Hit Rate:" +
        " 31.12 %"
        "2018-09-13 08:15:43.404 INFO  [rpc-perf] Percentiles: Response OK (us): min: 47 p50: 389" +
        " p90: 775 p99: 86436 p999: 89120 p9999: 89657 max: 89657"
    )
    expected = [
        Metric("rpcperf_p9999", value=89657, type=MetricType.GAUGE,
               help="99.99th percentile of latency in rpc-perf"),
        Metric("rpcperf_p999", value=89120, type=MetricType.GAUGE,
               help="99.9th percentile of latency in rpc-perf"),
        Metric("rpcperf_p99", value=86436, type=MetricType.GAUGE,
               help="99th percentile of latency in rpc-perf"),
        Metric("rpcperf_p90", value=775, type=MetricType.GAUGE,
               help="90th percentile of latency in rpc-perf"),
        Metric("rpcperf_p50", value=389, type=MetricType.GAUGE,
               help="50th percentile of latency in rpc-perf"),
        Metric("rpcperf_min", value=47, type=MetricType.GAUGE,
               help="min of latency in rpc-perf"),
        Metric("rpcperf_max", value=89657, type=MetricType.GAUGE,
               help="max of latency in rpc-perf"),
        Metric("rpcperf_hit_rate", value=31.12, type=MetricType.GAUGE,
               help="Hit rate in rpc-perf"),
        Metric("rpcperf_success", value=100.00, type=MetricType.GAUGE,
               help="Success responses in rpc-perf"),
        Metric("rpcperf_rate", value=15823.74, type=MetricType.GAUGE,
               help="Rate in rpc-perf"),
    ]
    assert expected == parse(input_, None, None, {}, 'rpcperf_')
