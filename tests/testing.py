# Copyright (c) 2018 Intel Corporation
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


"""Module for independent simple helper functions."""

import functools
import os
from typing import List, Dict, Union, Optional
from unittest.mock import mock_open, Mock, patch

from wca import platforms
from wca.allocators import AllocationConfiguration
from wca.runners.measurement import DEFAULT_EVENTS
from wca.containers import Container, ContainerSet, ContainerInterface
from wca.detectors import ContendedResource, ContentionAnomaly, LABEL_WORKLOAD_INSTANCE, \
    _create_uuid_from_tasks_ids
from wca.metrics import Metric, MetricType
from wca.nodes import TaskId, Task
from wca.platforms import RDTInformation
from wca.resctrl import ResGroup
from wca.runners import Runner


def relative_module_path(module_file, relative_path):
    """Returns path relative to current python module."""
    dir_path = os.path.dirname(os.path.realpath(module_file))
    return os.path.join(dir_path, relative_path)


def create_open_mock(paths: Dict[str, Mock]):
    """Creates open_mocks registry based on multiple path.

    You can access created open_mocks by using __getitem__ functions like this:
    OpenMock({'path':'body')['path']. Useful for write mocks assertions.

    For typical example of usage, check tests/test_testing:test_create_open_mock()

    """

    class OpenMock:
        def __init__(self, paths: Dict[str, Union[str, Mock]]):
            self.paths = {os.path.normpath(k): v for k, v in paths.items()}
            self._mocks = {}

        def __call__(self, path, mode='rb'):
            """Used instead of open function."""
            path = os.path.normpath(path)
            if path not in self.paths:
                raise Exception('opening %r is not mocked with OpenMock!' % path)
            mock_or_str = self.paths[path]
            if isinstance(mock_or_str, str) or isinstance(mock_or_str, bytes):
                mock = mock_open(read_data=mock_or_str)
                self._mocks[path] = mock
            else:
                mock = self.paths[path]
            return mock(path, mode)

        def __getitem__(self, path):
            path = os.path.normpath(path)
            if path not in self._mocks:
                raise Exception('mock %r was not open!' % path)

            return self._mocks[path]

    return OpenMock(paths)


def anomaly_metrics(contended_task_id: TaskId, contending_task_ids: List[TaskId],
                    contending_workload_instances: Dict[TaskId, str] = {},
                    labels: Dict[TaskId, Dict[str, str]] = {}):
    """Helper method to create metric based on anomaly.
    uuid is used if provided.
    """
    metrics = []
    for task_id in contending_task_ids:
        uuid = _create_uuid_from_tasks_ids(contending_task_ids + [contended_task_id])
        metric = Metric(
            name='anomaly',
            value=1,
            labels=dict(
                contended_task_id=contended_task_id,
                contending_task_id=task_id,
                resource=ContendedResource.MEMORY_BW, uuid=uuid,
                type='contention',
                contending_workload_instance=contending_workload_instances[task_id],
                workload_instance=contending_workload_instances[contended_task_id]
            ),
            type=MetricType.COUNTER)
        if contended_task_id in labels:
            metric.labels.update(labels[contended_task_id])
        metrics.append(metric)
    return metrics


def anomaly(contended_task_id: TaskId, contending_task_ids: List[TaskId],
            metrics: List[Metric] = None):
    """Helper method to create simple anomaly for single task.
    It is always about memory contention."""
    return ContentionAnomaly(
        contended_task_id=contended_task_id,
        contending_task_ids=contending_task_ids,
        resource=ContendedResource.MEMORY_BW,
        metrics=metrics or [],
    )


def task(cgroup_path, labels=None, resources=None, subcgroups_paths=None):
    """Helper method to create task with default values."""
    prefix = cgroup_path.replace('/', '')
    return Task(
        cgroup_path=cgroup_path,
        name=prefix + '_tasks_name',
        task_id=prefix + '_task_id',
        labels=labels or dict(),
        resources=resources or dict(),
        subcgroups_paths=subcgroups_paths or []
    )


