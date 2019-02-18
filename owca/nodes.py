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


from abc import ABC, abstractmethod
from typing import List, Dict

from dataclasses import dataclass

TaskId = str


@dataclass
class Task:
    # Human-friendly name of task
    name: str

    # Orchestration-level task identifier
    task_id: TaskId

    # Path to cgroup that all processes reside in. Starts with leading "/".
    cgroup_path: str

    # Task metadata expressed as labels.
    labels: Dict[str, str]

    # Initial resources assigned at orchestration level.
    resources: Dict[str, str]

    def __hash__(self):
        """Every instance of task is uniquely identified by cgroup_path."""
        return hash(self.cgroup_path)


class Node(ABC):
    """Base class for tasks(workloads discover)."""

    @abstractmethod
    def get_tasks(self) -> List[Task]:
        ...
