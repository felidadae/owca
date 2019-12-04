from pprint import pprint
from typing import Dict, List, Tuple
from unittest.mock import Mock

import pytest

from wca.allocators import AllocationType
from wca.detectors import TaskData, TasksData, TaskResource
from wca.extra.numa_allocator import NUMAAllocator, _get_platform_total_memory, GB, _get_task_memory_limit, \
    _get_numa_node_preferences, _get_most_used_node, _get_least_used_node, _get_current_node, \
    _get_best_memory_node, _get_best_memory_nodes, _get_most_free_memory_node, _get_most_free_memory_nodes, \
    _is_enough_memory_on_target, get_page_size, TaskId, NumaNodeId, _build_tasks_memory, _build_balanced_memory, \
    _get_pages_to_move, _is_ghost_task, _is_task_pinned, migration_minimizer_core
from wca.metrics import MetricName, MetricValue
from wca.platforms import Platform

# value from 0 to 1.0
PercentageMemUsage = float

NODE_SIZE = 96 * GB


def get_task_size_on_node(percentage_mem_usage: PercentageMemUsage):
    return int(percentage_mem_usage * NODE_SIZE)


def prepare_input(tasks: Dict[TaskId, Dict[NumaNodeId, PercentageMemUsage]],
                  numa_nodes: int) -> Tuple[Platform, TasksData]:
    """if len(tasks[task]) == 1, it means that task is pinned to that single numa node"""
    assert numa_nodes > 1, 'numa nodes must be greater than 1'

    print_structures: bool = False
    node_size = 96 * GB
    node_cpu = 10
    node_size_pages = node_size / get_page_size()
    cp_memory_per_node_percentage = 0.04

    tasks_data: TasksData = dict()
    for task_name, numa_memory in tasks.items():
        measurements = dict()
        measurements[MetricName.TASK_MEM_NUMA_PAGES] = \
            {str(numa_id): int(v * node_size_pages) for numa_id, v in numa_memory.items()}
        data = TaskData(
            name=task_name, task_id=task_name, cgroup_path='', subcgroups_paths=[''], labels={'uid': task_name},
            resources={'mem': int(sum(numa_memory.values()) * node_size)}, measurements=measurements)
        tasks_data[task_name] = data
    if print_structures:
        pprint(tasks_data)

    def node_cpus(numa_nodes):
        return {i: set(range(i * node_cpu, (i + 1) * node_cpu)) for i in range(numa_nodes)}

    platform_mock = Mock(spec=Platform, cpus=2 * node_cpu, sockets=numa_nodes,
                         node_cpus=node_cpus(numa_nodes), topology={},
                         numa_nodes=numa_nodes, cpu_codename=None)
    if print_structures:
        pprint(platform_mock.topology)

    def empty_measurements():
        return {v: {} for v in range(numa_nodes)}

    platform_mock.measurements = {MetricName.PLATFORM_MEM_NUMA_FREE_BYTES: empty_measurements(),
                                  MetricName.PLATFORM_MEM_NUMA_USED_BYTES: empty_measurements()}

    # Only percentage first
    for numa_node in range(numa_nodes):
        platform_mock.measurements[MetricName.PLATFORM_MEM_NUMA_FREE_BYTES][numa_node] = \
            (1.0 - cp_memory_per_node_percentage - sum([memory.get(numa_node, 0) for memory in tasks.values()]))
    if print_structures:
        pprint(platform_mock.measurements)

    # Multiply by node_size
    for numa_node in range(numa_nodes):
        platform_mock.measurements[MetricName.PLATFORM_MEM_NUMA_FREE_BYTES][numa_node] = \
            int(platform_mock.measurements[MetricName.PLATFORM_MEM_NUMA_FREE_BYTES][numa_node] * node_size)
        platform_mock.measurements[MetricName.PLATFORM_MEM_NUMA_USED_BYTES][numa_node] = \
            node_size - platform_mock.measurements[MetricName.PLATFORM_MEM_NUMA_FREE_BYTES][numa_node]
    if print_structures:
        pprint(platform_mock.measurements)

    # Add allocations to tasks_data[task]
    for task_name, numa_memory in tasks.items():
        # if len(..) == 1, then pinned, just to shorten notation
        if len(numa_memory.keys()) == 1:
            tasks_data[task_name].allocations = \
                {AllocationType.CPUSET_CPUS: ','.join(map(str, platform_mock.node_cpus[list(numa_memory.keys())[0]]))}
        # cpuset_cpus no pinned, means pinned to all available cpus
        else:
            tasks_data[task_name].allocations = \
                {AllocationType.CPUSET_CPUS: ','.join(map(str, range(numa_nodes * node_cpu)))}
    if print_structures:
        pprint(tasks_data.allocations)

    return platform_mock, tasks_data


