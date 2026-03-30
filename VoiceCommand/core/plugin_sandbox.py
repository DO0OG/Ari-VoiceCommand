"""플러그인 샌드박스 실행기."""
from __future__ import annotations

import logging
import multiprocessing as mp
import os

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15


def _sandbox_worker(code: str, queue) -> None:
    import io
    import runpy
    import sys
    import tempfile
    import traceback

    stdout_buffer = io.StringIO()
    error_text = ""
    try:
        original_stdout = sys.stdout
        sys.stdout = stdout_buffer
        with tempfile.NamedTemporaryFile("w", suffix="_sandbox_exec.py", encoding="utf-8", delete=False) as temp_file:
            temp_file.write(code)
            temp_path = temp_file.name
        try:
            runpy.run_path(temp_path, run_name="__main__")
            sys.stdout = original_stdout
        finally:
            os.remove(temp_path)
    except Exception:
        sys.stdout = sys.__stdout__
        error_text = traceback.format_exc()
    queue.put({
        "ok": not error_text,
        "output": stdout_buffer.getvalue()[:4096],
        "error": error_text[:4096],
    })


def run_sandboxed(code: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """코드 문자열을 별도 Python 프로세스에서 실행한다."""
    safe_timeout = max(1, min(int(timeout), 60))
    ctx = mp.get_context("spawn")
    queue = ctx.Queue()
    process = ctx.Process(target=_sandbox_worker, args=(code, queue))
    process.start()
    process.join(timeout=safe_timeout)

    if process.is_alive():
        process.terminate()
        process.join()
        logger.warning("[Sandbox] 타임아웃 (%ss) 초과", safe_timeout)
        return {"ok": False, "output": "", "error": f"타임아웃 ({safe_timeout}초) 초과"}

    if queue.empty():
        error_message = f"프로세스 종료 코드: {process.exitcode}"
        logger.error("[Sandbox] 실행 오류: %s", error_message)
        return {"ok": False, "output": "", "error": error_message}

    return queue.get()


if __name__ == "__main__":
    print(run_sandboxed("print(42)"))
