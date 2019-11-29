from dataclasses import dataclass
import logging
import math
import re
from typing import List, Dict, Set

from wca.allocators import Allocator, TasksAllocations, AllocationType
from wca.detectors import Anomaly, TaskData, TasksData
from wca.metrics import Metric, MetricName
from wca.logger import TRACE
from wca.platforms import Platform, encode_listformat, decode_listformat

log = logging.getLogger(__name__)
GB = 1024 ** 3
MB = 1024 ** 2
PAGE_SIZE=4096
TASK_NAME_REGEX = r'.*specjbb2-(...-\d+)-'

NumaNodeId = int
Preferences = Dict[NumaNodeId, float]


def parse_task_name(task_name):
    """Useful for debugging to shorten name of tasks."""
    s = re.search(TASK_NAME_REGEX, task_name)
    if s:
        return s.group(1)
    # could not match regex
    return task_name


def pages_to_bytes(pages):
    return PAGE_SIZE * pages


@dataclass
class NUMAAllocator(Allocator):

    # minimal value of task_balance so the task is not skipped during rebalancing analysis
    # by default turn off, none of tasks are skipped due to this reason
    loop_min_task_balance: float = 0.0

    # If True, then do not migrate if not enough space on target numa node.
    free_space_check: bool = False

    # syscall "migrate pages" per process memory migration
    migrate_pages: bool = True
    migrate_pages_min_task_balance: float = 0.95

    # cgroups based memory migration and pinning
    cgroups_memory_binding: bool = False
    # can be used only when cgroups_memory_binding is set to True
    cgroups_memory_migrate: bool = False

    # if use standard algorithm
    double_match: bool = True

    # if the >>balance_task<< search loop was finished without success,
    # returns the first available task
    candidate: bool = False

    # dry-run (for comparinson only)
    dryrun: bool = False

    def __post_init__(self):
        self._candidates_moves = 0
        self._match_moves = 0
        self._pages_to_move = {}

    def allocate(
            self,
            platform: Platform,
            tasks_data: TasksData
    ) -> (TasksAllocations, List[Anomaly], List[Metric]):
        log.debug('')
        log.debug('NUMAAllocator v7: dryrun=%s cgroups_memory_binding/migrate=%s/%s'
                  ' migrate_pages=%s double_match/candidate=%s/%s tasks=%s', self.dryrun,
                  self.cgroups_memory_binding, self.cgroups_memory_migrate,
                  self.migrate_pages, self.double_match, self.candidate, len(tasks_data))
        log.log(TRACE, 'Moves match=%s candidates=%s', self._match_moves, self._candidates_moves)
        log.log(TRACE, 'Tasks data %r', tasks_data)
        allocations = {}

        # 1. First, get current state of the system

        # Total host memory
        total_memory = _platform_total_memory(platform)

        extra_metrics = []
        extra_metrics.extend([
            Metric('numa__task_candidate_moves', value=self._candidates_moves),
            Metric('numa__task_match_moves', value=self._match_moves),
            Metric('numa__task_tasks_count', value=len(tasks_data)),
        ])

        # Collect tasks sizes and NUMA node usages
        tasks_memory = []
        for task, data in tasks_data.items():
            tasks_memory.append(
                (task,
                 _get_task_memory_limit(data.measurements, total_memory,
                                        task, data.resources),
                 _get_numa_node_preferences(data.measurements, platform.numa_nodes)))
        tasks_memory = sorted(tasks_memory, reverse=True, key=lambda x: x[1])

        # Current state of the system
        balanced_memory = {x: [] for x in range(platform.numa_nodes)}
        if self.migrate_pages:
            tasks_to_balance = []
            tasks_current_nodes = {}

        log.log(TRACE, "Printing tasks memory_limit, preferences, current_node_assignment")
        for task, memory, preferences in tasks_memory:
            current_node = _get_current_node(
                decode_listformat(tasks_data[task].allocations[AllocationType.CPUSET_CPUS]),
                platform.node_cpus)
            log.log(TRACE, "\ttask %s; memory_limit=%d[bytes] preferences=%s current_node_assignemnt=%d",
                task, memory, preferences, current_node)

            if current_node >= 0:
                balanced_memory[current_node].append((task, memory))

            if self.migrate_pages:
                tasks_current_nodes[task] = current_node
                if current_node >= 0 and preferences[current_node] < self.migrate_pages_min_task_balance:
                    tasks_to_balance.append(task)

        log.log(TRACE, "Current state of the system, balanced_memory=%s[bytes]" % balanced_memory)
        log.log(TRACE, "Current task assigments to nodes, expressed in sum of memory limits of pinned tasks: %s[bytes]" % {
            node: sum(t[1] for t in tasks)/2**10 for node, tasks in balanced_memory.items()})
        log.debug("Current task assigments: %s" % {
            node: len(tasks) for node, tasks in balanced_memory.items()})
        log.debug("Current task assigments: %s" % {
            node: [parse_task_name(task[0]) for task in tasks] for node, tasks in balanced_memory.items()})

        for node, tasks_with_memory in balanced_memory.items():
            extra_metrics.extend([
                Metric('numa__balanced_memory_tasks', value=len(tasks_with_memory),
                       labels=dict(numa_node=str(node))),
                Metric('numa__balanced_memory_size', value=sum([m for t, m in tasks_with_memory]),
                       labels=dict(numa_node=str(node)))
            ])

        if self.dryrun:
            return allocations, [], extra_metrics

        # 2. Re-balancing analysis

        log.log(TRACE, 'Starting re-balancing analysis')

        balance_task = None
        balance_task_node = None
        balance_task_candidate = None
        balance_task_node_candidate = None

        # ----------------- begin the loop to find >>balance_task<< -------------------------------
        for task, memory, preferences in tasks_memory:
            # var memory is not a real memory usage, but value calculated in function _get_task_memory_limit

            data: TaskData = tasks_data[task]

            log.log(TRACE, "Running for task %r; memory_limit=%d[bytes] preferences=%s memory_usage_per_numa_node=%s[bytes]",
                    task, memory, preferences, {k:pages_to_bytes(v) for k,v in tasks_data[task].measurements[MetricName.MEM_NUMA_STAT_PER_TASK].items()})
            current_node = _get_current_node(
                decode_listformat(tasks_data[task].allocations[AllocationType.CPUSET_CPUS]),
                platform.node_cpus)
            numa_free_measurements = platform.measurements[MetricName.MEM_NUMA_FREE]

            most_used_node = _get_most_used_node(preferences)
            most_used_nodes = _get_most_used_node_v2(preferences)
            best_memory_node = _get_best_memory_node(memory, balanced_memory)
            best_memory_nodes = _get_best_memory_node_v3(memory, balanced_memory)
            most_free_memory_node = _get_most_free_memory_node(memory, numa_free_measurements)
            most_free_memory_nodes = _get_most_free_memory_node_v3(memory, numa_free_measurements)

            extra_metrics.extend([
                Metric('numa__task_current_node', value=current_node,
                       labels=data.labels),
                Metric('numa__task_most_used_node', value=most_used_node,
                       labels=data.labels),
                Metric('numa__task_best_memory_node', value=best_memory_node,
                       labels=data.labels),
                Metric('numa__task_best_memory_node_preference', value=preferences[most_used_node],
                       labels=data.labels),
                Metric('numa__task_most_free_memory_mode', value=most_free_memory_node,
                       labels=data.labels)
            ])

            self._pages_to_move.setdefault(task, 0)
            if current_node >= 0:
                log.debug("Task %r CPUSET_CPUS already pinned to the node %d",
                          task, current_node)
                continue

            if memory == 0:
                # Handle missing data for "ghost" tasks
                # e.g. cgroup without processes when using StaticNode
                log.warning(
                    'skip allocation for %r task - not enough data - '
                    'maybe there are no processes there!',
                    task)
                continue

            log.log(TRACE, "Analysing task %r: Most used node: %d,"
                           " Best free node: %d, Best memory node: %d" %
                           (task, most_used_node, most_free_memory_node, best_memory_node))

            # If not yet task found for balancing.
            if balance_task is None:
                if preferences[most_used_node] < self.loop_min_task_balance:
                    log.log(TRACE, "   THRESHOLD: skipping due to loop_min_task_balance")
                    continue

                if self.double_match:
                    if len(most_used_nodes.intersection(best_memory_nodes)) == 1:
                        log.debug("\tOK: found task for best memory node")
                        balance_task = task
                        balance_task_node = list(most_used_nodes.intersection(best_memory_nodes))[0]
                    elif len(most_used_nodes.intersection(most_free_memory_nodes)) == 1:
                        log.debug("\tOK: found task for most free memory node")
                        balance_task = task
                        balance_task_node = list(most_used_nodes.intersection(most_free_memory_nodes))[0]
                    elif most_used_node in best_memory_nodes or most_used_node in most_free_memory_nodes:
                        log.debug("\tOK: minimized migrations case")
                        balance_task = task
                        balance_task_node = most_used_node
                        # break # commented to give a chance to generate other metrics
                    elif len(best_memory_nodes.intersection(most_free_memory_nodes)) == 1:
                        log.debug("\tOK: task not local, but both best available has only one alternative")
                        balance_task = task
                        balance_task_node = list(best_memory_nodes.intersection(most_free_memory_nodes))[0]
                    else:
                        log.debug("\tIGNORE: no good decisions can be made now for this task, continue")
                # --- candidate functionality ---
                if self.candidate and balance_task_candidate is None:
                    if self.free_space_check and not _is_enough_memory_on_target(task, best_memory_node, platform,
                                                                                 data.measurements, memory):
                        log.log(TRACE, '\tCANDIT - IGNORE CHOOSEN: not enough free space on target node %s.', balance_task_node_candidate)
                    else:
                        log.log(TRACE, '\tCANDIT OK: not perfect match, but remember as candidate, continue')
                        balance_task_candidate = task
                        balance_task_node_candidate = best_memory_node
                # --- end of candidate functionality ---

                # Validate if we have enough memory to migrate to desired node.
                if balance_task is not None:
                    if self.free_space_check and not _is_enough_memory_on_target(task, balance_task_node,
                                                                                   platform, data.measurements,
                                                                                   memory):
                        log.debug("\tIGNORE CHOOSEN: not enough free space on target node %s", balance_task_node)
                        balance_task, balance_task_node = None, None
        # ----------------- end of the loop -------------------------------------------------------

        # Do not send metrics of not existing tasks.
        old_tasks = [task for task in self._pages_to_move if task not in tasks_data]
        for old_task in old_tasks:
            if old_task in self._pages_to_move:
                del self._pages_to_move[old_task]

        # 3. Perform CPU pinning with optional memory binding and forced migration on >>balance_task<<

        if balance_task is not None:
            self._match_moves += 1

        # --- candidate functionality ---
        if balance_task is None and balance_task_candidate is not None:
            log.debug('Task %r: Using candidate rule', balance_task_candidate)
            balance_task = balance_task_candidate
            balance_task_node = balance_task_node_candidate

            balance_task_candidate, balance_task_node_candidate = None, None
            self._candidates_moves += 1
        # --- end of candidate functionality ---

        if balance_task is not None:
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
                self._pages_to_move[balance_task] += get_pages_to_move(
                    balance_task, tasks_data, balance_task_node, 'initial assignment')
                allocations.setdefault(balance_task, {})
                allocations[balance_task][AllocationType.MIGRATE_PAGES] = balance_task_node

        # 4. Memory migration of tasks already pinned. In that step we do not check if there is enough space
        #   on target node (self.free_space_check).

        if self.migrate_pages:
            log.log(TRACE, 'Migrating pages of tasks to balance memory between nodes')

            # If nessesary migrate pages to least used node, for task that are still not there.
            least_used_node = _get_least_used_node(platform)
            log.log(TRACE, 'Least used node: %s', least_used_node)
            log.log(TRACE, 'Tasks to balance: %s', tasks_to_balance)

            for task in tasks_to_balance:  # already pinned tasks
                if tasks_current_nodes[task] == least_used_node:
                    current_node = tasks_current_nodes[task]
                    self._pages_to_move[task] += get_pages_to_move(
                        task, tasks_data,
                        current_node, 'numa nodes balance disturbed')

                    allocations.setdefault(task, {})
                    allocations[task][AllocationType.MIGRATE_PAGES] = str(current_node)
            log.log(TRACE, 'Finished migrating pages of tasks')

        # 5. Add metrics for pages migrated

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

        log.log(TRACE, 'Allocations: %r', allocations)
        return allocations, [], extra_metrics


