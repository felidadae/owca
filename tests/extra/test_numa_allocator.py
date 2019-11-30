import pytest
from pprint import pprint
from unittest.mock import Mock, patch
from typing import Dict, List

from wca.detectors import TaskData, TasksData
from wca.metrics import MetricName, MetricValue
from wca.platforms import Platform
from wca.allocators import AllocationType

from wca.extra.numa_allocator import NUMAAllocator, _platform_total_memory, GB, _get_task_memory_limit, \
        _get_numa_node_preferences, _get_most_used_node, _get_least_used_node, _get_current_node, \
        _get_best_memory_node, _get_best_memory_node_v3, _get_most_free_memory_node, _get_most_free_memory_node_v3, _is_enough_memory_on_target, PAGE_SIZE


def prepare_input(tasks, numa_nodes):
    assert numa_nodes > 1, 'numa nodes must be greater than 1'

    print_structures: bool = False
    node_size = 96 * GB
    page_size = 4096
    node_cpu = 10
    node_size_pages = node_size / page_size
    cp_memory_per_node_percentage = 0.04

    tasks_data: TasksData = dict()
    for task_name, numa_memory in tasks.items():
        measurements = dict()
        measurements[MetricName.MEM_NUMA_STAT_PER_TASK] = \
            {str(numa_id): int(v * node_size_pages) for numa_id, v in numa_memory.items()}
        data = TaskData(
            name=task_name, task_id=task_name, cgroup_path='', subcgroups_paths=[''], labels={'uid': task_name},
            resources={'mem': int(sum(numa_memory.values()) * node_size)}, measurements=measurements)
        tasks_data[task_name] = data
    if print_structures:
        pprint(tasks_data)

    def node_cpus(numa_nodes):
        return {i: set(range(i*node_cpu, (i+1)*node_cpu)) for i in range(numa_nodes)}

    platform_mock = Mock(spec=Platform, cpus=2*node_cpu, sockets=numa_nodes,
                         node_cpus=node_cpus(numa_nodes), topology={},
                         numa_nodes=numa_nodes, cpu_codename=None)
    if print_structures:
        pprint(platform_mock.topology)

    def empty_measurements():
        return {v: {} for v in range(numa_nodes)}
    platform_mock.measurements = {MetricName.MEM_NUMA_FREE: empty_measurements(), MetricName.MEM_NUMA_USED: empty_measurements()}

    # Only percentage first
    for numa_node in range(numa_nodes):
        platform_mock.measurements[MetricName.MEM_NUMA_FREE][numa_node] = \
            (1.0-cp_memory_per_node_percentage-sum( [memory.get(numa_node, 0) for memory in tasks.values()] ))
    if print_structures:
        pprint(platform_mock.measurements)

    # Multiply by node_size
    for numa_node in range(numa_nodes):
        platform_mock.measurements[MetricName.MEM_NUMA_FREE][numa_node] = \
            int(platform_mock.measurements[MetricName.MEM_NUMA_FREE][numa_node] * node_size)
        platform_mock.measurements[MetricName.MEM_NUMA_USED][numa_node] = \
            node_size - platform_mock.measurements[MetricName.MEM_NUMA_FREE][numa_node]
    if print_structures:
        pprint(platform_mock.measurements)

    # Add allocations to tasks_data[task]
    for task_name, numa_memory in tasks.items():
        # if len(..) == 1, then pinned, just to shorten notation
        if len(numa_memory.keys()) == 1:
            tasks_data[task_name].allocations = \
                {AllocationType.CPUSET_CPUS: ','.join(map(str,platform_mock.node_cpus[list(numa_memory.keys())[0]]))}
        # cpuset_cpus no pinned, means pinned to all available cpus
        else:
            tasks_data[task_name].allocations = \
                {AllocationType.CPUSET_CPUS: ','.join(map(str, range(numa_nodes * node_cpu)))}
    if print_structures:
        pprint(tasks_data.allocations)

    return platform_mock, tasks_data

results_params = {
    'double_match': False,
    'candidate': True,
    'migrate_pages': True
}
alexander_params = {
    'double_match': True,
    'candidate': False,
    'migrate_pages': True
}
def merge_dicts(a,b):
    c = a.copy()
    c.update(b)
    return c

@pytest.mark.parametrize('constructor_params, tasks, moves', [
    # empty
    (
        [results_params, alexander_params],
        {},
        {}
    ),

    # t1 pinned to 0, t2 should be pinned to 1
    (
        [results_params, alexander_params],
        {'t1': {0:0.3}, 't2': {0:0.1, 1:0.1}},
        {'t2': 1}
    ),

    # t3 pinned to 1, t2 (as a bigger task) should be pinned to 0
    (
        [results_params, alexander_params],
        {'t1': {0: 0.1, 1: 0.2},
         't2': {0: 0.4, 1: 0.0},
         't3': {1: 0.5}},
        {'t2': 0}
    ),

    # not enough space for t3, t1 and t2 pinned
    (
        [merge_dicts(results_params, {'free_space_check': True}), merge_dicts(alexander_params, {'free_space_check': True})],
        {'t1': {0: 0.8},
         't2': {1: 0.8},
         't3': {0: 0.1, 1: 0.15}},
        {}
    ),
])
def test_algorithm(constructor_params: List[Dict],
                   tasks: Dict[str, Dict[int, MetricValue]],
                   moves: List[Dict[str, int]]):
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


