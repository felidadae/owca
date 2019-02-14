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


"""
Module is responsible for exposing functionality of storing labeled metrics
in durable external storage.
"""
import abc
import itertools
import logging
import re
import sys
import time
from typing import List, Tuple, Dict

import confluent_kafka
from dataclasses import dataclass, field

from owca import logger
from owca.metrics import Metric, MetricType

log = logging.getLogger(__name__)


class Storage(abc.ABC):

    @abc.abstractmethod
    def store(self, metrics: List[Metric]) -> None:
        """store metrics; may throw FailedDeliveryException"""
        ...


@dataclass
class LogStorage(Storage):

    output_filename: str = None  # Defaults to stderr.

    def __post_init__(self):
        if self.output_filename is not None:
            self.output = open(self.output_filename, 'a')
            log.info('configuring log storage to dump metrics to: %r', self.output_filename)
        else:
            self.output = sys.stderr

    def store(self, metrics):
        log.debug('storing: %d', len(metrics))
        log.log(logger.TRACE, 'Dump of metrics: %r', metrics)

        is_convertable, error_message = is_convertable_to_prometheus_exposition_format(metrics)
        if not is_convertable:
            log.warning(
                'failed to convert metrics into'
                'prometheus exposition format; error: "{}" - skipping '.format(error_message)
            )
        else:
            timestamp = get_current_time()
            msg = convert_to_prometheus_exposition_format(metrics, timestamp)
            log.log(logger.TRACE, 'Dump of metrics (text format): %r', msg)
            print(msg, file=self.output, flush=True)


class FailedDeliveryException(Exception):
    """when metrics has not been stored with success"""
    pass


def get_current_time() -> str:
    """current time in unix epoch (miliseconds)"""
    return str(int(time.time() * 1000))


# Comes from prometheus python client:
# https://github.com/prometheus/client_python/blob/master/prometheus_client/core.py#L25
_METRIC_NAME_RE = re.compile(r'^[a-zA-Z_:][a-zA-Z0-9_:]*$')
_METRIC_LABEL_NAME_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')
_RESERVED_METRIC_LABEL_NAME_RE = re.compile(r'^__.*$')


class UnconvertableToPrometheusExpositionFormat(Exception):
    pass


def is_convertable_to_prometheus_exposition_format(metrics: List[Metric]) -> (bool, str):
    """Check if metrics are convertable into prometheus exposition format.

    In case of metric type we modify scope of original prometheus exposition format requirements
    and only allow to set type to gauge and counter.

    Returns:
        Tuple with 1) boolean flag whether the metrics are convertable (True if they are)
        2) in case of not being convertable error message explaining the cause, otherwise
        empty string.
    """
    for metric in metrics:
        if not _METRIC_NAME_RE.match(metric.name):
            return (False, "Wrong metric name {}.".format(metric.name))
        for label_key, label_val in metric.labels.items():
            if not isinstance(label_val, str):
                return (False, "Label (at key {}) should be str type got {!r}"
                        .format(label_key, metric.name, type(label_val)))

            if not _METRIC_LABEL_NAME_RE.match(label_key):
                return (False, "Used wrong label name {} in metric {}."
                        .format(label_key, metric.name))
            if _RESERVED_METRIC_LABEL_NAME_RE.match(label_key):
                return (False, "Used reserved label name {} in metric {}."
                        .format(label_key, metric.name))

        # Its our internal OWCA requirement to use only GAUGE or COUNTER.
        #   However, as in that function we do validation that code also
        #   goes here.
        if metric.type is not None and (metric.type != MetricType.GAUGE and
                                        metric.type != MetricType.COUNTER):
            return (False, "Wrong metric type (used type {})."
                    .format(metric.type))

    return (True, "")


def group_metrics_by_name(metrics: List[Metric]) -> \
        List[Tuple[str, List[Metric]]]:
    """Group metrics with the same name to expose meta information only once."""

    def name_key(metric):
        return metric.name

    def labels_conversion_with_natural_sort(labels):
        """Convert labels to tuples of str and ints to allow natural string sorting."""
        return sorted((k, int(v) if v.isdigit() else v) for k, v in labels.items())

    def sorting_key_for_metrics(metric):
        """by labels with natural sort"""
        return labels_conversion_with_natural_sort(metric.labels)

    # sort by metrics first
    metrics = sorted(metrics, key=name_key)

    # and then group by just metadata
    grouped = []

    for metric_name, grouped_metrics in itertools.groupby(metrics, key=name_key):
        # sort metrics by labels for the same metadata.
        grouped_metrics = sorted(grouped_metrics, key=sorting_key_for_metrics)
        grouped.append((
            metric_name,
            grouped_metrics,
        ))
    return grouped