def get_pages_to_move(task, tasks_data, target_node, reason):
    data: TaskData = tasks_data[task]
    pages_to_move = sum(
        v for node, v
        in data.measurements[MetricName.MEM_NUMA_STAT_PER_TASK].items()
        if node != target_node)
    log.debug('Task: %s Moving %s MB to node %s reason %s', task,
              (pages_to_bytes(pages_to_move)) / MB, target_node, reason)
    return pages_to_move


def _platform_total_memory(platform):
    return sum(platform.measurements[MetricName.MEM_NUMA_FREE].values()) + \
           sum(platform.measurements[MetricName.MEM_NUMA_USED].values())


def _get_task_memory_limit(task_measurements, total_memory, task, task_resources):
    """Returns detected maximum memory for the task."""
    if 'mem' in task_resources:
        mems = task_resources['mem']
        log.log(TRACE, 'Taken memory limit for task %s from: task_resources[task][\'mem\']=%d[bytes]', task, mems)
        return mems

    limits_order = [
        MetricName.MEM_LIMIT_PER_TASK,
        MetricName.MEM_SOFT_LIMIT_PER_TASK,
        MetricName.MEM_MAX_USAGE_PER_TASK,
        MetricName.MEM_USAGE_PER_TASK, ]
    for limit in limits_order:
        if limit not in task_measurements:
            continue
        if task_measurements[limit] > total_memory:
            continue
        log.log(TRACE, 'Taken memory limit for task %s from cgroups limit metric %s %d[bytes]', task, limit,
                task_measurements[limit])
        return task_measurements[limit]
    return 0


