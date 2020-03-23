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
from typing import Tuple, Optional, List, Dict
import statistics

from wca.logger import TRACE
from wca.scheduler.algorithms import RescheduleResult
from wca.scheduler.algorithms.base import (
        BaseAlgorithm, QueryDataProviderInfo, DEFAULT_DIMENSIONS, subtract_resources,
        sum_resources, calculate_read_write_ratio, enough_resources_on_node,
        get_nodes_used_resources)
from wca.scheduler.algorithms.fit import app_fits
from wca.scheduler.data_providers.score import ScoreDataProvider, NodeType, AppsProfile
from wca.scheduler.types import (AppName, NodeName, ResourceType, TaskName, Resources)

log = logging.getLogger(__name__)


MIN_APP_PROFILES = 2

RescheduleApps = Dict[AppName, Dict[NodeName, List[TaskName]]]
ConsiderApps = Dict[AppName, List[TaskName]]


class Score(BaseAlgorithm):

    def __init__(self, data_provider: ScoreDataProvider,
                 dimensions: List[ResourceType] = DEFAULT_DIMENSIONS,
                 max_node_score: float = 10.,
                 alias: str = None,
                 score_target: Optional[float] = None,
                 ):
        super().__init__(data_provider, dimensions, max_node_score, alias)
        self.score_target = score_target

    def app_fit_node(self, node_name: NodeName, app_name: str,
                     data_provider_queried: QueryDataProviderInfo) -> Tuple[bool, str]:
        log.info('Trying to filter node %r for %r ', node_name, app_name)
        nodes_capacities, assigned_apps, apps_spec, _ = data_provider_queried

        fits, message, metrics = app_fits(
            node_name, app_name, self.dimensions,
            nodes_capacities, assigned_apps, apps_spec)

        self.metrics.extend(metrics)

        return fits, message

    def app_fit_nodes(self, node_names: List[NodeName], app_name: str,
                      data_provider_queried: QueryDataProviderInfo) \
            -> Tuple[List[NodeName], Dict[NodeName, str]]:

        apps_profile = self.calculate_apps_profile(data_provider_queried, nodes_types)
        apps_profile = self.data_provider_get_apps_profile()
        nodes_types: Dict[NodeName, NodeType] = self.data_provider.get_nodes_types()

        if log.getEffectiveLevel() <= TRACE:
            log.log(TRACE, '[Filter:PMEM specific] apps_profile: %s', str(apps_profile))
            log.log(TRACE, '[Filter:PMEM specific] nodes_types: %s', str(nodes_types))

        pmem_nodes_names = [node_name for node_name, node_type in nodes_types.items()
                            if node_type == NodeType.PMEM]
        dram_nodes_names = [node_name for node_name, node_type in nodes_types.items()
                            if node_type != NodeType.PMEM]

        if set(pmem_nodes_names).intersection(set(node_names)):
            if self.app_fit_node_type(app_name, NodeType.PMEM, apps_profile)[0]:
                return pmem_nodes_names, \
                            {node_name: 'App match PMEM and PMEM available!'
                             for node_name in dram_nodes_names}
        return node_names, {}

    def priority_for_node(self, node_name: str, app_name: str,
                          data_provider_queried: QueryDataProviderInfo) -> float:
        return 0.0

    def reschedule(self) -> RescheduleResult:
        apps_on_node, _ = self.data_provider.get_apps_counts()

        reschedule: RescheduleApps = {}
        consider: RescheduleApps = {}

        for node in apps_on_node:
            node_type = self.data_provider.get_node_type(node)
            for app in apps_on_node[node]:

                app_correct_placement, _ = self.app_fit_node_type(app, node)

                if not app_correct_placement:

                    # Apps, that no matching PMEM node, should be deleted.
                    if node_type == NodeType.PMEM:
                        if app not in reschedule:
                            reschedule[app] = {}
                        if node not in reschedule[app]:
                            reschedule[app][node] = []

                        reschedule[app][node] = apps_on_node[node][app]

                    # Apps, that matching PMEM but are in DRAM, should be considered to reschedule.
                    elif node_type == NodeType.DRAM:
                        if app not in consider:
                            consider[app] = {}
                        if node not in consider[app]:
                            consider[app][node] = []

                        consider[app][node] = apps_on_node[node][app]

        result = self.get_tasks_to_reschedule(reschedule, consider)

        return result

    def get_tasks_to_reschedule(self, reschedule: RescheduleApps,
                                consider: RescheduleApps) -> RescheduleResult:
        apps_spec = self.data_provider.get_apps_requested_resources(self.dimensions)

        apps_on_node, _ = self.data_provider.get_apps_counts()

        apps_on_pmem_nodes = {
                node: apps
                for node, apps in apps_on_node.items()
                if self.data_provider.get_node_type(node) == NodeType.PMEM
                }

        pmem_nodes_used_resources = get_nodes_used_resources(
                self.dimensions, apps_on_pmem_nodes, apps_spec)

        result: RescheduleResult = []

        # Free PMEM nodes resources.
        for app in reschedule:
            for node in reschedule[app]:

                if node in pmem_nodes_used_resources:
                    for task in reschedule[app][node]:

                        pmem_nodes_used_resources[node] =\
                            subtract_resources(
                                    pmem_nodes_used_resources[node],
                                    apps_spec[app])

                        result.append(task)
                else:
                    raise RuntimeError('Capacities of %r not available!', node)

        apps_profile = self.data_provider.get_apps_profile()
        sorted_apps_profile = sorted(apps_profile.items(), key=lambda x: x[1], reverse=True)

        # Start from the newest tasks.
        sorted_consider = {}
        for app, _ in sorted_apps_profile:
            if app in consider:
                sorted_consider[app] = []
                for node in consider[app]:
                    sorted_consider[app].extend(consider[app][node])
                sorted_consider[app] = sorted(sorted_consider[app], reverse=True)

        nodes_capacities = self.data_provider.get_nodes_capacities(self.dimensions)
        pmem_nodes_capacities = {
                node: capacities
                for node, capacities in nodes_capacities.items()
                if self.data_provider.get_node_type(node) == NodeType.PMEM
        }

        pmem_nodes_membw_ratio = {
                node: calculate_read_write_ratio(capacities)
                for node, capacities in pmem_nodes_capacities.items()
        }

        for app, _ in sorted_apps_profile:
            if app in sorted_consider:
                for task in sorted_consider[app]:
                    can_be_rescheduled = False
                    for node in pmem_nodes_used_resources:
                        # If app fit on add task to reschedule and continue with next.
                        requested_and_used = sum_resources(
                                pmem_nodes_used_resources[node], apps_spec[app])

                        enough_resources, _, _ = enough_resources_on_node(
                                nodes_capacities[node],
                                requested_and_used,
                                pmem_nodes_membw_ratio[node])

                        if enough_resources:
                            can_be_rescheduled = True
                            result.append(task)
                            pmem_nodes_used_resources[node] = requested_and_used
                            continue

                    if not can_be_rescheduled:
                        # TODO: Add metric.
                        log.warning('[Reschedule] %r cannot be rescheduled to PMEm node: '
                                    'There is no more space!', task)

        return result

    def app_fit_node_type(self, app_name: AppName, node_type: NodeType,
                          apps_profile: Dict[AppName, float]) -> Tuple[bool, str]:

        app_type = _get_app_node_type(apps_profile, app_name, self.score_target)

        if node_type != app_type:
            return False, '%r not prefered for %r type of node' % (app_name, node_type)

        return True, ''


