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
# limitations under the License

from dataclasses import dataclass
from wca.prometheus import Prometheus


@dataclass
class Queries:
    APP_WSS_TO_MEM_RATIO = 'max(max_over_time(app_wss_to_mem_ratio[3h])) by (app)'


class AppDataProvider:

    def __init__(self, prometheus: Prometheus, queries: Queries = Queries()):
        self.prometheus = prometheus
        self.queries = queries

    def get_wss_to_mem_ratio(self):
        return self._get_requested_app_metric(Queries.APP_WSS_TO_MEM_RATIO)

    def _get_requested_app_metric(self, query):
        query_result = self.prometheus.do_query(query)
        app_metrics = {}
        for row in query_result:
            app_metrics[row['metric']['app']] = float(row['value'][1])
        return app_metrics
