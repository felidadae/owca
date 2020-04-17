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
import logging

import pytest

from tests.scheduler.simulator.generic_experiment import experiments_iterator
from tests.scheduler.simulator.nodes_generators import prepare_nodes
from tests.scheduler.simulator.nodesets import (
    NODES_DEFINITIONS_2TYPES, NODES_DEFINITIONS_3TYPES)
from tests.scheduler.simulator.task_generators import TaskGeneratorEqual, \
    TaskGeneratorClasses, taskset_dimensions
from tests.scheduler.simulator.tasksets import TASKS_3TYPES, TASKS_2TYPES
from tests.scheduler.simulator.tasksets import TASKS_6TYPES
from wca.scheduler.algorithms.bar import BAR
from wca.scheduler.algorithms.fit import Fit
from wca.scheduler.algorithms.hierbar import HierBAR
from wca.scheduler.algorithms.least_used import LeastUsed
from wca.scheduler.algorithms.least_used_bar import LeastUsedBAR
from wca.scheduler.algorithms.nop_algorithm import NOPAlgorithm
from wca.scheduler.algorithms.score import Score
from wca.scheduler.algorithms.static_assigner import StaticAssigner
from wca.scheduler.types import WSS, MEM, CPU, MEMBW_WRITE, MEMBW_READ

log = logging.getLogger(__name__)

DIM5 = {CPU, MEM, MEMBW_READ, MEMBW_WRITE, WSS}
DIM4 = {CPU, MEM, MEMBW_READ, MEMBW_WRITE}
DIM2 = {CPU, MEM}


@pytest.mark.scheduler_simulator
def test_experiment_score():
    dim = DIM2
    results = experiments_iterator(
        'score',
        [  # Simulator & data provider configuration
            dict(retry_scheduling=True, data_provider_args=dict(normalization_dimension=CPU)),
            dict(retry_scheduling=True, data_provider_args=dict(normalization_dimension=MEM)),
        ],
        [20],
        [
            (TaskGeneratorEqual,
             dict(task_definitions=TASKS_3TYPES, dimensions=dim, replicas=3,
                  duration=None, node_name='dram_0')),
        ],
        [
            prepare_nodes(NODES_DEFINITIONS_2TYPES, dict(aep=1, dram=1), dim),
        ],
        [
            (Score, dict(dimensions=dim)),
        ],
        rmtree=False,
        charts=False,
        metrics=False,  # can be as list of metric names
    )
    assert len(results) == 2
    assert results == [{'ALGO': 'Score(2)',
                        'NODES': '2(aep=1,dram=1)',
                        'SIM': 'retry=1,norm=cpu',
                        'TASKS': '9(cpu=3,mbw=3,mem=3)',
                        'assigned%': 100,
                        'assigned_broken%': 0,
                        'balance': 0.90892333984375,
                        'cpu_util%': 30.0,
                        'cpu_util(AEP)%': 7.5,
                        'mem_util%': 38.00335570469799,
                        'mem_util(AEP)%': 30.0,
                        'scheduled': 9,
                        'utilization%': 34},
                       {'ALGO': 'Score(2)',
                        'NODES': '2(aep=1,dram=1)',
                        'SIM': 'retry=1,norm=mem',
                        'TASKS': '9(cpu=3,mbw=3,mem=3)',
                        'assigned%': 100,
                        'assigned_broken%': 0,
                        'balance': 0.90892333984375,
                        'cpu_util%': 30.0,
                        'cpu_util(AEP)%': 7.5,
                        'mem_util%': 38.00335570469799,
                        'mem_util(AEP)%': 30.0,
                        'scheduled': 9,
                        'utilization%': 34}]


@pytest.mark.scheduler_simulator
def test_experiment_bar():
    task_scale = 1
    cluster_scale = 1
    nodes_dimensions = DIM4

    results = experiments_iterator(
        'bar_weights',
        [{}],
        [30 * task_scale, ],
        [
            (TaskGeneratorClasses, dict(task_definitions=taskset_dimensions(nodes_dimensions,
                                                                            TASKS_6TYPES),
                                        counts=dict(mbw=20 * task_scale, cpu=5 * task_scale,
                                                    mem=5 * task_scale))),
        ],
        [
            prepare_nodes(NODES_DEFINITIONS_2TYPES,
                          dict(aep=2 * cluster_scale, dram=6 * cluster_scale), nodes_dimensions),
        ],
        [
            (LeastUsedBAR,
             dict(alias='BAR__LU_ON__WEIGHTS_UNEQUAL', dimensions=DIM4, least_used_weight=1,
                  bar_weights={MEM: 0.5})),
            (LeastUsedBAR,
             dict(alias='BAR__LU_ON__WEIGHTS_EQUAL', dimensions=DIM4, least_used_weight=1)),
            (LeastUsedBAR,
             dict(alias='BAR__LU_ON__WEIGHTS_100x', dimensions=DIM4, least_used_weight=100)),
            (LeastUsedBAR, dict(alias='BAR__LU_OFF', dimensions=DIM4, least_used_weight=0)),
        ],
    )
    assert len(results) == 4


