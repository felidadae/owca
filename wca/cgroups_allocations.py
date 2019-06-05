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

from typing import Dict, Tuple, Optional, List

from wca.allocations import AllocationValue, BoxedNumeric, InvalidAllocations, LabelsUpdater
from wca.allocators import AllocationType
from wca.containers import ContainerInterface
from wca.cgroups import QUOTA_NORMALIZED_MAX
from wca.metrics import Metric, MetricType


class QuotaAllocationValue(BoxedNumeric):

    def __init__(self, normalized_quota: float, container: ContainerInterface, common_labels: dict):
        self.normalized_quota = normalized_quota
        self.cgroup = container.get_cgroup()
        self.subcgroups = container.get_subcgroups()
        super().__init__(value=normalized_quota, common_labels=common_labels,
                         min_value=0, max_value=1.0)

    def generate_metrics(self):
        metrics = super().generate_metrics()
        for metric in metrics:
            metric.labels.update(allocation_type=AllocationType.QUOTA)
            metric.name = 'allocation_%s' % AllocationType.QUOTA.value
        return metrics

    def perform_allocations(self):
        self.cgroup.set_quota(self.value)
        for subcgroup in self.subcgroups:
            subcgroup.set_quota(QUOTA_NORMALIZED_MAX)


class SharesAllocationValue(BoxedNumeric):

    def __init__(self, normalized_shares: float, container: ContainerInterface,
                 common_labels: Dict[str, str]):
        self.normalized_shares = normalized_shares
        self.cgroup = container.get_cgroup()
        super().__init__(value=normalized_shares, common_labels=common_labels, min_value=0)

    def generate_metrics(self):
        metrics = super().generate_metrics()
        for metric in metrics:
            metric.labels.update(allocation_type=AllocationType.SHARES)
            metric.name = 'allocation_%s' % AllocationType.SHARES.value
        return metrics

    def perform_allocations(self):
        self.cgroup.set_shares(self.value)


class CPUSetAllocationValue(AllocationValue):

    def __init__(self, value: str, container: ContainerInterface, common_labels: dict):
        assert isinstance(value, str)
        self.cgroup = container.get_cgroup()
        self._original_value = value
        self.value = _parse_cpuset(value)
        self.common_labels = common_labels
        self.labels_updater = LabelsUpdater(common_labels or {})
        # First core
        self.min_value = 0
        # Last core
        self.max_value = self.cgroup.platform_cpus - 1

    def __repr__(self):
        return repr(self.value)

    def __eq__(self, other: 'CPUSetAllocationValue') -> bool:
        """Compare cpuset value to another value by taking value into consideration."""
        assert isinstance(other, CPUSetAllocationValue)
        return self.value == other.value

    def calculate_changeset(self, current: 'CPUSetAllocationValue') \
            -> Tuple['CPUSetAllocationValue', Optional['CPUSetAllocationValue']]:
        if current is None:
            # There is no old value, so there is a change
            value_changed = True
        else:
            # If we have old value compare them.
            assert isinstance(current, CPUSetAllocationValue)
            value_changed = (self != current)

        if value_changed:
            return self, self
        else:
            return current, None

    def generate_metrics(self) -> List[Metric]:
        assert isinstance(self.value, list)
        metrics = [Metric(
            name='allocation_cpuset',
            value=self.value,
            type=MetricType.GAUGE,
            labels=dict(allocation_type='cpuset')
        )]
        self.labels_updater.update_labels(metrics)
        return metrics

    def validate(self):
        if len(self.value) > 0:
            if self.value[0] < self.min_value or self.value[-1] > self.max_value:
                raise InvalidAllocations(
                        '{} not in range <{};{}>'
                        .format(self._original_value, self.min_value, self.max_value))
        else:
            raise InvalidAllocations(
                    '{} is invalid argument!'
                    .format(self._original_value))

    def perform_allocations(self):
        self.validate()
        normalized_cpus = _normalize_cpuset(self.value)
        normalized_mems = _normalize_cpuset(list(range(0, self.cgroup.platform_sockets)))
        self.cgroup.set_cpuset(normalized_cpus, normalized_mems)


def _parse_cpuset(value: str) -> List[int]:
    cores = set()

    if not value:
        return list()

    ranges = value.split(',')

    for r in ranges:
        boundaries = r.split('-')

        if len(boundaries) == 1:
            cores.add(int(boundaries[0]))
        elif len(boundaries) == 2:
            start = int(boundaries[0])
            end = int(boundaries[1])

            for i in range(start, end + 1):
                cores.add(i)

    return list(sorted(cores))


def _normalize_cpuset(cores: List[int]) -> str:
    all(isinstance(core, int) for core in cores)
    if len(cores) > 0:
        return str(cores[0])+''.join(','+str(core) for core in cores[1:])
    else:
        return ''
