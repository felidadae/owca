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
from common import application, command, json, pod, wrapper_kafka_brokers, wrapper_log_level, \
    wrapper_kafka_topic, wrapper_labels, slo


# ----------------------------------------------------------------------------------------------------
###
# Params which can be modified by exporting environment variables.
###

timeout = int(os.environ.get('timeout') or 30)
stressor = os.environ.get('stressor') or 'stream'
number_workers = int(os.environ.get('number_workers') or 1)
# ----------------------------------------------------------------------------------------------------

stress_ng_cmd = ('"while true; do stress-ng --{}={} --timeout={}'
                 ' --metrics --metrics-brief -Y /dev/stdout;done"').format(
                    stressor, number_workers, timeout)

stress_ng_run_cmd = """/usr/bin/stress_ng_wrapper.pex --command '{stress_ng_cmd}' \
--metric_name_prefix {metric_name_prefix} \
--stderr 1 --kafka_brokers '{kafka_brokers}' --kafka_topic {kafka_topic} \
--log_level {log_level} \
--subprocess_shell \
--labels '{labels}' \
--slo {slo} --sli_metric_name '{sli_metric_name}'""".format(
    stress_ng_cmd=stress_ng_cmd,
    application=application,
    metric_name_prefix=application + "_",
    kafka_brokers=wrapper_kafka_brokers,
    kafka_topic=wrapper_kafka_topic,
    log_level=wrapper_log_level,
    labels=json.dumps(wrapper_labels),
    slo=slo,
    sli_metric_name='stress_ng_bogo_ops_per_second_usr_sys_time')

command.append(stress_ng_run_cmd)

json_format = json.dumps(pod)
print(json_format)
