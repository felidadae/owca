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
from wca.scheduler.prometheus import Prometheus
from wca.scheduler.types import (
        Resources, ResourceType, NodeName, AppName,
        NodeCapacities, AppsCount)

log = logging.getLogger(__name__)


@dataclass
class Queries:
    NODES_PMM_MEMORY_MODE: str = 'sum(platform_mem_mode_size_bytes) by (nodename) != 0'
    MEMBW_CAPACITY_READ: str = 'sum(platform_nvdimm_read_bandwidth_bytes_per_second) by (nodename)'
    MEMBW_CAPACITY_WRITE: str =\
        'sum(platform_nvdimm_write_bandwidth_bytes_per_second) by (nodename)'
    NODES_DRAM_HIT_RATIO: str = 'platform_dram_hit_ratio'

    NODE_CAPACITY_MEM_WSS: str =\
        'sum(platform_dimm_total_size_bytes{dimm_type="ram"}) by (nodename)'
    NODE_CAPACITY_DRAM_MEMBW: str = 'platform_dimm_speed_bytes_per_second'

    APP_REQUESTED_RESOURCES_QUERY_MAP: Dict[ResourceType, str] = field(default_factory=lambda: {
            ResourceType.CPU: 'max(max_over_time(task_requested_cpus[3h])) by (app)',
            ResourceType.MEM: 'max(max_over_time(task_requested_mem_bytes[3h])) by (app)',
            ResourceType.MEMBW_READ:
            'max(max_over_time(task_membw_reads_bytes_per_second[3h])) by (app)',
            ResourceType.MEMBW_WRITE:
            'max(max_over_time(task_membw_writes_bytes_per_second[3h])) by (app)',
            ResourceType.WSS: 'max(max_over_time(task_wss_referenced_bytes[3h])) by (app)',
    })


def _convert_k8s_memory_capacity(memory: str) -> float:
    """ return as GB """
    # TODO: Consider if K8s return memory only in 'Ki' unit.
    assert memory.endswith('Ki')
    return int((float(int(memory[:-2]) * _MEMORY_UNITS['Ki'])) / 1e9)


class MissingBasicResources(Exception):
    pass


class WSSWithoutMemoryBandwidth(Exception):
    pass


@dataclass
class ClusterDataProvider(DataProvider):
    kubeapi: Kubeapi
    prometheus: Prometheus
    queries: Optional[Queries] = Queries()

    def _get_nodes_capacities_from_query(
            self, nodes: List[NodeName],
            resources: List[ResourceType], query: str) -> NodeCapacities:

        node_capacities = {node: {} for node in nodes}

        query_result = self.prometheus.do_query(query)
        for row in query_result:
            node = row['metric']['nodename']
            if node in nodes:
                value = float(row['value'][1])
                for resource in resources:
                    node_capacities[node][resource] = int(value)
            else:
                continue

        return node_capacities

    def _get_membw_and_wss_node_capacities(
            self, nodes: List[NodeName], memory_node_capacities: NodeCapacities,
            gather_wss: bool) -> NodeCapacities:

        # Check which nodes have PMem (Memory Mode).
        query_result = self.prometheus.do_query(self.queries.NODES_PMM_MEMORY_MODE)
        nodes_with_pmm = []
        for row in query_result:
            nodes_with_pmm.append(row['metric']['nodename'])

        # Every other node should be DRAM only.
        nodes_with_dram = list(nodes - nodes_with_pmm)

        node_capacities = {node: {} for node in nodes}

        # Read Memory Bandwidth from PMem nodes.
        if len(nodes_with_pmm) > 0:

            membw_read_capacities = self._get_nodes_capacities_from_query(
                    nodes_with_pmm, [ResourceType.MEMBW_READ],
                    self.queries.MEMBW_CAPACITY_READ)

            membw_write_capacities = self._get_nodes_capacities_from_query(
                    nodes_with_pmm, [ResourceType.MEMBW_WRITE],
                    self.queries.MEMBW_CAPACITY_WRITE)

            for node in nodes_with_pmm:
                node_capacities[node] = {
                    **membw_read_capacities[node], **membw_write_capacities[node]}

            if gather_wss:
                wss_capacities = self._get_nodes_capacities_from_query(
                        nodes_with_pmm, [ResourceType.WSS],
                        self.queries.NODE_CAPACITY_MEM_WSS)

                for node in nodes_with_pmm:
                    node_capacities[node] = {
                        **node_capacities[node], **wss_capacities[node]}

        # Read Memory Bandwidth from PMem nodes.
        if len(nodes_with_dram) > 0:
            membw_dram_capacities = self._get_nodes_capacities_from_query(
                nodes_with_dram, [ResourceType.MEMBW_READ, ResourceType.MEMBW_WRITE],
                self.queries.NODE_CAPACITY_DRAM_MEMBW)

            for node in nodes_with_dram:
                node_capacities[node] = {**node_capacities[node], **membw_dram_capacities[node]}

            if gather_wss:
                for node in nodes_with_dram:
                    node_capacities[node][ResourceType.WSS] = memory_node_capacities[node]

        return node_capacities

    def get_nodes_capacities(self, resources: Iterable[ResourceType]) -> Dict[NodeName, Resources]:
        # Check if basic resources are needed. If not, something is wrong.
        if ResourceType.CPU not in resources or ResourceType.MEM not in resources:
            raise MissingBasicResources

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

        nodes = node_capacities.keys()

        if ResourceType.MEMBW_READ in resources and ResourceType.MEMBW_WRITE in resources:
            calculate_wss = ResourceType.WSS in resources
            memory_node_capacities = {
                    node: node_capacities[node][ResourceType.MEM]
                    for node in nodes}
            membw_and_wss_node_capacities = self._get_membw_and_wss_node_capacities(
                    nodes, memory_node_capacities, calculate_wss)

            node_capacities = {
                node: {**node_capacities[node], **membw_and_wss_node_capacities[node]}
                for node in nodes}

        elif ResourceType.WSS in resources:
            raise WSSWithoutMemoryBandwidth(
                    'Cannot calculate WSS without MEMBW READS and WRITES!')

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
            dram_hit_ratio_per_node[row['metric']['nodename']] = float(row['value'][1])

        return dram_hit_ratio_per_node
