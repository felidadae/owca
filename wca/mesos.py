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
import urllib.parse
from typing import List, Optional, Dict, Union

import requests
from dataclasses import dataclass

from wca.config import assure_type, Numeric, Url
from wca.metrics import Measurements, Metric
from wca.nodes import Node, Task, TaskId, TaskSynchronizationException
from wca.security import SSL

MESOS_TASK_STATE_RUNNING = 'TASK_RUNNING'
CGROUP_DEFAULT_SUBSYSTEM = 'cpu'

log = logging.getLogger(__name__)


class MesosCgroupNotFoundException(Exception):
    """Raised when cannot find cgroup mesos path"""
    pass


@dataclass
class MesosTask(Task):
    # Fields only used debugging purposes.
    executor_pid: int
    container_id: str  # Mesos containerizer identifier "ID used to uniquely identify a container"
    executor_id: str
    agent_id: str

    def __post_init__(self):
        assure_type(self.name, str)
        assure_type(self.task_id, TaskId)
        assure_type(self.cgroup_path, str)
        assure_type(self.subcgroups_paths, List[str])
        assure_type(self.labels, Dict[str, str])
        assure_type(self.resources, Dict[str, Union[float, int, str]])
        assure_type(self.executor_pid, int)
        assure_type(self.container_id, str)
        assure_type(self.executor_id, str)
        assure_type(self.agent_id, str)

    def __hash__(self):
        """Override __hash__ method from base class and call it explicitly to workaround
        __hash__ methods overriding by dataclasses (dataclass rules specify if eq is True and
        there is no explict __hash__ method - replace it with None dataclasses.py:739).
        """
        return super().__hash__()


def find_cgroup(pid):
    """ Returns cgroup_path relative to 'cpu' subsystem based on /proc/{pid}/cgroup
    with leading '/'"""
    fname = f'/proc/{pid}/cgroup'
    with open(fname) as f:
        lines = f.readlines()
        for line in lines:
            _, subsystems, path = line.strip().split(':')
            subsystems = subsystems.split(',')
            if CGROUP_DEFAULT_SUBSYSTEM in subsystems:
                if path == '/':
                    raise MesosCgroupNotFoundException(
                        'Mesos executor pid=%s found in root cgroup ("/") for %s subsystem in %r. '
                        'Possible explanation: '
                        ' cgroups/cpu isolator is missing, initialization races'
                        ' or unsupported Mesos software stack'
                        % (pid, CGROUP_DEFAULT_SUBSYSTEM, fname))
                return path

        raise MesosCgroupNotFoundException(
            '%r controller not found for pid=%r in %s' % (CGROUP_DEFAULT_SUBSYSTEM, pid, fname))


@dataclass
class MesosNode(Node):
    mesos_agent_endpoint: Url = 'https://127.0.0.1:5051'

    # Timeout to access mesos agent.
    timeout: Numeric(1, 60) = 5.  # [s]

    # https://github.com/kennethreitz/requests/blob/5c1f72e80a7d7ac129631ea5b0c34c7876bc6ed7/requests/api.py#L41
    ssl: Optional[SSL] = None

    METHOD = 'GET_STATE'
    api_path = '/api/v1'

    def get_tasks(self):
        """ only return running tasks """
        full_url = urllib.parse.urljoin(self.mesos_agent_endpoint, self.api_path)

        try:
            if self.ssl:
                r = requests.post(
                        full_url,
                        json=dict(type=self.METHOD),
                        timeout=self.timeout,
                        verify=self.ssl.server_verify,
                        cert=self.ssl.get_client_certs())
            else:
                r = requests.post(
                        full_url,
                        json=dict(type=self.METHOD),
                        timeout=self.timeout)
        except requests.exceptions.ConnectionError as e:
            raise TaskSynchronizationException('%s' % e) from e

        r.raise_for_status()
        state = r.json()

        tasks = []

        # Fast return path if there is no any launched tasks.
        if 'launched_tasks' not in state['get_state']['get_tasks']:
            return []

        for launched_task in state['get_state']['get_tasks']['launched_tasks']:
            if 'statuses' not in launched_task or not len(launched_task['statuses']):
                continue

            statuses = launched_task['statuses']
            last_status = statuses[-1]  # Assume the last on is the latest state # TODO: confirm
            if last_status['state'] != MESOS_TASK_STATE_RUNNING:
                continue

            if 'executor_pid' not in last_status['container_status']:
                log.warning("'executor_pid' not found in container status for task %s on agent %s",
                            last_status['task_id']['value'],
                            last_status['agent_id']['value'])
                continue

            executor_pid = last_status['container_status']['executor_pid']
            task_name = launched_task['name']

            try:
                cgroup_path = find_cgroup(executor_pid)
            except MesosCgroupNotFoundException as e:
                log.warning('Cannot determine proper cgroup for task=%r! '
                            'Ignoring this task. Reason: %s', task_name, e)
                continue

            labels = {sanitize_label(label['key']): label['value']
                      for label in launched_task['labels']['labels']}

            # Extract scalar resources.
            resources = dict()
            for resource in launched_task['resources']:
                if resource['type'] == 'SCALAR':
                    resources[resource['name']] = float(resource['scalar']['value'])

            tasks.append(
                MesosTask(
                    name=task_name,
                    executor_pid=executor_pid,
                    cgroup_path=cgroup_path,
                    subcgroups_paths=[],
                    container_id=last_status['container_status']['container_id']['value'],
                    task_id=last_status['task_id']['value'],
                    agent_id=last_status['agent_id']['value'],
                    executor_id=last_status['executor_id']['value'],
                    labels=labels,
                    resources=resources
                )
            )

        return tasks


def create_metrics(task_measurements: Measurements) -> List[Metric]:
    """Prepare a list of metrics for a mesos tasks based on provided measurements
    applying common_labels.
    :param task_measurements: use values of measurements to create metrics
    """
    metrics = []
    for metric_name, metric_value in task_measurements.items():
        metric = Metric.create_metric_with_metadata(name=metric_name, value=metric_value)
        metrics.append(metric)
    return metrics


MESOS_LABELS_PREFIXES_TO_DROP = ('org.apache.', 'aurora.metadata.')


def sanitize_label(label_key):
    """Removes unwanted prefixes from Aurora & Mesos e.g. 'org.apache.aurora'
    and replaces invalid characters like "." with underscore.
    """
    # Drop unwanted prefixes
    for unwanted_prefix in MESOS_LABELS_PREFIXES_TO_DROP:
        if label_key.startswith(unwanted_prefix):
            label_key = label_key.replace(unwanted_prefix, '')

    # Prometheus labels cannot contain ".".
    label_key = label_key.replace('.', '_')

    return label_key
