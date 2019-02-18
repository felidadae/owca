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
from owca.testing import task, container


@pytest.mark.parametrize(
    'discovered_tasks,containers,expected_new_tasks,expected_containers_to_delete', (
        # scenario when two task are created and them first one is removed,
        ([task('/t1')], [],  # one new task, just arrived
         [task('/t1')], []),  # should created one container
        ([task('/t1')], [container('/t1')],  # after one iteration, our state is converged
         [], []),  # no actions
        ([task('/t1'), task('/t2')], [container('/t1'), ],  # another task arrived,
         [task('/t2')], []),  # let's create another container,
        ([task('/t1'), task('/t2')], [container('/t1'), container('/t2')],  # 2on2 converged
         [], []),  # nothing to do,
        ([task('/t2')], [container('/t1'), container('/t2')],  # first task just disappeared
         [], [container('/t1')]),  # remove the first container
        # some other cases
        ([task('/t1'), task('/t2')], [],  # the new task, just appeared
         [task('/t1'), task('/t2')], []),
        ([task('/t1'), task('/t3')], [container('/t1'),
                                      container('/t2')],  # t2 replaced with t3
         [task('/t3')], [container('/t2')]),  # nothing to do,
    ))
def test_calculate_desired_state(
        discovered_tasks,
        containers,
        expected_new_tasks,
        expected_containers_to_delete):
    new_tasks, containers_to_delete = _calculate_desired_state(
        discovered_tasks, containers
    )

    assert new_tasks == expected_new_tasks
    assert containers_to_delete == expected_containers_to_delete


@patch('owca.containers.ResGroup')
@patch('owca.containers.PerfCounters')
@patch('owca.containers.Container.sync')
@patch('owca.platforms.collect_topology_information', return_value=(1, 1, 1))
@pytest.mark.parametrize('tasks,existing_containers,expected_running_containers', (
    ([], {},
     {}),
    ([task('/t1')], {},
     {task('/t1'): container('/t1')}),
    ([task('/t1')], {task('/t2'): container('/t2')},
     {task('/t1'): container('/t1')}),
    ([task('/t1')], {task('/t1'): container('/t1'), task('/t2'): container('/t2')},
     {task('/t1'): container('/t1')}),
    ([], {task('/t1'): container('/t1'), task('/t2'): container('/t2')},
     {}),
))
def test_sync_containers_state(platform_mock, sync_mock,
                               PerfCoutners_mock, ResGroup_mock,
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

    # Call it.
    got_containers = runner.containers_manager.sync_containers_state(tasks)

    # Check internal state ...
    assert got_containers == expected_running_containers

    # Check other side effects like calling sync() on external objects.
    assert sync_mock.call_count == len(expected_running_containers)


def containerset(root_subgroup_path='/t1', subcgroups_paths=['/t1/c1', '/t1/c2']):
    return ContainerSet(root_subgroup_path, subcgroups_paths,
                        platform_cpus=2, allocation_configuration=None,
                        resgroup=None, rdt_enabled=True, rdt_mb_control_enabled=False)


@patch('owca.containers.Cgroup', spec=Cgroup,
       get_measurements=Mock(return_value={'cgroup_metric__1': 2}))
@patch('owca.containers.PerfCounters', spec=PerfCounters,
       get_measurements=Mock(return_value={'perf_event_metric__1': 2}))
def test_containerset_get_measurements(*args):
    """Check whether summing of metrics for children containers are done properly."""
    # 3 subcontainers are created.
    subcgroups_paths = ['/t1/c1', '/t1/c2', '/t1/c3']
    containerset_ = containerset('/t1', subcgroups_paths)

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
