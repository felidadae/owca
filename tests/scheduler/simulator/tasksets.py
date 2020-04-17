# Copyright (c) 2020 Intel Corporation
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

from wca.scheduler.cluster_simulator import Resources
from wca.scheduler.cluster_simulator import Task
from wca.scheduler.types import CPU, MEM, WSS, MEMBW_READ, \
    MEMBW_WRITE

TASKS_3TYPES = [
    Task('cpu', Resources({CPU: 10, MEM: 50, MEMBW_READ: 2, MEMBW_WRITE: 1, WSS: 1})),
    Task('mem', Resources({CPU: 1, MEM: 100, MEMBW_READ: 1, MEMBW_WRITE: 0, WSS: 1})),
    Task('mbw', Resources({CPU: 1, MEM: 1, MEMBW_READ: 10, MEMBW_WRITE: 5, WSS: 1})),
]

TASKS_2TYPES = [
    Task('cputask', Resources({CPU: 20, MEM: 40, MEMBW_READ: 0, MEMBW_WRITE: 0, WSS: 0})),
    Task('memtask', Resources({CPU: 10, MEM: 200, MEMBW_READ: 0, MEMBW_WRITE: 0, WSS: 0})),
]

TASKS_6TYPES = [
    # Artificial workloads
    Task('cpu', Resources({CPU: 10, MEM: 50, MEMBW_READ: 2, MEMBW_WRITE: 1, WSS: 1})),
    Task('cpu2', Resources({CPU: 5, MEM: 25, MEMBW_READ: 2, MEMBW_WRITE: 0, WSS: 1})),
    Task('mem', Resources({CPU: 1, MEM: 25, MEMBW_READ: 1, MEMBW_WRITE: 0, WSS: 1})),
    Task('mem2', Resources({CPU: 1, MEM: 20, MEMBW_READ: 1, MEMBW_WRITE: 1, WSS: 1})),
    Task('mbw', Resources({CPU: 1, MEM: 1, MEMBW_READ: 10, MEMBW_WRITE: 5, WSS: 1})),
    Task('mbw2', Resources({CPU: 1, MEM: 1, MEMBW_READ: 7, MEMBW_WRITE: 1, WSS: 1})),
]
