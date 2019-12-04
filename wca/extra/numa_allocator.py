import logging
import math
from typing import List, Dict, Union, Tuple, Optional, Set

from dataclasses import dataclass
from enum import Enum

from wca.allocators import Allocator, TasksAllocations, AllocationType, TaskAllocations
from wca.detectors import Anomaly, TaskData, TasksData, TaskResource
from wca.logger import TRACE
from wca.metrics import Metric, MetricName, Measurements
from wca.platforms import Platform, encode_listformat, decode_listformat

log = logging.getLogger(__name__)

GB = 2 ** 30
MB = 2 ** 20

NumaNodeId = int
Preferences = Dict[NumaNodeId, float]
TaskId = str
MemoryLimit = int
BalancedMemory = Dict[NumaNodeId, List[Tuple[TaskId, MemoryLimit]]]
# task_name, memory_limit, list of preferences
TaskMemory = Tuple[TaskId, MemoryLimit, Preferences]
TasksMemory = List[TaskMemory]


@dataclass
class NUMAAllocator(Allocator):
    """solve bin packing problem by heuristic which takes the biggest first"""
    fill_biggest_first_ = 'fill_biggest_first'

    """tries to minimize how much memory is migrated between numa nodes; in other words tries to keep taski
    where most of its memory resides"""
    minimize_migration_ = 'minimize_migration'

    algorithm: str = fill_biggest_first_

    # minimal value of task_balance so the task is not skipped during rebalancing analysis
    # by default turn off, none of tasks are skipped due to this reason
    loop_min_task_balance: float = 0.0

    # If True, then do not migrate if not enough space on target numa node.
    free_space_check: bool = False

    # syscall "migrate pages" per process memory migration
    migrate_pages: bool = True
    # if None re-migration of pages for tasks disabled
    migrate_pages_min_task_balance: Optional[float] = 0.95

    # cgroups based memory migration, cpu and memory pinning
    cgroups_cpus_binding: bool = True
    cgroups_memory_binding: bool = False
    # can be used only when cgroups_memory_binding is set to True
    cgroups_memory_migrate: bool = False

    # dry-run (for comparison only)
    dryrun: bool = False

    def __post_init__(self):
        self._pages_to_move = {}

    def allocate(self, platform: Platform, tasks_data: TasksData) -> (TasksAllocations, List[Anomaly], List[Metric]):
        allocations = {}
        extra_metrics = []

        self._log_initial(platform, tasks_data)

        # 1. First, get current state of the system
        tasks_memory: TasksMemory = _build_tasks_memory(tasks_data, platform)
        balanced_memory: BalancedMemory = _build_balanced_memory(tasks_memory, tasks_data, platform)
        _log_initial_state(tasks_data, balanced_memory, extra_metrics)

        if self.dryrun:
            return allocations, [], extra_metrics

        # 2. Re-balancing analysis
        log.log(TRACE, 'Starting re-balancing analysis')
        balance_task, balance_task_node = None, None

        task_memory: TaskMemory
        for task_memory in tasks_memory:
            task, memory_limit, preferences = task_memory
            self._pages_to_move.setdefault(task, 0)
            task_data: TaskData = tasks_data[task]
            current_node = _get_current_node(task_data.allocations, platform)
            _log_task_basic_info(extra_metrics, tasks_data, task_memory, current_node)

            if _is_task_pinned(current_node) or _is_ghost_task(memory_limit):
                continue

            if balance_task is None:
                if self.algorithm == self.minimize_migration_:
                    balance_task, balance_task_node = self.migration_minimizer(task_data, task_memory, balanced_memory,
                                                                               platform)
                elif self.algorithm == self.fill_biggest_first_:
                    balance_task, balance_task_node = self.fill_biggest_first(task, memory_limit, balanced_memory)

                # Validate if we have enough memory to migrate to desired node.
                if balance_task is not None:
                    if self.free_space_check and not _is_enough_memory_on_target(memory_limit, balance_task_node,
                                                                                 platform, task_data.measurements):
                        log.debug("\tIGNORE CHOSEN: not enough free space on target node %s", balance_task_node)
                        balance_task, balance_task_node = None, None

        # Do not send metrics of not existing tasks.
        self._update_pages_to_move(tasks_data)

        # 3. Perform CPU pinning with optional memory binding and forced migration on >>balance_task<<

        if balance_task is not None:
            self._allocate_task(allocations, balance_task, balance_task_node, tasks_data, platform)

        # 4. Memory migration of tasks already pinned. In that step we do not check if there is enough space
        #   on target node (self.free_space_check).

        if self.migrate_pages and self.migrate_pages_min_task_balance is not None:
            self._remigrate_pages_of_unbalanced_tasks(tasks_data, tasks_memory, platform)

        # 5. Add final metrics and return

        self._log_moved_pages(extra_metrics, tasks_data)
        log.log(TRACE, 'Allocations: %r', allocations)

        return allocations, [], extra_metrics

    def migration_minimizer(self, task_data: TaskData, task_memory: TaskMemory, balanced_memory: BalancedMemory,
                            platform: Platform) -> Tuple[str, int]:
        balance_task, balance_task_node = None, None
        task, memory, preferences = task_memory

        numa_free_measurements = platform.measurements[MetricName.PLATFORM_MEM_NUMA_FREE_BYTES]

        most_used_nodes = _get_most_used_nodes(preferences)
        best_memory_nodes = _get_best_memory_nodes(memory, balanced_memory)
        most_free_memory_nodes = _get_most_free_memory_nodes(memory, numa_free_measurements)

        log.log(TRACE, "Analysing task %r: Most used nodes: %s,"
                       " Best free nodes: %s, Best memory nodes: %s",
                (task_data.name, most_used_nodes, most_free_memory_nodes, best_memory_nodes))

        if preferences[_get_most_used_node(preferences)] < self.loop_min_task_balance:
            log.log(TRACE, "   THRESHOLD: skipping due to loop_min_task_balance")
            return None, None

        return migration_minimizer_core(task, most_used_nodes, best_memory_nodes, most_free_memory_nodes)


    def fill_biggest_first(self, task: TaskId, memory_limit: MemoryLimit, balanced_memory: BalancedMemory) -> Tuple[
        str, int]:
        return task, _get_best_memory_node(memory_limit, balanced_memory)

    def _allocate_task(self, allocations: TaskAllocations, balance_task: TaskId, balance_task_node: NumaNodeId,
                       tasks_data: TasksData, platform: Platform):
        log.debug("Task %r: assiging to node %s." % (balance_task, balance_task_node))
        allocations[balance_task] = {
            AllocationType.CPUSET_CPUS: encode_listformat(
                platform.node_cpus[balance_task_node]),
        }
        if self.cgroups_memory_binding:
            allocations[balance_task][AllocationType.CPUSET_MEMS] = encode_listformat({balance_task_node})

            if self.cgroups_memory_migrate:
                log.debug("Assign task %s to node %s with memory migrate" %
                          (balance_task, balance_task_node))
                allocations[balance_task][AllocationType.CPUSET_MEM_MIGRATE] = 1

        if self.migrate_pages:
            self._pages_to_move[balance_task] += _get_pages_to_move(
                balance_task, tasks_data, balance_task_node, 'initial assignment')
            allocations.setdefault(balance_task, {})
            allocations[balance_task][AllocationType.MIGRATE_PAGES] = balance_task_node

    def _update_pages_to_move(self, tasks_data: TasksData):
        old_tasks = [task for task in self._pages_to_move if task not in tasks_data]
        for old_task in old_tasks:
            if old_task in self._pages_to_move:
                del self._pages_to_move[old_task]

    def _log_moved_pages(self, extra_metrics: List[Metric], tasks_data: TasksData):
        """modify extra_metrics"""
        for task, page_to_move in self._pages_to_move.items():
            data: TaskData = tasks_data[task]
            extra_metrics.append(
                Metric('numa__task_pages_to_move', value=page_to_move,
                       labels=data.labels)
            )
        total_pages_to_move = sum(p for p in self._pages_to_move.values())
        extra_metrics.append(
            Metric('numa__total_pages_to_move', value=total_pages_to_move)
        )
        log.log(TRACE, 'Pages to move: %r', self._pages_to_move)

    def _remigrate_pages_of_unbalanced_tasks(self, tasks_data: TasksData, tasks_memory: TasksMemory,
                                             platform: Platform):
        log.log(TRACE, 'Migrating pages of tasks to balance memory between nodes')

        tasks_to_balance = []
        tasks_current_nodes = {}

        for task, memory_limit, preferences in tasks_memory:
            current_node = _get_current_node(tasks_data[task].allocations, platform)
            tasks_current_nodes[task] = current_node

            if current_node >= 0 and preferences[current_node] < self.migrate_pages_min_task_balance:
                tasks_to_balance.append(task)

        # If necessary migrate pages to least used node, for task that are still not there.
        least_used_node = _get_least_used_node(platform)
        log.log(TRACE, 'Least used node: %s', least_used_node)
        log.log(TRACE, 'Tasks to balance: %s', tasks_to_balance)

        for task in tasks_to_balance:  # already pinned tasks
            if tasks_current_nodes[task] == least_used_node:
                current_node = tasks_current_nodes[task]
                self._pages_to_move[task] += _get_pages_to_move(
                    task, tasks_data,
                    current_node, 'NUMA nodes balance disturbed')

                tasks_data[task].allocations.setdefault(task, {})
                tasks_data[task].allocations[task][AllocationType.MIGRATE_PAGES] = str(current_node)
        log.log(TRACE, 'Finished migrating pages of tasks')

    def _log_initial(self, platform: Platform, tasks_data: TasksData):
        log.debug('')
        log.debug('NUMAAllocator v7: dryrun=%s cgroups_memory_binding/migrate=%s/%s'
                  ' migrate_pages=%s algorithm=%s tasks=%s', self.dryrun,
                  self.cgroups_memory_binding, self.cgroups_memory_migrate,
                  self.migrate_pages, self.algorithm, len(tasks_data))
        log.log(TRACE, 'Tasks data %r', tasks_data)


