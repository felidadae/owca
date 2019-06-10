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

from wca.allocators import AllocationConfiguration
from wca.cgroups_allocations import QuotaAllocationValue, SharesAllocationValue, \
                                    CPUSetAllocationValue
from wca.containers import Container
from wca.platforms import RDTInformation
from tests.testing import allocation_metric


@patch('wca.perf.PerfCounters')
@patch('wca.cgroups.Cgroup')
def test_cgroup_allocations(Cgroup_mock, PerfCounters_mock):
    rdt_information = RDTInformation(True, True, True, True, '0', '0', 0, 0, 0)
    foo_container = Container(
            '/somepath', platform_cpus=10,
            platform_sockets=1, rdt_information=rdt_information)
    foo_container._cgroup.allocation_configuration = AllocationConfiguration()
    foo_container._cgroup.platform_cpus = 10
    foo_container._cgroup.platform_sockets = 1

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

    cpuset_allocation_value = CPUSetAllocationValue('0-2,4,6-8', foo_container, dict(foo='bar'))
    cpuset_allocation_value.perform_allocations()

    assert cpuset_allocation_value.generate_metrics() == [
        allocation_metric('cpuset', [0, 1, 2, 4, 6, 7, 8], foo='bar')
    ]

    Cgroup_mock.assert_has_calls([
        call().set_quota(0.2),
        call().set_shares(0.5),
        call().set_cpuset('0,1,2,4,6,7,8', '0')
    ], True)
