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

from owca.containers import _calculate_desired_state, ContainerSet, Container, ContainerManager
from owca.cgroups import Cgroup
from owca.perf import PerfCounters
from owca.resctrl import ResGroup
from owca.testing import task, container, containerset


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
# 1) .
# 2) One new task arrived.
# 3) One task dissapeared, one appeared.
# 4) One task dissapeared.
# 5) Two task dissapeared.
@patch('owca.containers.PerfCounters')
@patch('owca.containers.Container.sync')
@pytest.mark.parametrize('subsgroups', ([], ['/t1/c1', '/t1/c2']))
@pytest.mark.parametrize('tasks_, existing_containers_, '
                         'expected_running_containers_', (
    # 1)
    ([], {},
     {}),
    # 2)
    (['/t1'], {},
     {'/t1': '/t1'}),
    # 3)
    (['/t1'], {'/t2': '/t2'},
     {'/t1': '/t1'}),
    # 4)
    (['/t1'], {'/t1': '/t1', '/t2': '/t2'},
     {'/t1': '/t1'}),
    # 5)
    ([], {'/t1': '/t1', '/t2': '/t2'},
     {}),
))
def test_sync_containers_state(sync_mock, perf_counters_mock,
                               subsgroups,
                               tasks_, existing_containers_, expected_running_containers_):
    """Test both Container and ContainerSet classes."""
    tasks = [task(t, subcgroups_paths=subsgroups) for t in tasks_]
    existing_containers = {task(t, subcgroups_paths=subsgroups): container(c,subsgroups)
                           for t,c in existing_containers_.items()}
    expected_running_containers = {task(t, subcgroups_paths=subsgroups): container(c,subsgroups)
                                   for t,c in expected_running_containers_.items()}

    containers_manager = ContainerManager(
        rdt_enabled=False,
        rdt_mb_control_enabled=False,
        platform_cpus=1,
        allocation_configuration=None)
    containers_manager.containers = dict(existing_containers)

    # Call sync_containers_state
    got_containers = containers_manager.sync_containers_state(tasks)

    # Check internal state ...
    assert len(got_containers) == len(expected_running_containers)
    for expected_task, expected_container in expected_running_containers.items():
        assert expected_task in got_containers
        got_container = got_containers[expected_task]
        assert got_container.get_cgroup_path() == expected_container.get_cgroup_path()
        if subsgroups:
            assert type(got_container) == ContainerSet
            assert got_container._subcontainers == expected_container._subcontainers
        assert type(expected_container) == type(got_container)


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
