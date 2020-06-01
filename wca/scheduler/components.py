# Copyright (c) 2019 Intel Corporation
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

from wca.config import register
from wca.scheduler.algorithms.bar import BAR
from wca.scheduler.algorithms.dram_hit_ratio_provision import DramHitRatioProvision
from wca.scheduler.algorithms.least_used_bar import LeastUsedBAR
from wca.scheduler.algorithms.least_used import LeastUsed
from wca.scheduler.algorithms.fit import Fit
from wca.scheduler.algorithms.hierbar import HierBAR
from wca.scheduler.algorithms.static_assigner import StaticAssigner
from wca.scheduler.data_providers.cluster_data_provider import (
    ClusterDataProvider, Queries)
from wca.scheduler.algorithms.score import Score
from wca.scheduler.data_providers.score.cluster import ClusterScoreDataProvider
from wca.scheduler.kubeapi import Kubeapi
from wca.prometheus import Prometheus


def register_algorithms():
    register(Fit)
    register(LeastUsedBAR)
    register(LeastUsed)
    register(BAR)
    register(HierBAR)
    register(StaticAssigner)
    register(Score)
    register(DramHitRatioProvision)


def register_dataproviders():
    register(Kubeapi)
    register(Prometheus)
    register(Queries)
    register(ClusterDataProvider)
    register(ClusterScoreDataProvider)
