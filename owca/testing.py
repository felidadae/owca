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

import os
from typing import List, Dict, Union
from unittest.mock import mock_open, Mock, patch

from owca.allocators import AllocationConfiguration
from owca.containers import Container
from owca.detectors import ContendedResource, ContentionAnomaly, _create_uuid_from_tasks_ids
from owca.mesos import MesosTask, TaskId
from owca.metrics import Metric, MetricType
from owca.resctrl import ResGroup
from owca.runners.base import Runner


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


def anomaly_metrics(contended_task_id: TaskId, contending_task_ids: List[TaskId]):
    """Helper method to create metric based on anomaly.
    uuid is used if provided.
    """
    metrics = []
    for task_id in contending_task_ids:
        uuid = _create_uuid_from_tasks_ids(contending_task_ids + [contended_task_id])
        metrics.append(Metric(
            name='anomaly',
            value=1,
            labels=dict(
                contended_task_id=contended_task_id, contending_task_id=task_id,
                resource=ContendedResource.MEMORY_BW, uuid=uuid, type='contention'
            ),
            type=MetricType.COUNTER
        ))
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


def task(cgroup_path, labels=None, resources=None):
    """Helper method to create task with default values."""
    prefix = cgroup_path.replace('/', '')
    return MesosTask(
        cgroup_path=cgroup_path,
        name=prefix + '_tasks_name',
        executor_pid=1,
        container_id=prefix + '_container_id',
        task_id=prefix + '_task_id',
        executor_id=prefix + '_executor_id',
        agent_id=prefix + '_agent_id',
        labels=labels or dict(),
        resources=resources or dict()
    )


def container(cgroup_path, resgroup_name=None, with_config=False):
    """Helper method to create container with patched subsystems."""
    with patch('owca.containers.ResGroup'), patch('owca.containers.PerfCounters'):
        return Container(
            cgroup_path,
            rdt_enabled=False, platform_cpus=1,
            allocation_configuration=AllocationConfiguration() if with_config else None,
            resgroup=ResGroup(name=resgroup_name) if resgroup_name is not None else None
        )


def metric(name, labels=None):
    """Helper method to create metric with default values. Value is ignored during tests."""
    return Metric(name=name, value=1234, labels=labels or {})


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
        pass
