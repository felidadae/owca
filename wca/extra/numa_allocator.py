import logging
import math

from typing import List, Dict
from dataclasses import dataclass

from wca.allocators import Allocator, TasksAllocations, AllocationType
from wca.detectors import TasksMeasurements, TasksResources, TasksLabels, Anomaly
from wca.metrics import Metric, MetricName
from wca.logger import TRACE
from wca.platforms import Platform, encode_listformat, decode_listformat

log = logging.getLogger(__name__)


@dataclass
class NUMAAllocator(Allocator):

    # minimal value of task_balance so the task is not skipped during rebalancing analysis
    # by default turn off, none of tasks are skipped due to this reason
    loop_min_task_balance: float = 0.0

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

    def allocate(
            self,
            platform: Platform,
            tasks_measurements: TasksMeasurements,
            tasks_resources: TasksResources,
            tasks_labels: TasksLabels,
            tasks_allocations: TasksAllocations,
    ) -> (TasksAllocations, List[Anomaly], List[Metric]):
        log.debug('NUMAAllocator v7: dryrun=%s cgroups_memory_binding/migrate=%s/%s'
                  ' migrate_pages=%s double_match/candidate=%s/%s tasks=%s', self.dryrun,
                  self.cgroups_memory_binding, self.cgroups_memory_migrate,
                  self.migrate_pages, self.double_match, self.candidate, len(tasks_labels))
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
                 _get_task_memory_limit(tasks_measurements[task], total_memory,
                                        task, tasks_resources[task]),
                 _get_numa_node_preferences(tasks_measurements[task], platform)))
        tasks_memory = sorted(tasks_memory, reverse=True, key=lambda x: x[1])

        # Current state of the system
        balanced_memory = {x: [] for x in range(platform.numa_nodes)}
        if self.migrate_pages:
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
                if current_node >= 0 and preferences[current_node] < self.migrate_pages_min_task_balance:
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
            log.log(TRACE, "Task %r: Memory: %d Preferences: %s" % (task, memory, preferences))
            current_node = _get_current_node(
                decode_listformat(tasks_allocations[task][AllocationType.CPUSET_CPUS]),
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
                log.debug("Task CPUSET_CPUS %r already pinned to the node %d",
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
                        log.debug("   OK: found task for best memory node")
                        balance_task = task
                        balance_task_node = list(most_used_nodes.intersection(best_memory_nodes))[0]
                    elif len(most_used_nodes.intersection(most_free_memory_nodes)) == 1:
                        log.debug("   OK: found task for most free memory node")
                        balance_task = task
                        balance_task_node = list(most_used_nodes.intersection(most_free_memory_nodes))[0]
                    elif most_used_node in best_memory_nodes or most_used_node in most_free_memory_nodes:
                        log.debug("   OK: minimized migrations case")
                        balance_task = task
                        balance_task_node = most_used_node
                        # break # commented to give a chance to generate other metrics
                    elif len(best_memory_nodes.intersection(most_free_memory_nodes)) == 1:
                        log.debug("   OK: task not local, but both best available has only one alternative")
                        balance_task = task
                        balance_task_node = list(best_memory_nodes.intersection(most_free_memory_nodes))[0]
                    else:
                        log.debug("   IGNORE: no good decisions can be made now for this task, continue")
                # --- candidate functionality ---
                if self.candidate and balance_task_candidate is None:
                    log.log(TRACE, '   CANDIT: not perfect match'
                                   ', but remember as candidate, continue')
                    balance_task_candidate = task
                    balance_task_node_candidate = best_memory_node
                # --- end of candidate functionality ---

                # Validate if we have enough memory to migrate to desired node:
                if balance_task is not None:
                    if memory >= platform.measurements[MetricName.MEM_NUMA_FREE].get(balance_task_node, 0):
                        log.debug(" We can't migrate task '%s' to node '%d', because not enough memory on the target. Looking for another candidate" %
                                  (balance_task, balance_task_node))
                        balance_task, balance_task_node = None, None

        # ----------------- end of the loop -------------------------------------------------------

        # 3. Perform CPU pinning with optional memory binding and forced migration on >>balance_task<<

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
            self._match_moves += 1

            if self.cgroups_memory_binding:
                allocations[balance_task][AllocationType.CPUSET_MEMS] = encode_listformat({balance_task_node})

                if self.cgroups_memory_migrate:
                    log.debug("Assign task %s to node %s with memory migrate" %
                              (balance_task, balance_task_node))
                    allocations[balance_task][AllocationType.CPUSET_MEM_MIGRATE] = 1

            if self.migrate_pages:
                allocations[balance_task][AllocationType.MIGRATE_PAGES] = balance_task_node

        # 4. Memory migration of tasks already pinned.

        if self.migrate_pages:
            # If nessesary migrate pages to least used node, for task that are still not there.
            least_used_node = _get_least_used_node(platform)
            log.log(TRACE, 'Least used node: %s', least_used_node)
            log.log(TRACE, 'Tasks to balance: %s', tasks_to_balance)

            for task in tasks_to_balance:  # already pinned tasks
                if tasks_current_nodes[task] == least_used_node:
                    current_node = tasks_current_nodes[task]
                    memory_to_move = sum(
                        v for n, v
                        in tasks_measurements[task][MetricName.MEM_NUMA_STAT_PER_TASK].items()
                        if n != current_node)
                    log.debug('Task: %s Moving %s MB to node %s', task,
                              (memory_to_move * 4096) / 1024**2, current_node)
                    allocations[task][AllocationType.MIGRATE_PAGES] = current_node
            else:
                log.log(TRACE, 'no more tasks to move memory!')

        return allocations, [], extra_metrics


def _platform_total_memory(platform):
    return sum(platform.measurements[MetricName.MEM_NUMA_FREE].values()) + \
           sum(platform.measurements[MetricName.MEM_NUMA_USED].values())


def _get_task_memory_limit(task_measurements, total, task, task_resources):
    """Returns detected maximum memory for the task."""
    if 'mem' in task_resources:
        mems = task_resources['mem']
        log.log(TRACE, 'Task: %s from resources %s %s %s', task, 'is',
                mems, 'bytes')
        return mems

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
        log.log(TRACE, 'Task: %s from cgroups limit %s %s %s %s', task, limit, 'is',
                task_measurements[limit], 'bytes')
        return task_measurements[limit]
    return 0


def _get_numa_node_preferences(task_measurements, platform: Platform) -> Dict[int, float]:
    ret = {node_id: 0 for node_id in range(0, platform.numa_nodes)}
    if MetricName.MEM_NUMA_STAT_PER_TASK in task_measurements:
        metrics_val_sum = sum(task_measurements[MetricName.MEM_NUMA_STAT_PER_TASK].values())
        for node_id, metric_val in task_measurements[MetricName.MEM_NUMA_STAT_PER_TASK].items():
            ret[int(node_id)] = round(metric_val / max(1, metrics_val_sum), 4)
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
        d[node] = round(memory / (sum([k[1] for k in balanced_memory[node]]) + memory), 4)
    best = sorted(d.items(), reverse=True, key=lambda x: x[1])
    # print('best:')
    # pprint(best)
    return best[0][0]


def _get_most_free_memory_node(memory, node_memory_free):
    d = {}
    for node in node_memory_free:
        d[node] = round(memory / node_memory_free[node], 4)
    # pprint(d)
    free_nodes = sorted(d.items(), key=lambda x: x[1])
    # print('free:')
    # pprint(free_nodes)
    return free_nodes[0][0]


def _get_best_memory_node_v2(memory, balanced_memory):
    d = {}
    for node in balanced_memory:
        d[node] = round(math.log1p((memory / (sum([k[1] for k in balanced_memory[node]]) + memory))*100), 0)
    best = sorted(d.items(), reverse=True, key=lambda x: x[1])
    z = best[0][1]
    best_nodes = [x[0] for x in best if x[1] == z]
    return best_nodes


def _get_most_free_memory_node_v2(memory, node_memory_free):
    d = {}
    for node in node_memory_free:
        d[node] = round(math.log1p((memory / node_memory_free[node]) * 100), 0)
    free_nodes = sorted(d.items(), key=lambda x: x[1])
    z = free_nodes[0][1]
    best_free_nodes = [x[0] for x in free_nodes if x[1] == z]
    return best_free_nodes


def _get_best_memory_node_v3(memory, balanced_memory):
    d = {}
    for node in balanced_memory:
        d[node] = round(math.log10((sum([k[1] for k in balanced_memory[node]]) + memory)), 1)
    best = sorted(d.items(), key=lambda x: x[1])
    z = best[0][1]
    best_nodes = {x[0] for x in best if x[1] == z}
    return best_nodes


def _get_most_free_memory_node_v3(memory, node_memory_free):
    d = {}
    for node in node_memory_free:
        if memory >= node_memory_free[node]:
            # if we can't fit into free memory, don't consider that node at all
            continue
        d[node] = round(math.log10(node_memory_free[node] - memory), 1)
    free_nodes = sorted(d.items(), reverse=True, key=lambda x: x[1])
    best_free_nodes = set()
    if len(free_nodes) > 0:
        z = free_nodes[0][1]
        best_free_nodes = {x[0] for x in free_nodes if x[1] == z}
    return best_free_nodes


def _get_most_used_node_v2(preferences):
    d = {}
    for node in preferences:
        d[node] = round(math.log1p(preferences[node]*1000))
    nodes = sorted(d.items(), reverse=True, key=lambda x: x[1])
    z = nodes[0][1]
    best_nodes = {x[0] for x in nodes if x[1] == z}
    return best_nodes
