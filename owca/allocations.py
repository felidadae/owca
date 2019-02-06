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
import logging
import math
from abc import ABC, abstractmethod
from typing import List, Union, Tuple, Optional, Dict

from owca.logger import TRACE
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
        ...

    @abstractmethod
    def validate(self):
        """Raises an exception if some values are incorrect."""

    @abstractmethod
    def perform_allocations(self):
        """Perform allocations. Returns nothing."""


class AllocationsDict(dict, AllocationValue):
    """Base class for dict based Tasks and Task Allocations plain classes to
    extend them with necessary business logic like:
    - calculating change
    - validation
    - serialization to metrics
    - and recursive perform allocations
    """

    def calculate_changeset(self, current) \
            -> Tuple[AllocationValue, Optional[AllocationValue]]:
        assert isinstance(current, AllocationsDict), 'got %r(%s)' % (current, type(current))

        target = AllocationsDict(current)
        changeset = AllocationsDict({})

        for key, new_value in self.items():

            assert isinstance(new_value, AllocationValue)

            current_value = current.get(key)

            if current_value is None:
                # There is no current value, new is used
                target[key] = new_value
                changeset[key] = new_value

            else:
                assert isinstance(current_value, AllocationValue)
                # Both exists - recurse
                target_value, value_changeset = new_value.calculate_changeset(current_value)
                assert isinstance(target_value, AllocationValue)
                assert isinstance(value_changeset, (type(None), AllocationValue)), \
                    'expected AllocationValue got %r' % value_changeset
                target[key] = target_value
                if value_changeset is not None:
                    changeset[key] = value_changeset

        # Empty dict with no changes is like a None.
        if not changeset:
            changeset = None

        return target, changeset

    def generate_metrics(self):
        metrics = []
        for value in self.values():
            metrics.extend(value.generate_metrics())
        return metrics

    def perform_allocations(self):
        for value in self.values():
            value.perform_allocations()

    def validate(self):
        for _, value in self.items():
            value.validate()


class LabelsUpdater:
    """ Update any allocation values with common labels, when performing generate_metrics."""

    def __init__(self, common_labels):
        self.common_labels = common_labels

    def update_labels(self, metrics):
        for metric in metrics:
            metric.labels.update(**self.common_labels)
        return metrics


class BoxedNumeric(AllocationValue):
    """ Wraps floats and ints.

    Wrapper for floats and integers.
    If min_value is None then it becomes negative infinity.
    If max_value is Not then it becomes infinity.
    """
    # Defines default how sensitive in terms of
    # float precision are changes from RDTAllocation detected.
    FLOAT_VALUES_CHANGE_DETECTION = 0.05

    def __init__(self, value: Union[float, int],
                 common_labels: Dict[str, str] = None,
                 min_value: Optional[Union[int, float]] = 0,
                 max_value: Optional[Union[int, float]] = None,
                 float_value_change_sensitivity=FLOAT_VALUES_CHANGE_DETECTION,
                 ):
        assert isinstance(value, (float, int))
        self.value = value
        self.float_value_change_sensitivity = float_value_change_sensitivity
        self.min_value = min_value if min_value is not None else -math.inf
        self.max_value = max_value if max_value is not None else math.inf
        self.labels_updater = LabelsUpdater(common_labels or {})

    def __repr__(self):
        return repr(self.value)

    def __eq__(self, other: 'BoxedNumeric'):
        assert isinstance(other, BoxedNumeric), 'expected BoxedNumeric instance got %r(%s)' % (
            other, type(other))
        isclose = math.isclose(self.value, other.value,
                               abs_tol=self.float_value_change_sensitivity)

        log.log(TRACE, 'me=%s other=%s close=%s sens=%s', self, other, isclose,
                self.float_value_change_sensitivity)
        return isclose

    def generate_metrics(self) -> List[Metric]:
        """ Default metrics encoding method for float and integers values."""

        assert isinstance(self.value, (float, int))
        metrics = [Metric(
            name='allocation',
            value=self.value,
            type=MetricType.GAUGE,
        )]
        self.labels_updater.update_labels(metrics)
        return metrics

    def validate(self):
        if self.value < self.min_value or self.value > self.max_value:
            raise InvalidAllocations('%s does not belong to range <%s;%s>' % (
                self.value, self.min_value, self.max_value))

    def calculate_changeset(self, current: 'BoxedNumeric'):
        if current is None:
            # There is no old value, so there is a change
            value_changed = True
        else:
            # If we have old value compare them.
            if not isinstance(current, BoxedNumeric):
                return self, None, ['got invalid type for comparison %r' % current]

            value_changed = (self != current)

        if value_changed:
            # For floats merge is simple, is value is change, the
            # new_value just become target and changeset
            # target and changeset (overwrite policy)
            return self, self
        else:
            # If value is not changed, then is assumed current value is the same as
            # new so we can return any of them (lets return the new one) as target
            return current, None

    def perform_allocations(self):
        raise NotImplementedError('tried to execute perform_allocations on numeric value %r' % self)
