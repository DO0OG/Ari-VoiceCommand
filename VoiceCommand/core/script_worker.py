"""배포판에서 자율 실행 파이썬 스크립트를 돌리는 숨은 워커 모드.

Nuitka 배포판에는 파이썬 인터프리터가 없으므로 배포 실행 파일을 이 인자로 다시 띄워
새 프로세스에서 스크립트를 runpy로 실행한다.
"""
import runpy
import sys

from core._whisper_worker import bundled_executable_path
from core.resource_manager import is_bundled

SCRIPT_WORKER_ARGUMENT = "--ari-run-python-script"


def python_script_command(script_path: str) -> list[str]:
    """스크립트 파일을 새 프로세스에서 실행하는 명령을 반환한다."""
    if is_bundled():
        return [bundled_executable_path(), SCRIPT_WORKER_ARGUMENT, script_path]
    return [sys.executable, script_path]


def run_python_script(script_path: str) -> int:
    """`python 스크립트.py`처럼 스크립트를 __main__으로 실행한다."""
    # 부모 프로세스는 출력을 UTF-8로 읽는다. 배포판은 PYTHONIOENCODING을 따르지 않을 수 있다.
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sys.argv = [script_path]
    runpy.run_path(script_path, run_name="__main__")
    return 0


def dispatch_script_command(argv: list[str]) -> int | None:
    """Main.py가 GUI를 가져오기 전에 스크립트 실행 모드를 처리한다."""
    if len(argv) == 3 and argv[1] == SCRIPT_WORKER_ARGUMENT:
        return run_python_script(argv[2])
    return None
