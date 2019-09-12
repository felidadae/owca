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
from common import command, image_name, image_tag, initContainers, json, \
    securityContext, volumeMounts, pod, cpu_list

# ----------------------------------------------------------------------------------------------------
###
# Params which can be modified by exporting environment variables.
###

# Port that Cassandra will bind to.
cassandra_port = os.environ.get('communication_port', '9042')
jmx_port = os.environ.get('jmx_port', '7199')
storage_port = os.environ.get('storage_port', '7000')
# ----------------------------------------------------------------------------------------------------

volume = {"name": "shared-data"}

prep_cmd = ["sh", "-c",
            """
cd /prep_config && \
cp /etc/cassandra/cassandra.yaml . && \
cp /etc/cassandra/cassandra-env.sh .  \
&& sed -i 's/native_transport_port: 9042/native_transport_port: \
{cassandra_port}/' cassandra.yaml \
&& sed -i "s/storage_port: 7000/storage_port: {storage_port}/" cassandra.yaml \
&& sed -i 's/JMX_PORT=\"7199\"/JMX_PORT=\"{jmx_port}\"/' cassandra-env.sh
""".format(
                cassandra_port=cassandra_port,
                storage_port=storage_port,
                jmx_port=jmx_port)]

volume_prep_config = {
    "name": "shared-data",
    "mountPath": "/prep_config"}

initContainer = {
    "name": "prep-config",
    "image": image_name + ":" + image_tag,
    "securityContext": securityContext,
    "command": prep_cmd,
    "volumeMounts": [volume_prep_config]
}

initContainers.append(initContainer)
volumeMounts.append(volume_prep_config)

max_heap_size = int(os.getenv('ram', '1')) * 1024
max_heap_size = int(2.0/3.0 * max_heap_size)
heap_newsize = int(float(max_heap_size) / 5.0)

cmd = ("cp /prep_config/cassandra.yaml /etc/cassandra &&"
       "cp /prep_config/cassandra-env.sh /etc/cassandra && "
       "MAX_HEAP_SIZE=\"{}M\" HEAP_NEWSIZE=\"{}M\" "
       "CASSANDRA_CONFIG=\"/etc/cassandra\" "
       "/usr/bin/taskset -c {} /docker-entrypoint.sh".format(
        max_heap_size, heap_newsize, cpu_list))
command.append(cmd)

json_format = json.dumps(pod)
print(json_format)