def migration_minimizer_core(task: TaskId, most_used_nodes: Set[NumaNodeId],
                             best_memory_nodes: Set[NumaNodeId], most_free_memory_nodes: Set[NumaNodeId]):
    """seperated into function to simplify writing of unit test"""
    balance_task, balance_task_node = None, None
    if len(most_used_nodes.intersection(best_memory_nodes)) >= 1:
        log.debug("\tOK: found task for best memory node")
        balance_task = task
        balance_task_node = list(most_used_nodes.intersection(best_memory_nodes))[0]
    elif len(most_used_nodes.intersection(most_free_memory_nodes)) >= 1:
        log.debug("\tOK: found task for most free memory node")
        balance_task = task
        balance_task_node = list(most_used_nodes.intersection(most_free_memory_nodes))[0]
    elif len(best_memory_nodes.intersection(most_free_memory_nodes)) >= 1:
        log.debug("\tOK: task not local, but both best available has only one alternative")
        balance_task = task
        balance_task_node = list(best_memory_nodes.intersection(most_free_memory_nodes))[0]
    else:
        log.debug("\tIGNORE: no good decisions can be made now for this task, continue")
    return balance_task, balance_task_node


def _build_tasks_memory(tasks_data: TasksData, platform: Platform) -> TasksMemory:
    total_memory = _get_platform_total_memory(platform)

    tasks_memory = []
    for task, data in tasks_data.items():
        tasks_memory.append(
            (task,
             _get_task_memory_limit(data.measurements, total_memory, task, data.resources),
             _get_numa_node_preferences(data.measurements, platform.numa_nodes)))
    return sorted(tasks_memory, reverse=True, key=lambda x: x[1])


