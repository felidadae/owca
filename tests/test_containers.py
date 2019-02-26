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
from typing import List
import pytest

from owca.containers import _calculate_desired_state, ContainerSet, Container, \
    ContainerManager, ContainerInterface
from owca.cgroups import Cgroup
from owca.perf import PerfCounters
from owca.resctrl import ResGroup
from owca.testing import task, container, containerset


def assert_equal_containers(containers_a: List[ContainerInterface],
                            containers_b: List[ContainerInterface]):
    """Compares two list of containers. IMPORTANT: two containers are HERE
       treated as equal if they have the same cgroup_path set.

       One special assumption is made about private attribute of
       ContainerSet: that field _subcontainers exists with type
       dict[_, Container]."""
    assert len(containers_a) == len(containers_b)
    for a, b in zip(containers_a, containers_b):
        assert type(a) == type(b)
        assert a.get_cgroup_path() == b.get_cgroup_path()
        if type(a) == ContainerSet:
            assert len(a._subcontainers) == len(b._subcontainers)
            assert all([child_a.get_cgroup_path() == child_b.get_cgroup_path()
                        for child_a, child_b in zip(list(a._subcontainers.values()),
                                                    list(b._subcontainers.values()))])


# Parametrize scenarios:
# 1) One new task (t1) was discovered - before there was no containers.
# 2) No changes in environment - no actions are expected.
# 3) One new task (t2) was discovered.
# 4) No changes in environment - no actions are expected
#    (but now two containers already are running).
# 5) First task just disappeared - corresponding container should be removed.
# 6) Two new task were discovered.
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
    assert_equal_containers(containers_to_delete, expected_containers_to_delete)


# Parametrize scenarios:
# 1) Before the start - expecting no running containers.
# 2) One new task arrived - expecting that new container will be created.
# 3) One task dissapeared, one appeared.
# 4) One (of two) task dissapeared.
# 5) Two task (of two) dissapeared.
@patch('owca.containers.PerfCounters')
@patch('owca.containers.Container.sync')
@pytest.mark.parametrize('subsgroups', ([], ['/t1/c1', '/t1/c2']))
@pytest.mark.parametrize('tasks_, existing_containers_, expected_running_containers_', (
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
    """Test both Container and ContainerSet classes.
        Note: existing_containers, expected_running_containers and got_containers are of type:
        Dict[Task, ContainerInterface]."""

    # Create Task and Container/ContainerSet objects from strings given in parametrize.
    #   This is done to both test Container and ContainerSet classes (passing
    #   subsgroups parameter into constructing function >>container<<.
    tasks = [task(t, subcgroups_paths=subsgroups) for t in tasks_]
    existing_containers = {task(t, subcgroups_paths=subsgroups): container(c, subsgroups)
                           for t, c in existing_containers_.items()}
    expected_running_containers = {task(t, subcgroups_paths=subsgroups): container(c, subsgroups)
                                   for t, c in expected_running_containers_.items()}

    containers_manager = ContainerManager(rdt_enabled=False, rdt_mb_control_enabled=False,
                                          platform_cpus=1, allocation_configuration=None)
    # Put in into ContainerManager our input dict of containers.
    containers_manager.containers = dict(existing_containers)

    # Call sync_containers_state
    got_containers = containers_manager.sync_containers_state(tasks)

    # -----------------------
    # Assert that two sets of keys of two dictionaries got_containers and
    # expected_running_containers are equal.
    assert len(got_containers) == len(expected_running_containers)
    assert all([expected_task in got_containers
                for expected_task in expected_running_containers.keys()])
    # Get List[ContainerInterface] from Dict[Task, ContainerInterface]. Keep the same order
    # of elements in both expected_containers_ and got_containers_.
    got_containers_list = [got_containers[task] for task in expected_running_containers.keys()]
    expected_containers_list = [expected_running_containers[task]
                                for task in expected_running_containers.keys()]
    assert_equal_containers(got_containers_list, expected_containers_list)


ANY_METRIC_VALUE = 2


@patch('owca.containers.Cgroup', spec=Cgroup,
       get_measurements=Mock(return_value={'cgroup_metric__1': ANY_METRIC_VALUE}))
@patch('owca.containers.PerfCounters', spec=PerfCounters,
       get_measurements=Mock(return_value={'perf_event_metric__1': ANY_METRIC_VALUE}))
def test_containerset_get_measurements(*args):
    """Check whether summing of metrics for children containers are done properly.
       Note: because we are mocking here classes from which measurements are read,
       to calculate the proper value of ContainerSet we just need to multiple that
       single value by count of subcontainers (here defined as N)."""
    N = 3  # 3 subcontainers are created.
    subcgroups_paths = ['/t1/c1', '/t1/c2', '/t1/c3']
    containerset_ = containerset('/t1', subcgroups_paths, should_patch=False)

    resgroup_mock = Mock(spec=ResGroup, get_measurements=Mock(return_value={'foo': 3}))
    containerset_.set_resgroup(resgroup=resgroup_mock)

    # Call the main function.
    measurements = containerset_.get_measurements()

    resgroup_mock.get_measurements.assert_called_once()
    assert {'foo': 3, 'cgroup_metric__1': ANY_METRIC_VALUE*N,
            'perf_event_metric__1': ANY_METRIC_VALUE*N} == measurements


def smart_get_pids():
    # Note: here List[int] is used instead of >>int<<
    #   to pass mutable object (Integers are inmutable in Python).
    calls_count = [0]

    def fun():
        """Returns list of two consecutive integers. On first call
           return [0,1], on second [2,3], and so forth."""
        calls_count[0] += 2
        return [calls_count[0] - 2, calls_count[0] - 1]
    return fun


@patch('owca.containers.Cgroup')
@patch('owca.containers.Container', spec=Container, get_pids=Mock(side_effect=smart_get_pids()))
def test_containerset_get_pids(*args):
    subcgroups_paths = ['/t1/c1', '/t1/c2', '/t1/c3']
    containerset_ = containerset('/t1', subcgroups_paths)
    # We expect 6 consecutive numbers starting from 0 - as there are 3 subcgroups paths
    # for the container.
    assert containerset_.get_pids() == [0, 1, 2, 3, 4, 5]
