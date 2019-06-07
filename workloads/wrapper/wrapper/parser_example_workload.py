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

from wca.metrics import Metric, MetricType
from wrapper import wrapper_main


def parse(input: TextIOWrapper, regexp: str, separator: str = None,
          labels: Dict[str, str] = {}, metric_name_prefix: str = '') -> List[Metric]:
    return [Metric(name="example", value=1.337, labels={"test": "label"}, type=MetricType.GAUGE,
                   help="Empty example metric")]


if __name__ == "__main__":
    wrapper_main.main(parse)