def _build_balanced_memory(tasks_memory: TasksMemory, tasks_data: TasksData, platform: Platform) -> BalancedMemory:
    balanced_memory: BalancedMemory = {x: [] for x in range(platform.numa_nodes)}

    log.log(TRACE, "Printing tasks memory_limit, preferences, current_node_assignment")
    for task, memory, preferences in tasks_memory:
        current_node = _get_current_node(tasks_data[task].allocations, platform)
        log.log(TRACE, "\ttask %s; memory_limit=%d[bytes] preferences=%s current_node_assignemnt=%d",
                task, memory, preferences, current_node)

        if current_node >= 0:
            balanced_memory[current_node].append((task, memory))
    return balanced_memory


def _get_pages_to_move(task: TaskId, tasks_data: TaskData, target_node: NumaNodeId, reason: str) -> int:
    data: TaskData = tasks_data[task]
    pages_to_move = sum(
        v for node, v
        in data.measurements[MetricName.TASK_MEM_NUMA_PAGES].items()
        if node != target_node)
    log.debug('Task: %s Moving %s MB to node %s reason %s', task,
              (pages_to_bytes(pages_to_move)) / MB, target_node, reason)
    return pages_to_move


def _get_platform_total_memory(platform: Platform) -> int:
    return sum(platform.measurements[MetricName.PLATFORM_MEM_NUMA_FREE_BYTES].values()) + \
           sum(platform.measurements[MetricName.PLATFORM_MEM_NUMA_USED_BYTES].values())


