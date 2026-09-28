import ctypes
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core import single_instance


class _Signal:
    def __init__(self):
        self.callback = None

    def connect(self, callback):
        self.callback = callback

    def emit(self):
        self.callback()


class _FakeSocket:
    def __init__(self):
        self.write = Mock()
        self.connectToServer = Mock()
        self.waitForConnected = Mock(return_value=True)
        self.flush = Mock()
        self.waitForBytesWritten = Mock(return_value=True)
        self.disconnectFromServer = Mock()


class _FakeConnection:
    def __init__(self):
        self.readyRead = _Signal()
        self.disconnected = _Signal()
        self.readAll = Mock(return_value=b"show")
        self.disconnectFromServer = Mock()
        self.deleteLater = Mock()

    def bytesAvailable(self):
        return 4


class _FakeServer:
    instances = []
    listen_results = [True]
    removed_names = []

    def __init__(self):
        self.newConnection = _Signal()
        self.connection = _FakeConnection()
        self.listen = Mock(side_effect=type(self).listen_results)
        self.hasPendingConnections = Mock(side_effect=[True, False])
        self.nextPendingConnection = Mock(return_value=self.connection)
        type(self).instances.append(self)

    @classmethod
    def removeServer(cls, name):
        cls.removed_names.append(name)
        return True


class SingleInstanceTests(unittest.TestCase):
    def setUp(self):
        single_instance._MUTEX_HANDLE = None
        single_instance._LOCAL_SERVER = None
        _FakeServer.instances = []
        _FakeServer.listen_results = [True]
        _FakeServer.removed_names = []

    def _kernel32(self, last_error):
        create_mutex = Mock(return_value=object())

        def get_session_id(_process_id, session_id_pointer):
            ctypes.cast(session_id_pointer, ctypes.POINTER(ctypes.c_ulong)).contents.value = 7
            return True

        return SimpleNamespace(
            CreateMutexW=create_mutex,
            CloseHandle=Mock(return_value=True),
            GetLastError=Mock(return_value=last_error),
            SetLastError=Mock(),
            GetCurrentProcessId=Mock(return_value=123),
            ProcessIdToSessionId=Mock(side_effect=get_session_id),
        )

    def _patch_windows(self, kernel32):
        return (
            patch.object(single_instance.sys, "platform", "win32"),
            patch.object(
                ctypes,
                "windll",
                SimpleNamespace(kernel32=kernel32),
                create=True,
            ),
            patch.object(single_instance, "QLocalServer", _FakeServer),
        )

    def test_existing_instance_receives_show_request_and_returns_false(self):
        kernel32 = self._kernel32(183)
        socket = _FakeSocket()
        guards = self._patch_windows(kernel32)

        with guards[0], guards[1], guards[2], patch.object(
            single_instance, "QLocalSocket", return_value=socket
        ):
            should_start = single_instance.ensure_single_instance(["Main.py"])

        self.assertFalse(should_start)
        kernel32.CreateMutexW.assert_called_once_with(
            None, False, single_instance.INSTANCE_NAME
        )
        socket.connectToServer.assert_called_once_with(
            f"{single_instance.INSTANCE_NAME}-7"
        )
        socket.write.assert_called_once_with(b"show")
        socket.waitForBytesWritten.assert_called_once()
        kernel32.CloseHandle.assert_called_once_with(kernel32.CreateMutexW.return_value)
        self.assertEqual(_FakeServer.instances, [])

    def test_new_mutex_keeps_handle_and_starts_server(self):
        kernel32 = self._kernel32(0)
        callback = Mock()
        guards = self._patch_windows(kernel32)

        with guards[0], guards[1], guards[2]:
            should_start = single_instance.ensure_single_instance(["Main.py"])
            single_instance.start_single_instance_server(callback)

        self.assertTrue(should_start)
        self.assertIs(single_instance._MUTEX_HANDLE, kernel32.CreateMutexW.return_value)
        server = _FakeServer.instances[0]
        self.assertIs(single_instance._LOCAL_SERVER, server)
        server.listen.assert_called_once_with(f"{single_instance.INSTANCE_NAME}-7")
        server.newConnection.emit()
        callback.assert_called_once_with()

    def test_stale_server_name_is_removed_before_retry(self):
        kernel32 = self._kernel32(0)
        _FakeServer.listen_results = [False, True]
        guards = self._patch_windows(kernel32)

        with guards[0], guards[1], guards[2]:
            should_start = single_instance.ensure_single_instance(["Main.py"])
            single_instance.start_single_instance_server(Mock())

        self.assertTrue(should_start)
        self.assertEqual(
            _FakeServer.removed_names,
            [f"{single_instance.INSTANCE_NAME}-7"],
        )
        self.assertEqual(_FakeServer.instances[0].listen.call_count, 2)

    def test_exempt_worker_commands_skip_mutex_and_qt(self):
        commands = (
            "--decision-self-test",
            "--bundle-import-self-test",
            "--ari-whisper-worker",
            "--ari-whisper-worker-self-test",
            "--ari-run-python-script",
        )
        kernel32 = self._kernel32(183)
        guards = self._patch_windows(kernel32)

        with guards[0], guards[1], guards[2], patch.object(
            single_instance, "QLocalSocket"
        ) as local_socket:
            for command in commands:
                with self.subTest(command=command):
                    self.assertTrue(
                        single_instance.ensure_single_instance(
                            ["Main.py", command, "argument"]
                        )
                    )

        kernel32.CreateMutexW.assert_not_called()
        local_socket.assert_not_called()
        self.assertEqual(_FakeServer.instances, [])

    def test_non_windows_skips_mutex_and_qt(self):
        with (
            patch.object(single_instance.sys, "platform", "linux"),
            patch.object(single_instance, "QLocalServer") as local_server,
            patch.object(single_instance, "QLocalSocket") as local_socket,
        ):
            self.assertTrue(single_instance.ensure_single_instance(["Main.py"]))
            single_instance.start_single_instance_server(Mock())

        local_server.assert_not_called()
        local_socket.assert_not_called()
        self.assertIsNone(single_instance._MUTEX_HANDLE)


if __name__ == "__main__":
    unittest.main()
