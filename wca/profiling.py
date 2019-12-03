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
# Stores information about latest call durations for given function names in seconds.

import functools
import time
from collections import defaultdict
from typing import List, Callable

from wca.metrics import Metric, MetricType, MetricName


class Profiler:

    def __init__(self):
        self._durations = {}
        self._call_counts = defaultdict(lambda: 0)
        self._totals = defaultdict(lambda: 0)

    def profile_duration(self, name: str) -> Callable:
        """Register function to be profiled in terms of duration.

        Has to be used as decorator or you need override function manually.

        Example usage:

        profiler = Profile()

        class B:
            @profiler.profile_duration('bar')
            def method_bar(self):
                pass

        @profiler.profile_duration('bar')
        def func_foo():
            pass


        or
        B.method_bar = profiler.profile_duration('bar')(B.method_bar)

        """

        def _decorator(function_to_profile):
            @functools.wraps(function_to_profile)
            def _inner(*args, **kwargs):
                start = time.time()
                result = function_to_profile(*args, **kwargs)
                duration = time.time() - start
                function_name = name or function_to_profile.__name__
                self.register_duration(function_name, duration)
                return result

            return _inner

        return _decorator

    def register_duration(self, function_name, duration):
        self._durations[function_name] = duration
        self._call_counts[function_name] += 1
        self._totals[function_name] += duration

    def get_metrics(self) -> List[Metric]:
        metrics = []
        for function_name, last_duration_value in sorted(self._durations.items()):
            avg_time = self._totals[function_name] / self._call_counts[function_name]
            metrics.extend([
                Metric(name=MetricName.WCA_DURATION_SECONDS,
                       type=MetricType.GAUGE, value=last_duration_value,
                       labels=dict(function=function_name),
                       ),
                Metric(name=MetricName.WCA_DURATION_SECONDS_AVG,
                       type=MetricType.GAUGE, value=avg_time,
                       labels=dict(function=function_name),
                       ),
            ])
        return metrics


# Global shared object to be used across whole application.
profiler = Profiler()
