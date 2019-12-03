from wca.metrics import MetricName
from wca.wss import WSS
from tests.testing import create_open_mock
from unittest.mock import Mock, patch, call


pids = ['1', '2', '3', '4', '5']

smaps = {'/proc/{}/smaps'.format(pid): 'Referenced: {}'.format(str(1024*int(pid))) for pid in pids}

clear_refs = {'/proc/{}/clear_refs'.format(pid): pid for pid in pids}


@patch('os.listdir', return_value=pids)
def test_get_measurements(*mocks):
    mock_get_pids = Mock()
    mock_get_pids.return_value = pids

    with patch('builtins.open', new=create_open_mock(
            {**smaps, **clear_refs, '/dev/null': '0'})) as files:
        wss = WSS(get_pids=mock_get_pids, reset_interval=1)

        # In megabytes: ( 1 + 2 + 3 + 4 + 5 ) * 1024 / 1024
        assert wss.get_measurements() == {MetricName.TASK_WSS_REFERENCED_BYTES: 15360000}

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
