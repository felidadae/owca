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

from owca.allocations import BoxedNumeric


############################################################################
# BoxedNumericTests
############################################################################

@pytest.mark.parametrize(
    'value, min_value, max_value, float_value_change_sensitivity, expected_errors', (
            (1, 2, 3, 0.00001, ['1 does not belong to range <2;3>']),
            (1.1, 2, 3, 0.00001, ['1.1 does not belong to range <2;3>']),
            (2.5, 2, 3, 0.00001, []),
            (3, 2.5, 3.0, 0.00001, []),
            (2.0, 2, 3.0, 0.00001, []),
            (2.0, None, 3.0, 0.00001, []),
            (2.0, 1, None, 0.00001, []),
    )
)
def test_boxed_numeric_validation(value, min_value, max_value, float_value_change_sensitivity,
                                  expected_errors):
    boxed_value = BoxedNumeric(value, min_value, max_value, float_value_change_sensitivity)
    expected_new_value = None if expected_errors else boxed_value
    got_errors, got_new_value = boxed_value.validate()
    assert got_errors == expected_errors
    assert got_new_value == expected_new_value


@pytest.mark.parametrize(
    'current, new, expected_target, expected_changeset', (
            (10, 10.1, 10, None),
            (10, 10.99, 10.99, 10.99),
    )
)
def test_boxed_numeric_calculated_changeset(current, new, expected_target, expected_changeset):
    # convert to values
    expected_changeset = BoxedNumeric(expected_changeset) \
        if expected_changeset is not None else None
    expected_target = BoxedNumeric(expected_target)

    got_target, got_changeset, errors = BoxedNumeric(new).calculate_changeset(BoxedNumeric(current))

    # compare
    assert not errors
    assert got_target == expected_target
    assert got_changeset == expected_changeset


@pytest.mark.parametrize(
    'left, right, is_equal', (
            (BoxedNumeric(10), BoxedNumeric(10), True),
            (BoxedNumeric(10), BoxedNumeric(11), False),
            (BoxedNumeric(10), BoxedNumeric(10.1), True),
            (BoxedNumeric(10), BoxedNumeric(10.11), False),
            (BoxedNumeric(10.99), BoxedNumeric(10.99), True),
    )
)
def test_boxed_numeric_equal(left, right, is_equal):
    assert (left == right) == is_equal
