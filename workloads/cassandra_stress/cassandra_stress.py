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

import os
from common import application_host_ip, command, image_name, image_tag, \
    initContainers, json, securityContext, pod, wrapper_kafka_brokers, \
    wrapper_log_level, wrapper_kafka_topic, wrapper_labels, slo

# ----------------------------------------------------------------------------------------------------
###
# Params which can be modified by exporting environment variables.
###
communication_port = os.environ.get('communication_port', '9042')
threads = int(os.environ.get('threads') or 8)
# ----------------------------------------------------------------------------------------------------

# For testing purpose set to small number as 1000
number_of_rows = 100000

wait_for_cassandra_cmd = ["sh", "-c", """
          set -x
          until nc -vz {cassandra_address} {communication_port}; do
            echo "$(date) Waiting for cassandra to initialize itself."
            sleep 3
          done""".format(cassandra_address=application_host_ip,
                         communication_port=communication_port)]

wait_for_cassandra_container = {
    "name": "wait-for-cassandra",
    "image": image_name + ':' + image_tag,
    "securityContext": securityContext,
    "command": wait_for_cassandra_cmd}
initContainers.append(wait_for_cassandra_container)

cassandra_warmup_cmd = ['sh', '-c',
                        'cassandra-stress write n={} \
                        -node {} -port native={} -rate threads=14'.format(
                            number_of_rows,
                            application_host_ip,
                            communication_port)]

cassandra_warmup_container = {
    "name": "cassandra-warmuper",
    "image": image_name + ':' + image_tag,
    "securityContext": securityContext,
    "command": cassandra_warmup_cmd}
initContainers.append(cassandra_warmup_container)


cassandra_stress_cmd = ('"while true; do cassandra-stress mixed duration=90s '
                        '-pop seq=1..{} -node {} -port native={} -rate '
                        'threads={}; done"'.format(number_of_rows,
                                                   application_host_ip,
                                                   communication_port,
                                                   threads))
cmd = """/usr/bin/cassandra_stress_wrapper.pex \
--command '{cassandra_stress_cmd}' \
--metric_name_prefix 'cassandra_'  \
--stderr 0 --kafka_brokers '{kafka_brokers}' --kafka_topic {kafka_topic}  \
--log_level {log_level}  \
--peak_load {peak_load} --load_metric_name {load_metric_name} \
--slo {slo} --sli_metric_name {sli_metric_name}  \
--subprocess_shell  \
--labels \"{labels}\"""".format(
    cassandra_stress_cmd=cassandra_stress_cmd,
    kafka_brokers=wrapper_kafka_brokers,
    log_level=wrapper_log_level,
    kafka_topic=wrapper_kafka_topic,
    labels=wrapper_labels,
    slo=slo, sli_metric_name="cassandra_p99",
    # @TODO peak_load should match cassandra_stress parameters
    peak_load=10000, load_metric_name="cassandra_qps")

command.append(cmd)

json_format = json.dumps(pod)
print(json_format)
