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
from abc import abstractmethod
from typing import Tuple, Dict, List, Optional, Set

from wca.logger import TRACE
from wca.metrics import Metric, MetricType
from wca.scheduler.algorithms import Algorithm, log, DataMissingException, RescheduleResult
from wca.scheduler.data_providers import DataProvider
from wca.scheduler.metrics import MetricRegistry, MetricName
from wca.scheduler.types import NodeName, Resources, AppsCount, AppName, ResourceType, \
    ExtenderArgs, ExtenderFilterResult, HostPriority, Apps
from wca.scheduler.utils import extract_common_input

QueryDataProviderInfo = Tuple[
    Dict[NodeName, Resources],  # nodes_capacities
    Dict[NodeName, Apps],  # assigned_app count
    Dict[AppName, Resources],  # apps_spec
    AppsCount  # unassigend apps cout
]

DEFAULT_DIMENSIONS: List[ResourceType] = [
    ResourceType.CPU,
    ResourceType.MEM,
    ResourceType.MEMBW_READ,
    ResourceType.MEMBW_WRITE
]


# Convert data provider to common tuple.
def query_data_provider(data_provider, dimensions) -> QueryDataProviderInfo:
    """Should be overwritten if one needs more data from DataProvider."""
    assigned_apps, apps_unassigned = data_provider.get_apps_counts()
    nodes_capacities = data_provider.get_nodes_capacities(dimensions)
    apps_spec = data_provider.get_apps_requested_resources(dimensions)
    return nodes_capacities, assigned_apps, apps_spec, apps_unassigned


class BaseAlgorithm(Algorithm):
    """Implementing some basic functionalists which probably
       each Algorithm subclass will need to do. However forcing
       some way of implementing filtering and prioritizing which may
       not match everybody needs."""

    def __init__(self, data_provider: DataProvider,
                 dimensions: List[ResourceType] = DEFAULT_DIMENSIONS,
                 max_node_score: float = 10.,
                 alias: str = None
                 ):
        self.data_provider = data_provider
        self.dimensions = dimensions
        self.metrics: MetricRegistry = MetricRegistry()
        self.alias = alias
        self.max_node_score = max_node_score

    def __str__(self):
        if self.alias:
            return self.alias
        return '%s(%d)' % (self.__class__.__name__, len(self.dimensions))

    def filter(self, extender_args: ExtenderArgs) -> ExtenderFilterResult:
        log.debug('[Filter] -> %r' % extender_args)
        app_name, nodes_names, namespace, name = extract_common_input(extender_args)

        extender_filter_result = ExtenderFilterResult()

        # self.data_provider.update()
        data_provider_queried = query_data_provider(self.data_provider, self.dimensions)
        if log.getEffectiveLevel() <= TRACE:
            log.log(TRACE, '[Filter] data_queried: \n%s', str(data_provider_queried))

        # First pass (parallelize-able, fast K8S style)
        accepted_node_names = []
        for node_name in nodes_names:
            # Gather individual failed
            accepted, message = self.app_fit_node(node_name, app_name, data_provider_queried)
            if not accepted:
                log.log(TRACE, 'Failed Node %r, %r', node_name, message)
                log.debug('Failed Node %r, %r', node_name, message)
                extender_filter_result.FailedNodes[node_name] = message
            else:
                accepted_node_names.append(node_name)

        # Second pass (choose best among). Filter with context of all other nodes which passed
        # first stage. Only if we have something to filter at all.
        if accepted_node_names:
            accepted_node_names, failed = self.app_fit_nodes(accepted_node_names, app_name,
                                                             data_provider_queried)
            for failed_node_name, failed_message in failed.items():
                extender_filter_result.FailedNodes[failed_node_name] = failed_message

        for node_name in accepted_node_names:
            extender_filter_result.NodeNames.append(node_name)

        log.debug('[Filter] <- %r' % extender_filter_result)
        return extender_filter_result

    def prioritize(self, extender_args: ExtenderArgs) -> List[HostPriority]:
        """Extract necessary data from query and gather data from data provider (once)."""
        log.debug('[Prioritize] -> ExtenderArgs: %r' % extender_args)
        app_name, nodes_names, namespace, name = extract_common_input(extender_args)
        # self.data_provider.update()
        data_provider_queried = query_data_provider(self.data_provider, self.dimensions)
        if log.getEffectiveLevel() <= TRACE:
            log.log(TRACE, '[Filter] data_queried: \n%s', str(data_provider_queried))

        priorities = []
        for node_name in sorted(nodes_names):
            priority = self.priority_for_node(node_name, app_name, data_provider_queried)
            priority_scaled = int(priority * self.max_node_score)
            priorities.append(HostPriority(node_name, priority_scaled))

        log.debug('[Prioritize] <- %r', priorities)
        return priorities

    def get_metrics_registry(self) -> Optional[MetricRegistry]:
        return self.metrics

    def get_metrics_names(self) -> List[str]:
        return self.metrics.get_names()

    @abstractmethod
    def app_fit_node(self, node_name: NodeName, app_name: str,
                     data_provider_queried: QueryDataProviderInfo) -> Tuple[bool, str]:
        """Consider if the app match the given node."""

    @abstractmethod
    def priority_for_node(self, node_name: str, app_name: str,
                          data_provider_queried: QueryDataProviderInfo) -> float:
        """Considering priority of the given node."""

    # To be refactored -  comeback to holistic view of all nodes.
    # We need that app_fit_node thanks to fit implementation and then come back to list of nodes.
    def app_fit_nodes(self, node_names: List[NodeName], app_name: str,
                      data_provider_queried: QueryDataProviderInfo) -> \
            Tuple[List[NodeName], Dict[NodeName, str]]:
        """
        Return accepted and failed nodes.
        Default implementation always accepts all nodes.
        """
        return node_names, {}

    def reschedule(self) -> RescheduleResult:
        data_provider_queried = query_data_provider(self.data_provider, self.dimensions)
        if log.getEffectiveLevel() <= TRACE:
            log.log(TRACE,
                    '[Reschedule] data_queried: \n%s\n', str(data_provider_queried))
        apps_to_reschedule, metrics = self.reschedule_with_metrics(data_provider_queried)
        self.metrics.extend(metrics)
        log.debug('[Reschedule] <- Remove: %r', ','.join(apps_to_reschedule))
        return apps_to_reschedule

    def reschedule_with_metrics(self, data_provider_queried: QueryDataProviderInfo
                                ) -> Tuple[RescheduleResult, List[Metric]]:
        return [], []


