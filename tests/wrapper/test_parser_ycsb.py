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
from unittest.mock import patch

from wca.metrics import Metric, MetricType
from wrapper.parser_ycsb import parse


@patch('builtins.print')
def test_parse(mock_print):
    input_ = StringIO(
        "2018-08-22 17:33:25:811 581 sec: 581117 operations; "
        "975 current ops/sec; "
        "est completion in 2 hours 36 minutes "
        "[READ: Count=462, Max=554, Min=273, Avg=393.39, 90=457, "
        "99=525, 99.9=554, 99.99=554] [UPDATE: Count=513, Max=699, "
        "Min=254, Avg=383.83, 90=441, 99=512, 99.9=589, 99.99=699] # noq"
    )
    expected = [
        Metric("cassandra_operations", value=581117, type=MetricType.GAUGE,
               help="Done operations in Cassandra"),
        Metric("cassandra_ops_per_sec", value=975, type=MetricType.GAUGE,
               help="Ops per sec Cassandra"),
        Metric("cassandra_read_p9999", value=554.0, type=MetricType.GAUGE,
               help="99.99th percentile of read latency in Cassandra"),
        Metric("cassandra_update_p9999", value=699.0, type=MetricType.GAUGE,
               help="99.99th percentile of update latency in Cassandra"),
    ]
    assert expected == parse(input_, None, None, {}, 'cassandra_')
