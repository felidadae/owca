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

from wca.metrics import MetricName
from wca.wss import WSS
from tests.testing import create_open_mock
from unittest.mock import Mock, patch, call


pids = ['1', '2', '3', '4', '5']

smaps = {'/proc/{}/smaps'.format(pid): 'Referenced: {}'.format(str(1024*int(pid))) for pid in pids}

clear_refs = {'/proc/{}/clear_refs'.format(pid): pid for pid in pids}


@patch('wca.wss.WSS._update_stable_counter')
@patch('os.listdir', return_value=pids)
def test_get_measurements(*mocks):
    mock_get_pids = Mock()
    mock_get_pids.return_value = pids

    with patch('builtins.open', new=create_open_mock(
            {**smaps, **clear_refs, '/dev/null': '0'})) as files:
        wss = WSS(cycle_duration_s=5, get_pids=mock_get_pids, reset_interval=1)

        # In megabytes: ( 1 + 2 + 3 + 4 + 5 ) * 1024 / 1024
        assert wss.get_measurements({'task_mem_bandwidth_bytes': 1234567}) == \
            {MetricName.TASK_WSS_REFERENCED_BYTES: 15360000, 'task_working_set_size_bytes': 0}

        # Check if gets info from smaps
        for smap in smaps:
            expected_calls = [
                    call(smap, 'rb'),
                    call().__enter__(),
                    call().readlines(),
                    call().__exit__(None, None, None)]
            assert files[smap].mock_calls == expected_calls

        # Check if write '1' to clear_refs. It should happen on first run.
        for ref in clear_refs:
            expected_calls = [
                    call(ref, 'w'),
                    call().__enter__(),
                    call().write('1\n'),
                    call().__exit__(None, None, None)]
            assert files[ref].mock_calls == expected_calls
