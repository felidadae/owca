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

import logging
from typing import List, Dict, Union, Optional

import os
from dataclasses import dataclass, field

from wca.config import Str, Path
from wca.nodes import Node, Task

log = logging.getLogger(__name__)


@dataclass
class StaticNode(Node):
    """rst
    Simple implementation of Node that returns tasks based on
    provided list on tasks names.

    Tasks are returned only if corresponding cgroups exists:

    - ``/sys/fs/cgroup/cpu/(task_name)``
    - ``/sys/fs/cgroup/cpuacct/(task_name)``
    - ``/sys/fs/cgroup/perf_event/(task_name)``

    Otherwise, the item is ignored.

    Arguments:

    - ``tasks``: **List[Str]**
    - ``require_pids``: **bool** = *False*
    - ``default_labels``: **Dict[Str, Str]** = *{}*
    - ``default_resources``: **Dict[Str, Union[Str, float, int]]** = *{}*
    - ``tasks_labels``: **Optional[Dict[str, Dict[str, str]]]** = *None*
    - ``directory``: **Optional[Path]** - automatic discovery extendes list of tasks

    If directory is specified we will try to automaticaly watch over all existing directories
    there.
    """

    # List of task names.
    tasks: List[Str]
    require_pids: bool = False
    default_labels: Dict[Str, Str] = field(default_factory=dict)
    default_resources: Dict[Str, Union[Str, float, int]] = field(default_factory=dict)
    tasks_labels: Optional[Dict[str, Dict[str, str]]] = None
    directory: Optional[Path] = None

    _BASE_CGROUP_PATH = '/sys/fs/cgroup'
    _REQUIRED_CONTROLLERS = ('cpu', 'cpuacct', 'memory')

    def __post_init__(self):
        log.info('Static task discovery on cgroups: %r', self.tasks)
        if self.directory is not None:
            log.info('Dynamic task discovery on cgroups in directoy: %r', self.directory)

    def get_tasks(self) -> List[Task]:
        task_names = list(self.tasks)
        if self.directory is not None:
            _base_path = os.path.join(
                self._BASE_CGROUP_PATH, self._REQUIRED_CONTROLLERS[0], self.directory)
            task_names.extend(
                map(
                    lambda entry: os.path.join(self.directory, entry),
                    filter(
                        lambda entry: os.path.isdir(os.path.join(_base_path, entry)),
                        os.listdir(_base_path))
                   )
            )
            log.debug('static_node: task_names=%r', task_names)

        tasks = []
        for task_name in task_names:
            for required_controller in self._REQUIRED_CONTROLLERS:
                full_cgroup_path = os.path.join(
                    self._BASE_CGROUP_PATH, required_controller, task_name, 'tasks')
                if not os.path.exists(full_cgroup_path):
                    log.warning('StaticNode: There is no required cgroup %r for %r - skipping!',
                                full_cgroup_path, task_name)
                    break
                if self.require_pids and len(open(full_cgroup_path).readlines()) == 0:
                    log.warning('StaticNode: There is no pids in cgroup %r for %r - skipping!',
                                full_cgroup_path, task_name)
                    break
            else:
                labels = dict(self.default_labels)
                if self.tasks_labels:
                    labels.update(self.tasks_labels.get(task_name))
                tasks.append(
                    Task(
                        name=task_name,
                        task_id=task_name,
                        cgroup_path='/%s' % task_name,
                        labels=labels,
                        resources=dict(self.default_resources),
                        subcgroups_paths=[]
                    )
                )
        return tasks
