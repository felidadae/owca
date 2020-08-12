# Copyright (c) 2020 Intel Corporation
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
import logging
import os

from wca.metrics import Measurements, MetricName

log = logging.getLogger(__name__)

MB = 1000000


class WSS:
    def __init__(self, cycle_duration_s, get_pids, reset_interval, stable_duration=30):
        """cycle_duration_s -> duration of single cycle in seconds"""
        self.get_pids = get_pids

        self.cycle = 0
        self.started = time.time()
        self.values = []
        self.cycle_duration_s = cycle_duration_s

        self.reset_interval = reset_interval
        self.stable_cycles = stable_duration
        self.stable_cycles_counter = 0

        self.last_stable__task_working_set_size_bytes = None  # [B]

        # @TODO we only needs last two values.
        self.history_referenced = []  # [B]
        self.prev_membw = None  # [B/s]
        self.history_membw_delta = []  # [B/s]

    def get_curr_membw_delta(self):
        """Returns last membw delta (diff between two consecutive values)"""
        if not self.history_membw_delta:
            return 0
        else:
            return self.history_membw_delta[-1]

    def calculate_membw_delta(self, curr_membw):
        """As an argument takes last value of membw. Adds to self.history_membw_delta."""
        if self.prev_membw:
            last_membw_delta = (curr_membw - self.prev_membw) / self.cycle_duration_s
            self.history_membw_delta.append(last_membw_delta)
        self.prev_membw = curr_membw

    def _discover_pids(self):
        pids = set(self.get_pids(include_threads=False))
        all_pids = os.listdir('/proc')
        all_pids = set(map(str, filter(lambda x: x.isdecimal(), all_pids)))
        pids = pids & all_pids
        return pids

    def _update_stable_counter(self, curr_membw, curr_referenced):
        """Updates stable counter, which tells how many stable cycles in a row there were.
        stable: not changing rapidly in relation to previous values

        curr_membw: [B/s], curr_referenced: [B]
        """

        self.calculate_membw_delta(curr_membw)
        curr_membw_delta = self.get_curr_membw_delta()

        if len(self.history_referenced) > 0:
            curr_referenced_delta = \
                float(curr_referenced - self.history_referenced[-1]) / self.cycle_duration_s

            # Heuristic and magic number >>100<<.
            membw_threshold = curr_membw_delta / 100
            referenced_threshold = curr_referenced / 100

            if curr_referenced_delta >= 0:
                if curr_referenced_delta < membw_threshold \
                        or curr_referenced_delta < referenced_threshold:
                    self.stable_cycles_counter += 1
                    log.debug(
                        '[%3.0fs] curr_referenced[MB]=%d curr_referenced_delta[MB/s]=+%d '
                        'membw_threshold=+%d referenced_threshold=+%d '
                        'curr_membw_delta[MB/s]=%d -> stable '
                        'stable_cycles_counter=%d',
                        time.time() - self.started, curr_referenced/MB, curr_referenced_delta/MB,
                        membw_threshold/MB, referenced_threshold/MB,
                        curr_membw_delta/MB, self.stable_cycles_counter)
                else:
                    self.stable_cycles_counter = 0
            else:
                self.stable_cycles_counter = 0
        else:
            log.debug('[%3.0fs] curr_referenced[MB]=%d curr_membw_delta[MB/s]=%d',
                      time.time() - self.started, curr_referenced/MB, curr_membw_delta/MB)
            self.stable_cycles_counter = 0

    @staticmethod
    def _get_referenced(pids):
        """Returns referenced pages in [Bytes]"""
        if pids:
            dbg = {}
            for pid in pids:
                referenced = 0
                try:
                    with open('/proc/{}/smaps'.format(pid)) as f:
                        for line in f.readlines():
                            if 'Referenced' in line:
                                referenced += int(line.split('Referenced:')[1].split()[0])
                except (ProcessLookupError, FileNotFoundError):
                    print('WARN: process lookup error:', pid)
                    pass
                dbg[pid] = referenced
            return int(sum(dbg.values()) * 1000)  # Scale to Bytes (read as KB)
        return 0

    @staticmethod
    def _clear_refs(pids):
        for pid in pids:
            try:
                with open('/proc/{}/clear_refs'.format(pid), 'w') as f:
                    f.write('1\n')
            except FileNotFoundError:
                log.warning('pid does not exist for clearing refs - ignoring!')
                pass

    def get_measurements(self, rdt_measurements) -> Measurements:
        measurements = {}
        self.cycle += 1
        pids = self._discover_pids()
        log.debug('calculating wss for pids %s', pids)
        referenced = self._get_referenced(pids)
        measurements[MetricName.TASK_WSS_REFERENCED_BYTES] = referenced

        if rdt_measurements and MetricName.TASK_MEM_BANDWIDTH_BYTES in rdt_measurements:
            self._update_stable_counter(
                rdt_measurements.get(MetricName.TASK_MEM_BANDWIDTH_BYTES),
                referenced)
        else:
            log.warning('task_mem_bandwidth_bytes missing! Not measuring WSS!')
            return {}

        if self.stable_cycles != 0 and self.stable_cycles_counter == self.stable_cycles:
            self.stable_cycles_counter = 0
            should_reset = True
            measurements[MetricName.TASK_WORKING_SET_SIZE_BYTES] = referenced
            self.last_stable__task_working_set_size_bytes = referenced
        else:
            should_reset = False
            if self.last_stable__task_working_set_size_bytes:
                measurements[MetricName.TASK_WORKING_SET_SIZE_BYTES] = \
                    self.last_stable__task_working_set_size_bytes
            else:
                measurements[MetricName.TASK_WORKING_SET_SIZE_BYTES] = 0
        self.history_referenced.append(referenced)

        if (self.reset_interval is not None and self.cycle % self.reset_interval == 0)\
                or should_reset:
            log.debug('[%3.0fs] wss: resetting pids: %s ...' %
                      (time.time() - self.started, ','.join(map(str, pids))))
            rstart = time.time()
            self._clear_refs(pids)
            log.debug('[%3.0fs] wss: resetting pids done in %0.2fs' %
                      (time.time() - self.started, time.time() - rstart))

        return measurements
