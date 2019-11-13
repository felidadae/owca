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

import time
import subprocess  # nosec
import logging
from typing import Dict, Tuple, Optional, List

from wca.allocations import AllocationValue, BoxedNumeric, InvalidAllocations, LabelsUpdater
from wca.allocators import AllocationType
from wca.cgroups import QUOTA_NORMALIZED_MAX
from wca.containers import ContainerInterface
from wca.metrics import Metric, MetricType
from wca.platforms import decode_listformat
from wca.logger import TRACE

log = logging.getLogger(__name__)


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


class ListFormatBasedAllocationValue(AllocationValue):
    def __init__(self, value: str, container: ContainerInterface, common_labels: dict):
        assert isinstance(value, str)
        self.cgroup = container.get_cgroup()
        self.value = value
        self.common_labels = common_labels
        self.labels_updater = LabelsUpdater(common_labels or {})
        self.min_value = 0
        self.max_value = None  # TO BE UPDATED by subclass

    def __eq__(self, other) -> bool:
        """Compare listformat based value to another value by taking value into consideration."""
        assert isinstance(other, self.__class__)
        return decode_listformat(self.value) == decode_listformat(other.value)

    def calculate_changeset(self, current) \
            -> Tuple['ListFormatBasedAllocationValue', Optional['ListFormatBasedAllocationValue']]:
        if current is None:
            # There is no old value, so there is a change
            value_changed = True
        else:
            # If we have old value compare them.
            value_changed = (self != current)

        if value_changed:
            return self, self
        else:
            return current, None

    def validate(self):
        try:
            value = decode_listformat(self.value)
        except ValueError as e:
            raise InvalidAllocations('cannot decode list format %r: %s' % (self.value, e)) from e
        as_sorted_list = list(sorted(value))
        assert self.max_value is not None, 'should be initialized by subclass'
        if len(self.value) > 0:
            if as_sorted_list[0] < self.min_value or as_sorted_list[-1] > self.max_value:
                raise InvalidAllocations(
                    '{} not in range <{};{}>'.format(self.value, self.min_value,
                                                     self.max_value))
        else:
            raise InvalidAllocations(
                '{} is invalid argument! No data provided!'.format(self.value))


class CPUSetCPUSAllocationValue(ListFormatBasedAllocationValue):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_value = self.cgroup.platform.cpus - 1

    def generate_metrics(self) -> List[Metric]:
        cpus = decode_listformat(self.value)
        metrics = [Metric(
            name='allocation_cpuset_cpus_number_of_cpus',
            value=len(cpus),
            type=MetricType.GAUGE,
            labels=dict(allocation_type=AllocationType.CPUSET_CPUS)
        )]
        self.labels_updater.update_labels(metrics)
        return metrics

    def perform_allocations(self):
        cpus = decode_listformat(self.value)
        self.cgroup.set_cpuset_cpus(cpus)


class CPUSetMEMSAllocationValue(ListFormatBasedAllocationValue):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_value = len(self.cgroup.platform.node_cpus) - 1

    def generate_metrics(self) -> List[Metric]:
        mems = decode_listformat(self.value)
        metrics = [Metric(
            name='allocation_cpuset_mems_number_of_mems',
            value=len(mems),
            type=MetricType.GAUGE,
            labels=dict(allocation_type=AllocationType.CPUSET_MEMS)
        )]
        self.labels_updater.update_labels(metrics)
        return metrics

    def perform_allocations(self):
        self.cgroup.set_cpuset_mems(decode_listformat(self.value))


class CPUSetMemoryMigrateAllocationValue(BoxedNumeric):

    def __init__(self, value: bool, container: ContainerInterface, common_labels: Dict[str, str]):
        self.value = value
        self.cgroup = container.get_cgroup()
        super().__init__(value=value, common_labels=common_labels, min_value=0, max_value=1)

    def generate_metrics(self):
        metrics = super().generate_metrics()
        for metric in metrics:
            metric.labels.update(allocation_type=AllocationType.CPUSET_MEM_MIGRATE)
            metric.name = 'allocation_%s' % AllocationType.CPUSET_MEM_MIGRATE.value
        return metrics

    def perform_allocations(self):
        self.cgroup._set_memory_migrate(self.value)


class MigratePagesAllocationValue(BoxedNumeric):
    """Values represents."""

    def __init__(self, value: int, container: ContainerInterface, common_labels: Dict[str, str]):
        self.value = value
        self.container = container
        self.platform = self.container.get_cgroup().platform
        super().__init__(value=value, common_labels=common_labels,
                         min_value=0, max_value=self.platform.numa_nodes-1)

    def generate_metrics(self):
        metrics = super().generate_metrics()
        for metric in metrics:
            metric.labels.update(allocation_type=AllocationType.MIGRATE_PAGES)
            metric.name = 'allocation_%s' % AllocationType.MIGRATE_PAGES.value
        return metrics

    def perform_allocations(self):
        _migrate_pages(
            self.container.get_pids(include_threads=False),
            self.value,
            self.platform.numa_nodes,
        )


def _migrate_pages(task_pids, to_node, number_of_nodes):
    # if not all pages yet on place force them to move
    from_node = ','.join([str(i) for i in range(number_of_nodes) if i != to_node])
    to_node = str(to_node)
    for pid in task_pids:
        pid = str(pid)
        cmd = ['migratepages', pid, from_node, to_node]
        log.log(TRACE, 'migrate pages cmd: %s', ' '.join(cmd))
        try:
            start = time.time()
            subprocess.check_output(cmd)  # nosec - input is already validated
            duration = time.time() - start
            log.debug('Moving duration %0.2fs', duration)
        except subprocess.CalledProcessError as e:
            log.warn('cannot migrate pages for pid=%s: %s (ignored)', pid, e)
