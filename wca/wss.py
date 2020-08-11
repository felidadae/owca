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


class WSS:

    def __init__(self, get_pids, reset_interval, interval_s, stable_duration=30):
        self.get_pids = get_pids
        self.reset_interval = reset_interval
        self.cycle = 0
        self.prev_value = None
        self.all_values = []
        self.started = time.time()
        self.stable_cycles = stable_duration
        self.stable = 0
        self.values = []
        self.interval_s = interval_s
        self.last_stable = None

        # BW RDT
        self.bw_values = []

    def get_total_bw(self):
        if not self.bw_values:
            return 0
        else:
            return self.bw_values[-1]

    def _discover_pids(self):
        pids = set(self.get_pids(include_threads=False))
        all_pids = os.listdir('/proc')
        all_pids = set(map(str, filter(lambda x: x.isdecimal(), all_pids)))
        pids = pids & all_pids
        return pids

    def _update_stable_counter(self, current, referenced):
        """Updates stable counter, which tells how many stable cycles in a row there were.
        stable: not changing rapidly in relation to previous values"""

        if self.prev_value:
            value = (current - self.prev_value) / self.interval_s / 1000000
            self.bw_values.append(value)
        self.prev_value = current
        bw_mbs = self.get_total_bw()

        if len(self.all_values) > 0:
            increase = float(referenced - self.all_values[-1]) / self.interval_s  # mb/s
            bw_threshold = bw_mbs / 100
            if increase >= 0:
                if increase < bw_threshold or increase < referenced / 100:
                    self.stable += 1
                    log.debug(
                        '[%3.0fs] referenced[mb]=%d increase[mb/s]=+%d referenced increase '
                        '(less than 1%% of BW(%d) or referenced(%d)) BW[mb/s]=%d -> stable '
                        'hit=%d' % (time.time() - self.started, referenced, increase,
                                    bw_threshold, referenced / 100,
                                    bw_mbs, self.stable))
                else:
                    self.stable = 0
            else:
                self.stable = 0
        else:
            log.debug('[%3.0fs] referenced[mb]=%d BW[mb/s]=%d' % (time.time() - self.started,
                                                                  referenced, bw_mbs))
            self.stable = 0

    @staticmethod
    def _get_referenced(pids):
        """Returns referenced pages in [MB]"""
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
            referenced = sum(dbg.values())
            referenced = int(referenced / 1024)  # scale as MB
            return referenced
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
        # Referenced comes in kb (rescale to bytes)
        referenced_bytes = referenced * 1000
        measurements[MetricName.TASK_WSS_REFERENCED_BYTES] = referenced_bytes

        if rdt_measurements and MetricName.TASK_MEM_BANDWIDTH_BYTES in rdt_measurements:
            self._update_stable_counter(
                rdt_measurements.get(MetricName.TASK_MEM_BANDWIDTH_BYTES), referenced)
        else:
            log.warning('task_mem_bandwidth_bytes missing! Not measuring WSS!')
            return {}

        if self.stable_cycles != 0 and self.stable == self.stable_cycles:
            self.stable = 0
            should_reset = True
            measurements[MetricName.TASK_WORKING_SET_SIZE_BYTES] = referenced_bytes
            self.last_stable = referenced_bytes
        else:
            should_reset = False
            if self.last_stable:
                measurements[MetricName.TASK_WORKING_SET_SIZE_BYTES] = self.last_stable
            else:
                measurements[MetricName.TASK_WORKING_SET_SIZE_BYTES] = 0
        self.all_values.append(referenced)

        if (self.reset_interval is not None and self.cycle % self.reset_interval == 0)\
                or should_reset:
            log.debug('[%3.0fs] wss: resetting pids: %s ...' %
                      (time.time() - self.started, ','.join(map(str, pids))))
            rstart = time.time()
            self._clear_refs(pids)
            log.debug('[%3.0fs] wss: resetting pids done in %0.2fs' %
                      (time.time() - self.started, time.time() - rstart))

        return measurements
