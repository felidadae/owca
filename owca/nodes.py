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


from abc import ABC, abstractproperty, abstractmethod
from typing import List, Dict

TaskId = str


class Task(ABC):
    """Class used for abstracting information received from orchestration node service concerning single container
    (e.g. mesos container) or a group of containers (a mesos nested container or a kubernetes pod)."""

    @abstractproperty
    def name(self) -> str:
        """Human-friendly name of task (usefull for logging and debugging)."""

    @abstractproperty
    def task_id(self) -> TaskId:
        """Orchestration-level task identifier."""

    @abstractproperty
    def cgroup_path(self) -> str:
        """Path to root cgroup that all processes reside.
           Starts with leading "/".
           e.g. /kubepods/bestefforts/9012839."""

    @abstractproperty
    def subcgroups_paths(self) -> List[str]:
        """List of paths to subcgroups (if no subcgroups exist returns empty list)."""

    @abstractproperty
    def labels(self) -> Dict[str, str]:
        """Task metadata expressed as labels."""

    @abstractproperty
    def resources(self) -> Dict[str, float]:
        """Initial resources assigned to the task. """


class Node(ABC):
    """Base class for tasks(workloads discover)."""

    @abstractmethod
    def get_tasks(self) -> List[Task]:
        ...