def used_resources_on_node(
        dimensions: Set[ResourceType],
        assigned_apps_counts: AppsCount,
        apps_spec: Dict[AppName, Resources]) -> Resources:
    """Calculate used resources on a given node using data returned by data provider."""
    used = {dim: 0 for dim in dimensions}
    for app, count in assigned_apps_counts.items():
        for dim in dimensions:
            used[dim] += apps_spec[app][dim] * count
    return used


def _check_keys(a, b: Resources):
    if not set(a.keys()) == set(b.keys()):
        raise ValueError(
            'the same dimensions must be provided for both resources %r vs %r',
            a.keys(), b.keys())


def sum_resources(a: Resources, b: Resources) -> Resources:
    _check_keys(a, b)
    c = {}
    for resource in a.keys():
        c[resource] = a[resource] + b[resource]
    return c


def subtract_resources(a: Resources, b: Resources,
                       membw_read_write_ratio: Optional[float] = None) -> Resources:
    _check_keys(a, b)
    dimensions = set(a.keys())

    c = a.copy()
    for dimension in dimensions:
        if dimension not in (
                ResourceType.MEMBW_READ,
                ResourceType.MEMBW_WRITE) or membw_read_write_ratio is None:
            c[dimension] = a[dimension] - b[dimension]

    if ResourceType.MEMBW_READ in dimensions and membw_read_write_ratio is not None:
        assert ResourceType.MEMBW_WRITE in dimensions
        assert type(membw_read_write_ratio) == float
        read, write = ResourceType.MEMBW_READ, ResourceType.MEMBW_WRITE
        c[read] = a[read] - (b[read] + b[write] * membw_read_write_ratio)
        c[write] = a[write] - (b[write] + b[read] / membw_read_write_ratio)
    return c


def calculate_read_write_ratio(capacity: Resources) -> Optional[float]:
    dimensions = capacity.keys()
    if ResourceType.MEMBW_READ in dimensions:
        assert ResourceType.MEMBW_WRITE in dimensions
        return float(capacity[ResourceType.MEMBW_READ]) / float(capacity[ResourceType.MEMBW_WRITE])
    else:
        return None


def flat_membw_read_write(a: Resources, membw_read_write_ratio: Optional[float]) -> Resources:
    """Return resources with replaced memorybandwidth writes and reads """
    """with counted flat value."""
    dimensions = a.keys()
    b = a.copy()
    if ResourceType.MEMBW_READ in dimensions:
        assert ResourceType.MEMBW_WRITE in dimensions
        assert type(membw_read_write_ratio) == float
        del b[ResourceType.MEMBW_READ]
        del b[ResourceType.MEMBW_WRITE]
        b[ResourceType.MEMBW_FLAT] = \
            a[ResourceType.MEMBW_READ] + membw_read_write_ratio * a[ResourceType.MEMBW_WRITE]
    return b


