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
from collections import defaultdict
from typing import Iterable, Dict, Tuple

from wca.scheduler.algorithms.base import divide_resources, calculate_read_write_ratio
from wca.scheduler.algorithms.hierbar import _calc_average_resources
from wca.scheduler.cluster_simulator import ClusterSimulator
from wca.scheduler.data_providers import AppsOnNode
from wca.scheduler.data_providers.score import AppsProfile, NodeType
from wca.scheduler.data_providers.score.cluster import ClusterScoreDataProvider
from wca.scheduler.types import MEMBW_READ, MEMBW_WRITE, CPU, MEM, WSS
from wca.scheduler.types import Resources, NodeName, AppsCount, ResourceType, AppName


def _is_aep(node_name, node_capacity, dimensions) -> bool:
    if MEMBW_READ in dimensions:
        assert MEMBW_WRITE in dimensions
        return calculate_read_write_ratio(node_capacity) != 1
    else:
        return node_name.startswith('aep_')


def normalize_by(resources, dimension):
    return {dim: resources[dim] / resources[dimension]
            for dim in [CPU, MEM, MEMBW_WRITE, MEMBW_READ, WSS]
            if dim in resources}


def _calculate_score_for_apps(app_requested_resources, dimensions, node_capacities,
                              normalization_dimension: ResourceType
                              ):
    """Try to implement score algorithm in Python similar to Prometheus rules."""

    # Find AEP nodes (by BW ratio or by name)
    aep_capacities = [capacity
                      for node_name, capacity
                      in node_capacities.items()
                      if _is_aep(node_name, capacity, dimensions)]

    if not aep_capacities:
        # There is not AEP nodes in the cluster, cannot calculate score at all.
        return {}

    # ... and average AEP node capacity
    aep_average_resources = _calc_average_resources(aep_capacities)
    # ... then normalized by CPU
    aep_node_profile = normalize_by(aep_average_resources, normalization_dimension)

    # For application normalized first by cpu
    app_profile_norm_by_resource = {app: normalize_by(requested_resources, normalization_dimension)
                                    for app, requested_resources
                                    in app_requested_resources.items()}
    # Then divide by AEP node profile
    app_profile_norm_by_aep = {app: divide_resources(app_profile, aep_node_profile)
                               for app, app_profile
                               in app_profile_norm_by_resource.items()}

    # and calculate score accroding following formula:
    # MEM - max(BW_READ, BW_WRITE, WSS)
    if normalization_dimension == CPU:
        def score(r):
            positive = r[MEM]
            negatives = [r[d] for d in [MEMBW_READ, MEMBW_WRITE, WSS] if d in r]
            negative = max(negatives) if negatives else 0
            return positive - negative
    elif normalization_dimension == MEM:
        def score(r):
            negatives = [r[d] for d in [CPU, MEMBW_READ, MEMBW_WRITE, WSS] if d in r]
            negative = max(negatives) if negatives else 0
            return -negative
    else:
        def score(_):
            return 0

    scores = {app: score(r) for app, r in app_profile_norm_by_aep.items()}
    return scores


class ClusterSimulatorDataProvider(ClusterScoreDataProvider):

    def __init__(self, simulator: ClusterSimulator, normalization_dimension: ResourceType = CPU):
        self.simulator = simulator
        self.normalization_dimension = normalization_dimension

    def get_nodes_capacities(self, resources: Iterable[ResourceType]) -> Dict[NodeName, Resources]:
        """Returns resource capacities for nodes."""
        r = {}
        for node in self.simulator.nodes:
            r[node.name] = {
                r: node.initial.data[r]
                for r in resources
            }

        return r

    def get_apps_counts(self) -> Tuple[AppsOnNode, AppsCount]:
        apps_per_node = {node.name: defaultdict(list) for node in
                         self.simulator.nodes}
        unassigned_tasks = defaultdict(int)
        for task in self.simulator.tasks:
            app_name = task.get_core_name()
            if task.assignment is not None:
                node = task.assignment
                apps_per_node[node.name][app_name].append(task.name)
            else:
                unassigned_tasks[app_name] += 1

        # remove defaultdicts
        apps_per_node_dict = {
            node_name: dict(apps)
            for node_name, apps in apps_per_node.items()
        }
        return apps_per_node_dict, dict(unassigned_tasks)

    def get_apps_requested_resources(self, resources: Iterable[ResourceType]) \
            -> Dict[AppName, Resources]:
        apps_requested = {}

        for task in self.simulator.tasks:
            app_name = task.get_core_name()
            apps_requested[app_name] = {r: task.requested.data[r] for r in resources}

        return apps_requested

    def get_apps_profile(self) -> AppsProfile:
        dimensions = self.simulator._get_dimensions_from_first_node()
        app_requested_resources = self.get_apps_requested_resources(dimensions)
        node_capacities = self.get_nodes_capacities(dimensions)

        scores = _calculate_score_for_apps(
            app_requested_resources, dimensions, node_capacities, self.normalization_dimension
        )
        return scores

    def get_nodes_type(self) -> Dict[NodeName, NodeType]:
        """Node type is based on BW ratio or node name."""
        dimensions = self.simulator._get_dimensions_from_first_node()
        node_capacities = self.get_nodes_capacities(dimensions)
        return {node_name: NodeType.PMEM if _is_aep(node_name, node_resource,
                                                    dimensions) else NodeType.DRAM
                for node_name, node_resource in node_capacities.items()}

    def get_dram_hit_ratio(self) -> Dict[NodeName, float]:
        """Returns dram_hit_ratio for node"""
        return defaultdict(lambda: 1)
