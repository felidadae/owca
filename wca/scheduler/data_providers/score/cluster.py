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
from dataclasses import dataclass
from typing import Dict

from wca.scheduler.data_providers.cluster_data_provider import ClusterDataProvider
from wca.scheduler.data_providers.score import ScoreDataProvider, AppsProfile, NodeType


@dataclass
class ClusterScoreDataProvider(ClusterDataProvider, ScoreDataProvider):
    app_profiles_query = 'app_profile'
    node_type_query = 'node_type{nodename=%r}'
    nodes_types_query = 'node_type'

    def update(self):
        super().update()
        self.apps_profile = self.get_apps_profile()
        self.nodes_types = self.get_nodes_types()

    def get_apps_profile(self) -> AppsProfile:
        query_result = self.prometheus.do_query(self.app_profiles_query, use_time=True)

        return {row['metric']['app']: float(row['value'][1])
                for row in query_result}

    # @TODO should be removed
    def get_node_type(self, node) -> NodeType:
        query = self.node_type_query % node
        query_result = self.prometheus.do_query(query, use_time=True)
        if len(query_result) > 0:
            node_type = query_result[0]['metric']['nodetype']
            if node_type == NodeType.DRAM:
                return NodeType.DRAM
            elif node_type == NodeType.PMEM:
                return NodeType.PMEM
        else:
            return NodeType.UNKNOWN

    def get_nodes_types(self) -> Dict[str, NodeType]:
        query = self.nodes_types_query
        query_result = self.prometheus.do_query(query, use_time=True)
        assert len(query_result) > 0

        nodes_types = {}
        for single_result in query_result:
            node_type = single_result['metric']['nodetype']
            node_name = single_result['metric']['nodename']

            if node_type == NodeType.DRAM:
                nodes_types[node_name] = NodeType.DRAM
            elif node_type == NodeType.PMEM:
                nodes_types[node_name] = NodeType.PMEM
            else:
                nodes_types[node_name] = NodeType.UNKNOWN

        return nodes_types
