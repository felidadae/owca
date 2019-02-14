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

import pytest

from owca.allocations import BoxedNumeric, InvalidAllocations


############################################################################
# BoxedNumericTests
############################################################################
class BoxedNumericDummy(BoxedNumeric):
    def perform_allocations(self):
        pass


@pytest.mark.parametrize(
    'value, min_value, max_value, value_change_sensitivity', (
            (2.5, 2, 3, 0.00001),
            (3, 2.5, 3.0, 0.00001),
            (2.0, 2, 3.0, 0.00001),
            (2.0, None, 3.0, 0.00001),
            (2.0, 1, None, 0.00001),
    )
)
def test_boxed_numeric_validation(value, min_value, max_value, value_change_sensitivity):
    boxed_value = BoxedNumericDummy(value, min_value=min_value,
                                    max_value=max_value,
                                    value_change_sensitivity=value_change_sensitivity)
    boxed_value.validate()


@pytest.mark.parametrize(
    'value, min_value, max_value, value_change_sensitivity, expected_error', (
            (1, 2, 3, 0.00001, '1 does not belong to range'),
            (1.1, 2, 3, 0.00001, 'does not belong to range'),
    )
)
def test_boxed_numeric_validation_invalid(value, min_value, max_value, value_change_sensitivity,
                                          expected_error):
    boxed_value = BoxedNumericDummy(value, min_value=min_value,
                                    max_value=max_value,
                                    value_change_sensitivity=value_change_sensitivity)
    with pytest.raises(InvalidAllocations, match=expected_error):
        boxed_value.validate()


@pytest.mark.parametrize(
    'current, new, expected_target, expected_changeset', (
            (10, 10.01,
             10, None),
            (10, 10.99,
             10.99, 10.99),
    )
)
def test_boxed_numeric_calculated_changeset(current, new, expected_target, expected_changeset):
    expected_changeset = BoxedNumericDummy(expected_changeset) \
        if expected_changeset is not None else None
    expected_target = BoxedNumericDummy(expected_target)

    got_target, got_changeset = BoxedNumericDummy(new).calculate_changeset(
        BoxedNumericDummy(current))

    assert got_target == expected_target
    assert got_changeset == expected_changeset


@pytest.mark.parametrize(
    'left, right, is_equal', (
            (BoxedNumericDummy(10), BoxedNumericDummy(10), True),
            (BoxedNumericDummy(10), BoxedNumericDummy(11), False),
            (BoxedNumericDummy(10), BoxedNumericDummy(10.01), True),
            (BoxedNumericDummy(10), BoxedNumericDummy(10.11), False),
            (BoxedNumericDummy(10.99), BoxedNumericDummy(10.99), True),
    )
)
def test_boxed_numeric_equal(left, right, is_equal):
    assert (left == right) == is_equal