def convert_to_prometheus_exposition_format(metrics: List[Metric], timestamp) -> str:
    """Convert metrics to the prometheus format."""
    output = []

    grouped_metrics = group_metrics_by_name(metrics)

    for metric_name, metrics in grouped_metrics:
        first_metric = metrics[0]
        if first_metric.help:
            output.append('# HELP {0} {1}\n'.format(
                first_metric.name, first_metric.help.replace('\\', r'\\').replace('\n', r'\n')))

        if first_metric.type:
            output.append('# TYPE {0} {1}\n'.format(first_metric.name, first_metric.type))

        # Assert that all metrics with the same name have the same metadata.
        assert {metric.type for metric in metrics} == {first_metric.type}
        assert {metric.help for metric in metrics} == {first_metric.help}

        for metric in metrics:

            label_str = '{{{0}}}'.format(','.join(
                ['{0}="{1}"'.format(
                    k, v.replace('\\', r'\\').replace('\n', r'\n').replace('"', r'\"'))
                    for k, v in sorted(metric.labels.items())]))

            # Do not send empty labels.
            if label_str == '{}':
                label_str = ''

            # https://afterthoughtsoftware.com/posts/python-str-or-repr-on-a-float
            if type(metric.value) == float:
                value_str = repr(float(metric.value))  # here we use repr instead of str
            else:
                value_str = str(metric.value)

            output.append('{0}{1} {2} {3}\n'.format(metric.name, label_str,
                                                    value_str, timestamp))
        output.append('\n')

    return ''.join(output)


@dataclass
class KafkaStorage(Storage):
    """Storage for saving metrics in Kafka.

    Args:
        brokers_ips:  list of addresses with ports of all kafka brokers (kafka nodes)
        topic: name of a kafka topic where message should be saved
        max_timeout_in_seconds: if a message was not delivered in maximum_timeout seconds
            self.store will throw FailedDeliveryException
        producer_config: additionall key value pairs that will be passed to kafka driver
            https://github.com/edenhill/librdkafka/blob/master/CONFIGURATION.md
            e.g. {'debug':'broker,topic,msg'} to enable logging for kafka producer threads
    """
    topic: str
    brokers_ips: List[str] = field(default=("127.0.0.1:9092",))
    max_timeout_in_seconds: float = 0.5  # defaults half of a second
    extra_config: Dict[str, str] = None

    def __post_init__(self) -> None:
        try:
            self._create_producer()
        except Exception:
            log.exception('Exception durning kafka consumer initialization:')
            raise

        self.error_from_callback = None
        """used to pass error from within callback_on_delivery
          (called from different thread) to KafkaStorage instance"""

    def _create_producer(self) -> None:
        config = self.extra_config or dict()
        config.update({'bootstrap.servers': ",".join(self.brokers_ips)})
        self.producer = confluent_kafka.Producer(config)

    def callback_on_delivery(self, err, msg) -> None:
        """Called once for each message produced to indicate delivery result.
        Triggered by poll() or flush()."""
        if err is not None:
            self.error_from_callback = err
            log.error(
                'KafkaStorage failed to send message; error message: {}'.format(err))
        else:
            log.log(logger.TRACE,
                    'KafkaStorage succeeded to send message; message: {}'.format(msg))

    def store(self, metrics: List[Metric]) -> None:
        """Stores synchronously metrics in kafka.

        The function returns only after sending the message -
        by using synchronous self.producer.flush to block until
        the message (metrics) are delivered to the kafka.

        Raises:
            * UnconvertableToPrometheusExpositionFormat - if metrics are not convertable
                into prometheus exposition format.
            * FailedDeliveryException - if a message could not be written to kafka.
        """

        if not metrics:
            log.warning('Empty list of metrics, store is skipped!')
            return

        is_convertable, error_message = is_convertable_to_prometheus_exposition_format(metrics)
        if not is_convertable:
            log.error('KafkaStorage failed to convert metrics into'
                      'prometheus exposition format; error: "{}"'
                      .format(error_message))
            raise UnconvertableToPrometheusExpositionFormat(error_message)

        timestamp = get_current_time()
        msg = convert_to_prometheus_exposition_format(metrics, timestamp)
        self.producer.produce(self.topic, msg.encode('utf-8'),
                              callback=self.callback_on_delivery)

        r = self.producer.flush(self.max_timeout_in_seconds)  # block until all send

        # check if timeout expired
        if r > 0:
            raise FailedDeliveryException(
                "Maximum timeout {} for sending message has passed out.".format(
                    self.max_timeout_in_seconds))

        # check if any failed to be delivered
        if self.error_from_callback is not None:
            # before reseting self.error_from_callback we
            # assign the original value to seperate value
            # to pass it to exception
            error_from_callback__original_ref = self.error_from_callback
            self.error_from_callback = None

            raise FailedDeliveryException(
                "Message has failed to be writen to kafka. API error message: {}.".format(
                    error_from_callback__original_ref))

        log.debug('message size=%i with timestamp=%s stored in kafka topic=%r',
                  len(msg), timestamp, self.topic)

        return  # the message has been send to kafka


class MetricPackage:
    """Wraps storage to pack metrics from diffrent sources and apply common labels
    before send."""

    def __init__(self, storage: Storage):
        self.storage = storage
        self.metrics: List[Metric] = []

    def add_metrics(self, *metrics_args: List[Metric]):
        for metrics in metrics_args:
            self.metrics.extend(metrics)

    def send(self, common_labels: Dict[str, str] = None):
        """Apply common_labels and send using storage from constructor. """
        if common_labels:
            for metric in self.metrics:
                metric.labels.update(common_labels)
        self.storage.store(self.metrics)
