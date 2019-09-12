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
import math
from common import cpu, command, image_name, image_tag, cpu_list, \
    initContainers, json, securityContext, pod, wrapper_kafka_brokers, \
    wrapper_log_level, wrapper_kafka_topic, wrapper_labels, slo, volumeMounts


# ----------------------------------------------------------------------------------------------------
###
# Params which can be modified by exporting environment variables.
###

# Note: for specjbb only controller port can be assigned manually:
#   ports for backends and injectors are arbitrarily assigned.

# Port on which listen controller.
controller_host_ip = os.environ['controller_host_ip']
communication_port = os.environ.get('communication_port', '42000')

# Injection rate.
qps = os.environ.get('qps', '1000')

# Note:
# there are many specjbb config params which can be set.
# Please modify specjbb.config file to change them.

component_type = os.environ['specjbb_component_type']
if component_type != 'controller' and component_type != 'injector' and component_type != 'backend':
    raise Exception('specjbb_component_type must one of: injector, controller or backend.')
# ----------------------------------------------------------------------------------------------------


# Variables which cannot be changed differently than just by editing this file.

# Paths inside container.
config_path = '/prep_config/wca_config.raw'
specjbb_jar = '/home/specjbb/specjbb2015.jar'
specjbb_wrapper = '/usr/bin/specjbb_wrapper.pex'

threads_count = int(math.ceil(int(cpu)))

# We don't have yet good way of copying config to mesos container:
# here we just create it on the fly running shell commands inside container.
with open('specjbb/specjbb.config', 'r') as fconfig:
    config_content = "".join(fconfig.readlines())
    config_content = config_content.format(
        qps=qps,
        controller_host_ip=controller_host_ip,
        controller_listen_port=communication_port,
        config_path=config_path, threads_count=threads_count)
config_create_cmd = ["sh", "-c", """cat >{config_path} <<EOF
{config_content}
EOF
cat {config_path}""".format(config_path=config_path,
                            config_content=config_content)]

# By specifying the same group both in injector and backend
# we instruct a specjbb injector to communicate with
# the chosen backend.
controller_cmd = """java -Dspecjbb.forkjoin.workers={} \
 -Xms4g -Xmx4g -jar {} -m distcontroller -p {}""".format(
           threads_count, specjbb_jar, config_path)

# Add wrapper to controller_cmd; specjbb prints data to stderr.
controller_cmd = """{wrapper} --command '{command}' --stderr 0 \
                             --kafka_brokers {brokers} --log_level DEBUG \
                             --kafka_topic {kafka_topic} --log_level DEBUG \
                             --metric_name_prefix 'specjbb_' \
                             --labels \"{labels}\" \
                             --peak_load \"{peak_load}\" --load_metric_name \
                              \"const\" --slo {slo} --sli_metric_name \
                              specjbb_p99_total_purchase""".format(
    wrapper=specjbb_wrapper, command=controller_cmd,
    brokers=wrapper_kafka_brokers, log=wrapper_log_level,
    kafka_topic=wrapper_kafka_topic, labels=wrapper_labels,
    peak_load=qps, slo=slo)

# @TODO we should set max RAM assigned to JVM, but if set the job fails to run.
injector_cmd = """java -jar {jar} -m txinjector -p {config} -G GRP1 -J JVM_B"""\
    .format(jar=specjbb_jar, config=config_path)

backend_cmd = """
    /usr/bin/taskset -c {cpu_list} \
    java -Xms4g -Xmx4g -Xmn2g -XX:-UseBiasedLocking -XX:+UseParallelOldGC \
    -jar {jar} -m backend -p {config} -G GRP1 -J JVM_A"""\
    .format(cpu_list=cpu_list, jar=specjbb_jar, config=config_path)

volume_prep_config = {
    "name": "shared-data",
    "mountPath": "/prep_config"
}

prepare_config_container = {
    "name": "prep-config",
    "image": image_name + ":" + image_tag,
    "securityContext": securityContext,
    "command": config_create_cmd,
    "volumeMounts": [
        volume_prep_config
    ]
}
initContainers.append(prepare_config_container)
volumeMounts.append(volume_prep_config)

if component_type == 'controller':
    command.append(controller_cmd)
elif component_type == 'injector':
    command.append(injector_cmd)
elif component_type == 'backend':
    command.append(backend_cmd)

json_format = json.dumps(pod)
print(json_format)