def container(cgroup_path, subcgroups_paths=None, with_config=False,
              should_patch=True, resgroup_name='',
              rdt_enabled=True, rdt_mb_control_enabled=True,
              rdt_cache_control_enabled=True) \
              -> ContainerInterface:
    """Helper method to create Container or ContainerSet
        (depends if subcgroups_paths is empty or not),
        optionally with patched subsystems."""
    if subcgroups_paths is None:
        subcgroups_paths = []

    def unpatched():
        if len(subcgroups_paths):
            return ContainerSet(
                cgroup_path=cgroup_path,
                cgroup_paths=subcgroups_paths,
                platform_cpus=1,
                platform_sockets=1,
                allocation_configuration=AllocationConfiguration() if with_config else None,
                resgroup=ResGroup(name=resgroup_name) if rdt_enabled else None,
                rdt_information=RDTInformation(
                    True, True, rdt_mb_control_enabled,
                    rdt_cache_control_enabled, '0', '0', 0, 0, 0),
                event_names=DEFAULT_EVENTS)
        else:
            return Container(
                cgroup_path=cgroup_path,
                platform_cpus=1,
                platform_sockets=1,
                rdt_information=RDTInformation(True, True,
                                               True, True, '0', '0',
                                               0, 0, 0),
                allocation_configuration=AllocationConfiguration() if with_config else None,
                resgroup=ResGroup(name=resgroup_name) if rdt_enabled else None,
                event_names=DEFAULT_EVENTS
            )

    if should_patch:
        with patch('wca.resctrl.ResGroup'), patch('wca.perf.PerfCounters'):
            return unpatched()
    else:
        return unpatched()


DEFAULT_METRIC_VALUE = 1234


def metric(name, labels=None, value=DEFAULT_METRIC_VALUE):
    """Helper method to create metric with default values. Value is ignored during tests."""
    return Metric(name=name, value=value, labels=labels or {})


def allocation_metric(allocation_type, value, **labels):
    """Helper to create allocation typed like metric"""

    name = labels.pop('name', 'allocation')

    if allocation_type is not None:
        labels = dict(allocation_type=allocation_type, **(labels or dict()))

    return Metric(
        name='%s_%s' % (name, allocation_type),
        type=MetricType.GAUGE,
        value=value,
        labels=labels
    )


class DummyRunner(Runner):

    def run(self):
        return 0


platform_mock = Mock(
    spec=platforms.Platform,
    sockets=1,
    rdt_information=RDTInformation(
        cbm_mask='fffff',
        min_cbm_bits='1',
        rdt_cache_monitoring_enabled=True,
        rdt_cache_control_enabled=True,
        rdt_mb_monitoring_enabled=True,
        rdt_mb_control_enabled=True,
        num_closids=2,
        mb_bandwidth_gran=0,
        mb_min_bandwidth=0,
    ))


def redis_task_with_default_labels(task_id, subcgroups_paths=None):
    """Returns task instance and its labels."""
    if subcgroups_paths is None:
        subcgroups_paths = []
    task_labels = {
        'org.apache.aurora.metadata.load_generator': 'rpc-perf-%s' % task_id,
        'org.apache.aurora.metadata.name': 'redis-6792-%s' % task_id,
        LABEL_WORKLOAD_INSTANCE: 'redis_6792_%s' % task_id
    }
    return task('/%s' % task_id,
                resources=dict(cpus=8.),
                labels=task_labels,
                subcgroups_paths=subcgroups_paths)


TASK_CPU_USAGE = 23
WCA_MEMORY_USAGE = 100


