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

from typing import List, Dict
from wca.nodes import TaskResources


# https://kubernetes.io/docs/concepts/configuration/manage-compute-resources-container/#meaning-of-memory
_MEMORY_UNITS = {'Ki': 1024, 'Mi': 1024 ** 2, 'Gi': 1024 ** 3, 'Ti': 1024 ** 4,
                 'K': 1000, 'M': 1000 ** 2, 'G': 1000 ** 3, 'T': 1000 ** 4}
_CPU_UNITS = {'m': 0.001}
_RESOURCE_TYPES = ['requests', 'limits']
_MAPPING = {'requests_memory': 'mem', 'ephemeral-storage': 'disk', 'requests_cpu': 'cpus'}

_UNITS = {'memory': _MEMORY_UNITS, 'ephemeral-storage': _MEMORY_UNITS,
          'cpu': _CPU_UNITS}


def calculate_scalar_resources(task_resources: List[Dict[str, str]]) -> TaskResources:
    """Returns flat dictionary with keys created as resource_name,
       e.g. 'cpus': '8.0' """

    resources = {}

    for resource in task_resources:
        if resource['type'] == 'SCALAR':
            resources[resource['name']] = float(resource['scalar']['value'])

    # "disk" and "mem" resources are scalar values expressed in megabytes.
    # Source:
    # https://github.com/apache/mesos/blob/776b31c6658be234497218a9a33e3961075c83e6/include/mesos/mesos.proto#L1236
    # This resources should be converted to bytes to match k8s.
    for res in ['disk', 'mem']:
        resources[res] = resources[res] * _MEMORY_UNITS['M']

    return resources


def calculate_pod_resources(containers_spec: List[Dict[str, str]]) -> TaskResources:
    """Returns flat dictionary with keys created as resource_type + '_' + resource_name,
       e.g. 'cpu_limits': '0.25' """

    resources = {}

    for container in containers_spec:
        container_resources = container.get('resources')
        if not container_resources:
            continue

        for resource_type in _RESOURCE_TYPES:
            if resource_type not in container_resources:
                continue

            for resource_name, resource_value in \
                    container_resources.get(resource_type).items():
                value = resource_value
                for unit, multiplier in _UNITS.get(resource_name).items():
                    if resource_value.endswith(unit):
                        value = float(resource_value.split(unit)[0]) * multiplier
                        break

                resource_key = resource_type + '_' + resource_name
                if resource_key in resources:
                    resources[resource_key] += float(value)
                else:
                    resources[resource_key] = float(value)

    # Mapping resource names to make them consistent with mesos
    mapped_resources = dict()
    for original_resource, mapped_resource in _MAPPING.items():
        if original_resource in resources:
            mapped_resources[mapped_resource] = resources[original_resource]
    resources.update(mapped_resources)

    return resources
