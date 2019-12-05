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

try:
    import pkg_resources
except ImportError:
    # When running from pex use vendored library from pex.
    from pex.vendor._vendored.setuptools import pkg_resources

from wca.runners import detection
from wca.runners import allocation
from wca.runners import measurement
from wca.extra import static_allocator
from wca import config
from wca import detectors
from wca import allocators
from wca import mesos
from wca import kubernetes
from wca import storage
from wca.extra import static_node
from wca.extra import numa_allocator
from wca import security
from wca.metrics import DefaultDerivedMetricsGenerator
from wca.perf_uncore import UncoreDerivedMetricsGenerator

REGISTERED_COMPONENTS = [
    measurement.MeasurementRunner,
    allocation.AllocationRunner,
    detection.DetectionRunner,
    mesos.MesosNode,
    kubernetes.KubernetesNode,
    storage.LogStorage,
    storage.KafkaStorage,
    storage.FilterStorage,
    detectors.NOPAnomalyDetector,
    allocators.NOPAllocator,
    allocators.AllocationConfiguration,
    kubernetes.CgroupDriverType,
    static_node.StaticNode,
    numa_allocator.NUMAAllocator,
    static_allocator.StaticAllocator,
    security.SSL,
    measurement.TaskLabelRegexGenerator,
    DefaultDerivedMetricsGenerator,
    UncoreDerivedMetricsGenerator,
]


def register_components(extra_components: List[str]):
    for component in REGISTERED_COMPONENTS:
        config.register(component)

    for component in extra_components:
        # Load external class ignored its requirements.
        ep = pkg_resources.EntryPoint.parse('external_cls=%s' % component)
        cls = ep.resolve()
        config.register(cls)
