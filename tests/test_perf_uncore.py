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
from unittest.mock import patch, MagicMock, mock_open

from tests.testing import platform_mock
from wca.perf_uncore import Event, UncorePerfCounters, MetricName


@patch('wca.perf_uncore._parse_event_groups', return_value={
    MetricName.PLATFORM_PMM_BANDWIDTH_READS: 0.0})
@patch('wca.perf_uncore.UncorePerfCounters._open_for_cpu')
@patch('wca.perf._create_file_from_fd')
def test_get_measurements(*args):
    upc = UncorePerfCounters(
        [0], {17: [Event(event=227,
                         name=MetricName.PLATFORM_PMM_BANDWIDTH_READS,
                         umask=0, config1=0),
                   ]}, platform=platform_mock)
    upc._group_event_leader_files_per_pmu[17] = {0: mock_open()}
    expected_measurements = {MetricName.PLATFORM_PMM_BANDWIDTH_READS: {0: {17: 0.0}}}

    assert upc.get_measurements() == expected_measurements


@patch('wca.perf_uncore.UncorePerfCounters._open')
@patch('wca.perf_uncore._perf_event_open', return_value=5)
@patch('os.fdopen')
def test_open_for_cpu(*args):
    event = Event(event=227,
                  name=MetricName.PLATFORM_PMM_BANDWIDTH_READS,
                  umask=0, config1=0)

    upc = UncorePerfCounters(cpus=[], pmu_events={}, platform=platform_mock)
    assert len(upc._group_event_leader_files_per_pmu) == 0
    upc._open_for_cpu(pmu=17, cpu=0, event=event)
    assert len(upc._event_files) == 0
    assert len(upc._group_event_leader_files_per_pmu) == 1
    upc._open_for_cpu(pmu=17, cpu=0, event=event)
    assert len(upc._event_files) == 1
    assert len(upc._group_event_leader_files_per_pmu) == 1


@patch('wca.perf_uncore.UncorePerfCounters._open')
@patch('wca.perf_uncore._perf_event_open', return_value=5)
def test_cleanup(*args):
    reader = MagicMock()
    event_files = []
    call_count = 3
    for i in range(0, call_count - 1):
        event_files.append(MagicMock())

    event = Event(event=227,
                  name=MetricName.PLATFORM_PMM_BANDWIDTH_READS,
                  umask=0, config1=0)
    upc = UncorePerfCounters([0, 18], {17: [event]}, platform=platform_mock)
    upc._group_event_leader_files_per_pmu = {17: (None, {0: reader})}
    upc._event_files = event_files

    upc.cleanup()
    reader.close.assert_called_once()
    for event_file in event_files:
        event_file.close.assert_called_once()
