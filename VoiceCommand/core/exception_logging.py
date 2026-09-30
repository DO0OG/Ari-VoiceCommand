"""앱 콜백과 처리되지 않은 예외를 파일 로그에 남긴다."""
import logging
import sys
import threading
from functools import wraps


_error_count = 0
_error_lock = threading.Lock()


def get_error_count() -> int:
    with _error_lock:
        return _error_count


def log_exception(message: str, *args) -> None:
    global _error_count
    with _error_lock:
        _error_count += 1
    logging.exception(message, *args)


def capture_callback_errors(callback):
    @wraps(callback)
    def wrapped(*args, **kwargs):
        try:
            return callback(*args, **kwargs)
        except Exception:
            # Qt 주기 콜백 밖으로 예외가 새면 이벤트 루프가 중단될 수 있다.
            log_exception("주기 콜백 처리 실패: %s", callback.__qualname__)
            return None

    return wrapped


def _log_hook_exception(message, exc_type, exc_value, traceback) -> None:
    global _error_count
    with _error_lock:
        _error_count += 1
    logging.error(
        "%s: %s",
        message,
        exc_value,
        exc_info=(exc_type, exc_value, traceback),
    )


def _handle_uncaught_exception(exc_type, exc_value, traceback) -> None:
    _log_hook_exception("처리되지 않은 최상위 예외", exc_type, exc_value, traceback)


def _handle_thread_exception(args) -> None:
    thread_name = args.thread.name if args.thread is not None else "unknown"
    _log_hook_exception(
        "처리되지 않은 스레드 예외 (%s)" % thread_name,
        args.exc_type,
        args.exc_value,
        args.exc_traceback,
    )


def _handle_unraisable_exception(args) -> None:
    _log_hook_exception(
        "처리되지 않은 네이티브 콜백 예외",
        args.exc_type,
        args.exc_value,
        args.exc_traceback,
    )


def install_exception_hooks() -> None:
    sys.excepthook = _handle_uncaught_exception
    threading.excepthook = _handle_thread_exception
    sys.unraisablehook = _handle_unraisable_exception