@pytest.mark.scheduler_simulator
def test_experiment_static_assigner():
    dim = DIM2
    targeted_assigned_apps_counts = \
        {'aep_0': {'cputask': 1, 'memtask': 2},
         'dram_0': {'cputask': 1, 'memtask': 0}}

    results = experiments_iterator(
        'static_assigner',
        [{}],
        [6],
        [
            (TaskGeneratorClasses,
             dict(task_definitions=TASKS_2TYPES,
                  counts=dict(cputask=2, memtask=2), dimensions=dim)),
        ],
        [
            prepare_nodes(NODES_DEFINITIONS_2TYPES, dict(aep=1, dram=1), dim),
        ],
        [
            (StaticAssigner,
             dict(alias='StaticAssigner',
                  targeted_assigned_apps_counts=targeted_assigned_apps_counts,
                  dimensions=dim
                  )
             ),
        ],
    )
    assert len(results) == 1
    result = results[0]
    assert result == {'ALGO': 'StaticAssigner',
                      'NODES': '2(aep=1,dram=1)',
                      'SIM': 'default',
                      'TASKS': '4(cputask=2,memtask=2)',
                      'assigned%': 100,
                      'assigned_broken%': 0,
                      'balance': 0.8671381944444445,
                      'cpu_util%': 50.0,
                      'cpu_util(AEP)%': 100.0,
                      'mem_util%': 40.26845637583892,
                      'mem_util(AEP)%': 44.0,
                      'scheduled': 4,
                      'utilization%': 45}


# --- Long experiments (15 - 20 seconds) ---
# to run without: pytest -m 'not long'

@pytest.mark.scheduler_simulator
@pytest.mark.long
def test_experiment_hierbar():
    dim = DIM4
    iterations = 30
    results = experiments_iterator(
        'hierbar',
        [{}],
        [iterations],
        [
            (TaskGeneratorEqual, dict(task_definitions=TASKS_3TYPES, replicas=10, dimensions=dim)),
            (TaskGeneratorClasses,
             dict(task_definitions=TASKS_3TYPES, counts=dict(mem=30), dimensions=dim)),  # AEP
            (TaskGeneratorClasses,
             dict(task_definitions=TASKS_3TYPES, counts=dict(mbw=30), dimensions=dim)),  # no AEP
            (TaskGeneratorClasses,
             dict(task_definitions=TASKS_3TYPES, counts=dict(cpu=5, mem=5, mbw=20),
                  dimensions=dim)),
            (TaskGeneratorClasses,
             dict(task_definitions=TASKS_3TYPES, counts=dict(cpu=5, mem=20, mbw=5),
                  dimensions=dim)),
        ],
        [
            prepare_nodes(NODES_DEFINITIONS_3TYPES, dict(aep=2, sml=4, big=2), dim)
        ],
        [
            (LeastUsedBAR, dict(dimensions=DIM2, alias='native')),
            (HierBAR, dict(dimensions=dim)),
            (HierBAR, dict(dimensions=dim, merge_threshold=1, alias='extender')),
        ],
    )

    assert len(results) == 15


@pytest.mark.scheduler_simulator
@pytest.mark.long
def test_experiment_fit():
    dim = DIM2
    results = experiments_iterator(
        'fit',
        [dict(retry_scheduling=True)],  # Simulator configuration
        [1],
        [
            (TaskGeneratorEqual,
             dict(task_definitions=TASKS_2TYPES, dimensions=dim, replicas=3,
                  duration=None, node_name='dram_0')),
        ],
        [
            prepare_nodes(NODES_DEFINITIONS_2TYPES, dict(aep=1, dram=1), dim),
        ],
        [
            (Fit, dict(dimensions=dim)),
        ],
        rmtree=False,
        charts=False,
        metrics=False,  # can be as list of metric names
    )
    assert len(results) == 1
    assert results == [{'ALGO': 'Fit(2)',
                        'NODES': '2(aep=1,dram=1)',
                        'SIM': 'retry=1',
                        'TASKS': '6(cputask=3,memtask=3)',
                        'assigned%': 100,
                        'assigned_broken%': 0,
                        'balance': 0.7465277777777778,
                        'cpu_util%': 8.333333333333332,
                        'cpu_util(AEP)%': 0.0,
                        'mem_util%': 16.778523489932887,
                        'mem_util(AEP)%': 0.0,
                        'scheduled': 1,
                        'utilization%': 12}]