def divide_resources(a: Resources, b: Resources,
                     membw_read_write_ratio: Optional[float] = None) -> Resources:
    """if ratio is provided then Flattens rt.MEMBW_READ and rt.MEMBW_WRITE to rt.MEMBW_FLAT."""
    assert set(a.keys()) == set(b.keys()), \
        'the same dimensions must be provided for both resources'
    # must flatten membw_read_write
    if ResourceType.MEMBW_READ in a.keys() and membw_read_write_ratio is not None:
        a = flat_membw_read_write(a, membw_read_write_ratio)
        b = flat_membw_read_write(b, membw_read_write_ratio)

    dimensions = set(a.keys())

    c = {}
    for dimension in dimensions:
        c[dimension] = float(a[dimension]) / float(b[dimension])
    return c


def used_free_requested(
        node_name, app_name, dimensions,
        nodes_capacities, assigned_apps, apps_spec,
) -> Tuple[dict, dict, dict, dict, float, List[Metric]]:
    """Helper function not making any new calculations.
    All three values are returned in context of
    specified node_name and app_name.
    (Converts multiple nodes * apps to single)
    return used, free, requested, capacity, membw_read_write_ratio, metrics
    used:
    """

    capacity = nodes_capacities[node_name]
    membw_read_write_ratio = calculate_read_write_ratio(capacity)
    apps = assigned_apps[node_name]
    appscount = {app: len(tasks) for app, tasks in apps.items()}
    used = used_resources_on_node(dimensions, appscount, apps_spec)
    requested = apps_spec[app_name]

    # currently used and free currently
    free = subtract_resources(capacity,
                              used,
                              membw_read_write_ratio)

    metrics = []
    # Metrics: resources: used, free and requested
    for resource in used:
        metrics.append(
            Metric(name=MetricName.NODE_USED_RESOURCE,
                   value=used[resource],
                   labels=dict(node=node_name, resource=resource),
                   type=MetricType.GAUGE, ))
    for resource in free:
        metrics.append(
            Metric(name=MetricName.NODE_FREE_RESOURCE,
                   value=free[resource],
                   labels=dict(node=node_name, resource=resource),
                   type=MetricType.GAUGE, ))
    for resource in requested:
        metrics.append(
            Metric(name=MetricName.APP_REQUESTED_RESOURCE,
                   value=requested[resource],
                   labels=dict(resource=resource, app=app_name),
                   type=MetricType.GAUGE, ))
    for resource in capacity:
        metrics.append(
            Metric(name=MetricName.NODE_CAPACITY_RESOURCE,
                   value=capacity[resource],
                   labels=dict(resource=resource, node=node_name),
                   type=MetricType.GAUGE))

    # Extra metric
    free_membw_flat = flat_membw_read_write(free, membw_read_write_ratio)
    if ResourceType.MEMBW_FLAT in free_membw_flat:
        metrics.append(Metric(
            name=MetricName.FIT_PREDICTED_MEMBW_FLAT_USAGE,
            value=free_membw_flat[ResourceType.MEMBW_FLAT],
            labels=dict(app=app_name, node=node_name),
            type=MetricType.GAUGE))

    return used, free, requested, capacity, membw_read_write_ratio, metrics


def get_requested_fraction(app_name, apps_spec, assigned_apps, node_name,
                           nodes_capacities, dimensions) -> Tuple[Resources, List[Metric]]:
    """
    returns requested_fraction, metrics
    """
    # Current node context: used and free currently
    used, free, requested, capacity, membw_read_write_ratio, metrics = \
        used_free_requested(node_name, app_name, dimensions,
                            nodes_capacities, assigned_apps, apps_spec)

    # SUM requested by app and already used on node
    try:
        requested_and_used = sum_resources(requested, used)
    except ValueError as e:
        msg = 'cannot sum app=%s requested=%s and node=%s used=%s: %s' % (
            app_name, requested, node_name, used, e)
        log.error(msg)
        raise DataMissingException(msg) from e

    # FRACTION
    requested_fraction = divide_resources(
        requested_and_used, capacity,
        membw_read_write_ratio
    )
    for resource, fraction in requested_fraction.items():
        metrics.append(
            Metric(name=MetricName.BAR_REQUESTED_FRACTION,
                   value=fraction, labels=dict(app=app_name, resource=resource),
                   type=MetricType.GAUGE))
    return requested_fraction, metrics


def get_nodes_used_resources(
        dimensions: Set[ResourceType],
        apps_on_node: Dict[NodeName, Apps],
        apps_spec: Dict[AppName, Resources]):
    """Returns used resources on nodes."""
    nodes_used_resources = {}

    for node in apps_on_node:
        appscount = {
                app: len(tasks)
                for app, tasks in apps_on_node[node].items()
        }

        nodes_used_resources[node] = used_resources_on_node(
                dimensions, appscount, apps_spec)

    return nodes_used_resources


def enough_resources_on_node(capacity, used, membw_read_write_ratio):
    free = subtract_resources(
        capacity,
        used,
        membw_read_write_ratio,
    )

    # CHECK
    broken_capacities = {r: abs(v) for r, v in free.items() if v < 0}

    return not bool(broken_capacities), broken_capacities, free
