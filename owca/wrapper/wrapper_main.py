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


import argparse
import ast
import logging
import subprocess
import shlex
import threading
from functools import partial

from owca.storage import KafkaStorage, LogStorage
from owca.logger import TRACE
from owca.wrapper.parser import (default_parse, parse_loop, DEFAULT_REGEXP,
                                 ParseFunc, ServiceLevelArgs, append_service_level_metrics)
from owca.platforms import get_owca_version

log = logging.getLogger(__name__)


def main(parse: ParseFunc = default_parse):
    """
    Launches workload and parser with processed arguments. Handles workload shutdown.
    """
    arg_parser = prepare_argument_parser()
    # It is assumed that unknown arguments should be passed to workload.
    args = arg_parser.parse_args()

    # Additional argparse checks.
    if not ((args.load_metric_name is not None and args.peak_load is not None) or
            (args.load_metric_name is None and args.peak_load is None)):
        print("Both load_metric_name and peak_load have to be set, or none of them.")
        exit(1)

    # Needs to be passed to parse_loop
    service_level_args = ServiceLevelArgs(args.slo, args.sli_metric_name,
                                          args.inverse_sli_metric_value,
                                          args.peak_load, args.load_metric_name)

    # Configuring log
    logging.basicConfig(
        level=TRACE if args.log_level == 'TRACE' else args.log_level,
        format="%(asctime)-15s %(levelname)s %(module)s %(message)s")
    log.debug("Logger configured with {0}".format(args.log_level))
    log.info("Starting wrapper version {}".format(get_owca_version()))

    command_splited = shlex.split(args.command)
    log.info("Running command: {}".format(command_splited))
    workload_process = subprocess.Popen(command_splited,
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE,
                                        universal_newlines=True,
                                        bufsize=1,
                                        shell=args.subprocess_shell,
                                        )
    input = workload_process.stderr if args.stderr else workload_process.stdout

    labels = ast.literal_eval(args.labels)
    parse = partial(parse, regexp=args.regexp, separator=args.separator, labels=labels,
                    input=input, metric_name_prefix=args.metric_name_prefix)
    append_service_level_metrics_func = partial(
        append_service_level_metrics, labels=labels, service_level_args=service_level_args)

    # create kafka storage with list of kafka brokers from arguments
    kafka_brokers_addresses = args.kafka_brokers.replace(" ", "").split(',')
    if kafka_brokers_addresses != [""]:
        log.info("KafkaStorage {}".format(kafka_brokers_addresses))
        kafka_storage = KafkaStorage(brokers_ips=kafka_brokers_addresses,
                                     max_timeout_in_seconds=5.0,
                                     topic=args.kafka_topic)
    else:
        kafka_storage = LogStorage(args.storage_output_filename)

    t = threading.Thread(target=parse_loop, args=(parse, kafka_storage,
                                                  append_service_level_metrics_func))
    t.start()
    t.join()

    # terminate all spawned processes
    workload_process.terminate()


def prepare_argument_parser():
    parser = argparse.ArgumentParser(
        description='Wrapper that exposes APMs using Prometheus format.'
    )
    parser.add_argument(
        '--command',
        help='Workload run command',
        dest='command',
        required=True,
        type=str
    )
    parser.add_argument(
        '--stderr',
        help='If 0, parser will use stdout, if 1 stderr',
        dest='stderr',
        default=0,
        type=int
    )
    parser.add_argument(
        '--regexp',
        help='regexp used for parsing with the default parsing function\n'
             'Needs to contain 2 named groups "name" and "value"'
             'Defaults to {0} that matches values in format "a=4.0"'.format(DEFAULT_REGEXP),
        dest='regexp',
        type=str,
        default=DEFAULT_REGEXP
    )
    parser.add_argument(
        '--metric_name_prefix',
        help='metric name prefix (only relevant for default parse function)',
        default=''
    )
    parser.add_argument(
        '--separator',
        help='String that separates workload outputs',
        dest='separator',
        type=str,
        default=None
    )
    parser.add_argument(
        '--log_level',
        help='Logging level',
        dest='log_level',
        default='ERROR',
        choices=['ERROR', 'WARNING', 'INFO', 'DEBUG', 'TRACE'],
        type=str)
    parser.add_argument(
        '--labels',
        help="Prometheus labels. Provide them in a dict format."
             "Example: ""{'workload':'stress-ng','exper':'2'}""",
        dest='labels',
        type=str,
        default="{}"
    )
    parser.add_argument(
        '--kafka_brokers',
        help='list of addresses with ports of kafka brokers (kafka nodes). Coma separated',
        dest='kafka_brokers',
        default="",
        type=str
    )
    parser.add_argument(
        '--kafka_topic',
        help='Kafka messages topic, passed to KafkaStorage',
        dest='kafka_topic',
        default='owca_apms',
        type=str
    )
    parser.add_argument(
        '--storage_output_filename',
        help='When Kafka storage is not used, allows to redirect metrics to file',
        dest='storage_output_filename',
        default=None,
        type=str
    )
    parser.add_argument(
        '--peak_load',
        help='Expected maximum load.',
        default=None,
        type=int
    )
    parser.add_argument(
        '--load_metric_name',
        help='Metric name parsed from the application stream '
             'used as load level indicator. If set to `const` '
             'the behaviour is slightly different: as real load were all the time '
             'equal to peak_load (then load_normalized == 1).',
        default=None,
        type=str
    )
    parser.add_argument(
        '--slo',
        help='Service level objective. '
             'Must be expressed in the same units as SLI. '
             'Default value is +inf. '
             'Being used only if sli_metric_name also defined.',
        default=float("inf"),
        type=float
    )
    parser.add_argument(
        '--sli_metric_name',
        help='Metric name parsed from the application stream '
             'used as service level indicator.',
        default=None,
        type=str
    )
    parser.add_argument(
        '--inverse_sli_metric_value',
        help='Add this flag if value of a metric used to calculate service ' +
             'level indicator should be inversed.',
        action='store_true',
        default=False,
    )
    parser.add_argument(
        '--subprocess_shell',
        help='Run subprocess command with full shell support.',
        action='store_true',
        default=False,
    )
    return parser


def debug():
    """Debug hook to allow entering debug mode in compiled pex.
    Run it as PEX_MODULE=owca.wrapper.wrapper_main:debug
    """
    import warnings
    try:
        import ipdb as pdb
    except ImportError:
        warnings.warn('ipdb not available, using pdb')
        import pdb
    pdb.set_trace()
    main()


if __name__ == "__main__":
    main()
