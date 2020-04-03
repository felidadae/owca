import shutil
import os
from typing import List, Dict, Tuple, Optional
from datetime import datetime
import pprint
import enum
import subprocess
import random
import logging

FORMAT = "%(asctime)-15s:%(levelname)s %(module)s %(message)s"
logging.basicConfig(format=FORMAT, level=logging.DEBUG)


# 2020-03-18
AEP_NODES = ('node101',)


# Added on 2020-03-18 from logs from wca-scheduler
# Date: 2020-03-18 21:13:11.879063 Timestamp: 1584565991
NODES_CAPACITIES = \
{
    # ---
    # Note: master node
    # 'node36': {cpu: 72.0, 'mem': 404, 'wss': 404},
    'node37': {'cpu': 80.0, 'mem': 201, 'membw_read': 256, 'membw_write': 256, 'wss': 201},
    'node38': {'cpu': 80.0, 'mem': 404, 'membw_read': 256, 'membw_write': 256, 'wss': 404},
    'node39': {'cpu': 80.0, 'mem': 404, 'membw_read': 256, 'membw_write': 256, 'wss': 404},
    'node40': {'cpu': 80.0, 'mem': 201, 'membw_read': 256, 'membw_write': 256, 'wss': 201},
    # ---
    # Note: AEP
    'node101': {'cpu': 72.0, 'mem': 1596, 'membw_read': 57, 'membw_write': 16, 'wss': 58},
    # Note: >>turned off<< node due to performance instability
    # 'node102': {'cpu': 72.0, 'mem': 404, 'membw_read': 256, 'membw_write': 256, 'wss': 404},
    'node103': {'cpu': 72.0, 'mem': 201, 'membw_read': 256, 'membw_write': 256, 'wss': 201},
    'node104': {'cpu': 72.0, 'mem': 201, 'membw_read': 256, 'membw_write': 256, 'wss': 201},
    'node105': {'cpu': 72.0, 'mem': 201, 'membw_read': 256, 'membw_write': 256, 'wss': 201},
    # ---
    'node200': {'cpu': 96.0, 'mem': 201, 'membw_read': 256, 'membw_write': 256, 'wss': 201},
    # Note: >>turned off<< node due to performance instability (high temperature)
    # 'node201': {'cpu': 96.0, 'mem': 201, 'membw_read': 256, 'membw_write': 256, 'wss': 201},
    'node202': {'cpu': 96.0, 'mem': 201, 'membw_read': 256, 'membw_write': 256, 'wss': 201},
    'node203': {'cpu': 96.0, 'mem': 201, 'membw_read': 256, 'membw_write': 256, 'wss': 201},
    # ---
}