@pytest.mark.scheduler_simulator
@pytest.mark.long
def test_experiment_debug():
    task_scale = 1
    cluster_scale = 1
    dim = DIM4
    length = 90
    experiments_iterator(
        'debug',
        [dict(retry_scheduling=True)],
        [length * task_scale],
        [
            (TaskGeneratorEqual,
             dict(task_definitions=TASKS_3TYPES, replicas=10 * task_scale, duration=30,
                  alias='long', dimensions=dim)),
            (TaskGeneratorEqual,
             dict(task_definitions=TASKS_3TYPES, replicas=10 * task_scale, duration=5,
                  alias='short', dimensions=dim)),
            (TaskGeneratorEqual,
             dict(task_definitions=TASKS_3TYPES, replicas=10 * task_scale, duration=None,
                  dimensions=dim)),
        ],
        [
            prepare_nodes(NODES_DEFINITIONS_2TYPES,
                          dict(aep=2 * cluster_scale, dram=6 * cluster_scale), dim),
        ],
        [
            (LeastUsedBAR, dict(alias='BAR__LU_OFF', dimensions=DIM4, least_used_weight=0)),
        ],
    )


@pytest.mark.scheduler_simulator
@pytest.mark.long
def test_experiment_full(task_scale=1, cluster_scale=1):
    dim = DIM4
    experiments_iterator(
        'full',
        [{}],
        [30 * task_scale],
        [
            (TaskGeneratorEqual,
             dict(task_definitions=TASKS_3TYPES, replicas=10 * task_scale, dimensions=dim)),
            (TaskGeneratorClasses, dict(task_definitions=TASKS_3TYPES,
                                        counts=dict(mbw=3 * task_scale, cpu=12 * task_scale,
                                                    mem=15 * task_scale), dimensions=dim)),
            (TaskGeneratorClasses, dict(task_definitions=TASKS_3TYPES,
                                        counts=dict(mbw=20 * task_scale, cpu=5 * task_scale,
                                                    mem=5 * task_scale), dimensions=dim)),
            (TaskGeneratorClasses, dict(task_definitions=TASKS_3TYPES,
                                        counts=dict(mbw=30 * task_scale, cpu=0 * task_scale,
                                                    mem=0 * task_scale), dimensions=dim)),
            (TaskGeneratorClasses, dict(task_definitions=TASKS_3TYPES,
                                        counts=dict(mbw=0 * task_scale, cpu=0 * task_scale,
                                                    mem=30 * task_scale), dimensions=dim)),
        ],
        [
            prepare_nodes(NODES_DEFINITIONS_2TYPES, dict(aep=0, dram=6 * cluster_scale),
                          dim),
            prepare_nodes(NODES_DEFINITIONS_2TYPES,
                          dict(aep=2 * cluster_scale, dram=6 * cluster_scale), dim),
            prepare_nodes(NODES_DEFINITIONS_2TYPES, dict(aep=0, dram=8 * cluster_scale),
                          dim),
            prepare_nodes(NODES_DEFINITIONS_2TYPES, dict(aep=cluster_scale, dram=cluster_scale),
                          dim, ),
        ],
        [
            (NOPAlgorithm, {}),
            (Fit, dict(dimensions=DIM2)),
            (Fit, dict(dimensions=DIM4)),
            (LeastUsed, dict(dimensions=DIM2)),
            (LeastUsed, dict(dimensions=DIM4)),
            (BAR, dict(dimensions=DIM2)),
            (HierBAR, dict(dimensions=DIM2)),
            (LeastUsedBAR,
             dict(alias='kubernetes_baseline', dimensions={CPU, MEM})),
            (LeastUsedBAR, dict(alias='BAR__LU_OFF', dimensions=DIM4, least_used_weight=0)),
            (LeastUsedBAR,
             dict(alias='BAR__LU_ON__WEIGHTS_EQUAL', dimensions=DIM4, least_used_weight=1)),
            (LeastUsedBAR,
             dict(alias='BAR__LU_ON__WEIGHTS_UNEQUAL', dimensions=DIM4, least_used_weight=1,
                  bar_weights={MEM: 0.5})),
        ],
    )
