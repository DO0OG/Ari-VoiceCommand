"""
자율 실행 엔진 (Autonomous Execution Engine)
AI가 생성한 파이썬 코드 및 쉘 명령어를 안전하고 효율적으로 실행합니다.
"""
import os
import sys
import io
import contextlib
import subprocess
import logging
import traceback
import threading
import time
import re
import textwrap
from dataclasses import dataclass, field
from typing import List, Optional, Callable

from safety_checker import get_safety_checker, DangerLevel
from automation_helpers import AutomationHelpers


@dataclass
class ExecutionResult:
    success: bool
    output: str = ""
    error: str = ""
    duration_ms: int = 0
    code_or_cmd: str = ""


class AutonomousExecutor:
    """AI 자율 명령 실행기"""

    _MAX_HISTORY = 20

    def __init__(self, tts_func: Optional[Callable] = None):
        self.tts_wrapper = tts_func
        self._lock = threading.Lock()
        self._history: List[ExecutionResult] = []
        self._safety = get_safety_checker()
        self._automation = AutomationHelpers()

        # 실행 시 기본적으로 제공할 전역 변수들
        self.execution_globals = {
            'os': os,
            'sys': sys,
            'subprocess': subprocess,
            'threading': threading,
            'logging': logging,
            'time': __import__('time'),
            'webbrowser': __import__('webbrowser'),
            'datetime': __import__('datetime').datetime,
            'desktop_path': os.path.join(os.environ.get('USERPROFILE', os.path.expanduser('~')), 'Desktop'),
            'save_document': self._save_document,
            'choose_document_format': self._choose_document_format,
            'open_url': self._automation.open_url,
            'open_path': self._automation.open_path,
            'launch_app': self._automation.launch_app,
            'wait_seconds': self._automation.wait_seconds,
            'click_screen': self._automation.click_screen,
            'move_mouse': self._automation.move_mouse,
            'type_text': self._automation.type_text,
            'press_keys': self._automation.press_keys,
            'hotkey': self._automation.hotkey,
            'take_screenshot': self._automation.screenshot,
            'write_clipboard': self._automation.write_clipboard,
            'read_clipboard': self._automation.read_clipboard,
            'get_active_window_title': self._automation.get_active_window_title,
            'wait_for_window': self._automation.wait_for_window,
            'browser_login': self._automation.browser_login,
        }
        try:
            import pyautogui
            self.execution_globals['pyautogui'] = pyautogui
        except ImportError:
            pass
        
        try:
            from web_tools import web_search, web_fetch
            self.execution_globals['web_search'] = web_search
            self.execution_globals['web_fetch'] = web_fetch
        except ImportError:
            pass

    # ── 공개 API ────────────────────────────────────────────────────────────────

    def run_python(self, code: str) -> ExecutionResult:
        """파이썬 코드를 안전하게 실행하고 결과를 반환합니다."""
        if not self._lock.acquire(blocking=False):
            return ExecutionResult(success=False, error="이미 다른 코드가 실행 중입니다.", code_or_cmd=code)

        start = time.monotonic()
        try:
            report = self._safety.check_python(code)
            logging.info(f"[Executor] Python 안전 검사: {report.level.value} — {report.summary_kr}")

            if report.level == DangerLevel.DANGEROUS:
                if self.tts_wrapper:
                    self.tts_wrapper(f"주의! {report.summary_kr}")
                confirmed = self._ask_confirmation(f"Python 코드 실행\n\n{code[:200]}", report)
                if not confirmed:
                    result = ExecutionResult(success=False, error="사용자 취소", code_or_cmd=code)
                    if self.tts_wrapper:
                        self.tts_wrapper("실행을 취소했습니다.")
                    self._record_history(result)
                    return result

            elif report.level == DangerLevel.CAUTION:
                if self.tts_wrapper:
                    self.tts_wrapper(f"주의: {report.summary_kr}. 실행합니다.")

            result = self._do_run_python(code)
        finally:
            duration_ms = int((time.monotonic() - start) * 1000)
            self._lock.release()

        result.duration_ms = duration_ms
        result.code_or_cmd = code
        self._record_history(result)
        return result

    def run_shell(self, command: str) -> ExecutionResult:
        """쉘 명령을 안전하게 실행하고 결과를 반환합니다."""
        if not self._lock.acquire(blocking=False):
            return ExecutionResult(success=False, error="이미 다른 명령이 실행 중입니다.", code_or_cmd=command)

        start = time.monotonic()
        try:
            report = self._safety.check_shell(command)
            logging.info(f"[Executor] Shell 안전 검사: {report.level.value} — {report.summary_kr}")

            if report.level == DangerLevel.DANGEROUS:
                if self.tts_wrapper:
                    self.tts_wrapper(f"주의! {report.summary_kr}")
                confirmed = self._ask_confirmation(f"Shell 명령 실행\n\n{command}", report)
                if not confirmed:
                    result = ExecutionResult(success=False, error="사용자 취소", code_or_cmd=command)
                    if self.tts_wrapper:
                        self.tts_wrapper("실행을 취소했습니다.")
                    self._record_history(result)
                    return result

            elif report.level == DangerLevel.CAUTION:
                if self.tts_wrapper:
                    self.tts_wrapper(f"주의: {report.summary_kr}. 실행합니다.")

            result = self._do_run_shell(command)
        finally:
            duration_ms = int((time.monotonic() - start) * 1000)
            self._lock.release()

        result.duration_ms = duration_ms
        result.code_or_cmd = command
        self._record_history(result)
        return result

    def get_history(self) -> List[ExecutionResult]:
        return list(self._history)

    # ── 내부 실행 ───────────────────────────────────────────────────────────────

    def _do_run_python(self, code: str) -> ExecutionResult:
        code = self._normalize_python_code(code)
        logging.info(f"[Executor] Python 실행:\n{code}")
        output_capture = io.StringIO()
        try:
            with contextlib.redirect_stdout(output_capture), contextlib.redirect_stderr(output_capture):
                exec(code, self.execution_globals)  # noqa: S102
            output = output_capture.getvalue().strip()
            if output:
                logging.info(f"[Executor] Python 출력:\n{output}")
            return ExecutionResult(success=True, output=output)
        except Exception:
            err = traceback.format_exc()
            logging.error(f"[Executor] Python 오류:\n{err}")
            if self.tts_wrapper:
                self.tts_wrapper("코드 실행 중 기술적인 문제가 발생했어요.")
            return ExecutionResult(success=False, error=err)

    def _do_run_shell(self, command: str) -> ExecutionResult:
        logging.info(f"[Executor] Shell 실행: {command}")
        try:
            process = subprocess.Popen(
                command,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            stdout, stderr = process.communicate(timeout=30)
            if stdout:
                logging.info(f"[Executor] Shell 출력:\n{stdout.strip()}")
            if stderr:
                logging.warning(f"[Executor] Shell 에러:\n{stderr.strip()}")
            return ExecutionResult(
                success=process.returncode == 0,
                output=stdout.strip(),
                error=stderr.strip(),
            )
        except subprocess.TimeoutExpired:
            logging.error(f"[Executor] Shell 시간 초과: {command}")
            if self.tts_wrapper:
                self.tts_wrapper("명령어 실행 시간이 너무 길어 중단했습니다.")
            return ExecutionResult(success=False, error="실행 시간 초과 (30초)")
        except Exception as e:
            logging.error(f"[Executor] Shell 오류: {e}")
            if self.tts_wrapper:
                self.tts_wrapper("시스템 명령 실행 중 오류가 발생했습니다.")
            return ExecutionResult(success=False, error=str(e))

    def _ask_confirmation(self, action_desc: str, report) -> bool:
        """확인 다이얼로그 요청 (Qt 환경에서만 동작, 그 외엔 False 반환)"""
        try:
            from confirmation_manager import get_confirmation_manager
            return get_confirmation_manager().request_confirmation(
                action_desc, report, self.tts_wrapper
            )
        except Exception as e:
            logging.error(f"[Executor] 확인 다이얼로그 오류: {e}")
            return False

    def _record_history(self, result: ExecutionResult):
        self._history.append(result)
        if len(self._history) > self._MAX_HISTORY:
            self._history = self._history[-self._MAX_HISTORY:]

    def _choose_document_format(self, content: str, preferred_format: str = "auto", title: str = "") -> str:
        preferred = (preferred_format or "auto").strip().lower()
        if preferred in {"txt", "md", "pdf"}:
            if preferred != "pdf" or self._can_write_pdf():
                return preferred
            return "md" if ("#" in content or "- " in content or title) else "txt"

        normalized = content or ""
        if title or "## " in normalized or normalized.count("\n- ") >= 2 or normalized.count("\n#") >= 1:
            return "md"
        if len(normalized) > 2500 and self._can_write_pdf():
            return "pdf"
        return "txt"

    def _save_document(
        self,
        directory: str,
        base_name: str,
        content: str,
        preferred_format: str = "auto",
        title: str = "",
    ) -> str:
        os.makedirs(directory, exist_ok=True)
        doc_format = self._choose_document_format(content, preferred_format=preferred_format, title=title)
        safe_base = re.sub(r'[^A-Za-z0-9._-]+', '_', base_name).strip("._") or "document"
        path = os.path.join(directory, f"{safe_base}.{doc_format}")

        if doc_format == "pdf":
            self._write_simple_pdf(path, content, title=title)
        elif doc_format == "md":
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        else:
            plain = re.sub(r'^\s*#+\s*', '', content, flags=re.MULTILINE)
            plain = re.sub(r'^\s*[-*]\s+', '- ', plain, flags=re.MULTILINE)
            with open(path, "w", encoding="utf-8") as f:
                f.write(plain)
        return path

    def _can_write_pdf(self) -> bool:
        try:
            import reportlab  # noqa: F401
            return True
        except Exception:
            return False

    def _write_simple_pdf(self, path: str, content: str, title: str = ""):
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen import canvas

        font_name = "Helvetica"
        font_candidates = [
            ("MalgunGothic", r"C:\Windows\Fonts\malgun.ttf"),
            ("AppleGothic", r"C:\Windows\Fonts\malgun.ttf"),
        ]
        for candidate_name, candidate_path in font_candidates:
            if os.path.exists(candidate_path):
                try:
                    pdfmetrics.registerFont(TTFont(candidate_name, candidate_path))
                    font_name = candidate_name
                    break
                except Exception:
                    continue

        c = canvas.Canvas(path, pagesize=A4)
        width, height = A4
        y = height - 50
        c.setFont(font_name, 16 if title else 11)
        if title:
            c.drawString(40, y, title[:80])
            y -= 28
            c.setFont(font_name, 11)

        for raw_line in (content or "").splitlines():
            line = raw_line.replace("\t", "    ")
            wrapped = textwrap.wrap(line, width=52) or [""]
            for segment in wrapped:
                if y < 50:
                    c.showPage()
                    c.setFont(font_name, 11)
                    y = height - 50
                c.drawString(40, y, segment)
                y -= 16
        c.save()

    def _normalize_python_code(self, code: str) -> str:
        """LLM이 세미콜론으로 이어붙인 복합문을 실행 가능한 형태로 정리."""
        if not code:
            return code

        normalized = code.replace("\r\n", "\n").strip()
        compound_keywords = ("with ", "for ", "if ", "elif ", "else:", "try:", "except ", "finally:", "while ", "def ", "class ")

        for keyword in compound_keywords:
            normalized = re.sub(rf";\s*{re.escape(keyword)}", f"\n{keyword}", normalized)

        normalized = re.sub(r";\s*(#.*)", r"\n\1", normalized)
        return normalized


# ── 싱글톤 ──────────────────────────────────────────────────────────────────────

_instance: Optional[AutonomousExecutor] = None


def get_executor(tts_func: Optional[Callable] = None) -> AutonomousExecutor:
    """싱글톤 패턴으로 실행기 반환"""
    global _instance
    if _instance is None:
        _instance = AutonomousExecutor(tts_func)
    elif tts_func:
        _instance.tts_wrapper = tts_func
    return _instance