fill_biggest_first_params = {
    'algorithm': NUMAAllocator.fill_biggest_first_,
    'migrate_pages': True
}
minimize_migrate_params = {
    'algorithm': NUMAAllocator.minimize_migration_,
    'migrate_pages': True
}


def merge_dicts(a, b):
    c = a.copy()
    c.update(b)
    return c


@pytest.mark.parametrize('constructor_params, tasks, moves', [
    # empty
    (
            [fill_biggest_first_params, minimize_migrate_params],
            {},
            {}
    ),

    # t1 pinned to 0, t2 should be pinned to 1
    (
            [fill_biggest_first_params, minimize_migrate_params],
            {'t1': {0: 0.3}, 't2': {0: 0.1, 1: 0.1}},
            {'t2': 1}
    ),

    # t3 pinned to 1, t2 (as a bigger task) should be pinned to 0
    (
            [fill_biggest_first_params, minimize_migrate_params],
            {'t1': {0: 0.1, 1: 0.2},
             't2': {0: 0.4, 1: 0.0},
             't3': {1: 0.5}},
            {'t2': 0}
    ),

    # not enough space for t3, t1 and t2 pinned
    (
            [merge_dicts(fill_biggest_first_params, {'free_space_check': True}),
             merge_dicts(minimize_migrate_params, {'free_space_check': True})],
            {'t1': {0: 0.8},
             't2': {1: 0.8},
             't3': {0: 0.1, 1: 0.15}},
            {}
    ),

    # not enough space for t3, t1 and t2 pinned
    (
            [merge_dicts(fill_biggest_first_params, {'free_space_check': True}),
             merge_dicts(minimize_migrate_params, {'free_space_check': True})],
            {'t1': {0: 0.8},
             't2': {1: 0.8},
             't3': {0: 0.1, 1: 0.15}},
            {}
    ),
])
def test_algorithm(constructor_params: List[Dict],
                   tasks: Dict[TaskId, Dict[NumaNodeId, MetricValue]],
                   moves: List[Dict[TaskId, NumaNodeId]]):
    input_ = prepare_input(tasks=tasks, numa_nodes=2)
    platform_mock = input_[0]

    for i, constructor_param in enumerate(constructor_params):
        allocator = NUMAAllocator(**constructor_param)
        got_allocations, _, _ = allocator.allocate(*input_)

        expected_allocations = dict()
        moves = moves if type(moves) is not List else moves[i]
        for task_name, numa_node in moves.items():
            expected_allocations[task_name] = \
                {AllocationType.CPUSET_CPUS: ','.join(map(str, platform_mock.node_cpus[numa_node]))}
            if 'migrate_pages' in constructor_param:
                expected_allocations[task_name]['migrate_pages'] = moves[task_name]

        assert got_allocations == expected_allocations


@pytest.mark.parametrize('most_used, best_memory, best_free, expected', (
        ({1, 2, 3}, {1, 2}, {3}, 1),
        ({1}, {2}, {1}, 1),
        ({1}, {2}, {2}, 2),
        ({1}, {2}, {3}, None),
))
def test_migration_minimizer_core(most_used, best_memory, best_free, expected):
    assert migration_minimizer_core('t1', most_used, best_memory, best_free)[1] == expected


