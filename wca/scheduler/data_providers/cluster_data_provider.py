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
import logging

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Dict, Optional, List, Tuple

from wca.resources import _MEMORY_UNITS
from wca.scheduler.data_providers import DataProvider, AppsOnNode
from wca.scheduler.kubeapi import Kubeapi
from wca.prometheus import Prometheus
from wca.scheduler.types import (
        Resources, ResourceType, NodeName, AppName,
        NodeCapacities, AppsCount)

log = logging.getLogger(__name__)


@dataclass
class Queries:
    """ For defaults to work, it is required to upload prometheus rules >>score<<, otherwise
        define proper queries in the configuration file of wca-scheduler
        overwriting this values.

        ResourceType.CPU and ResourceType.MEM are not present in NODE_CAPACITY_RESOURCES_QUERY_MAP
        dict as this special basic types of resources are fetched from kubeabi.
    """

    APP_REQUESTED_RESOURCES_QUERY_MAP: Dict[ResourceType, str] = field(default_factory=lambda: {
        ResourceType.CPU: 'app_cpu',
        ResourceType.MEM: 'app_mem',
        ResourceType.MEMBW_READ: 'app_mbw_read',
        ResourceType.MEMBW_WRITE: 'app_mbw_write',
        ResourceType.MEMBW_FLAT: 'app_mbw_flat',
        ResourceType.WSS: 'app_wss',
    })
    NODE_CAPACITY_RESOURCES_QUERY_MAP: Dict[ResourceType, str] = field(default_factory=lambda: {
        # CPU and MEM are fetched directly from kubeapi.
        ResourceType.MEMBW_READ: 'node_capacity{dim="mbw_read"}',
        ResourceType.MEMBW_WRITE: 'node_capacity{dim="mbw_write"}',
        ResourceType.MEMBW_FLAT: 'node_capacity{dim="mbw_flat"}',
        ResourceType.WSS: 'node_capacity{dim="wss"}',
    })

    NODES_PMM_MEMORY_MODE: str = 'sum(platform_mem_mode_size_bytes) by (node) != 0'
    NODES_DRAM_HIT_RATIO: str = 'platform_dram_hit_ratio'


def _convert_k8s_memory_capacity(memory: str) -> float:
    """ return as GB """
    # TODO: Consider if K8s return memory only in 'Ki' unit.
    assert memory.endswith('Ki')
    return int((float(int(memory[:-2]) * _MEMORY_UNITS['Ki'])) / 1e9)


class MissingBasicResources(Exception):
    pass


class MissingQueryForResource(Exception):
    pass


