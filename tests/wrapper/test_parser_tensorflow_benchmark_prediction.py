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

from owca.metrics import Metric, MetricType
from owca.wrapper.parser_tensorflow_benchmark_prediction import parse


def test_parse():
    input_ = StringIO(
        "580	248.7 examples/sec"
    )
    expected = [
        Metric('tensorflow_prediction_speed', value=248.7, type=MetricType.GAUGE,
               help="Tensorflow Prediction Speed")
    ]
    assert expected == parse(input_, None, None, {}, 'tensorflow_benchmark_prediction_')