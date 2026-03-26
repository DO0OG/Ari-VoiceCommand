"""
자율 실행 엔진 (Autonomous Execution Engine)
AI가 생성한 파이썬 코드 및 쉘 명령어를 안전하고 효율적으로 실행합니다.
"""
import os
import sys
import subprocess
import logging
import traceback
import threading
import time
import re
import json
import tempfile
import textwrap
from dataclasses import dataclass
from typing import List, Optional, Callable

from agent.safety_checker import get_safety_checker, DangerLevel
from agent.automation_helpers import AutomationHelpers


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
    _MAX_CONCURRENT_PYTHON = 2
    _MAX_CONCURRENT_SHELL = 2

    def __init__(self, tts_func: Optional[Callable] = None):
        self.tts_wrapper = tts_func
        self._python_slots = threading.BoundedSemaphore(self._MAX_CONCURRENT_PYTHON)
        self._shell_slots = threading.BoundedSemaphore(self._MAX_CONCURRENT_SHELL)
        self._history: List[ExecutionResult] = []
        self._safety = get_safety_checker()
        self._automation = AutomationHelpers()

        # 실행 시 기본적으로 제공할 전역 변수들
        # os, subprocess, sys 는 직접 노출하지 않고 래퍼 함수를 통해서만 허용
        self.execution_globals = {
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
            'click_image': self._automation.click_image,
            'is_image_visible': self._automation.is_image_visible,
            'move_mouse': self._automation.move_mouse,
            'type_text': self._automation.type_text,
            'press_keys': self._automation.press_keys,
            'hotkey': self._automation.hotkey,
            'take_screenshot': self._automation.screenshot,
            'write_clipboard': self._automation.write_clipboard,
            'read_clipboard': self._automation.read_clipboard,
            'get_active_window_title': self._automation.get_active_window_title,
            'list_open_windows': self._automation.list_open_windows,
            'find_window': self._automation.find_window,
            'focus_window': self._automation.focus_window,
            'wait_for_window': self._automation.wait_for_window,
            'browser_login': self._automation.browser_login,
            'get_browser_state': self._automation.get_browser_state,
            'get_browser_current_url': self._automation.get_browser_current_url,
            'get_desktop_state': self._automation.get_desktop_state,
            'get_learned_strategies': self._automation.get_learned_strategies,
            'get_learned_strategy_summary': self._automation.get_learned_strategy_summary,
            'get_planning_snapshot': self._automation.get_planning_snapshot,
            'get_planning_snapshot_summary': self._automation.get_planning_snapshot_summary,
            'wait_for_download': self._automation.wait_for_download,
            'suggest_browser_actions': self._automation.suggest_browser_actions,
            'build_adaptive_browser_plan': self._automation.build_adaptive_browser_plan,
            'build_resilient_browser_plans': self._automation.build_resilient_browser_plans,
            'run_browser_actions': self._automation.run_browser_actions,
            'run_adaptive_browser_workflow': self._automation.run_adaptive_browser_workflow,
            'run_resilient_browser_workflow': self._automation.run_resilient_browser_workflow,
            'suggest_desktop_workflow': self._automation.suggest_desktop_workflow,
            'build_adaptive_desktop_plan': self._automation.build_adaptive_desktop_plan,
            'build_resilient_desktop_plans': self._automation.build_resilient_desktop_plans,
            'run_desktop_workflow': self._automation.run_desktop_workflow,
            'run_adaptive_desktop_workflow': self._automation.run_adaptive_desktop_workflow,
            'run_resilient_desktop_workflow': self._automation.run_resilient_desktop_workflow,
            'get_execution_history': self.get_history,
            'get_last_execution': self.get_last_execution,
            'get_runtime_state': self.get_runtime_state,
        }
        # 파일 작업 도구 주입 (Phase 1.2)
        try:
            from agent.file_tools import (
                rename_file, merge_text_files, organize_folder_by_extension,
                analyze_data_file, generate_markdown_report, detect_file_set,
                batch_rename_files,
            )
            self.execution_globals.update({
                'rename_file': rename_file,
                'merge_files': merge_text_files,
                'organize_folder': organize_folder_by_extension,
                'analyze_data': analyze_data_file,
                'generate_report': generate_markdown_report,
                'detect_file_set': detect_file_set,
                'batch_rename_files': batch_rename_files,
            })
        except ImportError as e:
            logging.warning(f"[Executor] file_tools 로드 실패: {e}")

        try:
            import pyautogui
            self.execution_globals['pyautogui'] = pyautogui
        except ImportError:
            pass
        
        try:
            from services.web_tools import web_search, web_fetch, get_smart_browser
            self.execution_globals['web_search'] = web_search
            self.execution_globals['web_fetch'] = web_fetch
            self.execution_globals['get_browser'] = get_smart_browser
            self.execution_globals['get_browser_state_detailed'] = lambda: get_smart_browser().get_state(include_dom_analysis=True)
        except ImportError:
            pass

    # ── 공개 API ────────────────────────────────────────────────────────────────

    def run_python(self, code: str, extra_globals: Optional[dict] = None) -> ExecutionResult:
        """파이썬 코드를 안전하게 실행하고 결과를 반환합니다."""
        self._python_slots.acquire()

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

            result = self._do_run_python(code, extra_globals=extra_globals)
        finally:
            duration_ms = int((time.monotonic() - start) * 1000)
            self._python_slots.release()

        result.duration_ms = duration_ms
        result.code_or_cmd = code
        self._record_history(result)
        return result

    def run_shell(self, command: str) -> ExecutionResult:
        """쉘 명령을 안전하게 실행하고 결과를 반환합니다."""
        self._shell_slots.acquire()

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
            self._shell_slots.release()

        result.duration_ms = duration_ms
        result.code_or_cmd = command
        self._record_history(result)
        return result

    def get_history(self) -> List[ExecutionResult]:
        return list(self._history)

    def get_last_execution(self) -> Optional[ExecutionResult]:
        return self._history[-1] if self._history else None

    def get_runtime_state(self) -> dict:
        """현재 실행 환경의 읽기 전용 상태 스냅샷."""
        browser_state = {}
        active_title = ""
        try:
            browser_state = self._automation.get_browser_state()
        except Exception:
            browser_state = {}
        try:
            active_title = self._automation.get_active_window_title()
        except Exception:
            active_title = ""
        try:
            open_windows = self._automation.list_open_windows()
        except Exception:
            open_windows = []
        try:
            desktop_state = self._automation.get_desktop_state()
        except Exception:
            desktop_state = {}

        last = self.get_last_execution()
        return {
            "active_window_title": active_title,
            "open_window_titles": open_windows,
            "browser_state": browser_state,
            "desktop_state": desktop_state,
            "learned_strategies": self._automation.get_learned_strategies(),
            "learned_strategy_summary": self._automation.get_learned_strategy_summary(),
            "planning_snapshot": self._automation.get_planning_snapshot(),
            "planning_snapshot_summary": self._automation.get_planning_snapshot_summary(),
            "last_execution_success": getattr(last, "success", None),
            "last_execution_output": (getattr(last, "output", "") or "")[:300],
            "last_execution_error": (getattr(last, "error", "") or "")[:300],
        }

    # ── 내부 실행 ───────────────────────────────────────────────────────────────

    def _do_run_python(self, code: str, extra_globals: Optional[dict] = None) -> ExecutionResult:
        code = self._normalize_python_code(code)
        logging.info(f"[Executor] Python 실행:\n{code}")
        runner_path = ""
        process = None
        try:
            runner_path = self._write_python_runner(code, extra_globals=extra_globals)
            child_env = os.environ.copy()
            child_env["PYTHONIOENCODING"] = "utf-8"
            child_env["PYTHONUTF8"] = "1"
            process = subprocess.Popen(  # nosec B603 - controlled runner invocation
                [sys.executable, runner_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=child_env,
            )
            stdout, stderr = process.communicate(timeout=30)
            output = (stdout or "").strip()
            error_output = (stderr or "").strip()
            if process.returncode != 0:
                logging.error(f"[Executor] Python 오류:\n{error_output}")
                if self.tts_wrapper:
                    self.tts_wrapper("코드 실행 중 기술적인 문제가 발생했어요.")
                return ExecutionResult(success=False, error=error_output or "파이썬 실행 실패")
            if output:
                logging.info(f"[Executor] Python 출력:\n{output}")
            return ExecutionResult(success=True, output=output)
        except subprocess.TimeoutExpired:
            logging.error("[Executor] Python 시간 초과")
            try:
                process.kill()
            except Exception:
                pass
            if self.tts_wrapper:
                self.tts_wrapper("코드 실행 시간이 너무 길어 중단했습니다.")
            return ExecutionResult(success=False, error="실행 시간 초과 (30초)")
        except Exception:
            err = traceback.format_exc()
            logging.error(f"[Executor] Python 오류:\n{err}")
            if self.tts_wrapper:
                self.tts_wrapper("코드 실행 중 기술적인 문제가 발생했어요.")
            return ExecutionResult(success=False, error=err)
        finally:
            if runner_path:
                self._safe_unlink(runner_path)

    def _do_run_shell(self, command: str) -> ExecutionResult:
        logging.info(f"[Executor] Shell 실행: {command}")
        process = None
        try:
            shell_command = self._build_shell_command(command)
            child_env = os.environ.copy()
            child_env["PYTHONIOENCODING"] = "utf-8"
            child_env["PYTHONUTF8"] = "1"
            process = subprocess.Popen(  # nosec B603 - controlled shell invocation
                shell_command,  # nosec B603
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=child_env,
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
            try:
                process.kill()
            except Exception:
                pass
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
            from agent.confirmation_manager import get_confirmation_manager
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

    def _write_python_runner(self, code: str, extra_globals: Optional[dict] = None) -> str:
        runner = self._build_python_runner_script(code, extra_globals=extra_globals)
        temp = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".py", delete=False)
        with temp:
            temp.write(runner)
        return temp.name

    def _build_python_runner_script(self, code: str, extra_globals: Optional[dict] = None) -> str:
        desktop_path = self.execution_globals.get(
            "desktop_path",
            os.path.join(os.environ.get('USERPROFILE', os.path.expanduser('~')), 'Desktop'),
        )
        payload = {
            "desktop_path": desktop_path,
            "module_dir": os.path.dirname(os.path.dirname(__file__)),
        }
        payload.update(self._sanitize_runner_payload(extra_globals))
        payload_json = json.dumps(payload, ensure_ascii=False)
        indented_code = textwrap.indent(code, "        ")
        return f'''import contextlib
import io
import json
import logging
import os
import re
import subprocess
import sys
import textwrap
import threading
import time
import traceback
import webbrowser
from datetime import datetime

PAYLOAD = json.loads({payload_json!r})
desktop_path = PAYLOAD.get("desktop_path", "")
step_outputs = PAYLOAD.get("step_outputs", {{}})
verification_context = PAYLOAD.get("verification_context", {{}})
module_dir = PAYLOAD.get("module_dir", "")
if module_dir and module_dir not in sys.path:
    sys.path.insert(0, module_dir)
from agent.automation_helpers import AutomationHelpers
_automation = AutomationHelpers()

def _choose_document_format(content: str, preferred_format: str = "auto", title: str = "") -> str:
    preferred = (preferred_format or "auto").strip().lower()
    if preferred in {{"txt", "md", "pdf"}}:
        if preferred != "pdf" or _can_write_pdf():
            return preferred
        return "md" if ("#" in content or "- " in content or title) else "txt"
    normalized = content or ""
    if title or "## " in normalized or normalized.count("\\n- ") >= 2 or normalized.count("\\n#") >= 1:
        return "md"
    if len(normalized) > 2500 and _can_write_pdf():
        return "pdf"
    return "txt"

def _can_write_pdf() -> bool:
    try:
        import reportlab  # noqa: F401
        return True
    except Exception:
        return False

def _write_simple_pdf(path: str, content: str, title: str = ""):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas
    font_name = "Helvetica"
    for candidate_name, candidate_path in [("MalgunGothic", r"C:\\Windows\\Fonts\\malgun.ttf"), ("AppleGothic", r"C:\\Windows\\Fonts\\malgun.ttf")]:
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
        line = raw_line.replace("\\t", "    ")
        wrapped = textwrap.wrap(line, width=52) or [""]
        for segment in wrapped:
            if y < 50:
                c.showPage()
                c.setFont(font_name, 11)
                y = height - 50
            c.drawString(40, y, segment)
            y -= 16
    c.save()

def save_document(directory: str, base_name: str, content: str, preferred_format: str = "auto", title: str = "") -> str:
    os.makedirs(directory, exist_ok=True)
    doc_format = _choose_document_format(content, preferred_format=preferred_format, title=title)
    safe_base = re.sub(r'[^A-Za-z0-9._-]+', '_', base_name).strip("._") or "document"
    path = os.path.join(directory, f"{{safe_base}}.{{doc_format}}")
    if doc_format == "pdf":
        _write_simple_pdf(path, content, title=title)
    elif doc_format == "md":
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    else:
        plain = re.sub(r'^\\s*#+\\s*', '', content, flags=re.MULTILINE)
        plain = re.sub(r'^\\s*[-*]\\s+', '- ', plain, flags=re.MULTILINE)
        with open(path, "w", encoding="utf-8") as f:
            f.write(plain)
    return path

try:
    from services.web_tools import web_search, web_fetch
except ImportError:
    web_search = None
    web_fetch = None

try:
    from agent.file_tools import (
        rename_file, merge_text_files, organize_folder_by_extension,
        analyze_data_file, generate_markdown_report, detect_file_set,
        batch_rename_files,
    )
except Exception:
    rename_file = None
    merge_text_files = None
    organize_folder_by_extension = None
    analyze_data_file = None
    generate_markdown_report = None
    detect_file_set = None
    batch_rename_files = None

execution_globals = {{
    "os": os,
    "sys": sys,
    "subprocess": subprocess,
    "threading": threading,
    "logging": logging,
    "time": time,
    "webbrowser": webbrowser,
    "datetime": datetime,
    "desktop_path": desktop_path,
    "step_outputs": step_outputs,
    "verification_context": verification_context,
    "save_document": save_document,
    "choose_document_format": _choose_document_format,
    "open_url": _automation.open_url,
    "open_path": _automation.open_path,
    "launch_app": _automation.launch_app,
    "wait_seconds": _automation.wait_seconds,
    "click_screen": _automation.click_screen,
    "click_image": _automation.click_image,
    "is_image_visible": _automation.is_image_visible,
    "move_mouse": _automation.move_mouse,
    "type_text": _automation.type_text,
    "press_keys": _automation.press_keys,
    "hotkey": _automation.hotkey,
    "take_screenshot": _automation.screenshot,
    "write_clipboard": _automation.write_clipboard,
    "read_clipboard": _automation.read_clipboard,
    "get_active_window_title": _automation.get_active_window_title,
    "find_window": _automation.find_window,
    "focus_window": _automation.focus_window,
    "wait_for_window": _automation.wait_for_window,
    "browser_login": _automation.browser_login,
    "get_browser_state": _automation.get_browser_state,
    "get_browser_current_url": _automation.get_browser_current_url,
    "get_desktop_state": _automation.get_desktop_state,
    "get_learned_strategies": _automation.get_learned_strategies,
    "get_learned_strategy_summary": _automation.get_learned_strategy_summary,
    "get_planning_snapshot": _automation.get_planning_snapshot,
    "get_planning_snapshot_summary": _automation.get_planning_snapshot_summary,
    "list_open_windows": _automation.list_open_windows,
    "wait_for_download": _automation.wait_for_download,
    "suggest_browser_actions": _automation.suggest_browser_actions,
    "build_adaptive_browser_plan": _automation.build_adaptive_browser_plan,
    "build_resilient_browser_plans": _automation.build_resilient_browser_plans,
    "run_browser_actions": _automation.run_browser_actions,
    "run_adaptive_browser_workflow": _automation.run_adaptive_browser_workflow,
    "run_resilient_browser_workflow": _automation.run_resilient_browser_workflow,
    "suggest_desktop_workflow": _automation.suggest_desktop_workflow,
    "build_adaptive_desktop_plan": _automation.build_adaptive_desktop_plan,
    "build_resilient_desktop_plans": _automation.build_resilient_desktop_plans,
    "run_desktop_workflow": _automation.run_desktop_workflow,
    "run_adaptive_desktop_workflow": _automation.run_adaptive_desktop_workflow,
    "run_resilient_desktop_workflow": _automation.run_resilient_desktop_workflow,
    "rename_file": rename_file,
    "merge_files": merge_text_files,
    "organize_folder": organize_folder_by_extension,
    "analyze_data": analyze_data_file,
    "generate_report": generate_markdown_report,
    "detect_file_set": detect_file_set,
    "batch_rename_files": batch_rename_files,
}}
if web_search:
    execution_globals["web_search"] = web_search
if web_fetch:
    execution_globals["web_fetch"] = web_fetch
execution_globals["get_execution_history"] = lambda: []
execution_globals["get_last_execution"] = lambda: None
execution_globals["get_runtime_state"] = lambda: {{
    "active_window_title": _automation.get_active_window_title(),
    "open_window_titles": _automation.list_open_windows(),
    "browser_state": _automation.get_browser_state(),
    "desktop_state": _automation.get_desktop_state(),
    "learned_strategies": _automation.get_learned_strategies(),
    "learned_strategy_summary": _automation.get_learned_strategy_summary(),
    "planning_snapshot": _automation.get_planning_snapshot(),
    "planning_snapshot_summary": _automation.get_planning_snapshot_summary(),
    "last_execution_success": None,
    "last_execution_output": "",
    "last_execution_error": "",
}}
globals().update(execution_globals)

_capture = io.StringIO()
try:
    with contextlib.redirect_stdout(_capture), contextlib.redirect_stderr(_capture):
{indented_code}
    print(_capture.getvalue().strip(), end="")
except Exception:
    traceback.print_exc()
    sys.exit(1)
'''

    def _sanitize_runner_payload(self, extra_globals: Optional[dict]) -> dict:
        payload = {}
        for key, value in (extra_globals or {}).items():
            try:
                json.dumps(value, ensure_ascii=False)
            except TypeError:
                payload[key] = str(value)
            else:
                payload[key] = value
        return payload

    def _safe_unlink(self, path: str):
        try:
            if path and os.path.exists(path):
                os.unlink(path)
        except OSError as e:
            logging.debug(f"[Executor] 임시 파일 삭제 실패: {e}")

    def _build_shell_command(self, command: str) -> List[str]:
        normalized = (command or "").strip()
        if sys.platform == "win32":
            return [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                normalized,
            ]
        return ["bash", "-lc", normalized]


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
