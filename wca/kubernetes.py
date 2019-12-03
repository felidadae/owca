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

import logging
import pathlib
from typing import Dict, List, Optional, Union
from urllib.parse import urljoin

import os
import requests
from dataclasses import dataclass, field
from enum import Enum

from wca import logger
from wca.cgroups import CgroupSubsystem
from wca.config import assure_type, Numeric, Url, Str, Path
from wca.logger import TRACE
from wca.nodes import Node, Task, TaskId, TaskSynchronizationException
from wca.resources import calculate_pod_resources
from wca.security import SSL, HTTPSAdapter

log = logging.getLogger(__name__)

SERVICE_TOKEN_FILENAME = "/var/run/secrets/kubernetes.io/serviceaccount/token"  # nosec
SERVICE_CERT_FILENAME = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"  # nosec


@dataclass
class KubernetesTask(Task):
    qos: str

    def __post_init__(self):
        assure_type(self.name, str)
        assure_type(self.task_id, TaskId)
        assure_type(self.cgroup_path, str)
        assure_type(self.subcgroups_paths, List[str])
        assure_type(self.labels, Dict[str, str])
        assure_type(self.resources, Dict[str, Union[float, int, str]])
        assure_type(self.qos, str)

    def __hash__(self):
        return super().__hash__()

    def get_summary(self) -> str:
        """Short representation of task. Used for logging."""
        return "({} {} -> {})".format(self.name,
                                      self.task_id,
                                      self.subcgroups_paths)


class CgroupDriverType(str, Enum):
    SYSTEMD = 'systemd'
    CGROUPFS = 'cgroupfs'


# Special label used
QOS_LABELNAME = 'app_kubernetes_io__qos_class'


class QosClass(str, Enum):
    BESTEFFORT = 'besteffort'
    BURSTABLE = 'burstable'
    GUARANTEED = 'guaranteed'

    @classmethod
    def has_value(cls, value):
        return any(value == item.value for item in cls)


@dataclass
class KubernetesNode(Node):
    # We need to know what cgroup driver is used to properly build cgroup paths for pods.
    #   Reference in source code for kubernetes version stable 1.13:
    #   https://github.com/kubernetes/kubernetes/blob/v1.13.3/pkg/kubelet/cm/cgroup_manager_linux.go#L207
    cgroup_driver: CgroupDriverType = field(
        default_factory=lambda: CgroupDriverType(CgroupDriverType.CGROUPFS))

    ssl: Optional[SSL] = None

    # Default path is using by pods. You can override it to use wca outside pod.
    client_token_path: Optional[Path(absolute=True, mode=os.R_OK)] = SERVICE_TOKEN_FILENAME
    server_cert_ca_path: Optional[Path(absolute=True, mode=os.R_OK)] = SERVICE_CERT_FILENAME

    # By default use localhost, however kubelet may not listen on it.
    kubelet_enabled: bool = False
    kubelet_endpoint: Url = 'https://127.0.0.1:10250'

    kubeapi_host: Str = None
    kubeapi_port: Str = None  # Because !Env is String and another type cast might be problematic
    node_ip: Str = None

    # Timeout to access kubernetes agent.
    timeout: Numeric(1, 60) = 5  # [s]

    # List of namespaces to monitor pods in.
    monitored_namespaces: List[Str] = field(default_factory=lambda: ["default"])

    def _request_kubeapi(self):
        kubeapi_endpoint = "https://{}:{}".format(self.kubeapi_host, self.kubeapi_port)
        log.debug("Created kubeapi endpoint %s", kubeapi_endpoint)

        with pathlib.Path(self.client_token_path).open() as f:
            service_token = f.read()

        pod_list_from_all_namespaces = []
        for namespace in self.monitored_namespaces:
            full_url = urljoin(kubeapi_endpoint, "/api/v1/namespaces/{}/pods".format(namespace))

            r = requests.get(
                full_url,
                headers={
                    "Authorization": "Bearer {}".format(service_token)
                },
                timeout=self.timeout,
                verify=self.server_cert_ca_path
            )

            if not r.ok:
                log.error('An unexpected error occurred for namespace "%s": %i %s - %s',
                          namespace, r.status_code, r.reason, r.raw)
            r.raise_for_status()

            pod_list_from_namespace = r.json().get('items')
            pod_list_from_all_namespaces.extend(pod_list_from_namespace)

        return pod_list_from_all_namespaces

    def _request_kubelet(self):
        PODS_PATH = '/pods'
        full_url = urljoin(self.kubelet_endpoint, PODS_PATH)

        if self.ssl:
            s = requests.Session()
            s.mount(self.kubelet_endpoint, HTTPSAdapter())
            r = s.get(
                full_url,
                json=dict(type='GET_STATE'),
                timeout=self.timeout,
                verify=self.ssl.server_verify,
                cert=self.ssl.get_client_certs())
        else:
            r = requests.get(
                full_url,
                json=dict(type='GET_STATE'),
                timeout=self.timeout)

        if not r.ok:
            log.error('%i %s - %s', r.status_code, r.reason, r.raw)
        r.raise_for_status()

        return r.json().get('items')

    def get_tasks(self) -> List[Task]:
        """Returns only running tasks."""
        try:
            if self.kubelet_enabled:
                podlist_json_response = self._request_kubelet()
            else:
                podlist_json_response = self._request_kubeapi()
                if self.node_ip is None:
                    raise ValueError("node_ip is not set in config")
        except requests.exceptions.ConnectionError as e:
            raise TaskSynchronizationException('connection error: %s' % e) from e
        except requests.exceptions.ReadTimeout as e:
            raise TaskSynchronizationException('timeout: %s' % e) from e

        tasks = []
        for pod in podlist_json_response:
            container_statuses = pod.get('status').get('containerStatuses')

            # Kubeapi returns all pods in cluster
            if not self.kubelet_enabled and pod["status"]["hostIP"] != self.node_ip.strip():
                continue

            # Kubelet return all pods on the node. Ignore pods in not monitored namespaces.
            if self.kubelet_enabled and \
                    pod.get('metadata').get('namespace') not in self.monitored_namespaces:
                continue

            # Lacking needed information.
            if not container_statuses:
                continue

            # Read into variables essential information about pod.
            pod_id = pod.get('metadata').get('uid')
            pod_name = pod.get('metadata').get('name')
            qos = pod.get('status').get('qosClass').lower()
            task_name = pod.get('metadata').get('namespace') + "/" + pod_name
            assert QosClass.has_value(qos)
            if pod.get('metadata').get('labels'):
                labels = {_sanitize_label(key): value
                          for key, value in
                          pod.get('metadata').get('labels').items()}
            else:
                labels = {}
            labels[_sanitize_label(QOS_LABELNAME)] = qos  # Add label with QOS class of the pod.

            # Apart from obvious part of the loop it checks whether all
            # containers are in ready state -
            # if at least one is not ready then skip this pod.
            containers_cgroups = []
            are_all_containers_ready = True
            for container in container_statuses:
                if not container.get('ready'):
                    are_all_containers_ready = False
                    container_state = list(container.get('state').keys())[0]
                    log.debug('Ignore pod with uid={} name={}. Container {} is in state={} .'
                              .format(pod_id, pod_name, container.get('name'), container_state))
                    break

                container_id = container.get('containerID').split('docker://')[1]
                containers_cgroups.append(
                    _build_cgroup_path(self.cgroup_driver, qos,
                                       pod_id, container_id))
            if not are_all_containers_ready:
                continue

            log.debug('Pod with uid={} name={} is ready and monitored by the system.'
                      .format(pod_id, pod_name))

            container_spec = pod.get('spec').get('containers')
            tasks.append(KubernetesTask(
                name=task_name, task_id=pod_id, qos=qos, labels=labels,
                resources=calculate_pod_resources(container_spec),
                cgroup_path=_build_cgroup_path(self.cgroup_driver, qos, pod_id),
                subcgroups_paths=containers_cgroups))

        _log_found_tasks(tasks)

        return tasks