@dataclass
class ClusterDataProvider(DataProvider):
    kubeapi: Kubeapi
    prometheus: Prometheus
    queries: Optional[Queries] = Queries()

    def get_pmem_nodes(self) -> List[str]:
        """Check which nodes have PMem (Memory Mode)"""
        query_result = self.prometheus.do_query(self.queries.NODES_PMM_MEMORY_MODE)
        nodes_with_pmm = []
        for row in query_result:
            nodes_with_pmm.append(row['metric']['node'])
        return nodes_with_pmm

    def _get_nodes_capacities_from_query(
            self, nodes: List[NodeName],
            resources: List[ResourceType], query: str) -> NodeCapacities:

        node_capacities = {node: {} for node in nodes}

        query_result = self.prometheus.do_query(query)
        for row in query_result:
            node = row['metric']['node']
            if node in nodes:
                value = float(row['value'][1])
                for resource in resources:
                    node_capacities[node][resource] = int(value)
            else:
                continue

        return node_capacities

    def get_nodes_capacities(self, resources: Iterable[ResourceType]) -> Dict[NodeName, Resources]:
        if ResourceType.CPU not in resources or ResourceType.MEM not in resources:
            raise MissingBasicResources('Resources (CPU, MEM) are required.')

        # CPU and Memory capacity source.
        kubeapi_nodes_data = list(self.kubeapi.request_kubeapi('/api/v1/nodes')['items'])

        # Get nodes names and basic resources.
        node_capacities = {
                node['metadata']['name']: {
                    ResourceType.CPU: float(node['status']['capacity']['cpu']),
                    ResourceType.MEM: _convert_k8s_memory_capacity(
                        node['status']['capacity']['memory']),
                    }
                for node in kubeapi_nodes_data
                if 'node-role.kubernetes.io/master' not in node['metadata']['labels']
        }

        nodes = list(node_capacities.keys())

        def update_subdicts(main, sub):
            for key in main:
                main[key] = {**main[key], **sub[key]}
            return None

        for resource in resources:
            if resource in (ResourceType.CPU, ResourceType.MEM):
                log.debug('Skipping resource {} as pulled '
                          'from kubeapi data source'.format(resource))
                continue
            elif resource not in self.queries.NODE_CAPACITY_RESOURCES_QUERY_MAP:
                raise MissingQueryForResource('Missing query for'
                                              ' node capacity for resource {}'.format(resource))

            nodes_resource_capacity = self._get_nodes_capacities_from_query(
                nodes, [resource],
                self.queries.NODE_CAPACITY_RESOURCES_QUERY_MAP[resource])
            update_subdicts(node_capacities, nodes_resource_capacity)

        log.debug('Node capacities: %r' % node_capacities)

        return node_capacities

    def get_apps_counts(self) -> Tuple[AppsOnNode, AppsCount]:

        unassigned_apps = defaultdict(int)

        nodes_data = list(self.kubeapi.request_kubeapi('/api/v1/nodes')['items'])
        node_names = [
            node['metadata']['name']for node in nodes_data
            if 'node-role.kubernetes.io/master' not in node['metadata']['labels']]

        assigned_apps = {}
        for node_name in node_names:
            assigned_apps[node_name] = {}

        for namespace in self.kubeapi.monitored_namespaces:
            pods_data = list(self.kubeapi.request_kubeapi(
                '/api/v1/namespaces/{}/pods'.format(namespace))['items'])

            for pod in pods_data:
                name = pod['metadata']['name']
                app = pod['metadata']['labels'].get('app')

                if not app:
                    log.warning('Unknown app label for pod %r' % name)
                    continue

                node = pod['spec'].get('nodeName')
                host_ip = pod['status'].get('hostIP')

                # Check if Pod is assigned.
                if not (node and host_ip):
                    unassigned_apps[app] += 1
                else:
                    if app not in assigned_apps[node]:
                        assigned_apps[node][app] = []

                    assigned_apps[node][app].append(name)

        # remove default dicts
        assigned_apps = {k: dict(v) for k, v in assigned_apps.items()}
        log.debug('Assigned apps: %r' % assigned_apps)
        log.debug('Unassigned apps: %r' % unassigned_apps)

        return assigned_apps, dict(unassigned_apps)

    def get_apps_requested_resources(self, resources: Iterable[ResourceType]) \
            -> Dict[AppName, Resources]:
        app_requested_resources = defaultdict(lambda: defaultdict(float))

        for resource in resources:
            query_result = self.prometheus.do_query(
                    self.queries.APP_REQUESTED_RESOURCES_QUERY_MAP[resource])
            for result in query_result:
                app = result['metric'].get('app')
                value = float(result['value'][1])
                if app:
                    app_requested_resources[app][resource] = float(value)

        app_requested_resources = {k: dict(v) for k, v in app_requested_resources.items()}
        log.debug('Resources requested by apps: %r' % app_requested_resources)
        return app_requested_resources

    def get_dram_hit_ratio(self) -> Dict[NodeName, float]:
        query_result = self.prometheus.do_query(self.queries.NODES_DRAM_HIT_RATIO)
        dram_hit_ratio_per_node = {}
        for row in query_result:
            dram_hit_ratio_per_node[row['metric']['node']] = float(row['value'][1])

        return dram_hit_ratio_per_node
