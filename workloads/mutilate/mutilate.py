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
from common import application, application_host_ip, command, image_name, image_tag, \
    initContainers, json, securityContext, pod, wrapper_kafka_brokers, \
    wrapper_log_level, wrapper_kafka_topic, wrapper_labels, slo

# ----------------------------------------------------------------------------------------------------
###
# Params which can be modified by exporting environment variables.
###

communication_port = int(os.environ.get('communication_port') or 11211)
qps = int(os.environ.get('qps') or 350000)
sli_percentile = int(os.environ.get('sli_percentile') or 99)
time = int(os.environ.get('time') or 90)
threads = int(os.environ.get('threads') or 8)
connections = int(os.environ.get('connections') or 24)
warmup_time = int(os.environ.get('warmup_time') or 30)
# Tells if scan mode is used
mutilate_scan = bool(os.environ.get('mutilate_scan') or False)
# ----------------------------------------------------------------------------------------------------

mutilate_warmup_cmd = ["sh", "-c", """/mutilate/mutilate -s {}:{} --time={} \
-R 40000 --update=1 --threads=4 -C 4""".format(application_host_ip,
                                               communication_port, warmup_time)]

mutilate_warmup_container = {
    "name": "mutilate-warmup",
    "image": image_name + ":" + image_tag,
    "securityContext": securityContext,
    "command": mutilate_warmup_cmd
}
initContainers.append(mutilate_warmup_container)

if mutilate_scan:
    mutilate_cmd = """ \"while true; do /mutilate/mutilate -s {}:{} \
    --scan {}:{}:0 --time={} --update=0.01 --threads={} -c {}; done\" """.format(
        application_host_ip, communication_port, qps, qps, time, threads, connections)
else:
    mutilate_cmd = """ \"while true; do /mutilate/mutilate -s {}:{} \
    -Q {} --time={} --update=0.01 --threads={} -c {}; done\" """.format(
        application_host_ip, communication_port, qps, time, threads, connections)

mutilate_run_cmd = """/usr/bin/mutilate_wrapper.pex --command '{mutilate_cmd}' \
--metric_name_prefix {metric_name_prefix} \
--stderr 0 --kafka_brokers '{kafka_brokers}' --kafka_topic {kafka_topic} \
--log_level {log_level} \
--slo {slo} --sli_metric_name {application}_read_p{sli_percentile} \
--peak_load {peak_load} --load_metric_name {application}_qps \
--subprocess_shell \
--labels \"{labels}\"""".format(
    mutilate_cmd=mutilate_cmd,
    application=application,
    metric_name_prefix=application + "_",
    kafka_brokers=wrapper_kafka_brokers,
    kafka_topic=wrapper_kafka_topic,
    log_level=wrapper_log_level,
    labels=wrapper_labels,
    slo=str(slo), peak_load=qps,
    sli_percentile=sli_percentile)

command.append(mutilate_run_cmd)

json_format = json.dumps(pod)
print(json_format)
