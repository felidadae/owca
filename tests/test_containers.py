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

from wca.containers import ContainerSet, Container, \
    ContainerManager, ContainerInterface, _find_new_and_dead_tasks
from wca.cgroups import Cgroup
from wca.platforms import RDTInformation
from wca.perf import PerfCounters
from wca.resctrl import ResGroup
from wca.testing import task, container
from wca.allocators import AllocationConfiguration


def assert_equal_containers(a: ContainerInterface, b: ContainerInterface):
    assert type(a) == type(b)
    assert a.get_cgroup_path() == b.get_cgroup_path()
    if type(a) == ContainerSet:
        assert len(a._subcontainers) == len(b._subcontainers)
        assert all([child_a.get_cgroup_path() == child_b.get_cgroup_path()
                    for child_a, child_b in zip(list(a._subcontainers.values()),
                                                list(b._subcontainers.values()))])


def assert_equal_containers_list(containers_a: List[ContainerInterface],
                                 containers_b: List[ContainerInterface]):
    """Compares two lists (order does have importance) of containers.
       IMPORTANT: two containers are HERE
       treated as equal if they have the same cgroup_path set.

       One special assumption is made about private attribute of
       ContainerSet: that field _subcontainers exists with type
       Dict[str, Container]."""
    assert len(containers_a) == len(containers_b)
    for a, b in zip(containers_a, containers_b):
        assert_equal_containers(a, b)


@pytest.mark.parametrize(
    'discovered_tasks, containers, '
    'expected_new_tasks, expected_containers_to_delete', (
        # 1) One new task (t1) was discovered - before there was no containers.
        ([task('/t1')], [],
         [task('/t1')], []),
        # 2) No changes in environment - no actions are expected.
        ([task('/t1')], [container('/t1')],
         [], []),
        # 3) One new task (t2) was discovered.
        ([task('/t1'), task('/t2')], [container('/t1')],
         [task('/t2')], []),
        # 4) No changes in environment - no actions are expected
        #    (but now two containers already are running).
        ([task('/t1'), task('/t2')], [container('/t1'), container('/t2')],
         [], []),
        # 5) First task just disappeared - corresponding container should be removed.
        ([task('/t2')], [container('/t1'), container('/t2')],
         [], [container('/t1')]),
        # 6) Two new task were discovered.
        ([task('/t1'), task('/t2')], [],
         [task('/t1'), task('/t2')], []),
        # 7) New task was discovered and one task disappeared.
        ([task('/t1'), task('/t3')], [container('/t1'), container('/t2')],
         [task('/t3')], [container('/t2')]),
    ))
def test_find_new_and_dead_tasks(discovered_tasks, containers,
                                 expected_new_tasks, expected_containers_to_delete):
    new_tasks, containers_to_delete = _find_new_and_dead_tasks(
        discovered_tasks, containers)

    assert new_tasks == expected_new_tasks
    assert_equal_containers_list(containers_to_delete, expected_containers_to_delete)


@patch('wca.resctrl.ResGroup.remove')
@patch('wca.resctrl.ResGroup.add_pids')
@patch('wca.resctrl.clean_taskless_groups')
@patch('wca.perf.PerfCounters')
@patch('wca.containers.Container.sync')
@patch('wca.containers.Container.get_pids')
@pytest.mark.parametrize('subcgroups', ([], ['/t1/c1', '/t1/c2']))
@pytest.mark.parametrize(
    'tasks_, pre_running_containers_, mon_groups_relation,'
    'expected_running_containers_, labels_relation_,'
    'pre_running_labels_relation_',
    (
        # 1) Before the start - expecting no running containers.
        ([], {}, {},
         {}, {}, {}),
        # 2) One new task arrived - expecting that new container will be created.
        (['/t1'], {}, {},
         {'/t1': '/t1'}, {'/t1': {'some_label': 'some_value'}},
         {}),
        # 3) One task disappeared, one appeared.
        (['/t1'], {'/t2': '/t2'}, {'be': ['t2', 't1']},
         {'/t1': '/t1'}, {'/t1': {'some_label': 'new_value'}},
         {'/t1': {'some_label': 'some_value'}}),
        # 4) One (of two) task disappeared (t2 has it's own resgroup).
        (['/t1'], {'/t1': '/t1', '/t2': '/t2'}, {'t2': ['t2']},
         {'/t1': '/t1'}, {}, {'/t1': {'some_label': 'new_value'}}),
        # 5) Two task (of two) disappeared.
        ([], {'/t1': '/t1', '/t2': '/t2'}, {},
         {}, {}, {}),
    )
)
def test_sync_containers_state(_, get_pids_mock, sync_mock, perf_counters_mock,
                               add_pids_mock, clean_taskless_groups_mock,
                               subcgroups,
                               tasks_, pre_running_containers_,
                               mon_groups_relation, expected_running_containers_,
                               labels_relation_, pre_running_labels_relation_):
    """Tests both Container and ContainerSet classes.

        Note: the input arguments tasks_, existing_containers_, expected_running_containers_
        contain in their names underscore at the end to distinguish them from the ones
        created inside the function body to emphasize the relationship: the input arguments
        is used to create real objects. We cannot pass already created objects, as to
        create them we need another argument from first of two paramatrize decorators:
        subcgroups.

        Note: we have three variables names with the same postfix:
        * pre_running_containers - state of ContainerManager before (pre) call sync_containers_state
        * expected_running_containers - similar as above but state expected after the call,
        * got_running_containers - similar as above but state which we got after the call.
        All of three are of the same type Dict[Task, ContainerInterface].
        """
    # Create Task and Container/ContainerSet objects from input arguments.
    #   This is done to both test Container and ContainerSet classes (to pass
    #   subcgroups argument into the constructing function >>container<<.
    tasks = [task(t, subcgroups_paths=subcgroups, labels=labels_relation_.get(t)) for t in tasks_]
    pre_running_containers = \
        {task(t, subcgroups_paths=subcgroups,
              labels=pre_running_labels_relation_.get(t)): container(c, subcgroups)
         for t, c in pre_running_containers_.items()}

    expected_running_containers = \
        {task(t, subcgroups_paths=subcgroups,
              labels=labels_relation_.get(t)): container(c, subcgroups)
         for t, c in expected_running_containers_.items()}

    rdt_information = RDTInformation(True, True, True, True, 'fff', '1', 0, 0, 0)
    containers_manager = ContainerManager(rdt_information=rdt_information,
                                          platform_cpus=1,
                                          platform_sockets=1,
                                          allocation_configuration=AllocationConfiguration(),
                                          event_names=[],
                                          )
    # Put in into ContainerManager our input dict of containers.
    containers_manager.containers = dict(pre_running_containers)

    # Call sync_containers_state
    with patch('wca.resctrl.read_mon_groups_relation', return_value=mon_groups_relation):
        got_running_containers = containers_manager.sync_containers_state(tasks)

    # -----------------------
    # Assert that two sets of keys of two dictionaries got_containers and
    # expected_running_containers are equal.
    assert len(got_running_containers) == len(expected_running_containers)
    assert all([expected_task in got_running_containers
                for expected_task in expected_running_containers.keys()])
    for t in expected_running_containers.keys():
        assert_equal_containers(expected_running_containers[t], got_running_containers[t])

    # Check container objects has proper resgroup assigned.
    got_container_resgroup_names = {c.get_name():
                                    c.get_resgroup().name for c in got_running_containers.values()}
    for expected_resgroup_name, container_names in mon_groups_relation.items():
        for container_name in container_names:
            if container_name in got_container_resgroup_names:
                got_resgroup_name = got_container_resgroup_names.get(container_name)
                assert got_resgroup_name == expected_resgroup_name


