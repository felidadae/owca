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
from typing import Dict, List, Callable

from tests.scheduler.simulator.data_provider import ClusterSimulatorDataProvider
from wca.scheduler.algorithms import Algorithm
from wca.scheduler.algorithms.fit import Fit
from wca.scheduler.algorithms.least_used_bar import LeastUsedBAR
from wca.scheduler.cluster_simulator import ClusterSimulator
from wca.scheduler.cluster_simulator import Node, Resources, Task
from wca.scheduler.types import CPU, MEM, MEMBW_READ, MEMBW_WRITE


def run_until_first_failure(
        nodes: List[Node], task_creation_fun: Callable[[int], Task],
        extra_simulator_args: Dict, algorithm_class: Algorithm,
        extra_scheduler_kwargs: Dict, iteration_finished_callback: Callable = None):
    """Compare standard algorithm with the algorithm which looks also at MEMBW"""
    simulator = ClusterSimulator(
        tasks=[],
        nodes=nodes,
        algorithm=None,
        **extra_simulator_args)
    data_proxy = ClusterSimulatorDataProvider(simulator)
    simulator.algorithm = algorithm_class(data_provider=data_proxy, **extra_scheduler_kwargs)

    iteration = 0
    while simulator.iterate_single_task(task_creation_fun(iteration)) == 1:
        if iteration_finished_callback is not None:
            iteration_finished_callback(iteration, simulator)
        iteration += 1

    return simulator


def test_single_run():
    nodes = [Node('0', Resources({CPU: 96, MEM: 1000})),
             Node('1', Resources({CPU: 96, MEM: 320}))]
    algorithm_class = Fit
    algorithm_args = {'dimensions': {CPU, MEM}}

    def task_creation_fun(identifier):
        r = Resources({CPU: 8, MEM: 10})
        t = Task('stress_ng_{}'.format(identifier), r)
        return t

    extra_simulator_args = {"allow_rough_assignment": False}
    simulator = run_until_first_failure(
        nodes, task_creation_fun, extra_simulator_args,
        algorithm_class, algorithm_args)
    assert len(simulator.tasks) == 25


def test_single_run_membw_write_read():
    """check code membw write/read specific"""
    dimensions = {CPU, MEM, MEMBW_READ, MEMBW_WRITE}
    nodes = [Node('0', Resources({CPU: 96, MEM: 1000, MEMBW_READ: 40, MEMBW_WRITE: 10})),
             Node('1', Resources({CPU: 96, MEM: 320, MEMBW_READ: 150, MEMBW_WRITE: 150}))]

    algorithm_args = {'dimensions': dimensions}

    def task_creation_fun_aep(identifier):
        r = Resources({CPU: 8, MEM: 10, MEMBW_WRITE: 5, MEMBW_READ: 5})
        t = Task('stress_ng_{}'.format(identifier), r)
        return t

    extra_simulator_args = {"allow_rough_assignment": True}
    for scheduler_class, expected_count in ((Fit, 14), (LeastUsedBAR, 14)):
        simulator = run_until_first_failure(
            nodes, task_creation_fun_aep, extra_simulator_args,
            scheduler_class, algorithm_args)
        assert len(simulator.tasks) == expected_count