def prepare_runner_patches(func):
    """Decorator to be used from runner tests.

    The idea behind this is to use proper classes and objects for Cgroup, Resctrl and others
    because they carry necessary information (in properties), but to cut off OS touching calls.

    Decorator is responsible for mocking all objects used by runner from perspective of:
    - resources: Cgroup, PerfCounters, ResGroup,
    - resctrl filesystem: check_resctrl, read_mon_groups_relation,
    - platform: collect_platform_information, collect_platform_topology,
    - other OS related calls: getrusage, are_privileges_sufficient

    It is not mocking runners internals like ContainerManager or Container classes
    to make sure that there is proper interaction between those classes.
    """

    @functools.wraps(func)
    def _decorated_function(*args, **kwargs):
        with patch('wca.cgroups.Cgroup.get_pids', return_value=['123']), \
             patch('wca.cgroups.Cgroup.set_quota'), \
             patch('wca.cgroups.Cgroup.set_shares'), \
             patch('wca.cgroups.Cgroup.get_measurements',
                   return_value=dict(cpu_usage=TASK_CPU_USAGE)), \
             patch('wca.resctrl.ResGroup.add_pids'), \
             patch('wca.resctrl.ResGroup.get_measurements'), \
             patch('wca.resctrl.ResGroup.get_mon_groups'), \
             patch('wca.resctrl.ResGroup.remove'), \
             patch('wca.resctrl.ResGroup.write_schemata'), \
             patch('wca.resctrl.read_mon_groups_relation', return_value={'': []}), \
             patch('wca.resctrl.check_resctrl', return_value=True), \
             patch('wca.resctrl.cleanup_resctrl'), \
             patch('wca.perf.PerfCounters'), \
             patch('wca.platforms.collect_platform_information',
                   return_value=(platform_mock, [metric('platform-cpu-usage')], {})), \
             patch('wca.platforms.collect_topology_information', return_value=(1, 1, 1)), \
             patch('wca.security.are_privileges_sufficient', return_value=True), \
             patch('resource.getrusage', return_value=Mock(ru_maxrss=WCA_MEMORY_USAGE)):
            func(*args, **kwargs)

    return _decorated_function


def assert_subdict(got_dict: dict, expected_subdict: dict):
    """Assert that one dict is a subset of another dict in recursive manner.
    Check if expected key exists and if value matches expected value.
    """
    for expected_key, expected_value in expected_subdict.items():
        if expected_key not in got_dict:
            raise AssertionError('key %r not found in %r' % (expected_key, got_dict))
        got_value = got_dict[expected_key]
        if isinstance(expected_value, dict):
            # When comparing with dict use 'containment' operation instead of equal.
            # If expected value is a dict, call assert_subdict recursively.
            if not isinstance(got_value, dict):
                raise AssertionError('expected dict type at %r key, got %r' % (
                    expected_key, type(got_value)))
            assert_subdict(got_value, expected_value)
        else:
            # For any other type check using ordinary equality operator.
            assert got_value == expected_value, \
                'value differs got=%r expected=%r at key=%r' % (
                    got_value, expected_value, expected_key)


def _is_dict_match(got_dict: dict, expected_subdict: dict):
    """Match values and keys from dict (non recursive)."""
    for expected_key, expected_value in expected_subdict.items():
        if expected_key not in got_dict:
            return False
        if got_dict[expected_key] != expected_value:
            return False
    return True


def assert_metric(got_metrics: List[Metric],
                  expected_metric_name: str,
                  expected_metric_some_labels: Optional[Dict] = None,
                  expected_metric_value: Optional[Union[float, int]] = None,
                  ):
    """Assert that given metrics exists in given set of metrics."""
    found_metric = None
    for got_metric in got_metrics:
        if got_metric.name == expected_metric_name:
            # found by name, should we check labels ?
            if expected_metric_some_labels is not None:
                # yes check by labels
                if _is_dict_match(got_metric.labels, expected_metric_some_labels):
                    found_metric = got_metric
                    break
            else:
                found_metric = got_metric
                break
    if not found_metric:
        raise AssertionError(
                'metric %r not found (labels=%s)' %
                (expected_metric_name, expected_metric_some_labels))
    # Check values as well
    if expected_metric_value is not None:
        assert found_metric.value == expected_metric_value, \
            'metric name=%r value differs got=%r expected=%r' % (
                found_metric.name, found_metric.value, expected_metric_value)
