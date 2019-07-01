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
from common import application, application_host_ip, command, json, \
    pod, wrapper_kafka_brokers, wrapper_log_level, wrapper_kafka_topic, \
    wrapper_labels, slo

# ----------------------------------------------------------------------------------------------------
###
# Params which can be modified by exporting environment variables.
###

# Port that stressed application listens on.
communication_port = os.environ.get('communication_port', 11211)

# @TODO Variables rpcperf_rate|thread_count|period
#   |amlitude|connections are not used
#   in the code (their values are not injected into config files).
# --
# Number of requests per second to generate (default:
# 1000; if `rpcperf_amplitude` and
# `rpcperf_period` are set - maximum of a sine curve).
# rpcperf_rate = os.environ.get('rpcperf_rate', '1000')
# --
# Number of threads used to generate traffic.
# rpcperf_thread_count = os.environ.get('rpcperf_thread_count', '1')
# --
# rpcperf_period and rpcperf_amplitiude are used to
# generate non-constant number of QpS;
# see:
# http://jwilson.coe.uga.edu/EMAT6680/Dunbar/Assignment1/sine_curves_KD.html
# rpcperf_period = os.environ.get('rpcperf_period', '100')
# rpcperf_amplitiude = os.environ.get('rpcperf_amplitiude', '100')
# --
# Number of connections per thread.
# rpcperf_connections = os.environ.get('rpcperf_connections', '1')

# ----------------------------------------------------------------------------------------------------


# Name of a protocol used to generate load.
if application == 'twemcache':
    rpcperf_protocol = 'memcache'
elif application == 'redis':
    rpcperf_protocol = 'redis'
else:
    raise Exception("Not supported application type >>{application}<<.".format(
                                                                application))

# SLI and Load base metrics.
sli_metric_name = "{application}_p99".format(application=application)
load_metric_name = "{application}_rate".format(application=application)

cmd = ("""rpc_perf_wrapper.pex \
--command 'rpc-perf --config /etc/rpc-perf.toml -p {protocol} \
--server {ip}:{port}' \
--log_level {log_level} \
--stderr 0 \
--labels '{labels}' \
--metric_name_prefix '{application}_' \
--kafka_topic {kafka_topic} \
--kafka_brokers {kafka_brokers} \
--peak_load '{peak_load}' --load_metric_name '{load_metric_name}' \
--slo {slo} --sli_metric_name '{sli_metric_name}'
""").format(protocol=rpcperf_protocol,
            ip=application_host_ip,
            port=communication_port,
            log_level=wrapper_log_level,
            labels=json.dumps(wrapper_labels),
            kafka_topic=wrapper_kafka_topic,
            kafka_brokers=wrapper_kafka_brokers,
            application=application,
            load_metric_name=load_metric_name,
            peak_load=str(15000),
            slo=slo,
            sli_metric_name=sli_metric_name)

# if K8s
command.append(cmd)
json_format = json.dumps(pod)
print(json_format)
