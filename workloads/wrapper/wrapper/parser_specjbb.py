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
EMPTY_LINE = r"^\s*$"


def parse(input: TextIOWrapper, regexp: str, separator: str = None,
          labels: Dict[str, str] = {}, metric_name_prefix: str = '') -> List[Metric]:
    """
    Custom parse function for specjbb.
    For sample output from specjbb see file:
    ./specjbb_sample_stdout.txt

    Discards until finds
    >>Response times:<<
    and read until empty line.

    Readed lines represents a table.
    In the code the table representation is named data_frame.
    """
    new_metrics = []
    input_lines = []

    # discarding lines
    new_line = readline_with_check(input)
    while not re.match(r"^\s*Response times:\s*$", new_line):
        new_line = readline_with_check(input)
    new_line = readline_with_check(input)

    # reading until empty line
    while not re.match(EMPTY_LINE, new_line):
        input_lines.append(new_line)
        new_line = readline_with_check(input)
    log.debug("Found separator in {0}".format(new_line))

    # Two dimensional list, first row contains names of columns. Almost as data frame.
    data_frame = [[el.strip() for el in line.split(",")] for line in input_lines]

    # For now we need only one metric: TotalPurchase, p99.
    metric_name = metric_name_prefix + 'p99_total_purchase'
    metric_value = float(data_frame[1][-3])  # total purchase, p99
    new_metrics.append(Metric(metric_name, metric_value,
                              type=MetricType.GAUGE, labels=labels,
                              help="Specjbb2015 metric, Total Purchase, percentile 99"))

    return new_metrics


if __name__ == "__main__":
    wrapper_main.main(parse)
