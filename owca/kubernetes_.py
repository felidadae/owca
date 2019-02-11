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
from typing import Dict, List
import logging
import pprint
import requests
import urllib.parse

from owca import logger
from owca.metrics import MetricName
from owca.nodes import Node

DEFAULT_EVENTS = (MetricName.INSTRUCTIONS, MetricName.CYCLES, MetricName.CACHE_MISSES)

log = logging.getLogger(__name__)


@dataclass
class KubernetesTask:
    name: str
    task_id: str
    cgroup_path: str
    qos: str

    sub_cgroup_paths: List[str] = field(default_factory=list)
    labels: Dict[str, str] = field(default_factory=dict)
    resources: Dict[str, float] = field(default_factory=dict)

    def __hash__(self):
        """Every instance of kubernetes task is uniqully identified by pod cgroup_path."""
        return id(self.task_id)


@dataclass
class KubernetesNode(Node):
    kubernetes_agent_enpoint: str = 'https://127.0.0.1:10250'
    client_private_key: str = None
    client_cert: str = None

    METHOD = 'GET_STATE'
    pods_path = '/pods'

    def get_tasks(self):
        """Returns only running tasks."""
        full_url = urllib.parse.urljoin(self.kubernetes_agent_enpoint, self.pods_path)
        r = requests.get(full_url, json=dict(type=self.METHOD),
                         verify=False, cert=(self.client_cert, self.client_private_key))
        r.raise_for_status()
        state = r.json()

        tasks = []

        for pod in state.get('items'):
            # @TODO only take into consideration
            #   running pods (all containers are in ready state)

            # Ignore Kubernetes internal pods.
            if pod.get('metadata').get('namespace') == 'kube-system':
                continue

            pod_id = pod.get('metadata').get('uid').replace('-', '_')
            qos = pod.get('status').get('qosClass')
            if pod.get('metadata').get('labels'):
                labels = {sanitize_label(key): value
                          for key, value in
                          pod.get('metadata').get('labels').items()}
            else:
                labels = {}

            containers_cgroups = []
            container_statuses = pod.get('status').get('containerStatuses')
            if not container_statuses:
                continue
            for container in container_statuses:
                container_id = container.get('containerID').split('docker://')[1]
                containers_cgroups.append(find_container_cgroup(pod_id, container_id, qos))

            tasks.append(
                KubernetesTask(
                    name=pod_id,
                    task_id=pod_id,
                    qos=qos.lower(),
                    labels=labels,
                    resources=find_resources(pod_id, qos),
                    cgroup_path=find_pod_cgroup(pod_id, qos),
                    sub_cgroup_paths=containers_cgroups))
        log.debug("Found %d kubernetes tasks (cumulatively %d cgroups leafs).",
                  len(tasks), sum([len(task.sub_cgroup_paths) for task in tasks]))
        log.log(logger.TRACE, "Found kubernetes tasks with (pod_id, sub_cgroup_paths): %s.",
                ", ".join(['(' + str(task.task_id) + ", " + str(task.sub_cgroup_paths) + ')' for task in tasks]))
        return tasks


def find_pod_cgroup(pod_id, qos):
    return ('/kubepods.slice/'
            'kubepods-{qos}.slice/'
            'kubepods-{qos}-pod{pod_id}.slice/'.format(qos=qos.lower(),
                                                       pod_id=pod_id))


def find_container_cgroup(pod_id, container_id, qos):
    return ('/kubepods.slice/'
            'kubepods-{qos}.slice/'
            'kubepods-{qos}-pod{pod_id}.slice/'
            'docker-{container_id}.scope'.format(qos=qos.lower(),
                                                 container_id=container_id,
                                                 pod_id=pod_id))


def find_resources(pod_id, qos):
    # @TODO implement me: get resources for the pod.
    return {}


def sanitize_label(label_key):
    return label_key.replace('.', '_').replace('-', '_')


if __name__ == "__main__":
    node = KubernetesNode(client_private_key="/home/vagrant/apiserver-kubelet.client.key",
                          client_cert="/home/vagrant/apiserver-kubelet-client.crt")
    pprint.PrettyPrinter(indent=4).pprint(node.get_tasks())
