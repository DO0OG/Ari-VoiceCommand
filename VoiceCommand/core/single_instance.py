"""Windows GUI 단일 인스턴스 관리."""

import ctypes
import logging
import sys
from collections.abc import Callable, Sequence

from PySide6.QtNetwork import QLocalServer, QLocalSocket


INSTANCE_NAME = "AriSingleInstance"
ERROR_ALREADY_EXISTS = 183
_WORKER_COMMANDS = {
    "--ari-whisper-worker",
    "--ari-whisper-worker-self-test",
}
_EXEMPT_COMMANDS = {
    "--decision-self-test",
    "--bundle-import-self-test",
    "--ari-run-python-script",
}

_MUTEX_HANDLE = None
_LOCAL_SERVER = None


def _is_exempt_command(argv: Sequence[str]) -> bool:
    if len(argv) < 2:
        return False
    if argv[1] in _WORKER_COMMANDS:
        return True
    return len(argv) == 3 and argv[1] in _EXEMPT_COMMANDS


def _server_name() -> str | None:
    kernel32 = ctypes.windll.kernel32
    get_process_id = kernel32.GetCurrentProcessId
    get_process_id.argtypes = ()
    get_process_id.restype = ctypes.c_ulong
    process_id_to_session_id = kernel32.ProcessIdToSessionId
    process_id_to_session_id.argtypes = (
        ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
    )
    process_id_to_session_id.restype = ctypes.c_int

    session_id = ctypes.c_ulong()
    if not process_id_to_session_id(get_process_id(), ctypes.byref(session_id)):
        logging.warning("Windows 세션 ID를 확인하지 못했습니다.")
        return None
    return f"{INSTANCE_NAME}-{session_id.value}"


def _send_show_request() -> None:
    try:
        server_name = _server_name()
        if server_name is None:
            return
        socket = QLocalSocket()
        socket.connectToServer(server_name)
        if not socket.waitForConnected(250):
            logging.debug("기존 인스턴스 IPC 연결 실패: %s", socket.errorString())
            return

        socket.write(b"show")
        socket.flush()
        if not socket.waitForBytesWritten(250):
            logging.debug("기존 인스턴스 IPC 요청 전송 실패: %s", socket.errorString())
        socket.disconnectFromServer()
    except RuntimeError as exc:
        logging.debug("기존 인스턴스 IPC 요청 실패: %s", exc)


def _handle_request(connection, on_show: Callable[[], None]) -> None:
    request = bytes(connection.readAll()).strip()
    if request == b"show":
        on_show()
    connection.disconnectFromServer()


def _accept_connections(server, on_show: Callable[[], None]) -> None:
    while server.hasPendingConnections():
        connection = server.nextPendingConnection()
        connection.readyRead.connect(
            lambda connection=connection: _handle_request(connection, on_show)
        )
        connection.disconnected.connect(connection.deleteLater)
        if connection.bytesAvailable():
            _handle_request(connection, on_show)


def _start_server(on_show: Callable[[], None]) -> None:
    global _LOCAL_SERVER

    server_name = _server_name()
    if server_name is None:
        return
    server = QLocalServer()
    server.newConnection.connect(lambda: _accept_connections(server, on_show))
    if not server.listen(server_name):
        QLocalServer.removeServer(server_name)
        if not server.listen(server_name):
            logging.warning("기존 인스턴스 IPC 서버를 열지 못했습니다.")
            return
    _LOCAL_SERVER = server


def ensure_single_instance(argv: Sequence[str]) -> bool:
    """이미 실행 중이면 표시를 요청하고, 새 실행이면 뮤텍스를 보관한다."""
    global _MUTEX_HANDLE

    if _is_exempt_command(argv) or sys.platform != "win32":
        return True

    kernel32 = ctypes.windll.kernel32
    create_mutex = kernel32.CreateMutexW
    create_mutex.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p)
    create_mutex.restype = ctypes.c_void_p
    get_last_error = kernel32.GetLastError
    get_last_error.argtypes = ()
    get_last_error.restype = ctypes.c_ulong
    set_last_error = kernel32.SetLastError
    set_last_error.argtypes = (ctypes.c_ulong,)
    set_last_error.restype = None
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (ctypes.c_void_p,)
    close_handle.restype = ctypes.c_int

    set_last_error(0)
    mutex_handle = create_mutex(None, False, INSTANCE_NAME)
    last_error = get_last_error()
    if not mutex_handle:
        # 검사를 못 해도 앱 실행은 막지 않는다.
        logging.warning("뮤텍스 생성 실패, 중복 실행 검사를 건너뜁니다: %s", last_error)
        return True
    if last_error == ERROR_ALREADY_EXISTS:
        if not close_handle(mutex_handle):
            logging.debug("중복 인스턴스 뮤텍스 핸들을 닫지 못했습니다.")
        _send_show_request()
        return False

    _MUTEX_HANDLE = mutex_handle
    return True


def start_single_instance_server(on_show: Callable[[], None]) -> None:
    """Qt 앱을 만든 뒤 기존 인스턴스 요청을 받는다."""
    if sys.platform == "win32" and _MUTEX_HANDLE is not None:
        _start_server(on_show)
