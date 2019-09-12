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
from common import command, json, pod, cpu_list


# ----------------------------------------------------------------------------------------------------
###
# Params which can be modified by exporting environment variables.
###

# Port that stressed application listens on.
communication_port = os.environ.get('communication_port', 11211)

# twemcache worker threads count
worker_threads = int(os.environ.get('worker_threads') or 1)
max_memory = int(os.environ.get('max_memory') or 1024)

# ----------------------------------------------------------------------------------------------------


cmd = """/usr/bin/taskset -c {cpu_list} twemcache --prealloc --hash-power=20 --max-memory={max_memory} \
--port={communication_port} --eviction-strategy=2 --verbosity=4 \
--threads={worker_threads} --backlog=128 -u twemcache \
--maximize-core-limit --slab-size=1048576 """.format(
    cpu_list=cpu_list,
    communication_port=communication_port,
    worker_threads=worker_threads,
    max_memory=max_memory)
command.append(cmd)

json_format = json.dumps(pod)
print(json_format)