def _get_task_memory_limit(task_measurements: Measurements, total_memory: int, task: TaskId,
                           task_resources: Dict[TaskResource, Union[int, float]]) -> MemoryLimit:
    """Returns detected maximum memory for the task."""
    if TaskResource.MEM in task_resources:
        mem = task_resources[TaskResource.MEM]
        log.log(TRACE, 'Taken memory limit for task %s from: task_resources[task][\'mem\']=%d[bytes]', task, mem)
        return mem

    limits_order = [
        MetricName.TASK_MEM_LIMIT_BYTES,
        MetricName.TASK_MEM_SOFT_LIMIT_BYTES,
        MetricName.TASK_MEM_MAX_USAGE_BYTES,
        MetricName.TASK_MEM_USAGE_BYTES, ]
    for limit in limits_order:
        if limit not in task_measurements:
            continue
        if task_measurements[limit] > total_memory:
            continue
        log.log(TRACE, 'Taken memory limit for task %s from cgroups limit metric %s %d[bytes]', task, limit,
                task_measurements[limit])
        return task_measurements[limit]
    return 0


def _get_numa_node_preferences(task_measurements: Measurements, numa_nodes: int) -> Preferences:
    ret = {node_id: 0 for node_id in range(0, numa_nodes)}
    if MetricName.TASK_MEM_NUMA_PAGES in task_measurements:
        metrics_val_sum = sum(task_measurements[MetricName.TASK_MEM_NUMA_PAGES].values())
        for node_id, metric_val in task_measurements[MetricName.TASK_MEM_NUMA_PAGES].items():
            ret[int(node_id)] = round(metric_val / max(1, metrics_val_sum), 4)
    else:
        log.warning('{} metric not available, crucial for numa_allocator!'.format(MetricName.TASK_MEM_NUMA_PAGES))
    return ret


def _get_most_used_node(preferences: Preferences) -> int:
    return sorted(preferences.items(), reverse=True, key=lambda x: x[1])[0][0]


def _get_most_used_nodes(preferences: Preferences) -> Set[int]:
    d = {}
    for node in preferences:
        d[node] = round(math.log1p(preferences[node] * 1000))
    nodes = sorted(d.items(), reverse=True, key=lambda x: x[1])
    z = nodes[0][1]
    best_nodes = {x[0] for x in nodes if x[1] == z}
    return best_nodes


def _get_least_used_node(platform: Platform) -> int:
    return sorted(platform.measurements[MetricName.PLATFORM_MEM_NUMA_FREE_BYTES].items(),
                  reverse=True,
                  key=lambda x: x[1])[0][0]


def _get_current_node(allocations: Optional[TaskAllocations], platform: Platform) -> NumaNodeId:
    cpus_assigned = decode_listformat(allocations[AllocationType.CPUSET_CPUS])
    for node, cpus in platform.node_cpus.items():
        if cpus == cpus_assigned:
            return node
    return -1


def _get_best_memory_node(memory_limit: MemoryLimit, balanced_memory: BalancedMemory) -> NumaNodeId:
    """memory -- memory limit"""
    log.log(TRACE, "Started _get_best_memory_node")
    log.log(TRACE, "memory=%s", memory_limit)
    log.log(TRACE, "balanced_memory=%s", balanced_memory)
    nodes_scores = {}
    for node in balanced_memory:
        nodes_scores[node] = round(memory_limit / (sum([k[1] for k in balanced_memory[node]]) + memory_limit), 4)
    return sorted(nodes_scores.items(), reverse=True, key=lambda x: x[1])[0][0]


def _get_best_memory_nodes(memory_limit: MemoryLimit, balanced_memory: BalancedMemory) -> Set[NumaNodeId]:
    d = {}
    for node in balanced_memory:
        d[node] = round(math.log10((sum([k[1] for k in balanced_memory[node]]) + memory_limit)), 1)
    best = sorted(d.items(), key=lambda x: x[1])
    z = best[0][1]
    best_nodes = {x[0] for x in best if x[1] == z}
    return best_nodes


