#!/usr/bin/env python3.6

import shutil
import os
from typing import List, Dict, Tuple, Optional, Union
from datetime import datetime
import pprint
import enum
from enum import Enum
import fileinput
from shutil import copyfile
import subprocess
import random
import re
import logging
import json
import requests

FORMAT = "%(asctime)-15s:%(levelname)s %(module)s %(message)s"
logging.basicConfig(format=FORMAT, level=logging.DEBUG)

DRY_RUN = False
if DRY_RUN:
    logging.info("[DRY_RUN] Running in DRY_RUN mode!")


class ClusterInfoLoader:
    instance = None

    def __init__(self, nodes_file='nodes.json', workloads_file='workloads.json'):
        with open(nodes_file) as fref:
            self.nodes = json.load(fref)

        with open(workloads_file) as fref:
            self.workloads = json.load(fref)

    @staticmethod
    def build_singleton():
        ClusterInfoLoader.instance = ClusterInfoLoader()

    @staticmethod
    def get_instance() -> 'ClusterInfoLoader':
        return ClusterInfoLoader.instance

    def get_workloads(self) -> List[Dict]:
        return self.workloads

    def get_workloads_names(self) -> List[str]:
        return list(self.workloads.keys())

    def get_nodes(self) -> List[Dict]:
        return self.nodes

    def get_nodes_names(self) -> List[str]:
        return list(self.nodes.keys())

    def get_aep_nodes(self) -> List[str]:
        return [node for node, capacity in self.nodes.items() if
                capacity['membw_read'] > capacity['membw_write']]


def random_with_total_utilization_specified(cpu_limit: Tuple[float, float],
                                            mem_limit: Tuple[float, float],
                                            nodes_capacities: Dict[str, Dict],
                                            workloads_set: Dict[str, Dict]
                                            ) -> Tuple[int, Dict[str, int], Dict[str, float]]:
    """Random number of app, but workloads expected usage of CPU and MEMORY sums to
       specified percentage (+- accuracy).
       Returns tuple, first item how many iterations were performed to random proper workloads set,
       second set of workloads.
       Pairs cpu_target_l/cpu_target_r and mem_target_l/mem_target_r are ranges,
       where l means beginning and r end of the range.
    """
    cpu_all, mem_all = 0, 0
    AEP_NODES = ClusterInfoLoader.get_instance().get_aep_nodes()
    for node_name, node in nodes_capacities.items():
        # Only count DRAM nodes
        if node_name in AEP_NODES:
            continue
        cpu_all += node['cpu']
        mem_all += node['mem']

    cpu_target_l, cpu_target_r = cpu_all * cpu_limit[0], cpu_all * cpu_limit[1]
    mem_target_l, mem_target_r = mem_all * mem_limit[0], mem_all * mem_limit[1]

    logging.debug("[randomizing workloads] cpu(all={}, l={}, r={}), mem(all={}, "
                  "l={}, r={}), N_nodes={})".format(cpu_all, cpu_target_l, cpu_target_r,
                                                    mem_all, mem_target_l, mem_target_r,
                                                    len(nodes_capacities) - 1))

    workloads_names = [workload_name for workload_name in workloads_set]
    workloads_list = [workloads_set[workload_name] for workload_name in workloads_names]
    choices_weights = [w['mem'] / w['cpu'] * w['scale_weights'] for w in workloads_list]
    choices_weights = [round(val + 5, 2) for val in choices_weights]
    logging.debug("[randomizing workloads] weights={}".format(list(zip(workloads_names,
                                                                       choices_weights))))
    best_for_now = (100, 1)
    found_solution = None
    iteration = 0
    while found_solution is None:
        cpu_curr = 0
        mem_curr = 0

        chosen_workloads = {}
        while cpu_curr < cpu_target_l or mem_curr < mem_target_l:
            chosen = random.choices(workloads_names, choices_weights)[0]
            if chosen in chosen_workloads:
                chosen_workloads[chosen] += 1
            else:
                chosen_workloads[chosen] = 1
            cpu_curr += ClusterInfoLoader.get_instance().get_workloads()[chosen]['cpu']
            mem_curr += ClusterInfoLoader.get_instance().get_workloads()[chosen]['mem']

        if cpu_curr <= cpu_target_r and mem_curr <= mem_target_r:
            found_solution = chosen_workloads
        else:
            if (mem_curr / mem_all) / (cpu_curr / cpu_all) > best_for_now[1] / best_for_now[0]:
                best_for_now = (round(cpu_curr / cpu_all, 4), round(mem_curr / mem_all, 4))
            iteration += 1
        if iteration > 0 and iteration % 1000 == 0:
            logging.debug("[randomizing workloads] Trying to find set of workloads already for {} "
                          "iterations. cpu_limits={} mem_limits={}".format(iteration, cpu_limit,
                                                                           mem_limit))
            logging.debug("[randomizing workloads] Best for now: (cpu={}, mem={})".format(
                best_for_now[0], best_for_now[1]))

    logging.debug("[randomizing workloads] chosen solution feature: cpu={} mem={}".format(
        round(cpu_curr / cpu_all, 2), round(mem_curr / mem_all, 2)))
    logging.debug("[randomizing workloads] chosen workloads:\n{}".format(pprint.pformat(
        chosen_workloads, indent=4)))
    utilization = {'cpu': cpu_curr / cpu_all, 'mem': mem_curr / mem_all}
    return iteration, chosen_workloads, utilization


