"""콘솔 창 숨기기와 표준 출력 스트림 정리."""

import os
import sys

_STREAM_NAMES = ("stdout", "stderr")


def _is_console(stream) -> bool:
    try:
        return stream is not None and stream.isatty()
    except (OSError, ValueError):
        return False


def hide_console(kernel32, user32) -> None:
    """콘솔을 분리하고, 분리로 무효가 된 표준 출력 스트림을 빈 출력으로 바꾼다.

    FreeConsole() 뒤에는 콘솔에 연결돼 있던 스트림 쓰기가 WinError 6으로 실패한다.
    파일로 리디렉션된 스트림은 그대로 둔다.
    """
    console_streams = [name for name in _STREAM_NAMES if _is_console(getattr(sys, name))]
    if not kernel32.FreeConsole():
        user32.ShowWindow(kernel32.GetConsoleWindow(), 0)
        return
    for name in console_streams:
        # 프로세스가 끝날 때까지 쓰는 표준 스트림이라 닫지 않는다.
        setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
