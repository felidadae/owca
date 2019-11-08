import logging
from typing import List, Dict
# from pprint import pprint

from dataclasses import dataclass

from wca.allocators import Allocator, TasksAllocations, AllocationType
from wca.detectors import TasksMeasurements, TasksResources, TasksLabels, Anomaly
from wca.metrics import Metric, MetricName
from wca.logger import TRACE
from wca.platforms import Platform, encode_listformat, decode_listformat

log = logging.getLogger(__name__)


@dataclass
class NUMAAllocator(Allocator):

    # preferences_threshold: float = 0.66
    preferences_threshold: float = 0.0  # always migrate

    # syscall "migrate pages" per process memory migration
    migrate_pages: bool = True
    migrate_pages_min_task_balance: float = 0.95

    # Cgroups based memory migration and pinning
    cgroups_memory_binding: bool = False
    cgroups_memory_migrate: bool = False  # can be used only when cgroups_memory_binding is set to True

    # use candidate
    candidate = True

    def __post_init__(self):
        self._candidates_moves = 0
        self._match_moves = 0

    def allocate(
            self,
            platform: Platform,
            tasks_measurements: TasksMeasurements,
            tasks_resources: TasksResources,
            tasks_labels: TasksLabels,
            tasks_allocations: TasksAllocations,
    ) -> (TasksAllocations, List[Anomaly], List[Metric]):
        log.debug('NUMA allocator Pv6 policy here for %s tasks...', len(tasks_measurements))
        log.log(TRACE, 'Moves match=%s candidates=%s', self._match_moves, self._candidates_moves)
        log.log(TRACE, 'Tasks resources %r', tasks_resources)
        allocations = {}

        # 1. First, get current state of the system

        # Total host memory
        total_memory = _platform_total_memory(platform)

        extra_metrics = []
        extra_metrics.extend([
            Metric('numa__task_candidate_moves', value=self._candidates_moves),
            Metric('numa__task_match_moves', value=self._match_moves),
            Metric('numa__task_tasks_count', value=len(tasks_measurements)),
        ])

        # Collect tasks sizes and NUMA node usages
        tasks_memory = []
        for task in tasks_labels:
            tasks_memory.append(
                (task,
                 _get_task_memory_limit(tasks_measurements[task], total_memory, task),
                 _get_numa_node_preferences(tasks_measurements[task], platform)))
        tasks_memory = sorted(tasks_memory, reverse=True, key=lambda x: x[1])

        # Current state of the system
        balanced_memory = {x: [] for x in range(platform.numa_nodes)}
        if migrate_pages:
            tasks_to_balance = []
            tasks_current_nodes = {}
        for task, memory, preferences in tasks_memory:
            current_node = _get_current_node(
                decode_listformat(tasks_allocations[task][AllocationType.CPUSET_CPUS]),
                platform.node_cpus)
            log.log(TRACE, "Task: %s Memory: %d Preferences: %s, Current node: %d" % (
                task, memory, preferences, current_node))
            tasks_current_nodes[task] = current_node

            if self.migrate_pages:
                if current_node >= 0 and 
                    preferences[current_node] < self.migrate_pages_min_task_balance):
                tasks_to_balance.append(task)

        log.log(TRACE, "Current state of the system: %s" % balanced_memory)
        log.log(TRACE, "Current state of the system per node: %s" % {
            node: sum(t[1] for t in tasks)/2**10 for node, tasks in balanced_memory.items()})
        log.debug("Current task assigments: %s" % {
            node: len(tasks) for node, tasks in balanced_memory.items()})

        for node, tasks_with_memory in balanced_memory.items():
            extra_metrics.extend([
                Metric('numa__balanced_memory_tasks', value=len(tasks_with_memory),
                       labels=dict(numa_node=str(node))),
                Metric('numa__balanced_memory_size', value=sum([m for t, m in tasks_with_memory]),
                       labels=dict(numa_node=str(node)))
            ])

        # 2. Re-balancing analysis

        log.log(TRACE, 'Starting re-balancing analysis')

        balance_task = None
        balance_task_node = None
        balance_task_candidate = None
        balance_task_node_candidate = None

        for task, memory, preferences in tasks_memory:
            log.log(TRACE, "Task %r: Memory: %d Preferences: %s" % (task, memory, preferences))
            current_node = _get_current_node(
                decode_listformat(tasks_allocations[task][AllocationType.CPUSET_CPUS]),
                platform.node_cpus)
            most_used_node = _get_most_used_node(preferences)
            best_memory_node = _get_best_memory_node(memory, balanced_memory)
            most_free_memory_node = \
                _get_most_free_memory_node(memory,
                                           platform.measurements[MetricName.MEM_NUMA_FREE])
            extra_metrics.extend([
                Metric('numa__task_current_node', value=current_node,
                       labels=tasks_labels[task]),
                Metric('numa__task_most_used_node', value=most_used_node,
                       labels=tasks_labels[task]),
                Metric('numa__task_best_memory_node', value=best_memory_node,
                       labels=tasks_labels[task]),
                Metric('numa__task_best_memory_node_preference', value=preferences[most_used_node],
                       labels=tasks_labels[task]),
                Metric('numa__task_most_free_memory_mode', value=most_free_memory_node,
                       labels=tasks_labels[task])
            ])

            if current_node >= 0:
                log.debug("Task %r: already placed on the node %d, taking next",
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

            # if not yet task found for balancing
            if balance_task is None:

                # Give a chance for AutoNUMA to re-balance memory
                if preferences[most_used_node] < self.preferences_threshold:
                    log.log(TRACE, "   THRESHOLD: not most of the memory balanced, continue")
                    continue

                if most_used_node == best_memory_node or most_used_node == most_free_memory_node:
                    log.log(TRACE, "   OK: found task for balancing: %s", task)
                    balance_task = task
                    balance_task_node = most_used_node
                    # break # commented to give a chance to generate other metrics

                elif self.candidate and balance_task_candidate is None:
                    log.log(TRACE, '   CANDIT: not perfect match'
                                   ', but remember as candidate, continue')
                    balance_task_candidate = task
                    balance_task_node_candidate = best_memory_node
                else:
                    log.log(TRACE, "   IGNORE: not perfect match"
                                   "and candidate set(disabled), continue")

        # 3. Perform CPU pinning with optional memory bindind and forced migration.
        if balance_task is None and balance_task_candidate is not None:
            log.debug('Task %r: Using candidate rule', balance_task_candidate)
            balance_task = balance_task_candidate
            balance_task_node = balance_task_node_candidate

            balance_task_candidate, balance_task_node_candidate = None, None
            self._candidates_moves += 1

        if balance_task is not None:
            log.debug("Task %r: assiging to node %s." % (balance_task, balance_task_node))
            allocations[balance_task] = {
                AllocationType.CPUSET_CPUS: encode_listformat(
                    platform.node_cpus[balance_task_node]),
            }
            self._match_moves += 1

            if self.cgroups_memory_binding:
                allocations[balance_task][AllocationType.CPUSET_MEMS] = encode_listformat({balance_task_node})

                if self.cgroups_memory_migrate:
                    log.debug("Assign task %s to node %s with memory migrate" %
                              (balance_task, balance_task_node))
                    allocations[balance_task][AllocationType.CPUSET_MEM_MIGRATE] = 1

            if self.migrate_pages:
                allocations[balance_task][AllocationType.MIGRATE_PAGES] = balance_task_node

        # 4. Memory migration
        # If nessesary migrate pages to least used node, for task that are still not there.
        least_used_node = _get_least_used_node(platform)
        log.log(TRACE, 'Least used node: %s', least_used_node)
        log.log(TRACE, 'Tasks to balance: %s', tasks_to_balance)

        if self.migrate_pages:
            for task in tasks_to_balance:
                if tasks_current_nodes[task] == least_used_node:
                    current_node = tasks_current_nodes[task]
                    memory_to_move = sum(
                        v for n, v
                        in tasks_measurements[task][MetricName.MEM_NUMA_STAT_PER_TASK].items()
                        if n != current_node)
                    log.debug('Task: %s Moving %s MB to node %s task balance = %r', task,
                              (memory_to_move * 4096) / 1024**2, current_node, task_balance)
                    allocations[task][AllocationType.MIGRATE_PAGES] = current_node
            else:
                log.log(TRACE, 'no more tasks to move memory!')

        return allocations, [], extra_metrics


def _platform_total_memory(platform):
    return sum(platform.measurements[MetricName.MEM_NUMA_FREE].values()) + \
           sum(platform.measurements[MetricName.MEM_NUMA_USED].values())


def _get_task_memory_limit(task_measurements, total, task):
    """Returns detected maximum memory for the task."""
    limits_order = [
        MetricName.MEM_LIMIT_PER_TASK,
        MetricName.MEM_SOFT_LIMIT_PER_TASK,
        MetricName.MEM_MAX_USAGE_PER_TASK,
        MetricName.MEM_USAGE_PER_TASK, ]
    for limit in limits_order:
        if limit not in task_measurements:
            continue
        if task_measurements[limit] > total:
            continue
        log.log(TRACE, 'Task: %s limit %s %s %s %s', task, limit, 'is',
                task_measurements[limit], 'bytes')
        return task_measurements[limit]
    return 0


def _get_numa_node_preferences(task_measurements, platform: Platform) -> Dict[int, float]:
    ret = {node_id: 0 for node_id in range(0, platform.numa_nodes)}
    if MetricName.MEM_NUMA_STAT_PER_TASK in task_measurements:
        metrics_val_sum = sum(task_measurements[MetricName.MEM_NUMA_STAT_PER_TASK].values())
        for node_id, metric_val in task_measurements[MetricName.MEM_NUMA_STAT_PER_TASK].items():
            ret[int(node_id)] = metric_val / max(1, metrics_val_sum)
    else:
        log.warning('{} metric not available'.format(MetricName.MEM_NUMA_STAT_PER_TASK))
    return ret


def _get_most_used_node(preferences):
    return sorted(preferences.items(), reverse=True, key=lambda x: x[1])[0][0]


def _get_least_used_node(platform):
    return sorted(platform.measurements[MetricName.MEM_NUMA_FREE].items(),
                  reverse=True,
                  key=lambda x: x[1])[0][0]


def _get_current_node(cpus, nodes):
    for node in nodes:
        if nodes[node] == cpus:
            return node
    return -1


def _get_best_memory_node(memory, balanced_memory):
    """for equal task memory, choose node with less allocated memory by WCA"""
    d = {}
    for node in balanced_memory:
        d[node] = memory / (sum([k[1] for k in balanced_memory[node]]) + memory)
    best = sorted(d.items(), reverse=True, key=lambda x: x[1])
    # print('best:')
    # pprint(best)
    return best[0][0]


def _get_most_free_memory_node(memory, node_memory_free):
    d = {}
    for node in node_memory_free:
        d[node] = memory / node_memory_free[node]
    # pprint(d)
    free_nodes = sorted(d.items(), key=lambda x: x[1])
    # print('free:')
    # pprint(free_nodes)
    return free_nodes[0][0]