WORKLOADS_SET = \
{
    'stress-stream-small': {'mem': 7, 'cpu': 2, 'membw_write': 2, 'membw_read': 1, 'wss': 7},
    'stress-stream-medium': {'mem': 13, 'cpu': 2, 'membw_write': 2, 'membw_read': 1, 'wss': 13},
    'stress-stream-big': {'mem': 13, 'cpu': 4, 'membw_write': 6, 'membw_read': 2, 'wss': 13},
    # ---
    'sysbench-memory-small': {'mem': 2, 'cpu': 2, 'membw_write': 4, 'membw_read': 1, 'wss': 2},
    'sysbench-memory-medium': {'mem': 4, 'cpu': 3, 'membw_write': 9, 'membw_read': 1, 'wss': 3},
    'sysbench-memory-big': {'mem': 10, 'cpu': 4, 'membw_write': 17, 'membw_read': 1, 'wss': 9},
    # ---
    'redis-memtier-small': {'mem': 10, 'cpu': 3, 'membw_write': 2, 'membw_read': 2, 'wss': 1},
    'redis-memtier-medium': {'mem': 11, 'cpu': 3, 'membw_write': 1, 'membw_read': 2, 'wss': 1},
    'redis-memtier-big': {'mem': 70, 'cpu': 3, 'membw_write': 2, 'membw_read': 3, 'wss': 1},
    'redis-memtier-big-wss': {'mem': 75, 'cpu': 3, 'membw_write': 3, 'membw_read': 2, 'wss': 1},
    # ---
    'memcached-mutilate-small': {'mem': 26, 'cpu': 10, 'membw_write': 2, 'membw_read': 2, 'wss': 5},
    'memcached-mutilate-medium': {'mem': 51, 'cpu': 10, 'membw_write': 2, 'membw_read': 3, 'wss': 8},
    'memcached-mutilate-big': {'mem': 91, 'cpu': 10, 'membw_write': 3, 'membw_read': 3, 'wss': 3}
    'memcached-mutilate-big-wss': {'mem': 91, 'cpu': 10, 'membw_write': 2, 'membw_read': 3, 'wss': 10},
    # ---
    'mysql-hammerdb-small': {'mem': 52, 'cpu': 4, 'membw_write': 1, 'membw_read': 1, 'wss': 1},
    # ---
    # NOTE: broken not stable among DRAM nodes (wrong configuration)
    # 'specjbb-preset-medium': {'mem': 26, 'cpu': 9, 'membw_write': 2, 'membw_read': 5, 'wss': 12},
    # 'specjbb-preset-small': {'mem': 12, 'cpu': 4, 'membw_write': 1, 'membw_read': 1, 'wss': 5},
    # 'specjbb-preset-big-60': {'mem': 66, 'cpu': 24, 'membw_write': 4, 'membw_read': 12, 'wss': 31},
    'specjbb-preset-big-120': {'mem': 126, 'cpu': 12, 'membw_write': 1, 'membw_read': 3, 'wss': 11},
}


# Workloads from an experiment from 02.03.2019.
def static_experiment_1(target_utilization, percentage_matching_aep):
    return {'redis-memtier-big': 8, 'redis-memtier-big-wss': 8, 'stress-stream-big': 5, 'sysbench-memory-big': 5}


def static_all_workloads_count_1():
    return {workloadname: 1 for workloadname in WORKLOADS_SET}


def random_with_total_utilization_specified(cpu_limit: Tuple[float, float],
                                            mem_limit: Tuple[float, float],
                                            nodes_capacities: Dict[str, Dict],
                                            workloads_set: Dict[str, Dict]) -> Tuple[int, Dict[str, int]]:
    """Random, but workloads expected usage of CPU and MEMOMORY sums to specified percentage (+- accuracy).
       Returns tuple, first item how many iterations were performed to random proper workloads set,
       second set of workloads."""
    cpu_all, mem_all = 0, 0
    for nodename, node in nodes_capacities.items():
        # Only cound DRAM nodes
        if nodename in AEP_NODES:
            continue
        cpu_all += node['cpu']
        mem_all += node['mem']

    cpu_target_l, cpu_target_r = cpu_all * cpu_limit[0], cpu_all * cpu_limit[1]
    mem_target_l, mem_target_r = mem_all * mem_limit[0], mem_all * mem_limit[1]

    logging.debug("[randomizing workloads] cpu(all={}, l={}, r={}), mem(all={}, l={}, r={}), N_nodes={})".format(
        cpu_all, cpu_target_l, cpu_target_r, mem_all, mem_target_l, mem_target_r, len(nodes_capacities)-1))

    workloads_names = [workload_name for workload_name in workloads_set]
    workloads_list = [workloads_set[workload_name] for workload_name in workloads_names]
    choices_weights = [w['mem']/w['cpu'] for w in workloads_list]
    # choices_weights = [round(math.log(val+5), 2) for val in choices_weights]
    choices_weights = [round(val+5, 2) for val in choices_weights]
    logging.debug("[randomizing workloads] weights={}".format(list(zip(workloads_names, choices_weights))))

    best_for_now = (100,1)
    found_solution = None
    iteration = 0
    while found_solution is None:
        cpu_curr = 0
        mem_curr = 0

        choosen_workloads = {}
        while cpu_curr < cpu_target_l or mem_curr < mem_target_l:
            choosen = random.choices(workloads_names, choices_weights)[0]
            # choosen = random.choice(workloads_names)
            if choosen in choosen_workloads:
                choosen_workloads[choosen] += 1
            else:
                choosen_workloads[choosen] = 1
            cpu_curr += workloads_set[choosen]['cpu']
            mem_curr += workloads_set[choosen]['mem']

        if cpu_curr <= cpu_target_r and mem_curr <= mem_target_r:
            found_solution = choosen_workloads
        else:
            if (mem_curr/mem_all)/(cpu_curr/cpu_all) > best_for_now[1]/best_for_now[0]:
                best_for_now = (round(cpu_curr/cpu_all, 4), round(mem_curr/mem_all, 4))
            iteration += 1
        if iteration > 0 and iteration % 1000 == 0:
            logging.debug("[randomizing workloads] Trying to find set of workloads already for {} iterations. cpu_limits={} mem_limits={}".format(iteration, cpu_limit, mem_limit))
            logging.debug("[randomizing workloads] Best for now: (cpu={}, mem={})".format(best_for_now[0], best_for_now[1]))

    logging.debug("[randomizing workloads] choosen solution feature: cpu={} mem={}".format(round(cpu_curr/cpu_all, 2), round(mem_curr/mem_all, 2)))
    logging.debug("[randomizing workloads] choosen workloads:\n{}".format(pprint.pformat(choosen_workloads, indent=4)))
    utilization = {'cpu': cpu_curr/cpu_all, 'mem': mem_curr/mem_all}
    return iteration, choosen_workloads, utilization


