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
from common import application_host_ip, command, image_name, \
    initContainers, json, securityContext, pod, volumeMounts, cpu_list


# ----------------------------------------------------------------------------------------------------
###
# Params which can be modified by exporting environment variables.
###

communication_port = os.environ.get('communication_port', 11211)
# ----------------------------------------------------------------------------------------------------

# Preparing config file.
cmdline_config = ["sh", "-c",
                  ("cd /prep_config && "
                   "cp /etc/redis.conf . && "
                   "sed -i 's/logfile.*/logfile \"\"/' \
                   redis.conf && "
                   "sed -i \"s/port 6379/port {communication_port}/\" \
                   redis.conf && "
                   "sed -i \"s/bind 127.0.0.1/bind {application_host_ip}/\" \
                   redis.conf ".format(communication_port=communication_port,
                                       application_host_ip=application_host_ip
                                       ))]

volume_prep_config = {
    "name": "shared-data",
    "mountPath": "/prep_config"
}

initContainer = {
    "name": "prep-config",
    "image": image_name,
    "securityContext": securityContext,
    "command": cmdline_config,
    "volumeMounts": [
        volume_prep_config
    ]
}
initContainers.append(initContainer)


volumeMounts.append(volume_prep_config)

command.append("/usr/bin/taskset -c {} redis-server /prep_config/redis.conf".format(cpu_list))

json_format = json.dumps(pod)
print(json_format)
