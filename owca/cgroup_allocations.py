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
from owca.allocations import BoxedNumeric
from owca.allocators import AllocationType
from owca.containers import ContainerInterface


class QuotaAllocationValue(BoxedNumeric):

    def __init__(self, normalized_quota: float, container: ContainerInterface, common_labels: dict):
        self.normalized_quota = normalized_quota
        self.cgroup = container.get_cgroup()
        super().__init__(value=normalized_quota, common_labels=common_labels,
                         min_value=0, max_value=1.0)

    def generate_metrics(self):
        metrics = super().generate_metrics()
        for metric in metrics:
            metric.labels.update(allocation_type=AllocationType.QUOTA)
        return metrics

    def perform_allocations(self):
        self.cgroup.set_normalized_quota(self.value)


class SharesAllocationValue(BoxedNumeric):

    def __init__(self, normalized_shares: float, container: ContainerInterface, common_labels: dict):
        self.normalized_shares = normalized_shares
        self.cgroup = container.get_cgroup()
        super().__init__(value=normalized_shares, common_labels=common_labels, min_value=0)

    def generate_metrics(self):
        metrics = super().generate_metrics()
        for metric in metrics:
            metric.labels.update(allocation_type=AllocationType.SHARES)
        return metrics

    def perform_allocations(self):
        self.cgroup.set_normalized_shares(self.value)