class NodesClass(enum.Enum):
    _1LM = '1'
    _2LM = '2'


class OnOffState(enum.Enum):
    On = True
    Off = False


def default_shell_run(command):
    """Default way of running commands."""
    logging.debug('command run in shell >>{}<<'.format(command))
    r = subprocess.run(command, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return r.stdout.decode('utf-8'), r.stderr.decode('utf-8')


def taint_nodes_class(nodes_class: NodesClass, new_state: OnOffState = OnOffState.On):
    """Taint or untaint 1lm or 2lm nodes."""
    if new_state == OnOffState.On:
        tweak_value = ''
    else:
        tweak_value = '-'
    command = "kubectl taint node -l memory={}lm run=taint:NoSchedule{} --overwrite || true".format(str(nodes_class.value), tweak_value)
    default_shell_run(command)


def scale_down_all_workloads(wait_time: int):
    """Kill all workloads"""
    command = "kubectl scale sts --all --replicas=0 && sleep {wait_time}".format(wait_time=wait_time)
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
    workloads_run_order_ = workloads_run_order.copy() # we edit the list

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
    assert not workloads_run_order_


def sleep(sleep_duration):
    default_shell_run('sleep {}'.format(sleep_duration))


MINUTE = 60  # in seconds


def copy_scheduler_logs(log_file):
    # ...
    stdout, _ = default_shell_run('kubectl get pods -n wca-scheduler')
    pod_name = None
    for word in stdout.split():
        if 'wca-scheduler-' in word:
            pod_name = word
            break
    else:
        assert False, 'Should found wca-scheduler pod, but not found'
    command = 'kubectl logs -n wca-scheduler {pod_name} wca-scheduler > {log_file}'
    default_shell_run(command.format(pod_name=pod_name, log_file=log_file))


class WaitPeriod:
    SCALE_DOWN = 'scale_down'
    STABILIZE = 'stabilize'


def single_3stage_experiment(experiment_id: str, workloads: Dict[str, int],
                             wait_periods: Dict[WaitPeriod, int], stages=[True, True, True],
                             experiment_root_dir: str = 'results/tmp'):
    """
    Run three stages experiment:
    1) kubernetes only, 2lm nodes not used
    2) kubernetes only, 2lm nodes used
    2) scheduler_extender, 2lm nodes used
    """
    events = []

    # @TODO remove this hack;
    # allows for setting different sleep time for each stage
    if type(wait_periods[WaitPeriod.STABILIZE]) == int:
        wait_periods[WaitPeriod.STABILIZE] = [wait_periods[WaitPeriod.STABILIZE]] * 3

    # kill all workloads
    scale_down_all_workloads(wait_time=wait_periods[WaitPeriod.SCALE_DOWN])

    # Before start random order of running workloads, but keep the order among the stages
    workloads_run_order: List[str] = get_shuffled_workloads_order(workloads)
    logging.debug("Workload run order: {}".format(list(reversed(workloads_run_order))))

    if stages[0]:
        # kubernetes only, 2lm off
        logging.info('Running first stage')
        switch_extender(OnOffState.Off)
        taint_nodes_class(NodesClass._2LM, OnOffState.Off)
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
        
    # Just to show on graph end of experiment
    sleep(100)


# Last tuning: time: "1584646650", Date: 2020-03-19 19:37:30
def tune_stage(workloads, sleep_time: int = 25*MINUTE):
    workloads_run_order: List[str] = get_shuffled_workloads_order(workloads)

    logging.debug("Running >>tuning<<")
    scale_down_all_workloads(wait_time=20)
    switch_extender(OnOffState.Off)
    taint_nodes_class(NodesClass._2LM)
    run_workloads(workloads_run_order, workloads)
    sleep(sleep_time)
    now = datetime.now()  # Read data just before killing workloads
    sleep(60)             # Additional 60 seconds of sleep, after reading >>now<<
    scale_down_all_workloads(wait_time=20)

    # Save and print result.
    logging.debug("Date: {} Timestamp: {}".format(now, int(now.timestamp())))
    if not os.path.isdir("tuning"):
        os.makedirs("tuning")
    with open('tuning/{}.txt'.format(now.strftime("%Y-%m-%d--%H-%M")), 'w') as fref:
        fref.write("Date: {}\n".format(now))
        fref.write("Timestamp: {}\n".format(now.timestamp()))


# -----------------------------------------------------------------------------------------------------
def experimentset_main(iterations=10, experiment_root_dir='results/tmp', overwrite=False):
    logging.debug("Running experimentset >>main<< with experiment_directory >>{}<<".format(experiment_root_dir))
    random.seed(datetime.now())

    if overwrite and os.path.isdir(experiment_root_dir):
        shutil.rmtree(experiment_root_dir)
    
    if not os.path.isdir(experiment_root_dir):
        os.makedirs(experiment_root_dir)
    else:
        raise Exception('experiment root directory already exists! {}'.format(experiment_root_dir))

    for i in range(iterations):
        iterations, workloads, utilization = random_with_total_utilization_specified(
            cpu_limit=(0.25, 0.46), mem_limit=(0.81, 0.9),
            nodes_capacities=NODES_CAPACITIES, workloads_set=WORKLOADS_SET)
        with open(os.path.join(experiment_root_dir, 'choosen_workloads_utilization.{}.txt'.format(i)), 'a') as fref:
            fref.write(str(utilization))
            fref.write('\n')

        experiment_id = str(i)
        single_3stage_experiment(experiment_id=experiment_id,
                                 workloads=workloads,
                                 wait_periods={WaitPeriod.SCALE_DOWN: 60,
                                               WaitPeriod.STABILIZE: 60*15},
                                 stages=[True, True, True],
                                 experiment_root_dir=experiment_root_dir)


def experimentset_main_pepe(iterations=10, experiment_root_dir='results/tmp', overwrite=False):
    logging.debug("Running experimentset >>main<< with experiment_directory >>{}<<".format(experiment_root_dir))
    random.seed(datetime.now())

    if overwrite and os.path.isdir(experiment_root_dir):
        shutil.rmtree(experiment_root_dir)
    
    if not os.path.isdir(experiment_root_dir):
        os.makedirs(experiment_root_dir)
    else:
        raise Exception('experiment root directory already exists! {}'.format(experiment_root_dir))

    workloads_set_pepe = \
    {
        'memcached-mutilate-big-wss': {'mem': 91, 'cpu': 10, 'membw_write': 2, 'membw_read': 3, 'wss': 10},
        'stress-stream-big': {'mem': 13, 'cpu': 4, 'membw_write': 6, 'membw_read': 2, 'wss': 13},
        'memcached-mutilate-big': {'mem': 91, 'cpu': 10, 'membw_write': 3, 'membw_read': 3, 'wss': 3},
        'sysbench-memory-big': {'mem': 10, 'cpu': 4, 'membw_write': 17, 'membw_read': 1, 'wss': 9},
    }

    for i in range(iterations):
        iterations, workloads, utilization = random_with_total_utilization_specified(
            cpu_limit=(0.25, 0.46), mem_limit=(0.81, 0.9),
            nodes_capacities=NODES_CAPACITIES, workloads_set=workloads_set_pepe)
        with open(os.path.join(experiment_root_dir, 'choosen_workloads_utilization.{}.txt'.format(i)), 'a') as fref:
            fref.write(str(utilization))
            fref.write('\n')

        experiment_id = str(i)
        single_3stage_experiment(experiment_id=experiment_id,
                                 workloads=workloads,
                                 wait_periods={WaitPeriod.SCALE_DOWN: 60,
                                               WaitPeriod.STABILIZE: 60*15},
                                 stages=[True, True, True],
                                 experiment_root_dir=experiment_root_dir)


def experimentset_single_workload_at_once(
        experiment_root_dir: str ='results/tmp', overwrite: bool = False,
        workloads_set: Optional[List[str]] = None):

    logging.debug("Running experimentset >>every workload is single<< with experiment_directory >>{}<<".format(experiment_root_dir))
    random.seed(datetime.now())

    if overwrite and os.path.isdir(experiment_root_dir):
        shutil.rmtree(experiment_root_dir)
    
    if not os.path.isdir(experiment_root_dir):
        os.makedirs(experiment_root_dir)
    else:
        raise Exception('experiment root directory already exists! {}'.format(experiment_root_dir))

    if workloads_set is None:
        # 5 workloadow, kazdy 3 -- > 15
        workloads_set = [
            # 'stress-stream-small',
            'stress-stream-medium',
            # 'stress-stream-big',
            # # ---
            # 'sysbench-memory-small',
            # 'sysbench-memory-medium',
            # 'sysbench-memory-big',
            # # ---
            # 'memcached-mutilate-small',
            # 'memcached-mutilate-medium',
            'memcached-mutilate-big',
            # 'memcached-mutilate-big-wss',
            # # ---
            # 'redis-memtier-small',
            # 'redis-memtier-medium',
            'redis-memtier-big',
            # 'redis-memtier-big-wss',
            # ---
            # 'specjbb-preset-big-60',
            'specjbb-preset-big-120',
            # # ---
            'mysql-hammerdb-small',
        ]

    i = 0
    for workload in workloads_set:
        for per_node_count in range(1, 4):
            experiment_id = str(i)

            # Run on all active nodes.
            # workloads = {workload: len(NODES_CAPACITIES)-len(AEP_NODES)}
            workloads = {workload: per_node_count * len(NODES_CAPACITIES)}

            single_3stage_experiment(experiment_id=experiment_id,
                                     workloads=workloads,
                                     wait_periods={WaitPeriod.SCALE_DOWN: 60,
                                                   # @NOTE:
                                                   # Just to keep runner_analyzer working, 
                                                   # keep 2,3 state, but very short.
                                                   WaitPeriod.STABILIZE: [60, 60 * 10, 60]},
                                     stages=[False, True, False],
                                     experiment_root_dir=experiment_root_dir)
            i += 1



def experimentset_test(experiment_root_dir='results/__test__'):
    logging.debug("Running experimentset >>test<<")
    random.seed(datetime.now())

    if not os.path.isdir(experiment_root_dir):
        os.makedirs(experiment_root_dir)

    _, workloads, _ = random_with_total_utilization_specified(
        cpu_limit=(0.25, 0.41), mem_limit=(0.65, 0.9),
        nodes_capacities=NODES_CAPACITIES, workloads_set=WORKLOADS_SET)
    single_3stage_experiment(experiment_id=0,
                             workloads=workloads,
                             wait_periods={WaitPeriod.SCALE_DOWN: 10,
                                           WaitPeriod.STABILIZE: 60},
                             stages=[False, False, True],
                             experiment_root_dir=experiment_root_dir)
# -----------------------------------------------------------------------------------------------------


if __name__ == "__main__":
    experimentset_single_workload_at_once(experiment_root_dir='results/2020-04-02__single_all_one-two-three')
