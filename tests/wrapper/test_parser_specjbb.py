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

import os

from wca.metrics import Metric, MetricType
from wrapper.parser_specjbb import parse


@patch('builtins.print')
def test_parse(mock_print):
    """Reads textfile with sample output from specjbb."""
    expected = [Metric("specjbb_p99_total_purchase", value=0,
                       type=MetricType.GAUGE,
                       help="Specjbb2015 metric, Total Purchase, percentile 99")]

    path = os.path.dirname(os.path.abspath(__file__))
    with open(path + '/specjbb_sample_stdout.txt', 'r') as fin:
        expected[0].value = 3800000.0
        assert expected == parse(fin, None, None, {}, 'specjbb_')
        expected[0].value = 581000.0
        assert expected == parse(fin, None, None, {}, 'specjbb_')
        expected[0].value = 6800000.0
        assert expected == parse(fin, None, None, {}, 'specjbb_')
