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
from abc import ABC, abstractmethod
from typing import Dict, Iterable, Tuple, List

from wca.scheduler.types import ResourceType, NodeName, Resources, AppName, AppsCount, Apps

AppsOnNode = Dict[NodeName, Apps]


class DataProvider(ABC):
    @abstractmethod
    def get_nodes_capacities(self, resources: Iterable[ResourceType]) -> Dict[NodeName, Resources]:
        """Returns for >>nodes<< maximal capacities for >>resources<<"""
        pass

    @abstractmethod
    def get_apps_counts(self) -> Tuple[AppsOnNode, AppsCount]:
        """Return apps assigned to nodes and usassigned yet.
        e.g. {'node_0': {'memcached_small': 3, 'stress_ng': 5}}, {'memcached_big': 8}
        """
        raise Exception('PROPOSAL FOR NEW API')

    @abstractmethod
    def get_apps_requested_resources(self, resources: Iterable[ResourceType]) \
            -> Dict[AppName, Resources]:
        """Returns all apps definitions on the cluster"""
        pass

    @abstractmethod
    def get_dram_hit_ratio(self) -> Dict[NodeName, float]:
        """Returns dram hit ratio for each node"""
        pass

    @abstractmethod
    def get_pmem_nodes(self) -> List[NodeName]:
        """Returns Memory Mode nodes in cluster"""
        pass
