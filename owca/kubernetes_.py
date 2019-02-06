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
import os
import kubernetes
import logging

from owca import logger
from owca.metrics import MetricName
from owca.nodes import Node
from owca.perf import PerfCounters

DEFAULT_EVENTS = (MetricName.INSTRUCTIONS, MetricName.CYCLES, MetricName.CACHE_MISSES)

log = logging.getLogger(__name__)


@dataclass
class KubernetesTask:
    name: str
    container_id: str
    pod_id: str
    qos: str  # Quality of Service
    # subcgroups: List[str] = None

    # inferred
    cgroup_path: str  # Starts with leading "/"
    task_id: str  # compability with MesosTask
    labels: Dict[str, str] = field(default_factory=dict)
    resources: Dict[str, float] = field(default_factory=dict)

    def __str__(self):
        descr = "KubernetesTask: {}\n".format(self.name)
        descr += "\tcontainer_id: {}\n".format(self.container_id)
        descr += "\tpod_id: {}\n".format(self.pod_id)
        descr += "\tqos: {}\n".format(self.qos)
        descr += "\tcgroup_path: {}\n".format(self.cgroup_path)
        return descr

    def __hash__(self):
        """Every instance of mesos task is uniqully identified by cgroup_path.
        Assumption here is that every mesos task is represented by one main cgroup.
        """
        return id(self.name)


@dataclass
class KubernetesPod:
    name: str
    containers: Dict[str, str]  # key: container_id, value: cgroup
    pod_id: str
    qos: str  # Quality of Service
    TASKS = 'tasks'

    def __post_init__(self):
        self.perf_counters = []
        for container_id, cgroup in self.containers.items():
            self.perf_counters.append(PerfCounters(cgroup, event_names=DEFAULT_EVENTS))

    def get_pids(self):
        all_pids = []
        for container_id, cgroup in self.containers.items():
            with open(os.path.join(cgroup, self.TASKS)) as f:
                pids = f.read().splitlines()
            all_pids.extend(pids)
        return all_pids

    def __str__(self):
        descr = "KubernetesPod: {}\n".format(self.name)
        descr += "\tpod_id: {}\n".format(self.pod_id)
        descr += "\tqos: {}\n".format(self.qos)
        return descr

    def get_measurements(self):
        measurements = dict()
        for perf_counter in self.perf_counters:
            for metric_name, metric_value in \
                    perf_counter.get_measurements().items():
                if metric_name in measurements:
                    measurements[metric_name] += metric_value
                else:
                    measurements[metric_name] = metric_value

        return measurements


@dataclass
class KubernetesNode(Node):
    def get_tasks(self):
        """ only return running tasks"""
        kubernetes.config.load_kube_config()
        v1 = kubernetes.client.CoreV1Api()
        pods = v1.list_pod_for_all_namespaces(watch=False)

        tasks = []

        for pod in pods.items:
            containers = dict()
            for container in pod.status.container_statuses:
                if container.state.running:
                    container_name = container.name

                    # @TODO temporary solution to cgroups bug
                    if "stressng" not in container_name:
                        continue

                    container_id = container.container_id.split('docker://')[1]
                    pod_id = pod.metadata.uid.replace('-', '_')
                    qos = pod.status.qos_class
                    containers[container_id] = find_cgroup(pod_id, container_id, qos)

                    labels = {sanitize_label(key): value for key, value in
                              pod.metadata.labels.items()}
                    tasks.append(
                        KubernetesTask(
                            name=container_name,
                            task_id=pod_id,
                            container_id=container_id,
                            pod_id=pod_id,
                            qos=qos.lower(),
                            labels=labels,
                            cgroup_path=find_cgroup(pod_id, container_id, qos)))
        log.debug("found %d tasks", len(tasks))
        log.log(logger.TRACE, "found %d kubernetes tasks with pod_id: %s",
                  len(tasks), ", ".join([str(task.pod_id) for task in tasks]))
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


def sanitize_label(label_key):
    # Prometheus labels cannot contain "." and "-".
    label_key = label_key.replace('.', '_')
    label_key = label_key.replace('-', '_')

    return label_key


if __name__ == "__main__":
    node = KubernetesNode()
    tasks = node.get_tasks()
    for task in tasks:
        print(task)
