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

import pytest

from owca.allocators import _calculate_task_allocations, _calculate_tasks_allocations, \
    RDTAllocation, AllocationType

r = AllocationType.RDT


@pytest.mark.parametrize(
    'old_task_allocations,new_task_allocations,'
    'expected_all_task_allocations,expected_resulting_task_allocations', (
        ({}, {},
         {}, {}),
        ({'a': 0.2}, {},
         {'a': 0.2}, {}),
        ({'b': 2}, {'b': 3},
         {'b': 3}, {'b': 3}),
        ({'a': 0.2, 'b': 0.4}, {'b': 0.5},
         {'a': 0.2, 'b': 0.5}, {'b': 0.5}),
        ({}, {'a': 0.2, 'b': 0.5},
         {'a': 0.2, 'b': 0.5}, {'a': 0.2, 'b': 0.5}),
        # RDTAllocations
        ({}, {r: RDTAllocation(name='', l3='ff')},
         {r: RDTAllocation(name='', l3='ff')}, {r: RDTAllocation(name='', l3='ff')}),
        ({r: RDTAllocation(name='', l3='ff')}, {},
         {r: RDTAllocation(name='', l3='ff')}, {}),
        ({r: RDTAllocation(name='', l3='ff')}, {r: RDTAllocation(name='x', l3='ff')},
         {r: RDTAllocation(name='x', l3='ff')}, {r: RDTAllocation(name='x', l3='ff')}),
        ({r: RDTAllocation(name='x', l3='ff')}, {r: RDTAllocation(name='x', l3='dd')},
         {r: RDTAllocation(name='x', l3='dd')}, {r: RDTAllocation(name='x', l3='dd')}),
        ({r: RDTAllocation(name='x', l3='dd', mb='ff')}, {r: RDTAllocation(name='x', mb='ff')},
         {r: RDTAllocation(name='x', l3='dd', mb='ff')}, {r: RDTAllocation(name='x', mb='ff')}),
    ))
def test_calculate_task_allocations(
        old_task_allocations, new_task_allocations,
        expected_all_task_allocations, expected_resulting_task_allocations):
    all_task_allocations, resulting_task_allocations = _calculate_task_allocations(
        old_task_allocations, new_task_allocations
    )
    assert all_task_allocations == expected_all_task_allocations
    assert resulting_task_allocations == expected_resulting_task_allocations


@pytest.mark.parametrize(
    'old_tasks_allocations,new_tasks_allocations,'
    'expected_all_tasks_allocations,expected_resulting_tasks_allocations', (
        ({}, {},
         {}, {}),
        (dict(t1={'a': 2}), {},
         dict(t1={'a': 2}), {}),
        (dict(t1={'a': 1}), dict(t1={'b': 2}, t2={'b': 3}),
         dict(t1={'a': 1, 'b': 2}, t2={'b': 3}), dict(t1={'b': 2}, t2={'b': 3})),
    ))
def test_calculate_tasks_allocations(
        old_tasks_allocations, new_tasks_allocations,
        expected_all_tasks_allocations, expected_resulting_tasks_allocations
):
    all_tasks_allocations, resulting_tasks_allocations = _calculate_tasks_allocations(
        old_tasks_allocations, new_tasks_allocations
    )
    assert all_tasks_allocations == expected_all_tasks_allocations
    assert resulting_tasks_allocations == expected_resulting_tasks_allocations
