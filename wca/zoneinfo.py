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
from typing import Pattern

from wca.metrics import Measurements, MetricName

log = logging.getLogger(__name__)

DEFAULT_REGEXP = r'\s+([a-z_]+)\s+(\d+)'


def get_zoneinfo_measurements(zoneinfo_regexp: Pattern) -> Measurements:
    """ Read and parse zoneinfo only from normal ZONE
    (only expose simple fields with key value
    """

    measurements = {}

    with open('/proc/zoneinfo') as f:
        for line in f.readlines():

            if line.startswith('Node '):
                numa_node = str(int(line.split()[1][:-1]))
                if 'Normal' in line:
                    zone = 'Normal'
                if 'DMA32' in line:
                    zone = 'DMA32'
                elif 'DMA' in line:
                    zone = 'DMA'

                continue

            match = zoneinfo_regexp.match(line)
            if not match:
                continue
            key = str(match.group(1))

            try:
                value = float(match.group(2))
            except ValueError:
                log.warning('cannot parse /proc/zoneinfo using regexp: %r', zoneinfo_regexp)
                continue

            if numa_node not in measurements:
                measurements[numa_node] = {}
            if zone not in measurements[numa_node]:
                measurements[numa_node][zone] = {}
            measurements[numa_node][zone][key] = value

    return {MetricName.PLATFORM_ZONEINFO: measurements}