def _get_numa_node_preferences(task_measurements, numa_nodes: int) -> Dict[int, float]:
    ret = {node_id: 0 for node_id in range(0, numa_nodes)}
    if MetricName.MEM_NUMA_STAT_PER_TASK in task_measurements:
        metrics_val_sum = sum(task_measurements[MetricName.MEM_NUMA_STAT_PER_TASK].values())
        for node_id, metric_val in task_measurements[MetricName.MEM_NUMA_STAT_PER_TASK].items():
            ret[int(node_id)] = round(metric_val / max(1, metrics_val_sum), 4)
    else:
        log.warning('{} metric not available, crucial for numa_allocator!'.format(MetricName.MEM_NUMA_STAT_PER_TASK))
    return ret


def _get_most_used_node(preferences: Preferences):
    return sorted(preferences.items(), reverse=True, key=lambda x: x[1])[0][0]


def _get_most_used_node_v2(preferences):
    d = {}
    for node in preferences:
        d[node] = round(math.log1p(preferences[node]*1000))
    nodes = sorted(d.items(), reverse=True, key=lambda x: x[1])
    z = nodes[0][1]
    best_nodes = {x[0] for x in nodes if x[1] == z}
    return best_nodes


def _get_least_used_node(platform):
    return sorted(platform.measurements[MetricName.MEM_NUMA_FREE].items(),
                  reverse=True,
                  key=lambda x: x[1])[0][0]


