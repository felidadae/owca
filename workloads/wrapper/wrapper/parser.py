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


import collections
import _thread
import logging
import re
import time
from io import TextIOWrapper
from typing import List, Dict, Callable

import wca
from wca.metrics import Metric, MetricType
from wca.storage import KafkaStorage

log = logging.getLogger(__name__)
ParseFunc = Callable[[TextIOWrapper, str, str, Dict[str, str]], List[Metric]]

# Matches values returned in format "a=4.2". If different format is needed,
# provide regex in arguments. It needs to have 2 named groups "name" and "value"
DEFAULT_REGEXP = r"(?P<name>\w+?)=(?P<value>\d+?.?\d*)"

MAX_ATTEMPTS = 5


def readline_with_check(input: TextIOWrapper, EOF_line='') -> str:
    """Additionally check if EOF."""
    new_line = input.readline()
    # Print to stdout read lines from subprocess stdout or stderr.
    print(new_line, end='')
    if new_line == EOF_line:
        raise StopIteration
    return new_line


def default_parse(input: TextIOWrapper, regexp: str, separator: str = None,
                  labels: Dict[str, str] = {}, metric_name_prefix: str = '') -> List[Metric]:
    """
    Parses workload output. If no separator is provided, parses only one line at a time.
    With separator, it appends lines to a list until the line with separator appears and then
    uses regexp on the collected output. Separator should be sent in a separate line,
    without metrics. If there is no new lines in input from the workload, function stay at
    input.readline() call. After new data arrives, previously read values will be overwritten.
    :param input: output of the workload process
    :param regexp: regexp used for finding metric names and their values.
           Needs to contain 2 named groups "name" and "value".
    :param separator: string that separates blocks of measurements. If none is passed,
           only one line of input will be parsed
    :param labels: dictionary of labels like workload name, workload parameters etc.
           Used for labeling the metrics in prometheus format.
    :return: List of Metrics
    """
    new_metrics = []
    input_lines = []

    new_line = readline_with_check(input)
    if separator is not None:
        # With separator, first we read the whole block of output until the separator appears

        while not re.match(separator, new_line) and not new_line == '':
            input_lines.append(new_line)
            new_line = readline_with_check(input)
        log.debug("Found separator in {0}".format(new_line))
    else:
        # Without separator only one line is processed at a time
        input_lines.append(new_line)
    found_metrics = re.finditer(regexp, '\n'.join(input_lines))
    for metric in list(found_metrics):
        metric = metric.groupdict()
        new_metrics.append(Metric(metric_name_prefix+metric['name'], float(metric['value']),
                                  labels=labels))
    return new_metrics


def kafka_store_with_retry(kafka_storage: KafkaStorage, metrics: List[Metric]):
    # Try MAX_ATTEMPTS times to send metrics to kafka server
    # with increasing sleep time between attempts
    backoff_delay = 1
    for attempt in range(MAX_ATTEMPTS):
        try:
            kafka_storage.store(metrics)
        except wca.storage.FailedDeliveryException:
            log.warning("Failed to deliver message to kafka, "
                        "tried {0} times".format(attempt + 1))
            if attempt == MAX_ATTEMPTS - 1:
                raise
            time.sleep(backoff_delay)
            backoff_delay *= 2
            continue
        break


ServiceLevelArgs = collections.namedtuple(
    'ServiceLevelArgs',
    ['slo', 'sli_metric_name', 'inverse_sli_metric_value',
     'peak_load', 'load_metric_name'])


def append_service_level_metrics(service_level_args: ServiceLevelArgs,
                                 labels: Dict[str, str], metrics: List[Metric]):
    """Append service level metrics based on choosen matric from parsed metrics.
    :param metrics: list of metrics, additional service level metrics will
        be appended to that list.
    """
    for metric in metrics:
        if (service_level_args.sli_metric_name is not None and
                service_level_args.sli_metric_name == metric.name):
            if service_level_args.inverse_sli_metric_value:
                value = 1.0/float(metric.value)
            else:
                value = float(metric.value)
            log.debug(metric)
            # Send `slo` metric only if SLI was found.
            metrics.append(Metric(
                "slo",
                float(service_level_args.slo),
                labels=labels,
                type=MetricType.GAUGE,
                help='Service Level Objective based on %s metric' %
                     service_level_args.sli_metric_name,
            ))
            metrics.append(Metric(
                "sli",
                value,
                labels=labels,
                type=MetricType.GAUGE,
                help='Service Level Indicator based on %s metric' %
                     service_level_args.sli_metric_name,
            ))
            metrics.append(Metric(
                "sli_normalized",
                value/service_level_args.slo,
                labels=labels,
                type=MetricType.GAUGE,
                help='Normalized Service Level Indicator based on %s metric and SLO' %
                     service_level_args.sli_metric_name,

            ))

        if (service_level_args.load_metric_name not in (None, "const") and
                service_level_args.load_metric_name == metric.name):
            value = float(metric.value)
            peak_load = float(service_level_args.peak_load)
            metrics.append(Metric("peak_load", float(service_level_args.peak_load), labels=labels))
            metrics.append(Metric("load", value, labels=labels))
            metrics.append(Metric("load_normalized", value/peak_load,
                                  labels=labels))

    # If set to `const` the behaviour is slightly different:
    #   as real load were all the time equal to peak_load
    #   (then load_normalized == 1).
    if service_level_args.load_metric_name == "const":
        metrics.append(Metric("peak_load", float(service_level_args.peak_load), labels=labels))
        metrics.append(Metric("load", float(service_level_args.peak_load), labels=labels))
        metrics.append(Metric("load_normalized", 1.0, labels=labels))


def parse_loop(parse: Callable[[], List[Metric]], kafka_storage: KafkaStorage,
               append_service_level_metrics_func: Callable[[List[Metric]], None]):
    """
    Runs parsing and kafka storage in loop. parse_loop.last_valid_metrics list is accessed
    by the HTTP server GET request handler.
    """
    parse_loop.metrics = []
    parse_loop.last_valid_metrics = []
    while True:
        try:
            parse_loop.metrics = parse()
            # parse() can return an empty list, so we store new values for kafka and http server
            # only when there are new metrics to store
            if parse_loop.metrics:
                append_service_level_metrics_func(metrics=parse_loop.metrics)
                for metric in parse_loop.metrics:
                    log.debug("Found metric: {}".format(metric))
                parse_loop.last_valid_metrics = parse_loop.metrics.copy()
                if kafka_storage is not None:
                    kafka_store_with_retry(kafka_storage, parse_loop.last_valid_metrics)

        except BaseException:
            _thread.interrupt_main()
            raise
