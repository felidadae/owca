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

from owca.allocations import BoxedNumeric, InvalidAllocations


############################################################################
# BoxedNumericTests
############################################################################

@pytest.mark.parametrize(
    'value, min_value, max_value, float_value_change_sensitivity, expected_error', (
            (1, 2, 3, 0.00001, '1 does not belong to range'),
            (1.1, 2, 3, 0.00001, 'does not belong to range'),
            (2.5, 2, 3, 0.00001, None),
            (3, 2.5, 3.0, 0.00001, None),
            (2.0, 2, 3.0, 0.00001, None),
            (2.0, None, 3.0, 0.00001, None),
            (2.0, 1, None, 0.00001, None),
    )
)
def test_boxed_numeric_validation(value, min_value, max_value, float_value_change_sensitivity,
                                  expected_error):
    boxed_value = BoxedNumeric(value, min_value=min_value,
                               max_value=max_value,
                               float_value_change_sensitivity=float_value_change_sensitivity)
    if expected_error:
        with pytest.raises(InvalidAllocations, match=expected_error):
            boxed_value.validate()
    else:
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
    expected_changeset = BoxedNumeric(expected_changeset) \
        if expected_changeset is not None else None
    expected_target = BoxedNumeric(expected_target)

    got_target, got_changeset = BoxedNumeric(new).calculate_changeset(BoxedNumeric(current))

    assert got_target == expected_target
    assert got_changeset == expected_changeset


@pytest.mark.parametrize(
    'left, right, is_equal', (
            (BoxedNumeric(10), BoxedNumeric(10), True),
            (BoxedNumeric(10), BoxedNumeric(11), False),
            (BoxedNumeric(10), BoxedNumeric(10.01), True),
            (BoxedNumeric(10), BoxedNumeric(10.11), False),
            (BoxedNumeric(10.99), BoxedNumeric(10.99), True),
    )
)
def test_boxed_numeric_equal(left, right, is_equal):
    assert (left == right) == is_equal
