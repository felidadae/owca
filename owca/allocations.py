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
import logging
import math
from abc import ABC, abstractmethod
from typing import List, Union, Tuple, Optional, Dict

from owca.metrics import Metric, MetricType

log = logging.getLogger(__name__)


class InvalidAllocations(Exception):
    pass


class AllocationValue(ABC):

    @abstractmethod
    def calculate_changeset(self, current: 'AllocationValue') \
            -> Tuple['AllocationValue', Optional['AllocationValue']]:
        """Calculate difference between current value and self(new) value and
        return merged state (sum) as *target* and difference as *changeset*
        :returns target, changeset
        """

    @abstractmethod
    def generate_metrics(self) -> List[Metric]:
        """Generate metrics that encode information about
        allocations performed by this allocation value."""

    @abstractmethod
    def validate(self):
        """Raises InvalidAllocation exception if some values are incorrect."""

    @abstractmethod
    def perform_allocations(self):
        """Perform allocations. Returns nothing."""


class AllocationsDict(dict, AllocationValue):
    """Base class for dict based Tasks and Task Allocations plain classes to
    extend them with necessary business logic for:
    - calculating changeset for comparing dict like containers
    - recursive validation of all values of dict
    - collection of metrics of all values
    - and recursive perform allocations
    """

    def calculate_changeset(self, current: 'AllocationsDict') \
            -> Tuple['AllocationsDict', Optional['AllocationsDict']]:
        assert isinstance(current, AllocationsDict)

        # Create an shallow copy of current object that will represent 'sum'.
        target = AllocationsDict(current)
        # Empty object to represnt nessesary changes to apply.
        changeset = AllocationsDict({})

        for key, new_value in self.items():

            assert isinstance(new_value, AllocationValue)

            current_value = current.get(key)

            if current_value is None:
                # There is no current value, new is used as both target and changeset.
                target[key] = new_value
                changeset[key] = new_value
            else:
                # Both exists - recurse into values.
                assert isinstance(current_value, AllocationValue)
                target_value, value_changeset = new_value.calculate_changeset(current_value)
                assert isinstance(target_value, AllocationValue)
                assert isinstance(value_changeset, (type(None), AllocationValue))
                target[key] = target_value
                if value_changeset is not None:
                    changeset[key] = value_changeset

        # If there are no fields in changeset dict return None
        # to indicate no changes are required at all.
        if not changeset:
            changeset = None

        return target, changeset

    def generate_metrics(self) -> List[Metric]:
        metrics = []
        for value in self.values():
            metrics.extend(value.generate_metrics())
        return metrics

    def perform_allocations(self):
        for value in self.values():
            value.perform_allocations()

    def validate(self):
        for value in self.values():
            value.validate()


class LabelsUpdater:
    """Helper object to update metrics."""

    def __init__(self, common_labels):
        self.common_labels = common_labels

    def update_labels(self, metrics):
        """Update labels values inplace."""
        for metric in metrics:
            metric.labels.update(**self.common_labels)


class BoxedNumeric(AllocationValue):
    """ AllocationValue for numeric values (floats and ints).
    Wrapper for floats and integers.
    If min_value is None then it becomes negative infinity (default is 0).
    If max_value is None then it becomes infinity (default is None(infinity).
    """
    # Defines precision of number comparison. See: math.isclose()
    VALUE_CHANGE_SENSITIVITY = 0.05

    def __init__(self, value: Union[float, int],
                 common_labels: Dict[str, str] = None,
                 min_value: Optional[Union[int, float]] = 0,
                 max_value: Optional[Union[int, float]] = None,
                 value_change_sensitivity: float = VALUE_CHANGE_SENSITIVITY,
                 ):
        assert isinstance(value, (float, int))
        self.value = value
        self.value_change_sensitivity = value_change_sensitivity
        self.min_value = min_value if min_value is not None else -math.inf
        self.max_value = max_value if max_value is not None else math.inf
        self.labels_updater = LabelsUpdater(common_labels or {})

    def __repr__(self):
        return repr(self.value)

    def __eq__(self, other: 'BoxedNumeric') -> bool:
        """Compare numeric value to another value taking value_change_sensitivity into
        consideration."""
        assert isinstance(other, BoxedNumeric)
        return math.isclose(self.value, other.value,
                            abs_tol=self.value_change_sensitivity)

    def generate_metrics(self) -> List[Metric]:
        """Encode numeric based allocation."""

        assert isinstance(self.value, (float, int))
        metrics = [Metric(
            name='allocation_numeric',
            value=self.value,
            type=MetricType.GAUGE,
            labels=dict(allocation_type='numeric')
        )]
        self.labels_updater.update_labels(metrics)
        return metrics

    def validate(self):
        if self.value < self.min_value or self.value > self.max_value:
            raise InvalidAllocations('%s does not belong to range <%s;%s>' % (
                self.value, self.min_value, self.max_value))

    def calculate_changeset(self, current: 'BoxedNumeric') \
            -> Tuple['BoxedNumeric', Optional['BoxedNumeric']]:
        if current is None:
            # There is no old value, so there is a change
            value_changed = True
        else:
            # If we have old value compare them.
            assert isinstance(current, BoxedNumeric)

            value_changed = (self != current)

        if value_changed:
            # If value is changed then self becomes target state
            # and changeset.
            return self, self
        else:
            # If value is not changed, then value is the same as
            # new so we can return any of them (lets return the new one) as target
            return current, None
