# Copyright (c) 2020 Intel Corporation
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

import itertools
import logging
import os
import shutil
from typing import List, Tuple, Callable, Dict, Type, Union

from wca.nodes import Node
from wca.scheduler.algorithms import Algorithm
from wca.scheduler.cluster_simulator import ClusterSimulator
from wca.scheduler.data_providers.cluster_simulator_data_provider import \
    ClusterSimulatorDataProvider
from wca.scheduler.simulator_experiments.reporting import (
    IterationData, wrapper_iteration_finished_callback,
    generate_subexperiment_report, generate_experiment_report)
from wca.scheduler.simulator_experiments.task_generators import TaskGenerator

log = logging.getLogger(__name__)

reports_root_directory: str = 'experiments_results'


def experiments_iterator(exp_name, simulator_args,
                         lengths: List[int],  # max iterations
                         task_gen_func_defs: List[Tuple[Type[TaskGenerator], dict]],
                         nodes_sets: List[List[Node]],
                         algorithm_defs: List[Tuple[Type[Algorithm], dict]],
                         rmtree: bool = True,
                         charts: bool = False,
                         metrics: Union[bool, List[str]] = False,
                         ):
    exp_stats: List[dict] = []

    # Recreate results directory.
    exp_dir = '{}/{}'.format(reports_root_directory, exp_name)
    if rmtree:
        if os.path.isdir(exp_dir):
            shutil.rmtree(exp_dir)
    os.makedirs(exp_dir, exist_ok=True)

    for n, args in enumerate(itertools.product(
            lengths,
            task_gen_func_defs,
            nodes_sets,
            algorithm_defs
    )):
        length, task_gen_func_def, nodes, algorithm_def = args
        iterations_data, task_gen, simulator = \
            perform_one_experiment(simulator_args, length, task_gen_func_def, nodes, algorithm_def)

        # Sub experiment report
        subexp_name = '%d_%snodes_%s_%s' % (n, len(simulator.nodes), task_gen, simulator.algorithm)
        stats = generate_subexperiment_report(
            exp_name,
            exp_dir,
            subexp_name,
            iterations_data,
            task_gen=task_gen,
            algorithm=simulator.algorithm,
            charts=charts,
            metrics=metrics,
        )

        log.debug('Finished experiment.', n)
        log.debug('Stats:', stats)
        exp_stats.append(stats)

    # Experiment report
    generate_experiment_report(exp_stats, exp_dir)


def perform_one_experiment(
        simulator_args: dict,
        length: int,
        task_gen_def: Tuple[Type[TaskGenerator], Dict],
        nodes: List[Node],
        algorithm_def: Tuple[Type[Algorithm], Dict],
):
    algorithm_class, algorithm_args = algorithm_def
    iterations_data: List[IterationData] = []

    # Back reference between data proxy and simulator.
    simulator = ClusterSimulator(tasks=[], nodes=nodes, algorithm=None, **simulator_args)
    data_proxy = ClusterSimulatorDataProvider(simulator)
    simulator.algorithm = algorithm_class(data_provider=data_proxy, **algorithm_args)

    task_gen_class, task_gen_args = task_gen_def
    task_gen = task_gen_class(**task_gen_args)

    run_n_iter(length, simulator, task_gen,
               wrapper_iteration_finished_callback(iterations_data))

    return iterations_data, task_gen, simulator


def run_n_iter(length: int,
               simulator: ClusterSimulator,
               task_gen: TaskGenerator,
               iteration_finished_callback: Callable):
    iteration = 0
    while iteration < length:
        new_task = task_gen(iteration)
        assert new_task is not None or iteration > 0, 'in first iteration we need at least one task'
        simulator.iterate_single_task(new_task)
        iteration_finished_callback(iteration, simulator)
        iteration += 1
    return simulator