def _get_app_node_type(
        apps_profile: AppsProfile, app_name: AppName,
        score_target: Optional[float] = None) -> NodeType:

    if len(apps_profile) > MIN_APP_PROFILES:
        if score_target:
            if app_name in apps_profile and apps_profile[app_name] >= score_target:
                return NodeType.PMEM
        else:
            sorted_apps_profile = sorted(apps_profile.items(), key=lambda x: x[1], reverse=True)
            if app_name == sorted_apps_profile[0][0]:
                return NodeType.PMEM

    return NodeType.DRAM


class Score2(Score):
    def app_fit_nodes(self, node_names: List[NodeName], app_name: str,
                      data_provider_queried: QueryDataProviderInfo) \
            -> Tuple[List[NodeName], Dict[NodeName, str]]:

        nodes_types: Dict[NodeName, NodeType] = self.data_provider.get_nodes_types()
        apps_profile = self.calculate_apps_profile(data_provider_queried, nodes_types)

        if log.getEffectiveLevel() <= TRACE:
            log.log(TRACE, '[Filter:PMEM specific] apps_profile: %s', str(apps_profile))
            log.log(TRACE, '[Filter:PMEM specific] nodes_types: %s', str(nodes_types))

        pmem_nodes_names = [node_name for node_name, node_type in nodes_types.items()
                            if node_type == NodeType.PMEM]
        dram_nodes_names = [node_name for node_name, node_type in nodes_types.items()
                            if node_type != NodeType.PMEM]

        if set(pmem_nodes_names).intersection(set(node_names)):
            if self.app_fit_node_type(app_name, NodeType.PMEM, apps_profile)[0]:
                return pmem_nodes_names, \
                            {node_name: 'App match PMEM and PMEM available!'
                             for node_name in dram_nodes_names}
        return node_names, {}

    def normalize_capacity_to_memory(self, capacity: Resources):
        dim_mem_v = capacity['mem']
        return {dim: dim_v/dim_mem_v for dim, dim_v in capacity.items()}

    def calculate_apps_profile(self, data_provider_queried: QueryDataProviderInfo,
                               nodes_types: Dict[NodeName, NodeType]) \
            -> Tuple[Dict[AppName, float], Dict[AppName, Resources]]:
        nodes_capacities, _, apps_spec, _ = data_provider_queried

        # take only PMEM nodes
        pmem_nodes = [node_name for node_name, node_type in nodes_types if node_type == NodeType.PMEM]

        # calculate capacities normalized with mem
        pmem_normalized = {}
        for node_name, node_capacity in nodes_capacities.items():
            if node_name not in pmem_nodes:
                continue
            pmem_normalized[node_name] = self.normalize_capacity_to_memory(node_capacity)

        # take average of each dimension
        for capacity in pmem_normalized.values():
            assert set(capacity.keys()) == set(self.dimensions)

        def average_per_dim(pmem_normalized, dim):
            return statistics.mean([capacity[dim] for capacity in pmem_normalized.values()])

        average_pmem_normalized = {dim: average_per_dim(pmem_normalized, dim)
                                   for dim in self.dimensions}

        apps_scores = {}
        apps_spec_normalized = {}
        apps_spec_normalized_2 = {}
        for app_name in apps_spec:

            # normalize
            app_spec = apps_spec[app_name]
            app_spec_normalized = self.normalize_capacity_to_memory(app_spec)

            # normalize2
            app_spec_normalized_2 = {dim: app_spec_normalized[dim] / average_pmem_normalized[dim]
                                     for dim in self.dimensions}

            # score
            score = -1 * max([dim_value for dim, dim_value in app_spec_normalized_2.items()
                              if dim != 'mem'])

            def round_dict(dict_, precision=1):
                return {key: round(value, precision) for key, value in dict_.items()}

            # keep for debug purposes
            apps_scores[app_name] = score
            apps_spec_normalized[app_name] = round_dict(app_spec_normalized)
            apps_spec_normalized_2[app_name] = round_dict(app_spec_normalized_2)

        debug_info = sorted([(app, apps_scores[app] > self.score_target, round(apps_scores[app], 2),
                              apps_spec_normalized[app], apps_spec_normalized_2[app])
                              for app in apps_spec], reverse=True, key=lambda el: el[2])
        log.info('[Filter:PMEM specific] (app, match_PMEM, normalized, normalize_2): %s', str(debug_info))
        log.info('[Filter:PMEM specific] average_pmem_normalized: %s', str(average_pmem_normalized))

        return apps_scores