def test_build_tasks_memory():
    mem_usage_on_node = 0.3
    platform, tasks_data = prepare_input({'t1': {0: mem_usage_on_node}}, 2)
    assert _build_tasks_memory(tasks_data, platform) == \
           [('t1', get_task_size_on_node(mem_usage_on_node), {0: 1.0, 1: 0.0})]


def test_build_balanced_memory():
    mem_usage_on_node = 0.3
    platform, tasks_data = prepare_input({'t1': {0: mem_usage_on_node}}, 2)
    tasks_memory = _build_tasks_memory(tasks_data, platform)
    assert _build_balanced_memory(tasks_memory, tasks_data, platform) == \
    {0: [ ('t1', get_task_size_on_node(mem_usage_on_node)), ], 1: []}


def test_get_pages_to_move():
    mem_usage_on_node = 0.3
    platform, tasks_data = prepare_input({'t1': {0: mem_usage_on_node}}, 2)
    assert _get_pages_to_move('t1', tasks_data, 1, 'for fun') == \
    tasks_data['t1'].measurements[MetricName.TASK_MEM_NUMA_PAGES]['0']


def test_platform_total_memory():
    platform = Mock()
    platform.measurements = dict()
    platform.measurements[MetricName.PLATFORM_MEM_NUMA_FREE_BYTES] = {0: 200, 1: 300}
    platform.measurements[MetricName.PLATFORM_MEM_NUMA_USED_BYTES] = {0: 100, 1: 100}
    assert _get_platform_total_memory(platform) == (200 + 300 + 100 + 100)


def test_get_task_memory_limit():
    tasks_measurements = {}
    total_memory = 96 * GB
    task = 't1'
    task_resources = {TaskResource.MEM: 20 * GB, TaskResource.CPUS: 11.0, TaskResource.DISK: 10 * GB}

    # where 'mem' in task_resources
    assert _get_task_memory_limit(tasks_measurements, total_memory, task, task_resources) == 20 * GB

    # no 'mem' in task_resources and task_measurements empty
    task_resources = {}
    assert _get_task_memory_limit(tasks_measurements, total_memory, task, task_resources) == 0

    # no 'mem' in task_resources and task_measurement contains MetricName.TASK_MEM_LIMIT_BYTES
    tasks_measurements = {MetricName.TASK_MEM_LIMIT_BYTES: 30 * GB}
    assert _get_task_memory_limit(tasks_measurements, total_memory, task, task_resources) == 30 * GB

    # no 'mem' in task_resources and task_measurement
    # contains MetricName.TASK_MEM_LIMIT_BYTES, but total_memory smaller than that value
    total_memory = 20 * GB
    assert _get_task_memory_limit(tasks_measurements, total_memory, task, task_resources) == 0


@pytest.mark.parametrize('numa_nodes, task_measurements_vals, expected', (
        (2, [5 * GB, 5 * GB], {0: 0.5, 1: 0.5}),
        (2, [3 * GB, 2 * GB], {0: 0.6, 1: 0.4}),
        (4, [3 * GB, 2 * GB, 3 * GB, 2 * GB], {0: 0.3, 1: 0.2, 2: 0.3, 3: 0.2}),
))
def test_get_numa_node_preferences(numa_nodes, task_measurements_vals, expected):
    task_measurements = {MetricName.TASK_MEM_NUMA_PAGES: {inode: val for inode, val in
                                                             enumerate(task_measurements_vals)}}
    assert _get_numa_node_preferences(task_measurements, numa_nodes) == expected


@pytest.mark.parametrize('preferences, expected', (
        ({0: 0.3, 1: 0.7}, 1),
        ({0: 0.3, 2: 0.3, 3: 0.2, 4: 0.2}, 0),
))
def test_get_most_used_node(preferences, expected):
    assert _get_most_used_node(preferences) == expected


