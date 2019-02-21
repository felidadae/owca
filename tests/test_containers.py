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

from unittest.mock import patch, Mock

import pytest

from owca.containers import _calculate_desired_state, ContainerSet, Container
from owca.cgroups import Cgroup
from owca.perf import PerfCounters
from owca.resctrl import ResGroup
from owca.runners.detection import DetectionRunner
from owca.testing import task, container, containerset, kubernetes_task


# Parametrize scenarios:
# 1) One new task (t1) was discovered - before there was no containers.
# 2) State converged, no actions.
# 3) One new task (t2) was discovered.
# 4) 2on2 converged, no actions.
# 5) First task just disappeared - remove the container.
# 6) Two new task was discovered.
# 7) New task was discovered and one task disappeared.
@pytest.mark.parametrize(
    'discovered_tasks, containers, '
    'expected_new_tasks, expected_containers_to_delete', (
        # 1)
        ([task('/t1')], [],
         [task('/t1')], []),
        # 2)
        ([task('/t1')], [container('/t1')],
         [], []),
        # 3)
        ([task('/t1'), task('/t2')], [container('/t1')],
         [task('/t2')], []),
        # 4)
        ([task('/t1'), task('/t2')], [container('/t1'), container('/t2')],
         [], []),
        # 5)
        ([task('/t2')], [container('/t1'), container('/t2')],
         [], [container('/t1')]),
        # 6)
        ([task('/t1'), task('/t2')], [],
         [task('/t1'), task('/t2')], []),
        # 7)
        ([task('/t1'), task('/t3')], [container('/t1'), container('/t2')],
         [task('/t3')], [container('/t2')]),
    ))
def test_calculate_desired_state(discovered_tasks, containers,
                                 expected_new_tasks, expected_containers_to_delete):
    new_tasks, containers_to_delete = _calculate_desired_state(
        discovered_tasks, containers)

    assert new_tasks == expected_new_tasks
    assert containers_to_delete == expected_containers_to_delete


# Parametrize scenarios:
# 1)
# 2)
# 3)
# 4)
# 5)
# 6)
# 7)
@patch('owca.containers.ResGroup')
@patch('owca.containers.PerfCounters')
@patch('owca.containers.Container.sync')
@patch('owca.platforms.collect_topology_information', return_value=(1, 1, 1))
@pytest.mark.parametrize('task_type', ('MesosTask', 'KubernetesTask'))
@pytest.mark.parametrize('tasks, existing_containers, '
                         'expected_running_containers', (
    # 1)
    ([], {},
     {}),
    # 2)
    ([task('/t1')], {},
     {task('/t1'): container('/t1')}),
    # 3)
    ([task('/t1')], {},
     {task('/t1'): container('/t1')}),
    # 4)
    ([task('/t1')], {task('/t2'): container('/t2')},
     {task('/t1'): container('/t1')}),
    # 5)
    ([task('/t1')], {task('/t1'): container('/t1'), task('/t2'): container('/t2')},
     {task('/t1'): container('/t1')}),
    # 6)
    ([], {task('/t1'): container('/t1'), task('/t2'): container('/t2')},
     {}),
    # 7)
    ([kubernetes_task('/t1', ['/t1/c1', '/t1/c2'])], {},
     {kubernetes_task('/t1', ['/t1/c1', '/t1/c2']): containerset('/t1', ['/t1/c1', '/t1/c2'])}),
))
def test_sync_containers_state(platform_mock, sync_mock,
                               perf_counters_mock, resgroup_mock,
                               task_type,
                               tasks, existing_containers,
                               expected_running_containers):
    # Mocker runner, because we're only interested in one sync_containers_state function.
    runner = DetectionRunner(
        node=Mock(),
        metrics_storage=Mock(),
        anomalies_storage=Mock(),
        detector=Mock(),
        rdt_enabled=False,
    )
    # Prepare internal state used by sync_containers_state function - mock.
    # Use list for copying to have original list.
    runner.containers_manager.containers = dict(existing_containers)

    # Call sync_containers_state
    got_containers = runner.containers_manager.sync_containers_state(tasks)

    # Check internal state ...
    assert len(got_containers) == len(expected_running_containers)
    for expected_task, expected_container in expected_running_containers.items():
        assert expected_task in got_containers
        got_container = got_containers[expected_task]
        assert got_container.get_cgroup_path() == expected_container.get_cgroup_path()
        assert type(expected_container) == type(got_container)
        if len(expected_task.subcgroups_paths):
            assert got_container._subcontainers == expected_container._subcontainers


@patch('owca.containers.Cgroup', spec=Cgroup,
       get_measurements=Mock(return_value={'cgroup_metric__1': 2}))
@patch('owca.containers.PerfCounters', spec=PerfCounters,
       get_measurements=Mock(return_value={'perf_event_metric__1': 2}))
def test_containerset_get_measurements(*args):
    """Check whether summing of metrics for children containers are done properly."""
    # 3 subcontainers are created.
    subcgroups_paths = ['/t1/c1', '/t1/c2', '/t1/c3']
    containerset_ = containerset('/t1', subcgroups_paths, should_patch=False)

    resgroup_mock = Mock(spec=ResGroup, get_measurements=Mock(return_value={'foo': 3}))
    containerset_.set_resgroup(resgroup=resgroup_mock)

    # Call the main function.
    measurements = containerset_.get_measurements()

    resgroup_mock.get_measurements.assert_called_once()
    assert {'foo': 3, 'cgroup_metric__1': 2+2+2, 'perf_event_metric__1': 2+2+2} == measurements


def smart_get_pids():
    calls_count = [0]  # Make list to pass mutable object.

    def fun():
        calls_count[0] += 2
        return [calls_count[0] - 2, calls_count[0] - 1]
    return fun


@patch('owca.containers.Cgroup')
@patch('owca.containers.Container', spec=Container, get_pids=Mock(side_effect=smart_get_pids()))
def test_containerset_get_pids(*args):
    # 3 subcontainers are created.
    subcgroups_paths = ['/t1/c1', '/t1/c2', '/t1/c3']
    containerset_ = containerset('/t1', subcgroups_paths)
    assert containerset_.get_pids() == [0, 1, 2, 3, 4, 5]


def test_get_allocations():
    # TODO implement me
    pass
