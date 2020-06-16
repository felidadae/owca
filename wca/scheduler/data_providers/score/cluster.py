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

from wca.scheduler.data_providers.cluster_data_provider import ClusterDataProvider
from wca.scheduler.data_providers.score import ScoreDataProvider, AppsProfile, NodesType


@dataclass
class ClusterScoreDataProvider(ClusterDataProvider, ScoreDataProvider):
    app_profiles_query = 'app_profile'
    node_type_query = 'node_type'

    def get_apps_profile(self) -> AppsProfile:
        query_result = self.prometheus.do_query(self.app_profiles_query, use_time=True)

        return {row['metric']['app']: float(row['value'][1])
                for row in query_result}

    def get_nodes_type(self) -> NodesType:
        query_result = self.prometheus.do_query(self.node_type_query, use_time=True)
        return {row['metric']['node']: row['metric']['nodetype']
                for row in query_result}