def _get_current_node(cpus_assigned: Set[int], node_cpus: Dict[int, Set[int]]):
    for node in node_cpus:
        if node_cpus[node] == cpus_assigned:
            return node
    return -1


def _get_best_memory_node(memory, balanced_memory):
    """memory -- memory limit"""
    log.debug("Started _get_best_memory_node")
    log.debug("memory=%s", memory)
    log.debug("balanced_memory=%s", balanced_memory)
    nodes_scores = {}
    for node in balanced_memory:
        nodes_scores[node] = round(memory / (sum([k[1] for k in balanced_memory[node]]) + memory), 4)
    return sorted(nodes_scores.items(), reverse=True, key=lambda x: x[1])[0][0]


def _get_best_memory_node_v3(memory, balanced_memory):
    d = {}
    for node in balanced_memory:
        d[node] = round(math.log10((sum([k[1] for k in balanced_memory[node]]) + memory)), 1)
    best = sorted(d.items(), key=lambda x: x[1])
    z = best[0][1]
    best_nodes = {x[0] for x in best if x[1] == z}
    return best_nodes


def _get_most_free_memory_node(memory, node_memory_free):
    d = {}
    for node in node_memory_free:
        d[node] = round(memory / node_memory_free[node], 4)
    return sorted(d.items(), key=lambda x: x[1])[0][0]


def _get_most_free_memory_node_v3(memory, node_memory_free):
    d = {}
    for node in node_memory_free:
        if memory >= node_memory_free[node]:
            # if we can't fit into free memory, don't consider that node at all
            continue
        d[node] = round(math.log10(node_memory_free[node] - memory), 1)
    print(d)
    free_nodes = sorted(d.items(), reverse=True, key=lambda x: x[1])
    best_free_nodes = set()
    if len(free_nodes) > 0:
        z = free_nodes[0][1]
        best_free_nodes = {x[0] for x in free_nodes if x[1] == z}
    return best_free_nodes


def _is_enough_memory_on_target(task, target_node, platform, tasks_measurements, task_max_memory):
    """assuming that task_max_memory is a real limit"""
    max_memory_to_move = task_max_memory - pages_to_bytes(tasks_measurements[MetricName.MEM_NUMA_STAT_PER_TASK][str(target_node)])
    platform_free_memory = platform.measurements[MetricName.MEM_NUMA_FREE][target_node]
    log.log(TRACE, "platform_free_memory=%d[GB]", platform_free_memory/GB)
    log.log(TRACE, "max_memory_to_move=%d[GB]", max_memory_to_move/GB)
    return max_memory_to_move < platform_free_memory