class NodesClass(enum.Enum):
    _1LM = '1'
    _2LM = '2'


class OnOffState(enum.Enum):
    On = True
    Off = False


def default_shell_run(command, verbose=True):
    """Default way of running commands."""
    if verbose:
        logging.debug('command run in shell >>{}<<'.format(command))
    if not DRY_RUN:
        r = subprocess.run(command, shell=True, check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return r.stdout.decode('utf-8'), r.stderr.decode('utf-8')
    else:
        return None, None


def taint_nodes_class(nodes_class: NodesClass, new_state: OnOffState = OnOffState.On):
    """Taint or untaint 1lm or 2lm nodes."""
    if new_state == OnOffState.On:
        tweak_value = ''
    else:
        tweak_value = '-'
    command = "kubectl taint node -l memory={}lm run=taint:NoSchedule{} --overwrite || true".format(
        str(nodes_class.value), tweak_value)
    default_shell_run(command)


def scale_down_all_workloads(wait_time: int):
    """Kill all workloads"""
    command = "kubectl scale sts --all --replicas=0 && sleep {wait_time}".format(
        wait_time=wait_time)
    default_shell_run(command)


def switch_extender(new_state: OnOffState):
    """Turn off/on wca_scheduler extender"""
    first = True
    while True:
        if not first:
            logging.debug('Trying again to switch extender state')
        first = False

        if new_state == OnOffState.On:
            params = {"replicas": 1, "sleep_time": 5}
        elif new_state == OnOffState.Off:
            params = {"replicas": 0, "sleep_time": 1}
        command = "kubectl -n wca-scheduler scale deployment wca-scheduler --replicas={replicas} " \
                  "&& sleep {sleep_time}".format(**params)
        default_shell_run(command)

        stdout, stderr = default_shell_run('kubectl get pods -n wca-scheduler')
        if DRY_RUN:
            return
        if new_state == OnOffState.On:
            if '2/2' in stdout and 'Running' in stdout:
                break
        elif new_state == OnOffState.Off:
            if 'Running' not in stdout:
                break


def get_shuffled_workloads_order(workloads_counts: Dict[str, int]) -> List[str]:
    """To run in random order workloads given in >>workloads_counts<<"""
    workloads_run_order = [[w] * count for w, count in workloads_counts.items()]
    workloads_run_order = [leaf for sublist in workloads_run_order for leaf in sublist]
    random.shuffle(workloads_run_order)
    return workloads_run_order


def run_workloads(workloads_run_order: List[str], workloads_counts: Dict[str, int]):
    command = "kubectl scale sts {workload_name} --replicas={replicas} && sleep 5"
    workloads_run_order_ = workloads_run_order.copy()  # we edit the list

    irun = 0
    workloads_counts_run = {workload: 0 for workload in workloads_counts}
    while workloads_counts_run:
        workload_name = workloads_run_order_.pop()
        workloads_counts_run[workload_name] += 1
        default_shell_run(command.format(workload_name=workload_name,
                                         replicas=workloads_counts_run[workload_name]))
        if workloads_counts_run[workload_name] == workloads_counts[workload_name]:
            del workloads_counts_run[workload_name]
        irun += 1


def run_workloads_equally_per_node(workloads_counts: Dict[str, int],
                                   nodes: Optional[List[str]] = None):
    """Make sure all nodes will end up with the same workloads being run - assumes that
       extender_scheduler is turned off. Needs to wait after tainting (5s)."""
    cmd_scale = "kubectl scale sts {workload} --replicas={replicas}"
    cmd_taint = "kubectl taint nodes {node} wca_runner=any:NoSchedule --overwrite"  # add taint
    cmd_untaint = "kubectl taint nodes {node} wca_runner=any:NoSchedule- --overwrite"  # remove

    all_nodes = ClusterInfoLoader.get_instance().get_nodes_names()
    # should be equal to all nodes available on cluster

    if nodes is None:
        nodes = all_nodes

    workloads_count_all_walker = {workload: 0 for workload in workloads_counts}
    workloads_run_order = [workload for workload, count in workloads_counts.items()
                           for i in range(count)]

    for nodename in all_nodes:
        try:
            default_shell_run(cmd_untaint.format(node=nodename), verbose=True)
        except Exception:
            continue
    sleep(5)

    for nodename in nodes:
        logging.info("Running workloads on node={}".format(nodename))
        for nodename_ in all_nodes:
            if nodename_ != nodename:
                default_shell_run(cmd_taint.format(node=nodename_), verbose=True)

        sleep(5)
        for workload in workloads_run_order:
            workloads_count_all_walker[workload] += 1
            default_shell_run(cmd_scale.format(workload=workload,
                                               replicas=workloads_count_all_walker[workload]))
        sleep(10)

        for nodename_ in all_nodes:
            if nodename_ != nodename:
                default_shell_run(cmd_untaint.format(node=nodename_), verbose=True)
        sleep(5)

    workloads_count_all_target = {workload: len(nodes) * count for workload, count in
                                  workloads_counts.items()}
    assert workloads_count_all_walker == workloads_count_all_target


def sleep(sleep_duration):
    default_shell_run('sleep {}'.format(sleep_duration))


MINUTE = 60  # in seconds


class PodNotFoundException(Exception):
    pass


def copy_scheduler_logs(log_file):
    stdout, _ = default_shell_run('kubectl get pods -n wca-scheduler')
    if not DRY_RUN:
        for word in stdout.split():
            if 'wca-scheduler-' in word:
                pod_name = word
                break
        else:
            raise PodNotFoundException('wca-scheduler pod not found')
    command = 'kubectl logs -n wca-scheduler {pod_name} wca-scheduler > {log_file}'
    default_shell_run(command.format(pod_name=pod_name, log_file=log_file))


class WaitPeriod:
    SCALE_DOWN = 'scale_down'
    STABILIZE = 'stabilize'


def single_3stage_experiment(experiment_id: str, workloads: Dict[str, int],
                             wait_periods: Dict[WaitPeriod, Union[int, Tuple[int, int, int]]],
                             stages: Tuple[bool, bool, bool] = (True, True, True),
                             experiment_root_dir: str = 'results/tmp'):
    """
    Run three stages experiment:
    1) kubernetes only, 2lm nodes not used
    2) kubernetes only, 2lm nodes used
    2) scheduler_extender, 2lm nodes used
    """
    logging.info('Running experiment >>single_3stage_experiment<<')
    events = []

    if type(wait_periods[WaitPeriod.STABILIZE]) == int:
        wait_periods[WaitPeriod.STABILIZE] = [wait_periods[WaitPeriod.STABILIZE]] * 3

    # kill all workloads
    scale_down_all_workloads(wait_time=wait_periods[WaitPeriod.SCALE_DOWN])

    # Before start randomize order of running workloads, but keep the order among the stages
    workloads_run_order: List[str] = get_shuffled_workloads_order(workloads)
    logging.debug("Workload run order: {}".format(list(reversed(workloads_run_order))))
    annotate("Start experiment {}".format(experiment_id))
    annotate("Start experiment {}".format(experiment_id), dashboard_id=70)

    if stages[0]:
        # kubernetes only, 2lm off
        logging.info('Running first stage')
        switch_extender(OnOffState.Off)
        taint_nodes_class(NodesClass._2LM)
        run_workloads(workloads_run_order, workloads)
        events.append((datetime.now(), 'first stage: after run workloads'))
        sleep(wait_periods[WaitPeriod.STABILIZE][0])
        events.append((datetime.now(), 'first stage: before killing workloads'))
        scale_down_all_workloads(wait_time=wait_periods[WaitPeriod.SCALE_DOWN])

    if stages[1]:
        # # kubernetes only, 2lm on
        logging.info('Running second stage')
        taint_nodes_class(NodesClass._2LM, OnOffState.Off)
        run_workloads(workloads_run_order, workloads)
        events.append((datetime.now(), 'second stage: after run workloads'))
        sleep(wait_periods[WaitPeriod.STABILIZE][1])
        events.append((datetime.now(), 'second stage: before killing workloads'))
        scale_down_all_workloads(wait_time=wait_periods[WaitPeriod.SCALE_DOWN])

    if stages[2]:
        # wca-scheduler, 2lm on
        logging.info('Running third stage')
        taint_nodes_class(NodesClass._2LM, OnOffState.Off)
        switch_extender(OnOffState.On)
        run_workloads(workloads_run_order, workloads)
        events.append((datetime.now(), 'third stage: after run workloads'))
        sleep(wait_periods[WaitPeriod.STABILIZE][2])
        events.append((datetime.now(), 'third stage: before killing workloads'))
        scale_down_all_workloads(wait_time=wait_periods[WaitPeriod.SCALE_DOWN])
        logs_file = 'wca_scheduler_logs.{}'.format(experiment_id)
        copy_scheduler_logs(os.path.join(experiment_root_dir, logs_file))

    with open(os.path.join(experiment_root_dir, 'events.txt'), 'a') as fref:
        fref.write(str(workloads))
        fref.write('\n')
        fref.write(str(events))
        fref.write('\n')

    annotate("End experiment {}".format(experiment_id))
    annotate("End experiment {}".format(experiment_id), dashboard_id=70)
    # Just to show on graph end of experiment
    sleep(100)


class RunMode(Enum):
    """Run maximum number of pods which will fit all nodes"""
    EQUAL_ON_ALL_NODES = 'equal_on_all_nodes'

    """Run up to given"""
    RUN_ON_NODES_WHERE_ENOUGH_RESOURCES = 'run_on_nodes_where_enough_resources'


def get_max_count_per_smallest_node(workload: str, nodes: List[str]) -> int:
    """nodes -- nodes from which choose the smallest"""
    w_cpu = ClusterInfoLoader.get_instance().get_workloads()[workload]['cpu']
    w_mem = ClusterInfoLoader.get_instance().get_workloads()[workload]['mem']
    min_mem = min(
        c['mem'] for n, c in ClusterInfoLoader.get_instance().get_nodes().items() if n in nodes)
    min_cpu = min(
        c['cpu'] for n, c in ClusterInfoLoader.get_instance().get_nodes().items() if n in nodes)
    max_count = min(int(0.9 * min_cpu / w_cpu), int(0.95 * min_mem / w_mem))
    return max_count


def single_step1workload_experiment(run_mode: RunMode, workload: str,
                                    count_per_node_list: Optional[List[int]],
                                    wait_periods: Dict[WaitPeriod, int],
                                    nodes: Optional[List[str]] = None,
                                    experiment_root_dir: str = 'results/tmp'):
    """nodes - on which nodes run experiments"""
    logging.info(
        'Running experiment >>single_step1workload_experiment<< for workload {}'.format(workload))

    events = []

    if nodes is None:
        nodes = ClusterInfoLoader.get_instance().get_nodes_names()

    workload_cpu = ClusterInfoLoader.get_instance().get_workloads()[workload]['cpu']
    workload_mem = ClusterInfoLoader.get_instance().get_workloads()[workload]['mem']

    if run_mode == RunMode.EQUAL_ON_ALL_NODES:
        max_count = get_max_count_per_smallest_node(workload, nodes)

        if count_per_node_list is None:
            count_per_node_list = list(range(1, max_count + 1, int(max_count / 5 + 1)))
            logging.debug(
                "[EQUAL_ON_ALL_NODES] will run experiment for {}(cpu={}, mem={}) "
                "with counts {} (possible_max={})".format(
                    workload, workload_cpu, workload_mem, count_per_node_list, max_count))

    # kubernetes only, 2lm on
    switch_extender(OnOffState.Off)
    taint_nodes_class(NodesClass._2LM, OnOffState.Off)
    scale_down_all_workloads(wait_time=10)

    for i, count_per_node in enumerate(count_per_node_list):
        logging.info('Stepping into count={}'.format(count_per_node))

        if run_mode == RunMode.EQUAL_ON_ALL_NODES:
            if count_per_node > max_count:
                logging.info(
                    '[EQUAL_ON_ALL_NODES] Skipping count={}, '
                    'not enough space on nodes max_count={}'.format(
                        count_per_node, max_count))
                continue
        elif run_mode == RunMode.RUN_ON_NODES_WHERE_ENOUGH_RESOURCES:
            nodes = [node for node, capacity in ClusterInfoLoader.get_instance().get_nodes().items()
                     if node in nodes
                     and count_per_node * workload_cpu < capacity['cpu']
                     and count_per_node * workload_mem < capacity['mem']]
            # Log.
            if not nodes:
                logging.info(
                    '[RUN_ON_NODES_WHERE_ENOUGH_RESOURCES] '
                    'Skipping run - cannot be run on any node.')
                break
            else:
                logging.info(
                    '[RUN_ON_NODES_WHERE_ENOUGH_RESOURCES] '
                    'Running on nodes {}. Totally {} pods'.format(
                        nodes, len(nodes) * count_per_node))
        else:
            raise Exception("Unsupported run_mode={}".format(run_mode))

        run_workloads_equally_per_node({workload: count_per_node}, nodes=nodes)
        events.append((datetime.now(), '{} stage: after running workloads'.format(i)))
        sleep(wait_periods[WaitPeriod.STABILIZE])
        events.append((datetime.now(), '{} stage: before killing workloads'.format(i)))
        scale_down_all_workloads(wait_time=wait_periods[WaitPeriod.SCALE_DOWN])

    with open(os.path.join(experiment_root_dir, 'events.txt'), 'a') as fref:
        fref.write(str({workload: count_per_node_list}))
        fref.write('\n')
        fref.write(str(events))
        fref.write('\n')

    # Just to show on graph the end of experiment
    sleep(100)


def tune_stage(workloads: List[str], sleep_time: int = 25 * MINUTE):
    """
    This stage runs one instance from each workload.
    This helps in calculating the score for each workload and determining the timestamp.
    The timestamp is displayed at the end.
    """
    assert type(workloads) == list
    workloads_run_order: List[str] = workloads

    logging.debug("Running >>tuning<<")
    scale_down_all_workloads(wait_time=20)
    switch_extender(OnOffState.Off)
    taint_nodes_class(NodesClass._2LM)
    run_workloads(workloads_run_order, {workload: 1 for workload in workloads})
    sleep(sleep_time)
    now = datetime.now()  # Read data just before killing workloads
    sleep(60)  # Additional 60 seconds of sleep, after reading >>now<<
    scale_down_all_workloads(wait_time=20)

    # Save and print result.
    logging.debug("Date: {} Timestamp: {}".format(now, int(now.timestamp())))
    if not os.path.isdir("tuning"):
        os.makedirs("tuning")
    with open('tuning/{}.txt'.format(now.strftime("%Y-%m-%d--%H-%M")), 'w') as fref:
        fref.write("Date: {}\n".format(now))
        fref.write("Timestamp: {}\n".format(now.timestamp()))


def modify_configmap(regexes: List[(str)], experiment_index: int, experiment_root_dir: str):
    path = '../wca-scheduler/'
    config_name = 'config.yaml'

    # Replace text in config
    for regex in regexes:
        with fileinput.FileInput(path + config_name, inplace=True) as file:
            for line in file:
                # regexes[0] - regex_to_search, regexes[1] - replacement_text
                print(re.sub(regex[0], regex[1], line), end='')

    # Make copy config
    copyfile(path + config_name,
             experiment_root_dir + '/' + 'wca_scheduler_config_'
             + str(experiment_index) + '_' + config_name)

    # Apply changes
    command = "kubectl apply -k {path_to_kustomize_folder_wca_scheduler} " \
              "&& sleep {sleep_time}".format(
                path_to_kustomize_folder_wca_scheduler=path,
                sleep_time='10s')
    default_shell_run(command)
    switch_extender(OnOffState.Off)


def create_experiment_root_dir(path: str, overwrite: bool):
    if overwrite and os.path.isdir(path):
        shutil.rmtree(path)

    if not os.path.isdir(path):
        os.makedirs(path)
    else:
        raise Exception('experiment root directory already exists! {}'.format(path))


def annotate(text, tags=[], dashboard_id=90):
    GRAFANA_URL = "http://100.64.176.12:3000"
    BEARER_TOKEN = \
        "Bearer eyJrIjoiQXBwRnVwczdXMHVQWFJOQm42ejFVaXVLdDdHOTcxWW0iLCJuIjoicnVubmVyIiwiaWQiOjF9"
    URL_PATH = GRAFANA_URL + '/api/annotations'  # '/api/search?folderIds=78&query=&starred=false'

    url = URL_PATH
    headers = {'Content-type': 'application/json',
               'Accept': 'text/plain',
               'Authorization': BEARER_TOKEN}

    # Scheduler demo v2 original - 90, panelId - 42
    # Workload 2LM profiling - 70
    data = {
        "dashboardId": dashboard_id,
        "tags": tags,
        "text": text
    }

    try:
        r = requests.post(url, data=json.dumps(data), headers=headers)
        r.raise_for_status()
    except requests.exceptions.ConnectionError as e:
        raise Exception("ConnectionError") from e
    except requests.exceptions.HTTPError as e:
        raise Exception(r.content) from e

    j = r.json()
    if j['message'] == 'Annotation added':
        logging.debug("Annotated successful")
    else:
        logging.debug("Annotated unsuccessful")


# -----------------------------------------------------------------------------------------------------
def experimentset_main(
        iterations: int = 10,
        configmap_regex_parameters={},
        experiment_root_dir: str = 'results/tmp',
        overwrite: bool = False):
    """3 stage experiment: our classic way of benchmarking the wca_scheduler."""
    logging.debug("Running experimentset >>main<< with experiment_directory >>{}<<".format(
        experiment_root_dir))
    random.seed(datetime.now())
    create_experiment_root_dir(experiment_root_dir, overwrite)

    for i in range(iterations):

        if i in configmap_regex_parameters:
            modify_configmap(configmap_regex_parameters.get(i), i, experiment_root_dir)

        iterations, workloads, utilization = random_with_total_utilization_specified(
            cpu_limit=(0.22, 0.46), mem_limit=(0.75, 0.9),  # total cluster cpu/mem usage
            nodes_capacities=ClusterInfoLoader.get_instance().get_nodes(),
            workloads_set=ClusterInfoLoader.get_instance().get_workloads())
        with open(
                os.path.join(experiment_root_dir, 'choosen_workloads_utilization.{}.txt'.format(i)),
                'a') as fref:
            fref.write(str(utilization))
            fref.write('\n')

        experiment_id = str(i)
        single_3stage_experiment(experiment_id=experiment_id,
                                 workloads=workloads,
                                 wait_periods={WaitPeriod.SCALE_DOWN: MINUTE,
                                               WaitPeriod.STABILIZE: MINUTE * 15},
                                 stages=[True, True, True],
                                 experiment_root_dir=experiment_root_dir)


def experimentset_single_workload_at_once(
        experiment_root_dir: str = 'results/tmp',
        overwrite: bool = False):
    logging.debug("Running experimentset >>every workload is single<<"
                  " with experiment_directory >>{}<<".format(experiment_root_dir))
    random.seed(datetime.now())
    create_experiment_root_dir(experiment_root_dir, overwrite)

    # Experiment params, could be passed
    workloads = [
        # 'stress-stream-medium',
        'memcached-mutilate-big',
        # 'redis-memtier-medium',
        'redis-memtier-big',
        # 'redis-memtier-big-wss',
    ]
    count_per_node_list = {
        # 6,6,6 = 18 --> 9h
        # 'stress-stream-medium': [4],
        'memcached-mutilate-big': [3],
        # 'redis-memtier-medium': [1, 3, 8, 10, 14, 18],  # 1 20% 40% 60% 80% 100%
        'redis-memtier-big': [2],
        # 'redis-memtier-big-wss': [1, 2],
    }

    for i, workload in enumerate(workloads):
        single_step1workload_experiment(
            run_mode=RunMode.RUN_ON_NODES_WHERE_ENOUGH_RESOURCES,
            experiment_id=str(i),
            workload=workload,
            count_per_node_list=count_per_node_list[workload],
            wait_periods={WaitPeriod.SCALE_DOWN: MINUTE,
                          WaitPeriod.STABILIZE: MINUTE * 20},
            nodes=None,
            experiment_root_dir=experiment_root_dir)


def experimentset_test(experiment_root_dir='results/__test__'):
    logging.debug("Running experimentset >>test<<")
    random.seed(datetime.now())

    if not os.path.isdir(experiment_root_dir):
        os.makedirs(experiment_root_dir)

    _, workloads, _ = random_with_total_utilization_specified(
        cpu_limit=(0.25, 0.41), mem_limit=(0.65, 0.9),
        nodes_capacities=ClusterInfoLoader.get_instance().get_nodes(),
        workloads_set=ClusterInfoLoader.get_instance().get_workloads())
    single_3stage_experiment(experiment_id=0,
                             workloads=workloads,
                             wait_periods={WaitPeriod.SCALE_DOWN: 10,
                                           WaitPeriod.STABILIZE: MINUTE},
                             stages=[False, False, True],
                             experiment_root_dir=experiment_root_dir)


# -----------------------------------------------------------------------------------------------------


if __name__ == "__main__":
    ClusterInfoLoader.build_singleton()

    # key - in which iteration, will be use list regex
    # value - list of tuples (regex, new value)
    # example:
    # regexs_map = {
    #     0: [(r'score_target: -\d.\d', 'score_target: -2.3'), ],
    #     10: [(r'score_target: -\d.\d', 'score_target: -6.5'),
    #          (r'cpu_scale_factor: \d.\d', 'cpu_scale_factor: 0.7'), ],
    # }

    regexs_map = {
        # 0: [(r'score_target: -\d.\d', 'score_target: -1.0'), ],
        # 10: [(r'score_target: -\d.\d', 'score_target: -2.5'), ],
    }

    # experimentset_test()
    # tune_stage(ClusterInfoLoader.get_instance().get_workloads_names())
    # experimentset_single_workload_at_once(experiment_root_dir='results/2020-05-13__stepping_single_workloads')
    experimentset_main(iterations=10, configmap_regex_parameters=regexs_map,
                       experiment_root_dir='results/final-demo-2lm')