@pytest.mark.parametrize('numa_free, expected', (
        ({0: 5 * GB, 1: 3 * GB}, 0),
        ({0: 5 * GB, 1: 3 * GB, 2: 20 * GB}, 2),
))
def test_get_least_used_node(numa_free, expected):
    platform = Mock
    platform.measurements = {MetricName.PLATFORM_MEM_NUMA_FREE_BYTES: numa_free}
    assert _get_least_used_node(platform) == expected


@pytest.mark.parametrize('cpus_assigned, node_cpus, expected', (
        (set(range(0, 10)), {0: set(range(0, 10)), 1: set(range(10, 20))}, 0),
        (set(range(0, 20)), {0: set(range(0, 10)), 1: set(range(10, 20))}, -1),
))
def test_get_current_node(cpus_assigned, node_cpus, expected):
    allocations = {AllocationType.CPUSET_CPUS: ",".join([str(item) for item in cpus_assigned])}
    platform = Mock()
    platform.node_cpus = node_cpus
    assert _get_current_node(allocations, platform) == expected


@pytest.mark.parametrize('memory, balanced_memory, expected', (
        (10 * GB, {0: [('task1', 20 * GB), ('task2', 20 * GB)], 1: [('task3', 15 * GB), ('task4', 10 * GB)]}, 1),
))
def test_get_best_memory_node(memory, balanced_memory, expected):
    assert _get_best_memory_node(memory, balanced_memory) == expected


@pytest.mark.parametrize('memory, balanced_memory, expected', (
        (10 * GB, {0: [('task1', 20 * GB), ], 1: [('task3', 19 * GB), ]}, {0, 1}),
        (10 * GB, {0: [('task1', 20 * GB), ], 1: [('task3', 17 * GB), ]}, {0, 1}),
        (50 * GB, {0: [('task1', 80 * GB), ], 1: [('task3', 60 * GB), ]}, {0, 1}),
        (10 * GB, {0: [('task1', 20 * GB), ], 1: [('task3', 13 * GB), ]}, {1}),
        (10 * GB, {0: [('task1', 20 * GB), ], 1: [('task3', 5 * GB), ]}, {1}),
))
def test_get_best_memory_node_v3(memory, balanced_memory, expected):
    assert _get_best_memory_nodes(memory, balanced_memory) == expected


@pytest.mark.parametrize('memory, node_memory_free, expected', (
        (2 * GB, {0: 5 * GB, 1: 3 * GB}, 0),
))
def test_get_free_memory_node(memory, node_memory_free, expected):
    assert _get_most_free_memory_node(memory, node_memory_free) == expected


@pytest.mark.parametrize('memory, node_memory_free, expected', (
        (27 * GB, {0: 34 * GB, 1: 35 * GB}, {0, 1}),
        (28 * GB, {0: 34 * GB, 1: 35 * GB}, {1}),
))
def test_get_free_memory_node_v3(memory, node_memory_free, expected):
    assert _get_most_free_memory_nodes(memory, node_memory_free) == expected


@pytest.mark.parametrize('target_node, task_max_memory, numa_free, numa_task, expected', (
        (1, 10 * GB, {0: 2 * GB, 1: 3 * GB}, {"0": 3 * GB / get_page_size(), "1": 2 * GB / get_page_size()}, False),
        (1, 10 * GB, {0: 6 * GB, 1: 6 * GB}, {"0": 5 * GB / get_page_size(), "1": 5 * GB / get_page_size()}, True),
))
def test_is_enough_memory_on_target(target_node, task_max_memory, numa_free, numa_task, expected):
    platform = Mock()
    platform.measurements[MetricName.PLATFORM_MEM_NUMA_FREE_BYTES] = numa_free
    tasks_measurements = {MetricName.TASK_MEM_NUMA_PAGES: numa_task}
    assert _is_enough_memory_on_target(
        task_max_memory, target_node, platform, tasks_measurements) == expected


def test_is_task_pinned():
    assert _is_task_pinned(-1) == False
    assert _is_task_pinned(0) == True


def test_is_ghost_task():
    assert _is_ghost_task(0) == True
    assert _is_ghost_task(1024) == False
