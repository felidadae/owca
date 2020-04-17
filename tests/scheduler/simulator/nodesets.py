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
from wca.scheduler.types import CPU, MEM, MEMBW_READ, MEMBW_WRITE, WSS

NODES_DEFINITIONS_2TYPES = dict(
    aep={CPU: 40, MEM: 1000, MEMBW_READ: 40, MEMBW_WRITE: 10, WSS: 192},
    dram={CPU: 80, MEM: 192, MEMBW_READ: 150, MEMBW_WRITE: 150, WSS: 192},
)

NODES_DEFINITIONS_3TYPES = dict(
    aep={CPU: 40, MEM: 1000, MEMBW_READ: 40, MEMBW_WRITE: 10, WSS: 256},
    sml={CPU: 48, MEM: 192, MEMBW_READ: 150, MEMBW_WRITE: 150, WSS: 192},
    big={CPU: 40, MEM: 394, MEMBW_READ: 200, MEMBW_WRITE: 200, WSS: 394}
)

NODES_DEFINITIONS_ARTIFICIAL_2DIM_2TYPES = dict(
    cpuhost={CPU: 100, MEM: 200, MEMBW_READ: 100, MEMBW_WRITE: 100},
    memhost={CPU: 50, MEM: 1000, MEMBW_READ: 100, MEMBW_WRITE: 100},
)