def _get_most_free_memory_node(memory_limit: MemoryLimit, node_memory_free: Dict[int, int]) -> NumaNodeId:
    d = {}
    for node in node_memory_free:
        d[node] = round(memory_limit / node_memory_free[node], 4)
    return sorted(d.items(), key=lambda x: x[1])[0][0]


def _get_most_free_memory_nodes(memory_limit: MemoryLimit, node_memory_free: Dict[int, int]) -> Set[NumaNodeId]:
    d = {}
    for node in node_memory_free:
        if memory_limit >= node_memory_free[node]:
            # if we can't fit into free memory, don't consider that node at all
            continue
        d[node] = round(math.log10(node_memory_free[node] - memory_limit), 1)
    print(d)
    free_nodes = sorted(d.items(), reverse=True, key=lambda x: x[1])
    best_free_nodes = set()
    if len(free_nodes) > 0:
        z = free_nodes[0][1]
        best_free_nodes = {x[0] for x in free_nodes if x[1] == z}
    return best_free_nodes


def _is_enough_memory_on_target(memory_limit: MemoryLimit, target_node: NumaNodeId,
                                platform: Platform,
                                tasks_measurements: Measurements):
    """assuming that task_max_memory is a real limit"""
    task_numa_stat = tasks_measurements[MetricName.TASK_MEM_NUMA_PAGES]
    max_memory_to_move = memory_limit - \
                         pages_to_bytes(task_numa_stat[str(target_node)])
    platform_free_memory = platform.measurements[MetricName.PLATFORM_MEM_NUMA_FREE_BYTES][target_node]
    log.log(TRACE, "platform_free_memory=%d[GB] on node %d max_memory_to_move=%d[GB]",
            platform_free_memory / GB, target_node, max_memory_to_move / GB)
    return max_memory_to_move < platform_free_memory


def pages_to_bytes(pages):
    return get_page_size() * pages


def get_page_size() -> int:
    return 4096


def _is_task_pinned(current_node: int) -> bool:
    if current_node >= 0:
        log.debug("CPUSET_CPUS already pinned to the node %d", current_node)
        return True
    return False


def _is_ghost_task(memory):
    if memory == 0:
        # Handle missing data for "ghost" tasks
        # e.g. cgroup without processes when using StaticNode
        log.warning('skip allocation - not enough data -maybe there are no processes there!')
        return True
    return False


def _log_task_basic_info(extra_metrics, tasks_data, task_memory, current_node):
    task, memory, preferences = task_memory
    task_numastat = tasks_data[task].measurements[MetricName.TASK_MEM_NUMA_PAGES]
    log.log(TRACE, "Running for task %r; memory_limit=%d[bytes] preferences=%s memory_usage_per_numa_node=%s[bytes]",
            task, memory, preferences, {k: pages_to_bytes(v) for k, v in task_numastat.items()})
    extra_metrics.extend([Metric('numa__task_current_node', value=current_node, labels=tasks_data[task].labels)])


def _log_initial_state(tasks_data, balanced_memory, extra_metrics):
    log.log(TRACE, "Current state of the system, balanced_memory=%s[bytes]" % balanced_memory)
    log.log(TRACE, "Current task assigments to nodes, expressed in sum of memory limits of pinned tasks: %s[bytes]" % {
        node: sum(t[1] for t in tasks) / 2 ** 10 for node, tasks in balanced_memory.items()})
    log.debug("Current task assigments: %s" % {
        node: len(tasks) for node, tasks in balanced_memory.items()})
    log.debug("Current task assigments: %s" % {
        node: [task[0] for task in tasks] for node, tasks in balanced_memory.items()})

    for node, tasks_with_memory in balanced_memory.items():
        extra_metrics.extend([
            Metric('numa__balanced_memory_tasks', value=len(tasks_with_memory),
                   labels=dict(numa_node=str(node))),
            Metric('numa__balanced_memory_size', value=sum([m for t, m in tasks_with_memory]),
                   labels=dict(numa_node=str(node))),
            Metric('numa__task_tasks_count', value=len(tasks_data)),
        ])
