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

from unittest.mock import patch, call

from owca.allocators import AllocationConfiguration
from owca.cgroups_allocations import QuotaAllocationValue, SharesAllocationValue
from owca.containers import Container
from owca.testing import allocation_metric


@patch('owca.containers.PerfCounters')
@patch('owca.containers.Cgroup')
def test_cgroup_allocations(Cgroup_mock, PerfCounters_mock):
    foo_container = Container('/somepath', platform_cpus=1)
    foo_container.cgroup.allocation_configuration = AllocationConfiguration()

    quota_allocation_value = QuotaAllocationValue(0.2, foo_container, dict(foo='bar'))
    quota_allocation_value.perform_allocations()
    assert quota_allocation_value.generate_metrics() == [
        allocation_metric('cpu_quota', 0.2, foo='bar')
    ]

    shares_allocation_value = SharesAllocationValue(0.5, foo_container, dict(foo='bar'))
    shares_allocation_value.perform_allocations()

    assert shares_allocation_value.generate_metrics() == [
        allocation_metric('cpu_shares', 0.5, foo='bar')
    ]

    Cgroup_mock.assert_has_calls([
        call().set_quota(0.2),
        call().set_shares(0.5)
    ])
