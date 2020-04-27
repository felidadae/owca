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

from wca.logger import TRACE
from wca.scheduler.algorithms import RescheduleResult
from wca.scheduler.algorithms.base import (
    QueryDataProviderInfo, DEFAULT_DIMENSIONS, subtract_resources,
    sum_resources, calculate_read_write_ratio, enough_resources_on_node,
    get_nodes_used_resources)
from wca.scheduler.algorithms.dram_hit_ratio_provision import DramHitRatioProvision
from wca.scheduler.algorithms.fit import Fit
from wca.scheduler.data_providers import AppsOnNode
from wca.scheduler.data_providers.score import ScoreDataProvider, NodeType, AppsProfile
from wca.scheduler.types import (AppName, NodeName, ResourceType, TaskName)

log = logging.getLogger(__name__)

MIN_APP_PROFILES = 2

RescheduleApps = Dict[AppName, Dict[NodeName, List[TaskName]]]
ConsiderApps = Dict[AppName, List[TaskName]]


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


class Score(Fit, DramHitRatioProvision):

    def __init__(self, data_provider: ScoreDataProvider,
                 dimensions: List[ResourceType] = DEFAULT_DIMENSIONS,
                 max_node_score: float = 10.,
                 alias: str = None,
                 score_target: Optional[float] = None,
                 strict_mode_placement: bool = False,
                 threshold: float = 0.97,
                 cpu_scale_factor: float = 1
                 ):
        Fit.__init__(self, data_provider, dimensions, max_node_score, alias, cpu_scale_factor)
        DramHitRatioProvision.__init__(self, data_provider, dimensions, max_node_score,
                                       alias, threshold)
        self.score_target = score_target
        self.strict_mode_placement = strict_mode_placement
        self.nodes_type = self.data_provider.get_nodes_type()

    def app_fit_node(self, node_name: NodeName, app_name: str,
                     data_provider_queried: QueryDataProviderInfo) -> Tuple[bool, str]:
        fit, fit_cause = Fit.app_fit_node(self, node_name, app_name, data_provider_queried)
        dram_hit_ratio_ok, dram_cause = True, ''
        if self.nodes_type[node_name] == NodeType.PMEM:
            dram_hit_ratio_ok, dram_cause = DramHitRatioProvision.app_fit_node(
                self, node_name, app_name, data_provider_queried)
        return fit and dram_hit_ratio_ok, '{} {}'.format(fit_cause, dram_cause)

    def _app_fit_node_type(
            self, apps_profile,
            app_name: AppName,
            node_type: NodeType) -> Tuple[bool, str]:

        if log.getEffectiveLevel() <= TRACE:
            log.log(TRACE, '[Filter:PMEM specific] apps_profile: \n%s',
                    str(sorted(apps_profile.items(), key=lambda x: x[1], reverse=True)))
            log.log(TRACE, '[Filter:PMEM specific] node_type: \n%s', str(node_type))

        app_type = _get_app_node_type(apps_profile, app_name, self.score_target)

        if node_type != app_type:
            return False, '%r not preferred for %r type of node' % (app_name, node_type)

        return True, ''

    def app_fit_nodes(self, node_names: List[NodeName], app_name: str,
                      data_provider_queried: QueryDataProviderInfo) -> \
            Tuple[List[NodeName], Dict[NodeName, str]]:
        """
        Returns accepted and failed nodes.
        """
        fit_nodes = []

        if node_names:
            nodes_type = self.data_provider.get_nodes_type()
            apps_profile = self.data_provider.get_apps_profile()

            for node in node_names:
                fit, _ = self._app_fit_node_type(apps_profile, app_name, nodes_type[node])
                if fit:
                    fit_nodes.append(node)

            if not fit_nodes:
                # There is no preferred nodes.
                if not self.strict_mode_placement:
                    # We can use different nodes, only if we allow it.
                    return node_names, {}

        return fit_nodes, {}

    def reschedule(self) -> RescheduleResult:
        apps_on_node, _ = self.data_provider.get_apps_counts()
        apps_profile = self.data_provider.get_apps_profile()

        reschedule: RescheduleApps = {}
        consider: RescheduleApps = {}

        for node in apps_on_node:
            node_type = self.nodes_type[node]
            for app in apps_on_node[node]:

                app_correct_placement, _ = self._app_fit_node_type(apps_profile, app, node_type)

                if not app_correct_placement:

                    # Apps, that not matching PMEM node, should be deleted.
                    if node_type == NodeType.PMEM:
                        if app not in reschedule:
                            reschedule[app] = {}
                        if node not in reschedule[app]:
                            reschedule[app][node] = []

                        reschedule[app][node] = apps_on_node[node][app]

                    # Apps, that matching PMEM but are on DRAM, should be considered to reschedule.
                    elif node_type == NodeType.DRAM:
                        if app not in consider:
                            consider[app] = {}
                        if node not in consider[app]:
                            consider[app][node] = []

                        consider[app][node] = apps_on_node[node][app]

        result = self._get_tasks_to_reschedule(
            reschedule, consider, apps_profile, apps_on_node)

        return result

    def _get_tasks_to_reschedule(self, reschedule: RescheduleApps,
                                 consider: RescheduleApps,
                                 apps_profile,
                                 apps_on_node: AppsOnNode) -> RescheduleResult:
        result: RescheduleResult = []

        if len(consider) <= 0:
            return []

        apps_spec = self.data_provider.get_apps_requested_resources(self.dimensions)

        apps_on_pmem_nodes = {
            node: apps
            for node, apps in apps_on_node.items()
            if self.nodes_type[node] == NodeType.PMEM
        }

        pmem_nodes_used_resources = get_nodes_used_resources(
            self.dimensions, apps_on_pmem_nodes, apps_spec)

        # Free PMEM nodes resources.
        for app in reschedule:
            for node in reschedule[app]:

                if node in pmem_nodes_used_resources:
                    for task in reschedule[app][node]:
                        pmem_nodes_used_resources[node] = \
                            subtract_resources(
                                pmem_nodes_used_resources[node],
                                apps_spec[app])

                        result.append(task)
                else:
                    raise RuntimeError('Capacities of %r not available!', node)

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
            if self.nodes_type[node] == NodeType.PMEM
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
                        log.warning('[Reschedule] %r cannot be rescheduled to PMEm node: '
                                    'There is no more space!', task)

        return result
