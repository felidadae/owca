# Copyright (c) 2018 Intel Corporation
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


from typing import List
import pkg_resources

from owca import config
from owca import detectors
from owca import allocators
from owca import mesos
from owca import kubernetes_
from owca import runner
from owca import storage


def register_components(extra_components: List[str]):
    config.register(runner.DetectionRunner)
    config.register(runner.AllocationRunner)
    config.register(mesos.MesosNode)
    config.register(kubernetes_.KubernetesNode)
    config.register(storage.LogStorage)
    config.register(storage.KafkaStorage)
    config.register(detectors.NOPAnomalyDetector)
    config.register(allocators.NOPAllocator)
    config.register(allocators.AllocationConfiguration)

    for component in extra_components:
        # Load external class ignored its requirements.
        ep = pkg_resources.EntryPoint.parse('external_cls=%s' % component)
        cls = ep.resolve()
        config.register(cls)