_ANY_METRIC_VALUE = 2


@patch('wca.cgroups.Cgroup', spec=Cgroup,
       get_measurements=Mock(return_value={'cgroup_metric__1': _ANY_METRIC_VALUE}))
@patch('wca.perf.PerfCounters', spec=PerfCounters,
       get_measurements=Mock(return_value={'perf_event_metric__1': _ANY_METRIC_VALUE}))
@patch('wca.containers.ResGroup', spec=ResGroup,
       get_measurements=Mock(return_value={'foo': 3}))
def test_containerset_get_measurements(resgroup_mock, perfcounter_mock, cgroup_mock):
    """Check whether summing of metrics for children containers are done properly.
       Note: because we are mocking here classes from which measurements are read,
       to calculate the proper value of ContainerSet we just need to multiple that
       single value by count of subcontainers (here defined as N)."""
    N = 3  # 3 subcontainers are created.
    subcgroups_paths = ['/t1/c1', '/t1/c2', '/t1/c3']
    containerset = container('/t1', subcgroups_paths, should_patch=False, rdt_enabled=True)

    containerset.set_resgroup(resgroup=resgroup_mock)

    # Call the main function.
    measurements = containerset.get_measurements()

    resgroup_mock.get_measurements.assert_called_once()
    assert {'foo': 3, 'cgroup_metric__1': _ANY_METRIC_VALUE * N,
            'perf_event_metric__1': _ANY_METRIC_VALUE * N} == measurements


def _smart_get_pids():
    # Note: here List[int] is used instead of >>int<<
    #   to pass mutable object (Integers are immutable in Python).
    calls_count = [1]

    def fun() -> List[str]:
        """Returns list of two consecutive integers. On first call
           return [1,2], on second [3,4], and so forth."""
        calls_count[0] += 2
        return [str(calls_count[0] - 2), str(calls_count[0] - 1)]
    return fun


@patch('wca.cgroups.Cgroup')
@patch('wca.containers.Container', spec=Container, get_pids=Mock(side_effect=_smart_get_pids()))
def test_containerset_get_pids(*args):
    subcgroups_paths = ['/t1/c1', '/t1/c2', '/t1/c3']
    containerset = container('/t1', subcgroups_paths)
    # We expect 6 consecutive numbers starting from 1 - as there are 3 subcgroups paths
    # for the container.
    assert containerset.get_pids() == [str(i) for i in range(1, 7)]


@patch('wca.containers.ResGroup.get_allocations', return_value={})
@patch('wca.cgroups.Cgroup.get_allocations', return_value={})
@patch('wca.containers.Container', spec=Container)
def test_container_get_allocations(*mock):
    c = container("/t1", [], rdt_enabled=True, resgroup_name='t1')
    assert c.get_allocations() == {}


@patch('wca.containers.ResGroup.get_allocations', return_value={})
@patch('wca.cgroups.Cgroup.get_allocations', return_value={})
@patch('wca.containers.ContainerSet', spec=ContainerSet)
def test_containerset_get_allocations(*mock):
    c = container("/t1", ['/t1/s1', '/t1/s2'], rdt_enabled=True, resgroup_name='t1')
    assert c.get_allocations() == {}
