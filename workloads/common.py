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


import textwrap
import os
import json

# Common environment variables for all workloads.

# Workload identification
workload_name = os.getenv('workload_name')
workload_version_name = os.getenv('workload_version_name', 'default')
replica_index = os.getenv('replica_index', 0)
job_uniq_id = os.getenv('job_uniq_id')
job_name = os.getenv('job_name')

application = os.getenv('application')
load_generator = os.getenv('load_generator', None)

# Cluster job key identification.
cluster = os.getenv('cluster', 'example')
role = os.getenv('role', os.getenv('USER'))
env_uniq_id = os.getenv('env_uniq_id')

environment = 'staging' + env_uniq_id

# For workloads like tensorflow ignore load_generator_host_ip is ignored.
application_host_ip = os.getenv('application_host_ip')
load_generator_host_ip = os.getenv('load_generator_host_ip')
own_ip = os.getenv('own_ip')

# Performance related variables
slo = os.getenv('slo', 'inf')  # optional: default to inf

# Docker image.
image_tag = os.getenv('image_tag')
image_name = os.getenv('image_name')
# print('image_tag:', image_tag)
# print('image_name:', image_name)

# Resources:
cpu = os.getenv('cpu', '1')
ram = os.getenv('ram', '1') + 'Gi'
disk = os.getenv('disk', '1') + 'Gi'

# K8s specific variables:
pod_namespace = os.getenv('k8s_namespace', 'default')
pod_naming_types = ('short', 'full')
pod_naming = os.getenv('k8s_pod_naming', 'short')
assert pod_naming in pod_naming_types

# Wrapper variables:
wrapper_kafka_brokers = os.getenv('wrapper_kafka_brokers', '')
wrapper_kafka_topic = os.getenv('wrapper_kafka_topic', '')
wrapper_log_level = os.getenv('wrapper_log_level', 'DEBUG')
# Here as dict, must be passed to wrapper as json string.
#   Can be extended as desired in workload's aurora manifests.
extra_labels = json.loads(os.getenv('labels', '{}'))
wrapper_labels = {
    'workload_name': workload_name,
    'workload_version_name': workload_version_name,
    'workload_instance': '--'.join([workload_name,
                                    workload_version_name,
                                    env_uniq_id, job_uniq_id]),
    'replica_index': replica_index,
    'name': job_name,       # not to break compatibility
    'job_name': job_name,   #
    'application': application,
    'load_generator': load_generator,
    'job_uniq_id': job_uniq_id,
    'env_uniq_id': env_uniq_id,
    'own_ip': own_ip,
    'application_host_ip': application_host_ip,
    'load_generator_host_ip': load_generator_host_ip,
}
wrapper_labels.update(extra_labels)


# Pre 0.20 way of adding metadata
class AddMetadata:

    def __init__(self, labels):
        self.labels = labels

    def pre_create_job(self, config):
        for label_nama, label_value in self.labels.items():
            config.add_metadata(label_nama, label_value)
        return config


def dedent(s):
    return textwrap.dedent(s).replace('\n', ' ').replace('\'', '"')


command = ["sh", "-c"]

securityContext = {
    "runAsUser": 0
}

limits = {
    "cpu": cpu,
    "memory": ram,
    "ephemeral-storage": disk,
}

volumes = [{"name": "shared-data"}]
initContainers = []

volumeMounts = []

containers = [
    {
        "name": job_name.replace('_', '-').replace('.', '-'),
        "image": image_name + ":" + image_tag,
        "resources": {"limits": limits},
        "securityContext": securityContext,
        "volumeMounts": volumeMounts,
        "command": command,

    }
]

# Creates uniq name of a pod from job_name, env_uniq_id, role and cluster.
pod_name = env_uniq_id + "--" + job_name.replace('_', '-').replace('.', '-')
if pod_naming == "full":
    pod_name = cluster + "--" + role + "--" + pod_name

metadata = {
    "namespace": pod_namespace,
    "name": pod_name,
    "labels": wrapper_labels
}

pod = {
    "apiVersion": "v1",
    "kind": "Pod",
    "metadata": metadata,
    "spec": {
        "volumes": volumes,
        "hostNetwork": True,
        "initContainers": initContainers,
        "containers": containers,
        "nodeSelector": {
            "own_ip": own_ip
        }
    }
}
