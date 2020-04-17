import os

# Pre any tests discovery, windows support for running unit tests in WCA.
# We do not want to run our code in Windows environment but we want be able to run tests on NT.
if os.name == 'nt':
    import sys
    from unittest import mock

    # For some tests we require USER env set
    os.environ['USER'] = 'root'

    # Mock all CDLL lib calls
    mock.patch('ctypes.CDLL').__enter__()

    # Mock all unavailable packages for Windows
    sys.modules['kazoo'] = mock.MagicMock()
    sys.modules['kazoo.client'] = mock.MagicMock()
    sys.modules['kazoo.client'].KazooClient = mock.MagicMock(
        'windowspath_mock_kazoo', return_value=mock.Mock(get=mock.Mock(return_value=[b'value'])))
    sys.modules['kazoo.handlers'] = mock.MagicMock()
    sys.modules['kazoo.exceptions'] = mock.MagicMock()
    sys.modules['kazoo.handlers.threading'] = mock.MagicMock()
    sys.modules['kazoo.handlers.utils'] = mock.MagicMock()
    sys.modules['resource'] = mock.MagicMock()

    # Those functions are not available on windows
    os.geteuid = mock.MagicMock()
    os.getuid = mock.MagicMock()
    # For internal WCA we need always to join path using posix style.
    import posixpath
    import ntpath

    ntpath.join = posixpath.join
