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


import time
import socket
import hashlib
from owca.metrics import Metric
from owca.detectors import (TasksMeasurements, ContentionAnomaly,
                            ContendedResource, AnomalyDetector, TasksResources, TasksLabels)
from owca.allocators import Allocator, AllocationType
from owca.platforms import Platform

import logging
log = logging.getLogger(__name__)


class ExampleDetector(AnomalyDetector):
    """Simulation for anomaly detection based on deterministic
       schema based on phases in cycle"""

    def __init__(self, cycle_length: int = 90, skew: bool = False):
        self.cycle_length = cycle_length
        self.skew = skew

    def detect(self, platform: Platform,
               tasks_measurements: TasksMeasurements,
               tasks_resources: TasksResources,
               tasks_labels: TasksLabels
               ):

        anomalies = []

        # Based on hostname generate skew of phase for different hosts,
        # to simulate contention alerting firing from multiple sources at different time.
        if self.skew:
            phase_skew = sum(hashlib.sha256(socket.gethostname().encode('UTF-8')).digest())
        else:
            phase_skew = 0

        # Find out moment of cycle.
        second_of_cycle = int(time.time() + phase_skew) % self.cycle_length

        # Make sure we have enough tasks (to simulate contention).
        if len(tasks_measurements) >= 10:

            resources = [
                ContendedResource.CPUS,
                ContendedResource.LLC,
                ContendedResource.MEMORY_BW,
            ]

            # Define phases of simulation.
            if second_of_cycle < 10:
                # Single contention on one resource with single contender task.
                tasks_count = 1
                resources_count = 1
                metrics_count = 1
            elif second_of_cycle < 20:
                # Single contention on two resources with single contender task
                # (with two additional metrics)
                tasks_count = 1
                resources_count = 2
                metrics_count = 2
            elif second_of_cycle < 30:
                # Single contention on three resources with two contender tasks
                # (with two additional metrics each)
                tasks_count = 1
                resources_count = 3
                metrics_count = 2
            elif second_of_cycle < 40:
                # Two contentions each on two resources with two contender tasks
                # (with two additional metrics each)
                tasks_count = 2
                resources_count = 2
                metrics_count = 3
            elif second_of_cycle < 50:
                # Multiple (three) contentions each on single resource with single contender task
                # (with two additional metrics each)
                tasks_count = 3
                resources_count = 1
                metrics_count = 1
            else:
                # Contention free period.
                resources_count = 0
                tasks_count = 0
                metrics_count = 0

            log.info('detector simulation: tasks=%d resources=%d metrics=%d!',
                     tasks_count, resources_count, metrics_count)

            # Make sure that we choose tasks pairs for generating faked contention.
            task_ids = sorted(tasks_measurements.keys())

            # Predefined pairs of contended and contending tasks.
            task_pairs = [
                (task_ids[0], task_ids[1:3]),  # 0 vs 1,2
                (task_ids[3], task_ids[4:5]),  # 3 vs 4
                (task_ids[6], task_ids[7:10]),  # 6 vs 7,8,9
            ]

            # Generate multiple contention based on scenario phase.
            for resource_idx in range(resources_count):
                for task_pair_idx in range(tasks_count):

                    contended_task_id, contending_task_ids = task_pairs[task_pair_idx]
                    resource = resources[resource_idx]
                    metrics = [
                        Metric(name="cpu_threshold_%d" % i, value="%d" % (i+1)*10, type="gauge")
                        for i in range(metrics_count)
                    ]

                    anomalies.append(
                        ContentionAnomaly(
                            contended_task_id=contended_task_id,
                            contending_task_ids=contending_task_ids,
                            resource=resource,
                            metrics=metrics,
                        )
                    )
        else:
            log.warning('not enough tasks %d to simulate contention!', len(tasks_measurements))

        debugging_metrics = [
            Metric(
                name='second_of_cycle',
                value=second_of_cycle,
                type="gauge",
            )
        ]

        return anomalies, debugging_metrics


class ExampleAllocator(Allocator):

    def allocate(self, platform, tasks_measurements, tasks_resources,
                 tasks_labels, tasks_allocations):
        log.debug('allocated called with tasks_allocations: %r', tasks_allocations)

        if tasks_measurements:
            task_id = list(tasks_measurements.keys())[0]
            tasks_allocations[task_id] = {
                AllocationType.QUOTA: 0.5
            }

        return tasks_allocations, [], []
