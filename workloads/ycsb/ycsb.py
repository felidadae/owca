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

# --------------------------------------------------------------------------------------------------
###
# Params which can be modified by exporting environment variables.
###

# Port that Cassandra will bind to.
communication_port = os.environ.get('communication_port', '9042')

# Number of QpS send to cassandra (default: 1000;
# if `ycsb_amplitude` and `ycsb_period` are set - maximum of a sine curve).
ycsb_target = os.environ.get('ycsb_target', '1000')

# Number of YCSB threads.
ycsb_thread_count = os.environ.get('ycsb_thread_count', '1')

# ycsb_period and ycsb_amplitude are used to
# generate non-constant number of QpS;
# see:
# http://jwilson.coe.uga.edu/EMAT6680/Dunbar/Assignment1/sine_curves_KD.html.
ycsb_period = os.environ.get('ycsb_period', '100')
ycsb_amplitude = os.environ.get('ycsb_amplitude', '100')
# Defaults to:
# https://docs.oracle.com/javase/7/docs/api/java/lang/Integer.html#MAX_VALUE
ycsb_operation_count = os.environ.get('ycsb_operation_count', '2147483647')

# --------------------------------------------------------------------------------------------------

wait_for_cassandra_cmd = ["sh", "-c", """
          until nc -vz {cassandra_address} {communication_port}; do
            echo "$(date) Waiting for cassandra to initialize itself."
            sleep 3
          done""".format(
    cassandra_address=application_host_ip,
    communication_port=communication_port)]

wait_for_cassandra_container = {
    "name": "ycsb-wait-for-cassandra",
    "image": image_name + ':' + image_tag,
    "securityContext": securityContext,
    "command": wait_for_cassandra_cmd}
initContainers.append(wait_for_cassandra_container)

create_structure_cmd = ["sh", "-c", """
            cqlsh --cqlversion 3.4.4 -e \
                "create keyspace ycsb WITH REPLICATION = {{
                'class' : 'SimpleStrategy', 'replication_factor': 1
                }};" \
                {cassandra_address} {communication_port} || true
            cqlsh --cqlversion 3.4.4 -k ycsb -e \
                "create table usertable (y_id varchar primary key,
                field0 varchar, field1 varchar, field2 varchar,
                field3 varchar, field4 varchar, field5 varchar,
                field6 varchar, field7 varchar, field8 varchar,
                field9 varchar);" \
                {cassandra_address} {communication_port} || true
          """.format(cassandra_address=application_host_ip,
                     communication_port=communication_port)]

create_structure_container = {
    "name": "ycsb-cassandra-create-structure",
    "image": image_name + ':' + image_tag,
    "securityContext": securityContext,
    "command": create_structure_cmd}
initContainers.append(create_structure_container)

ycsb_cassandra_load_cmd = ["sh", "-c", """
            cd /opt/ycsb
            ./bin/ycsb load cassandra2-cql -s \
                -P workloads/workloada \
                -p hosts={cassandra_host} \
                -p port={communication_port} \
                -p status.interval=1 \
                -p threadcount=20
          """.format(cassandra_host=application_host_ip,
                     communication_port=communication_port)]

ycsb_cassandra_load_container = {
    "name": "ycsb-cassandra-load",
    "image": image_name + ':' + image_tag,
    "securityContext": securityContext,
    "command": ycsb_cassandra_load_cmd}
initContainers.append(ycsb_cassandra_load_container)

ycsb_cassandra_run_cmd = """
            cd /opt/ycsb
            ycsb_wrapper.pex \
                --command \
                    "/opt/ycsb/bin/ycsb run cassandra2-cql -s \
                        -P workloads/workloada \
                        -p hosts={application_host_ip} \
                        -p port={communication_port} \
                        -target {ycsb_target} \
                        -p status.interval=1 \
                        -p threadcount={ycsb_thread_count} \
                        -p workload.peroid={ycsb_period} \
                        -p workload.amplitude={ycsb_amplitude} \
                        -p workload.phase=0 \
                        -p operationcount={ycsb_operation_count}" \
                --metric_name_prefix 'cassandra_' \
                --stderr 1 --kafka_brokers "{kafka_brokers}" \
                --kafka_topic {kafka_topic} \
                --log_level {log_level} \
                --labels "{labels}" \
                --peak_load {peak_load} \
                --load_metric_name "cassandra_ops_per_sec" \
                --slo {slo} --sli_metric_name "cassandra_read_p9999"
          """.format(
    application_host_ip=application_host_ip,
    communication_port=communication_port,
    ycsb_target=ycsb_target,
    ycsb_thread_count=ycsb_thread_count,
    ycsb_period=ycsb_period,
    ycsb_amplitude=ycsb_amplitude,
    ycsb_operation_count=ycsb_operation_count,
    kafka_brokers=wrapper_kafka_brokers,
    kafka_topic=wrapper_kafka_topic,
    log_level=wrapper_log_level,
    labels=str(wrapper_labels),
    peak_load=str(int(ycsb_target) + int(ycsb_amplitude)),
    slo=slo)

command.append(ycsb_cassandra_run_cmd)

json_format = json.dumps(pod)
print(json_format)
