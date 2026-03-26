"""플러그인 샌드박스 실행기."""
from __future__ import annotations

import json
import logging
import subprocess
import sys
import textwrap

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15


def run_sandboxed(code: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """코드 문자열을 별도 Python 프로세스에서 실행한다."""
    wrapper = textwrap.dedent(
        f"""
        import io, json, sys, traceback
        _out = io.StringIO()
        _err = ""
        try:
            import sys as _sys
            _sys.stdout = _out
            exec({code!r}, {{}})
            _sys.stdout = sys.__stdout__
        except Exception:
            _sys.stdout = sys.__stdout__
            _err = traceback.format_exc()
        print(json.dumps({{"ok": not _err, "output": _out.getvalue()[:4096], "error": _err}}))
        """
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", wrapper],
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=0x08000000 if sys.platform == "win32" else 0,
        )
        stdout = (result.stdout or "").strip()
        if stdout:
            try:
                return json.loads(stdout)
            except json.JSONDecodeError:
                return {"ok": True, "output": stdout[:4096], "error": ""}
        return {"ok": False, "output": "", "error": (result.stderr or "").strip()[:4096]}
    except subprocess.TimeoutExpired:
        logger.warning("[Sandbox] 타임아웃 (%ss) 초과", timeout)
        return {"ok": False, "output": "", "error": f"타임아웃 ({timeout}초) 초과"}
    except Exception as exc:
        logger.error("[Sandbox] 실행 오류: %s", exc)
        return {"ok": False, "output": "", "error": str(exc)}


if __name__ == "__main__":
    print(run_sandboxed("print(42)"))