def test_platform_total_memory():
    platform = Mock()
    platform.measurements = dict()
    platform.measurements[MetricName.MEM_NUMA_FREE] = {0: 200, 1: 300}
    platform.measurements[MetricName.MEM_NUMA_USED] = {0: 100, 1: 100}
    assert _platform_total_memory(platform) == (200+300+100+100)


def test_get_task_memory_limit():
    tasks_measurements = {}
    total_memory = 96 * GB
    task = 't1'
    task_resources = {'mem': 20 * GB, 'cpus': 11.0, 'disk': 10 * GB}

    # where 'mem' in task_resources
    assert _get_task_memory_limit(tasks_measurements, total_memory, task, task_resources) == 20 * GB

    # no 'mem' in task_resources and task_measurements empty
    task_resources = {}
    assert _get_task_memory_limit(tasks_measurements, total_memory, task, task_resources) == 0

    # no 'mem' in task_resources and task_measurement contains MetricName.MEM_LIMIT_PER_TASK
    tasks_measurements = {MetricName.MEM_LIMIT_PER_TASK: 30 * GB}
    assert _get_task_memory_limit(tasks_measurements, total_memory, task, task_resources) == 30 * GB

    # no 'mem' in task_resources and task_measurement contains MetricName.MEM_LIMIT_PER_TASK, but total_memory smaller than that value
    total_memory = 20 * GB
    assert _get_task_memory_limit(tasks_measurements, total_memory, task, task_resources) == 0


@pytest.mark.parametrize('numa_nodes, task_measurements_vals, expected', (
    (2, [5 * GB, 5 * GB], {0: 0.5, 1: 0.5}),
    (2, [3 * GB, 2 * GB], {0: 0.6, 1: 0.4}),
    (4, [3 * GB, 2 * GB, 3 * GB, 2 * GB], {0: 0.3, 1: 0.2, 2: 0.3, 3: 0.2}),
))
def test_get_numa_node_preferences(numa_nodes, task_measurements_vals, expected):
    task_measurements = {MetricName.MEM_NUMA_STAT_PER_TASK: {inode: val for inode, val in
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
    platform.measurements = {MetricName.MEM_NUMA_FREE: numa_free}
    assert _get_least_used_node(platform) == expected


@pytest.mark.parametrize('cpus_assigned, node_cpus, expected', (
    (set(range(0,10)), {0: set(range(0,10)), 1: set(range(10,20))}, 0),
    (set(range(0,20)), {0: set(range(0,10)), 1: set(range(10,20))}, -1),
))
def test_get_current_node(cpus_assigned, node_cpus, expected):
    assert _get_current_node(cpus_assigned, node_cpus) == expected


@pytest.mark.parametrize('memory, balanced_memory, expected', (
    (10 * GB, {0: [('task1', 20 * GB), ('task2', 20 * GB)], 1: [('task3', 15 * GB ), ('task4', 10 * GB)]}, 1),
))
def test_get_best_memory_node(memory, balanced_memory, expected):
    assert _get_best_memory_node(memory, balanced_memory) == expected


@pytest.mark.parametrize('memory, balanced_memory, expected', (
    (10 * GB, {0: [('task1', 20 * GB),], 1: [('task3', 19 * GB ),]}, {0,1}),
    (10 * GB, {0: [('task1', 20 * GB),], 1: [('task3', 17 * GB ),]}, {0,1}),
    (10 * GB, {0: [('task1', 20 * GB),], 1: [('task3', 13 * GB ),]}, {1}),
    (50 * GB, {0: [('task1', 80 * GB), ], 1: [('task3', 60 * GB), ]}, {1}),
))
def test_get_best_memory_node_v3(memory, balanced_memory, expected):
    assert _get_best_memory_node_v3(memory, balanced_memory) == expected


@pytest.mark.parametrize('memory, node_memory_free, expected', (
    (2 * GB, {0: 5 * GB, 1: 3 * GB}, 0),
))
def test_get_free_memory_node(memory, node_memory_free, expected):
    assert _get_most_free_memory_node(memory, node_memory_free) == expected


@pytest.mark.parametrize('memory, node_memory_free, expected', (
    (27 * GB, {0: 34 * GB, 1: 35 * GB}, {0,1}),
    (28 * GB, {0: 34 * GB, 1: 35 * GB}, {1}),
))
def test_get_free_memory_node_v3(memory, node_memory_free, expected):
    assert _get_most_free_memory_node_v3(memory, node_memory_free) == expected


@pytest.mark.parametrize('target_node, task_max_memory, numa_free, numa_task, expected', (
    (1, 10 * GB, {0: 2 * GB, 1: 3 * GB}, {"0": 3 * GB/PAGE_SIZE, "1": 2 * GB/PAGE_SIZE}, False),
    (1, 10 * GB, {0: 6 * GB, 1: 6 * GB}, {"0": 5 * GB/PAGE_SIZE, "1": 5 * GB/PAGE_SIZE}, True),
))
def test_is_enough_memory_on_target(target_node, task_max_memory, numa_free, numa_task, expected):
    platform = Mock()
    platform.measurements[MetricName.MEM_NUMA_FREE] = numa_free
    tasks_measurements = {'t1': {MetricName.MEM_NUMA_STAT_PER_TASK: numa_task}}
    assert _is_enough_memory_on_target(
        't1', target_node, platform, tasks_measurements, task_max_memory) == expected
