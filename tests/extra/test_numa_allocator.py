import pytest
from pprint import pprint
from unittest.mock import Mock, patch
from wca.metrics import MetricName
from tests.testing import platform_mock
from wca.platforms import Platform
from wca.allocators import AllocationType

from wca.extra.numa_allocator import NUMAAllocator


def prepare_input(tasks, numa_nodes):
    GB = 1024 * 1024 * 1024
    assert numa_nodes > 1, 'numa nodes must be greater than 1'

    node_size = 96 * GB
    page_size = 4096
    node_cpu = 10
    node_size_pages = node_size / page_size

    cp_memory_per_node_percentage = 0.04  #proportional t

    #pprint(tasks)

    MetricName.MEM_NUMA_STAT_PER_TASK

    tasks_measurements = {task_name: {MetricName.MEM_NUMA_STAT_PER_TASK: {numa_id: int(v*node_size_pages) for numa_id,v in numa_memory.items()}} 
                          for task_name, numa_memory in tasks.items()}
    #pprint(tasks_measurements)
    tasks_resources = {task_name: {'mem': int(sum(numa_memory.values())* node_size) } for task_name, numa_memory in tasks.items()}
    #pprint(tasks_resources)
    tasks_labels = {task_name: {'uid': task_name} for task_name in tasks}
    # pprint(tasks_labels)

    def node_cpus(numa_nodes):
        r = {}
        for i in range(numa_nodes):
            r[i] = set(range(i*node_cpu, (i+1)*node_cpu))
        return r

    platform_mock = Mock(
        spec=Platform,
        cpus=2*node_cpu,
        sockets=numa_nodes,
        node_cpus=node_cpus(numa_nodes),
        topology={},
        numa_nodes=numa_nodes,
        cpu_codename=None,
    )
    #pprint(platform_mock.topology)

    def empty_measurements():
        return {v: {} for v in range(numa_nodes)}
    platform_mock.measurements = {MetricName.MEM_NUMA_FREE: empty_measurements(), MetricName.MEM_NUMA_USED: empty_measurements()}

    for numa_node in range(numa_nodes):
        platform_mock.measurements[MetricName.MEM_NUMA_FREE][numa_node] = \
            (1.0-cp_memory_per_node_percentage-sum( [memory.get(numa_node, 0) for memory in tasks.values()] ))
    #pprint(platform_mock.measurements)

    for numa_node in range(numa_nodes):
        platform_mock.measurements[MetricName.MEM_NUMA_FREE][numa_node] = \
            int(platform_mock.measurements[MetricName.MEM_NUMA_FREE][numa_node] * node_size)
        platform_mock.measurements[MetricName.MEM_NUMA_USED][numa_node] = \
            node_size - platform_mock.measurements[MetricName.MEM_NUMA_FREE][numa_node]

    #pprint(platform_mock.measurements)

    tasks_allocations = {task_name: {AllocationType.CPUSET_CPUS: ','.join(map(str,platform_mock.node_cpus[list(memory.keys())[0]]))} for task_name, memory in tasks.items() if len(memory.keys()) == 1 }
    #pprint(tasks_allocations)

    tasks_allocations = {task_name: {AllocationType.CPUSET_CPUS: ','.join(map(str, range(numa_nodes*node_cpu)))} 
                         if task_name not in tasks_allocations else tasks_allocations[task_name] for task_name in tasks}
    #pprint(tasks_allocations)

    return platform_mock, tasks_measurements, tasks_resources, tasks_labels, tasks_allocations

@pytest.mark.parametrize('tasks, moves', [
    # # empty
    # (
    #     {},
    #     {}
    # ),

    # # t1 pinned to 0, t2 should be pinned to 1
    # (
    #     {'t1': {0:0.3}, 't2': {0:0.1, 1:0.1}},
    #     {'t2': 1}
    # ),

    # # t3 pinned to 1, t2 (as a bigger task) should be pinned to 0
    # (
    #     {'t1': {0: 0.1, 1: 0.2}, 
    #      't2': {0: 0.4, 1: 0.0},
    #      't3': {1: 0.5}},
    #     {'t2': 0}
    # ),

    # not enough space for t3, t1 and t2 pinned
    (
        {'t1': {0: 0.8}, 
         't2': {1: 0.8},
         't3': {0: 0.1, 1: 0.15}},
        {}
    ),
])
def test_candidate(tasks, moves):
    input_ = prepare_input(tasks=tasks, numa_nodes=2)
    platform_mock = input_[0]
    allocator = NUMAAllocator(double_match=False, candidate=True)
    got_allocations, _, _ = allocator.allocate(*input_)
    pprint(got_allocations)
    expected_allocations = {task_name: {AllocationType.CPUSET_CPUS: ','.join(map(str,platform_mock.node_cpus[numa_node]))} for task_name, numa_node in moves.items()}
    for task_name in expected_allocations:
        if allocator.migrate_pages:
            expected_allocations[task_name]['migrate_pages'] = moves[task_name]
 
    assert got_allocations == expected_allocations
