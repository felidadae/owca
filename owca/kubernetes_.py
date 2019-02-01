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


from dataclasses import dataclass, field
from typing import Dict
import kubernetes
import logging

from owca.nodes import Node

log = logging.getLogger(__name__)


@dataclass
class KubernetesTask:
    name: str
    container_id: str
    pod_id: str
    qos: str  # Quality of Service

    # inferred
    cgroup_path: str  # Starts with leading "/"
    labels: Dict[str, str] = field(default_factory=dict)

    def __str__(self):
        descr = "KubernetesTask: {}\n".format(self.name)
        descr += "\tcontainer_id: {}\n".format(self.container_id)
        descr += "\tpod_id: {}\n".format(self.pod_id)
        descr += "\tqos: {}\n".format(self.qos)
        descr += "\tcgroup_path: {}\n".format(self.cgroup_path)
        return descr

@dataclass
class KubernetesNode(Node):
    def get_tasks(self):
        """ only return running tasks"""
        kubernetes.config.load_kube_config()
        v1 = kubernetes.client.CoreV1Api()
        pods = v1.list_pod_for_all_namespaces(watch=False)

        tasks = []

        for pod in pods.items:
            for container in pod.status.container_statuses:
                if container.state.running:
                    container_name = container.name
                    # @TODO temporary solution to cgroups bug
                    if "nginx" not in container_name:
                        continue
                    container_id = container.container_id.strip('docker://')
                    pod_id = pod.metadata.uid.replace('-', '_')
                    qos = pod.status.qos_class
                    labels = pod.metadata.labels
                    tasks.append(
                        KubernetesTask(
                            name=container_name,
                            container_id=container_id,
                            pod_id=pod_id,
                            qos=qos.lower(),
                            labels=labels,
                            cgroup_path=find_cgroup(pod_id, container_id, qos)))
        return tasks


def find_cgroup(pod_id, container_id, qos):
    """
    :param pod_id: string uniquely identifying container
    :param container_id: container ID
    :param qos: quality of service for pod
    :return: cgroup path relative to 'cpu'
    """
    return ('/kubepods.slice/'
            'kubepods-{qos}.slice/'
            'kubepods-{qos}-pod{pod_id}.slice/'
            'docker-{container_id}.scope'.format(qos=qos.lower(),
                                                 container_id=container_id,
                                                 pod_id=pod_id))


if __name__ == "__main__":
    node = KubernetesNode()
    tasks = node.get_tasks()
    for task in tasks:
        print(task)