class MissingCgroupException(Exception):
    pass


def _build_cgroup_path(cgroup_driver, qos: str, pod_id: str, container_id=''):
    """If cgroup for pod needed set container_id to empty string."""
    result: str = ""
    if cgroup_driver == CgroupDriverType.SYSTEMD:
        pod_id = pod_id.replace("-", "_")
        if container_id != "":
            container_id = "docker-" + container_id + ".scope"
        result = os.path.join('/kubepods.slice',
                              'kubepods-{}.slice'.format(qos),
                              'kubepods-{}-pod{}.slice'.format(qos, pod_id),
                              container_id, "")

    elif cgroup_driver == CgroupDriverType.CGROUPFS:
        # Pod cgroup is same as pod_id.
        # StaticPod cgroup is hash (metadata.annotations.kubernetes.io/config.hash)
        # same as pod_id but without `-` characters.

        pod_path = os.path.join('/kubepods',
                                '' if qos == 'guaranteed' else qos,
                                'pod{}'.format(pod_id))

        cutted_pod_path = os.path.join('/kubepods',
                                       '' if qos == 'guaranteed' else qos,
                                       'pod{}'.format(pod_id.replace('-', '')))

        log.log(TRACE, 'pod_id=%s container_id=%s cgroup locations %r and %r',
                pod_id, container_id, pod_path, cutted_pod_path)
        if os.path.exists(CgroupSubsystem.CPU + pod_path):
            log.log(TRACE, 'pod_id=%s container_id=%s cgroup path=%r location',
                    pod_id, container_id, pod_path)
            result = os.path.join(pod_path, container_id, "")
        elif os.path.exists(CgroupSubsystem.CPU + cutted_pod_path):
            result = os.path.join(cutted_pod_path, container_id, "")
            log.log(TRACE, 'pod_id=%s container_id=%s cgroup path=%r location',
                    pod_id, container_id, cutted_pod_path)
        else:
            raise MissingCgroupException(
                'There is no pod cgroup matching pod_id: {} !'.format(pod_id))

    # Remove last slash from path.
    if len(result) > 1 and result[-1] == '/':
        result = result[:-1]
    return result


def _sanitize_label(label_key):
    return label_key.replace('.', '_').replace('-', '_').replace('/', '__')


def _log_found_tasks(tasks):
    log.debug("Found %d kubernetes tasks (cumulatively %d cgroups leafs).",
              len(tasks), sum([len(task.subcgroups_paths) for task in tasks]))
    log.log(logger.TRACE, "Found kubernetes tasks with (name, task_id, subcgroups_paths): %s.",
            ", ".join([task.get_summary() for task in tasks]))


def have_tasks_qos_label(tasks: List[Task]):
    return all([QOS_LABELNAME in task.labels for task in tasks])


def are_all_tasks_of_single_qos(tasks: List[Task]):
    """Public method to be used outside of this module
       to check whether all tasks are of the same
       QOS class."""
    return len({task.labels[QOS_LABELNAME] for task in tasks}) <= 1
