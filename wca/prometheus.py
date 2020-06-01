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
import requests

from dataclasses import dataclass
from typing import Optional

from wca.config import Numeric
from wca.security import SSL, HTTPSAdapter


QUERY_PATH = "/api/v1/query"
URL_TPL = '{prometheus_ip}{path}?query={name}'


class PrometheusDataProviderException(Exception):
    pass


@dataclass
class Prometheus:
    host: str
    port: int
    timeout: Optional[Numeric(1, 60)] = 1.0
    ssl: Optional[SSL] = None
    time: Optional[str] = None  # Evaluation timestamp.

    def do_query(self, query: str, use_time: bool = True):
        """ Implements: https://prometheus.io/docs/prometheus/2.16/querying/api/#instant-queries"""
        url = URL_TPL.format(
                prometheus_ip='{}:{}'.format(self.host, str(self.port)),
                path=QUERY_PATH,
                name=query)

        if self.time and use_time:
            url += '&time={}'.format(self.time)

        try:
            if self.ssl:
                s = requests.Session()
                s.mount(self.ip, HTTPSAdapter())
                response = s.get(
                        url,
                        timeout=self.timeout,
                        verify=self.ssl.server_verify,
                        cert=self.ssl.get_client_certs())
            else:
                response = requests.get(url, timeout=self.timeout)
                response.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise PrometheusDataProviderException(e)

        return response.json()['data']['result']
