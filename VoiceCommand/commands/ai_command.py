from commands.base_command import BaseCommand
import json
import logging
import os
import re
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from agent.assistant_text_utils import (
    clean_tool_artifact_text,
    contains_specific_goal_markers,
    is_generic_agent_explanation,
    resolve_agent_task_goal,
)
from agent.autonomous_executor import get_executor, ExecutionResult
from agent.agent_orchestrator import get_orchestrator, AgentRunResult


class AICommand(BaseCommand):
    """AI 어시스턴트 대화 명령 (기본/fallback)"""
    priority = 100
    _KR_NUM = {
        "한": 1,
        "두": 2,
        "세": 3,
        "네": 4,
        "다섯": 5,
        "여섯": 6,
        "일곱": 7,
        "여덟": 8,
        "아홉": 9,
        "열": 10,
        "반": 0.5,
    }
    _COMPLEX_TASK_KEYWORDS = (
        "저장", "정리", "요약", "보고서", "리포트", "분석", "검색", "찾아",
        "만들", "생성", "열어", "실행", "복사", "이동", "삭제", "로그인",
        "브라우저", "파일", "폴더", "문서", "다운로드", "자동화",
        "보안", "점검", "진단", "검사",
        "설치", "업데이트", "업그레이드", "백업", "복원",
        "관리", "모니터링", "알림", "알려줘", "확인해줘",
        "스케줄", "예약", "반복", "매일", "매주",
        "스크린샷", "캡처", "녹화", "클립보드",
    )
    _SIMPLE_CHAT_KEYWORDS = (
        "안녕", "고마워", "감사", "잘자", "반가", "미안", "사랑", "농담",
        "몇 시", "시간", "날씨", "볼륨", "음악", "노래", "타이머",
    )
    _SHUTDOWN_KEYWORDS = ("컴퓨터", "pc", "시스템", "윈도우")
    _SCHEDULE_PATTERN_STRINGS = (
        # 복합 상대 시간 (순서 중요: 긴 표현을 먼저 매칭)
        r'(\d+\s*시간\s*\d+\s*분\s*\d+\s*초\s*(?:후|뒤))',
        r'(\d+\s*시간\s*\d+\s*분\s*(?:후|뒤))',
        r'(\d+\s*시간\s*\d+\s*초\s*(?:후|뒤))',
        r'(\d+\s*분\s*\d+\s*초\s*(?:후|뒤))',
        # 단일 상대 시간
        r'(\d+\s*일\s*(?:후|뒤))',
        r'(반\s*시간\s*(?:후|뒤))',
        r'([한두세네다섯여섯일곱여덟아홉열]\s*시간\s*(?:후|뒤))',
        r'(\d+\s*시간\s*(?:후|뒤))',
        r'(\d+\s*분\s*(?:후|뒤))',
        r'(\d+\s*초\s*(?:후|뒤))',
        r'(매시간)',
        r'(매일\s*(?:오전|오후)?\s*\d{1,2}시(?:\s*\d{1,2}분)?\s*에?)',
        r'(내일\s*(?:오전|오후)?\s*\d{1,2}시(?:\s*\d{1,2}분)?\s*에?)',
        r'((?:오늘\s*)?(?:오전|오후)\s*\d{1,2}시(?:\s*\d{1,2}분)?\s*에?)',
        r'((?:오늘\s*)?\d{1,2}시(?:\s*\d{1,2}분)?\s*에?)',
        r'(\d{1,2}\s*분에)',
    )
    # 매 호출마다 재컴파일을 방지하기 위해 클래스 로드 시 한 번만 컴파일
    _SCHEDULE_PATTERNS = tuple(re.compile(p, re.IGNORECASE) for p in _SCHEDULE_PATTERN_STRINGS)

    def __init__(self, ai_assistant, tts_func, learning_mode_ref):
        self.ai_assistant = ai_assistant
        self.tts_wrapper = tts_func
        self.learning_mode_ref = learning_mode_ref
        self.executor = get_executor(tts_func)
        self.orchestrator = get_orchestrator(tts_func)
        self._exec_lock = threading.Lock()
        self._current_goal = ""          # _handle_python/shell에서 self-fix 목표로 사용

        # 능동적 스케줄러 초기화 (늦은 바인딩으로 순환 임포트 방지)
        try:
            from agent.proactive_scheduler import get_scheduler
            self.scheduler = get_scheduler(tts_func)
            self.scheduler.set_orchestrator_func(self.orchestrator.run)
        except Exception as e:
            logging.warning("[AICommand] 스케줄러 초기화 실패: %s", e)
            self.scheduler = None

        self._plugin_handlers: Dict[str, Callable] = {}
        self._dispatch = self._build_dispatch_table()

    def matches(self, text: str) -> bool:
        return True

    # ── 디스패치 테이블 ─────────────────────────────────────────────────────────

    def _build_dispatch_table(self) -> Dict[str, Callable]:
        table = {
            "play_youtube":          self._handle_play_youtube,
            "set_timer":             self._handle_set_timer,
            "cancel_timer":          self._handle_cancel_timer,
            "get_weather":           self._handle_get_weather,
            "adjust_volume":         self._handle_adjust_volume,
            "get_current_time":      self._handle_get_current_time,
            "shutdown_computer":     self._handle_shutdown_computer,
            "get_screen_status":     self._handle_get_screen_status,
            "execute_python_code":      self._handle_python,
            "execute_shell_command":    self._handle_shell,
            "run_agent_task":           self._handle_agent_task,
            "web_search":               self._handle_web_search,
            "web_fetch":                self._handle_web_fetch,
            "mcp_call":                 self._handle_mcp_call,
            "schedule_task":            self._handle_schedule_task,
            "cancel_scheduled_task":    self._handle_cancel_scheduled_task,
            "list_scheduled_tasks":     self._handle_list_scheduled_tasks,
        }
        for name, handler in self._plugin_handlers.items():
            if name not in table:
                table[name] = handler
        return table

    def register_plugin_tool_handler(self, tool_name: str, handler: Callable) -> None:
        """플러그인 도구 핸들러를 등록하고 디스패치 테이블을 갱신한다."""
        self._plugin_handlers[tool_name] = handler
        self._dispatch = self._build_dispatch_table()

    def unregister_plugin_tool_handler(self, tool_name: str) -> None:
        self._plugin_handlers.pop(tool_name, None)
        self._dispatch = self._build_dispatch_table()

    # ── 핸들러들 ────────────────────────────────────────────────────────────────

    def _handle_play_youtube(self, args: dict) -> Optional[str]:
        from core.VoiceCommand import execute_command
        query = args.get("query", "").strip()
        if not query:
            self.tts_wrapper("어떤 음악이나 영상을 재생할까요?")
            return None
        execute_command(f"유튜브 {query} 재생")
        return None

    def _handle_set_timer(self, args: dict) -> Optional[str]:
        # LLM이 종료 요청에 set_timer를 잘못 호출한 경우 → SystemCommand로 리다이렉트
        if self._is_shutdown_request(self._current_goal) and self._extract_schedule_phrase(self._current_goal):
            from core.VoiceCommand import execute_command
            execute_command(self._current_goal)
            return None

        from core.VoiceCommand import timer_manager

        minutes = float(args.get("minutes", 0) or 0)
        seconds = float(args.get("seconds", 0) or 0)
        name = str(args.get("name", "") or "").strip()
        total_minutes = minutes + (seconds / 60.0)
        if total_minutes <= 0:
            self.tts_wrapper("타이머 시간을 말씀해 주세요.")
            return None
        try:
            timer_manager.set_timer(total_minutes, name=name)
        except ValueError as exc:
            return str(exc)
        return None

    def _handle_cancel_timer(self, args: dict) -> Optional[str]:
        from core.VoiceCommand import timer_manager

        timer_manager.cancel_timer(name=str(args.get("name", "") or ""))
        return None

    def _handle_get_weather(self, args: dict) -> Optional[str]:
        from core.VoiceCommand import execute_command
        execute_command("날씨 알려줘")
        return None

    def _handle_adjust_volume(self, args: dict) -> Optional[str]:
        from core.VoiceCommand import execute_command
        direction = args.get("direction", "up")
        cmd_map = {"up": "볼륨 올려", "down": "볼륨 내려", "mute": "볼륨 음소거"}
        execute_command(cmd_map.get(direction, "볼륨 올려"))
        return None

    def _handle_get_current_time(self, args: dict) -> Optional[str]:
        now = datetime.now()
        am_pm = "오전" if now.hour < 12 else "오후"
        hour = now.hour if now.hour <= 12 else now.hour - 12
        if hour == 0:
            hour = 12
        if now.minute:
            return f"현재 시간은 {am_pm} {hour}시 {now.minute}분입니다."
        return f"현재 시간은 {am_pm} {hour}시입니다."

    def _handle_shutdown_computer(self, args: dict) -> Optional[str]:
        scheduled = self._maybe_schedule_shutdown_from_goal(self._current_goal)
        if scheduled:
            return scheduled
        from core.VoiceCommand import execute_command
        execute_command("컴퓨터 종료")
        return None

    def _handle_get_screen_status(self, args: dict) -> Optional[str]:
        """현재 화면 상태 (작업표시줄, 전체화면 등) 정보를 수집하여 반환"""
        try:
            from core.VoiceCommand import _state
            character_widget = _state.character_widget
            if not character_widget:
                return "캐릭터 위젯이 아직 초기화되지 않았습니다."

            geom = character_widget.get_screen_geometry()
            from PySide6.QtWidgets import QApplication
            full_geom = QApplication.primaryScreen().geometry()
            
            is_full = (geom.width() >= full_geom.width() - 10 and 
                       geom.height() >= full_geom.height() - 10)
            
            status = f"현재 화면 상태: {'[전체화면 모드]' if is_full else '[일반 모드]'}\n"
            status += f"- 가용 화면 크기: {geom.width()}x{geom.height()}\n"
            status += f"- 전체 모니터 크기: {full_geom.width()}x{full_geom.height()}\n"
            
            if not is_full:
                status += "- 현재 작업표시줄이 화면의 일부를 차지하고 있어, 저는 작업표시줄 바로 위에 서 있습니다."
            else:
                status += "- 현재 게임이나 영상이 전체화면으로 실행 중이거나 작업표시줄이 숨겨져 있어, 저는 화면 맨 아래 바닥에 서 있습니다."
            
            return status
        except Exception as e:
            return f"화면 상태 확인 중 오류 발생: {e}"

    def _handle_python(self, args: dict) -> Optional[str]:
        """단일 Python 코드 실행 — 실패 시 오케스트레이터가 자동 수정 후 재시도"""
        code = args.get("code", "").strip()
        if not code:
            return None
        result: ExecutionResult = self.orchestrator.execute_with_self_fix(
            code, "python", self._current_goal
        )
        return self._result_to_korean(result)

    def _handle_shell(self, args: dict) -> Optional[str]:
        """단일 Shell 명령 실행 — 실패 시 오케스트레이터가 자동 수정 후 재시도"""
        command = args.get("command", "").strip()
        if not command:
            return None
        result: ExecutionResult = self.orchestrator.execute_with_self_fix(
            command, "shell", self._current_goal
        )
        return self._result_to_korean(result)

    def _handle_agent_task(self, args: dict) -> Optional[str]:
        """
        복잡한 다단계 목표 — Plan→Execute+Self-Fix→Verify 루프 실행.
        달성 여부, 단계 수, 요약을 반환.
        """
        goal = self._resolve_agent_task_goal(args)
        if not goal:
            return None
        self.tts_wrapper("복잡한 목표를 단계별로 처리할게요.")
        run_result: AgentRunResult = self.orchestrator.run(goal)
        report_path = ""
        if self._is_developer_agent_goal(goal):
            report_path = self._save_agent_run_report(goal, run_result)
        return self._agent_run_to_korean(run_result, report_path=report_path)

    def _handle_web_search(self, args: dict) -> Optional[str]:
        """인터넷 검색 후 결과 반환"""
        query = args.get("query", "").strip()
        if not query:
            return None
        max_results = int(args.get("max_results", 5))
        try:
            from services.web_tools import web_search
            logging.info("[AICommand] web_search 실행: query=%r, max_results=%s", query, max_results)
            result = web_search(query, max_results=max_results)
            return f"[웹 검색 결과]\n{result}\n\n지시사항: 위 검색 결과를 바탕으로 사용자의 원래 질문에 대해 구어체로 3문장 이내로 요약하여 자연스럽게 대답해주세요."
        except Exception as e:
            logging.error("web_search 오류: %s", e)
            return f"검색 오류: {e}"

    def _handle_web_fetch(self, args: dict) -> Optional[str]:
        """URL 내용 가져오기"""
        url = args.get("url", "").strip()
        if not url:
            return None
        try:
            from services.web_tools import web_fetch
            result = web_fetch(url)
            return result
        except Exception as e:
            logging.error("web_fetch 오류: %s", e)
            return f"페이지 로드 오류: {e}"

    def _handle_mcp_call(self, args: dict) -> Optional[str]:
        endpoint = str(args.get("endpoint", "") or "").strip()
        tool_name = str(args.get("tool", "") or "").strip()
        raw_arguments = args.get("arguments", {})
        if not endpoint or not tool_name:
            from i18n.translator import _

            return _("MCP 호출 실패: endpoint와 tool이 필요합니다.")

        if isinstance(raw_arguments, str):
            try:
                raw_arguments = json.loads(raw_arguments)
            except json.JSONDecodeError:
                raw_arguments = {"input": raw_arguments}
        if raw_arguments is None:
            raw_arguments = {}
        if not isinstance(raw_arguments, dict):
            raw_arguments = {"input": raw_arguments}

        try:
            from agent.mcp_client import get_mcp_pool

            return get_mcp_pool().call(endpoint, tool_name, raw_arguments)
        except Exception as exc:
            from i18n.translator import _

            logging.error("mcp_call 오류: %s", exc, exc_info=True)
            return _("MCP 도구 호출 중 오류가 발생했습니다: {error}").format(error=exc)

    def _handle_schedule_task(self, args: dict) -> Optional[str]:
        """작업 예약"""
        goal = args.get("goal", "").strip()
        when = args.get("when", "").strip()
        if not goal or not when:
            return "예약할 작업과 시간을 알려주세요."

        # 종료/재시작 goal → 에이전트 루프 대신 SystemCommand 직접 라우팅
        _SHUTDOWN_GOALS = ("컴퓨터 종료", "pc 종료", "시스템 종료", "전원 끄기", "shutdown")
        _RESTART_GOALS  = ("컴퓨터 재시작", "재부팅", "restart")
        goal_lower = goal.lower()
        if any(k in goal_lower for k in _SHUTDOWN_GOALS):
            from core.VoiceCommand import execute_command
            execute_command(f"{when}에 컴퓨터 꺼줘")
            return None
        if any(k in goal_lower for k in _RESTART_GOALS):
            from core.VoiceCommand import execute_command
            execute_command(f"{when}에 컴퓨터 재시작해줘")
            return None

        if self.scheduler is None:
            return "스케줄러를 사용할 수 없습니다."

        next_run, repeat, repeat_seconds = self._parse_schedule(when)
        if next_run is None:
            return f"'{when}' 시간 표현을 이해하지 못했어요. '5분 뒤', '11시 30분에', '매일 오전 9시' 형식으로 말씀해 주세요."

        task_id = self.scheduler.schedule(
            goal=goal,
            next_run_dt=next_run,
            desc=when,
            repeat=repeat,
            repeat_sec=repeat_seconds,
        )
        repeat_str = " (반복)" if repeat else ""
        formatted = self._format_datetime_kr(next_run)
        return f"작업 예약 완료 (ID: {task_id}){repeat_str}. {formatted}에 실행됩니다."

    def _handle_cancel_scheduled_task(self, args: dict) -> Optional[str]:
        """예약 작업 취소"""
        task_id = args.get("task_id", "").strip()
        if not task_id:
            return "취소할 작업 ID를 알려주세요."
        if self.scheduler is None:
            return "스케줄러를 사용할 수 없습니다."
        success = self.scheduler.cancel(task_id)
        return f"작업 {task_id}가 취소되었습니다." if success else f"ID '{task_id}'에 해당하는 작업을 찾을 수 없어요."

    def _handle_list_scheduled_tasks(self, args: dict) -> Optional[str]:
        """예약 작업 목록 조회"""
        if self.scheduler is None:
            return "스케줄러를 사용할 수 없습니다."
        tasks = self.scheduler.list_tasks()
        if not tasks:
            return "현재 예약된 작업이 없습니다."
        lines = [f"예약된 작업 {len(tasks)}개:"]
        for t in tasks:
            try:
                dt = datetime.fromisoformat(t.next_run)
                time_str = self._format_datetime_kr(dt)
            except Exception as exc:
                logging.debug("[AICommand] 예약 시간 파싱 실패, 원본 문자열 사용: %s", exc)
                time_str = t.next_run
            repeat_str = " [반복]" if t.repeat else ""
            lines.append(f"  [{t.task_id}] {time_str}{repeat_str} — {t.goal[:40]}")
        return "\n".join(lines)

    # ── 스케줄 파싱 ──────────────────────────────────────────────────────────────

    def _parse_schedule(self, when_kr: str) -> Tuple[Optional[datetime], bool, int]:
        """
        한국어 시간 표현을 (next_run_dt, repeat, repeat_seconds) 튜플로 변환.
        파싱 실패 시 (None, False, 0) 반환.
        """
        now = datetime.now()
        normalized = re.sub(r"\s+", " ", (when_kr or "").strip())

        relative_target = self._parse_relative_schedule(normalized, now)
        if relative_target is not None:
            return relative_target, False, 0

        minute_target = self._parse_minute_of_hour_schedule(normalized, now)
        if minute_target is not None:
            return minute_target, False, 0
            
        # "매시간" (1시간 마다 반복)
        if "매시간" in normalized.replace(" ", ""):
            return now + timedelta(hours=1), True, 3600

        # "매일 [오전|오후] N시 [M분]" → 반복 (매 24시간)
        m = re.search(r'매일\s*(오전|오후)?\s*(\d{1,2})시(?:\s*(\d{1,2})분)?\s*에?', normalized)
        if m:
            hour = self._resolve_hour(m.group(1), int(m.group(2)))
            minute = int(m.group(3) or 0)
            if hour is None or minute > 59:
                return None, False, 0
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            return target, True, 86400

        # "내일 [오전|오후] N시 [M분]"
        m = re.search(r'내일\s*(오전|오후)?\s*(\d{1,2})시(?:\s*(\d{1,2})분)?\s*에?', normalized)
        if m:
            hour = self._resolve_hour(m.group(1), int(m.group(2)))
            minute = int(m.group(3) or 0)
            if hour is None or minute > 59:
                return None, False, 0
            target = (now + timedelta(days=1)).replace(hour=hour, minute=minute, second=0, microsecond=0)
            return target, False, 0

        # "[오늘] [오전|오후] N시 [M분]"
        m = re.search(r'(?:오늘\s*)?(오전|오후)?\s*(\d{1,2})시(?:\s*(\d{1,2})분)?\s*에?', normalized)
        if m:
            hour = self._resolve_hour(m.group(1), int(m.group(2)))
            minute = int(m.group(3) or 0)
            if hour is None or minute > 59:
                return None, False, 0
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= now and "오늘" not in normalized:
                target += timedelta(days=1)
            return target, False, 0

        return None, False, 0

    def _parse_relative_schedule(self, when_kr: str, now: datetime) -> Optional[datetime]:
        if re.search(r'반\s*시간\s*(?:후|뒤)', when_kr):
            return now + timedelta(minutes=30)

        patterns = (
            (r'(\d+)\s*일\s*(?:후|뒤)', "days"),
            (r'(\d+)\s*시간\s*(?:후|뒤)', "hours"),
            (r'(\d+)\s*분\s*(?:후|뒤)', "minutes"),
            (r'(\d+)\s*초\s*(?:후|뒤)', "seconds"),
        )
        total = timedelta()
        found = False
        for pattern, unit in patterns:
            match = re.search(pattern, when_kr)
            if match:
                total += timedelta(**{unit: int(match.group(1))})
                found = True
        kr_hour = re.search(r'([한두세네다섯여섯일곱여덟아홉열])\s*시간\s*(?:후|뒤)', when_kr)
        if kr_hour:
            total += timedelta(hours=self._KR_NUM.get(kr_hour.group(1), 0))
            found = True
        return now + total if found else None

    def _parse_minute_of_hour_schedule(self, when_kr: str, now: datetime) -> Optional[datetime]:
        if "시" in when_kr:
            return None
        match = re.search(r'(\d{1,2})\s*분에', when_kr)
        if not match:
            return None
        minute = int(match.group(1))
        if minute > 59:
            return None
        target = now.replace(minute=minute, second=0, microsecond=0)
        if target <= now:
            target += timedelta(hours=1)
        return target

    def _resolve_hour(self, ampm: Optional[str], hour: int) -> Optional[int]:
        if hour < 0 or hour > 23:
            return None
        if ampm == "오전":
            return 0 if hour == 12 else hour
        if ampm == "오후":
            if hour == 12:
                return 12
            return hour + 12 if hour < 12 else None
        return hour

    def _format_datetime_kr(self, dt: datetime) -> str:
        ampm = "오전" if dt.hour < 12 else "오후"
        hour = dt.hour if dt.hour <= 12 else dt.hour - 12
        if hour == 0:
            hour = 12
        if dt.minute:
            return f"{dt.month}월 {dt.day}일 {ampm} {hour}시 {dt.minute}분"
        return f"{dt.month}월 {dt.day}일 {ampm} {hour}시"

    def _is_developer_agent_goal(self, goal: str) -> bool:
        try:
            planner = getattr(self.orchestrator, "planner", None)
            return bool(planner and hasattr(planner, "is_developer_goal") and planner.is_developer_goal(goal))
        except Exception as exc:
            logging.debug("[AICommand] 개발자 목표 판별 실패, 일반 목표로 처리: %s", exc)
            return False

    def _resolve_user_report_dir(self) -> Path:
        user_home = Path(os.environ.get("USERPROFILE", str(Path.home())))
        desktop = user_home / "Desktop"
        report_root = desktop if desktop.is_dir() else user_home
        report_dir = report_root / "Ari Reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        return report_dir

    def _save_agent_run_report(self, goal: str, run: AgentRunResult) -> str:
        try:
            report_dir = self._resolve_user_report_dir()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            report_path = report_dir / f"agent_run_{timestamp}.md"
            saved_path = self._extract_saved_path_from_agent_run(run)
            lines = [
                "# Ari Agent Execution Report",
                "",
                f"- Generated: {datetime.now().isoformat(timespec='seconds')}",
                f"- Goal: {goal}",
                f"- Status: {'success' if run.achieved else 'failure'}",
                f"- Iterations: {run.total_iterations}",
                f"- Summary: {self._shorten_user_summary(run.summary, limit=200)}",
            ]
            if saved_path:
                lines.append(f"- Task artifact: {saved_path}")
            lines.extend(["", "## Steps", ""])
            if not run.step_results:
                lines.append("_No executed steps._")
            for index, step_result in enumerate(run.step_results, start=1):
                step = step_result.step
                exec_result = step_result.exec_result
                content_preview = (step.content or "").strip()
                output_preview = (exec_result.output or exec_result.error or "").strip()
                if len(content_preview) > 500:
                    content_preview = content_preview[:500].rstrip() + "..."
                if len(output_preview) > 800:
                    output_preview = output_preview[:800].rstrip() + "..."
                lines.extend([
                    f"### {index}. {step.description_kr}",
                    f"- Type: `{step.step_type}`",
                    f"- Success: `{bool(exec_result.success)}`",
                    f"- Attempt: `{step_result.attempt}`",
                    f"- Auto-fix: `{bool(step_result.was_fixed)}`",
                ])
                if content_preview:
                    lines.extend(["", "```text", content_preview, "```"])
                if output_preview:
                    lines.extend(["", "```text", output_preview, "```"])
                state_delta = str(getattr(exec_result, "state_delta_summary", "") or "").strip()
                if state_delta:
                    lines.extend(["", "```text", state_delta[:500], "```"])
                lines.append("")
            report_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
            return str(report_path)
        except Exception as exc:
            logging.warning("[AICommand] 실행 보고서 저장 실패: %s", exc)
            return ""

    def _describe_report_location(self, report_path: str) -> str:
        if not report_path:
            return ""
        path = Path(report_path)
        user_home = Path(os.environ.get("USERPROFILE", str(Path.home())))
        desktop = user_home / "Desktop"
        if desktop.is_dir():
            try:
                path.relative_to(desktop)
                return f"바탕화면 {path.parent.name} 폴더의 {path.name}"
            except ValueError:
                return f"{path.parent.name} 폴더의 {path.name}"
        return f"{path.parent.name} 폴더의 {path.name}"

    # ── 결과 변환 ────────────────────────────────────────────────────────────────

    def _result_to_korean(self, result: ExecutionResult) -> Optional[str]:
        if not result.success:
            if result.error == "사용자 취소":
                return "사용자가 실행을 취소했습니다."
            return f"실행 실패: {result.error[:80]}" if result.error else "실행에 실패했습니다."
        if result.output:
            return f"실행 완료. 출력: {result.output[:200]}"
        return "실행이 완료되었습니다."

    def _agent_run_to_korean(self, run: AgentRunResult, report_path: str = "") -> str:
        steps_done = len(run.step_results)
        saved_path = self._extract_saved_path_from_agent_run(run)
        if run.achieved:
            if saved_path:
                folder_name = saved_path.rsplit("\\", 1)[0].rsplit("\\", 1)[-1]
                file_name = saved_path.rsplit("\\", 1)[-1]
                message = f"작업 완료. {folder_name} 폴더에 {file_name}를 저장했습니다."
            else:
                message = f"작업 완료 ({steps_done}단계). {self._shorten_user_summary(run.summary)}"
        else:
            message = f"작업 실패 ({run.total_iterations}회 시도). {self._shorten_user_summary(run.summary)}"
        if report_path:
            message += f" 실행 보고서는 {self._describe_report_location(report_path)}에 저장했습니다."
        return message

    def _shorten_user_summary(self, summary: str, limit: int = 90) -> str:
        normalized = re.sub(r'\s+', ' ', (summary or '').strip())
        if len(normalized) <= limit:
            return normalized
        for separator in (". ", "입니다.", "어요.", "했다."):
            idx = normalized.find(separator)
            if 0 < idx < limit:
                return normalized[:idx + len(separator)].strip()
        return normalized[:limit].rstrip() + "..."

    def _extract_saved_path_from_agent_run(self, run: AgentRunResult) -> str:
        for step_result in reversed(run.step_results):
            exec_result = getattr(step_result, "exec_result", None)
            output = str(getattr(exec_result, "output", "") or "")
            if not output:
                continue
            try:
                payload = json.loads(output)
            except Exception as exc:
                logging.debug("[AICommand] agent output JSON 파싱 실패, 텍스트 경로 추출 시도: %s", exc)
                payload = None
            if isinstance(payload, dict):
                for key in ("saved_path", "report_path", "output_path"):
                    saved_path = str(payload.get(key, "") or "")
                    if saved_path:
                        return saved_path
            for line in output.splitlines():
                lowered = line.lower()
                if not any(token in lowered for token in ("saved_path", "report_path", "output_path", "저장", "saved")):
                    continue
                path_match = re.search(r'([A-Za-z]:\\[^\r\n]+?\.(?:md|txt|pdf))', line)
                if path_match:
                    return path_match.group(1)
        return ""

    def _is_generic_agent_explanation(self, text: str) -> bool:
        return is_generic_agent_explanation(text)

    def _contains_specific_goal_markers(self, text: str) -> bool:
        return contains_specific_goal_markers(text)

    def _resolve_agent_task_goal(self, args: dict) -> str:
        goal = str(args.get("goal", "") or "").strip()
        explanation = str(args.get("explanation", "") or "").strip()
        return resolve_agent_task_goal(goal, explanation)

    def _sanitize_user_facing_text(self, message: Optional[str]) -> str:
        return clean_tool_artifact_text(message or "", discard_short_text=True)

    def _emit_user_message(self, message: Optional[str]) -> None:
        cleaned = self._sanitize_user_facing_text(message)
        if cleaned:
            self.tts_wrapper(cleaned)

    def _get_skill_context(self, text: str) -> dict:
        try:
            from agent.skill_manager import get_skill_manager

            return get_skill_manager().build_match_context(text)
        except Exception as exc:
            logging.debug("[AICommand] 스킬 컨텍스트 조회 실패: %s", exc)
            return {
                "skills": [],
                "prompt": "",
                "required_tool_names": [],
                "preferred_tool": "",
                "force_web_search": False,
                "escalate_to_agent": False,
                "search_query_template": "",
            }

    def _get_primary_skill_name(self, skill_ctx: dict) -> str:
        skills = list(skill_ctx.get("skills", []) or [])
        if not skills:
            return ""
        return str(getattr(skills[0], "name", "") or "")

    def _get_current_language(self) -> str:
        try:
            from i18n.translator import get_language

            return get_language()
        except Exception as exc:
            logging.debug("[AICommand] 언어 조회 실패, ko 기본값 사용: %s", exc)
            return "ko"

    def _build_script_skill_escalation_tool_call(self, text: str, skill_ctx: dict) -> dict:
        try:
            from i18n.translator import _
        except Exception:
            _ = lambda message, **kwargs: message.format(**kwargs) if kwargs else message  # type: ignore[assignment]

        skill_name = self._get_primary_skill_name(skill_ctx) or "script"
        logging.info("[AICommand] script 스킬 감지 → run_agent_task 승격: %s", skill_name)
        return {
            "id": "skill_script_escalate",
            "name": "run_agent_task",
            "arguments": {
                "goal": text,
                "explanation": _("{name} 스킬 실행을 위해 에이전트 모드로 전환합니다.").format(name=skill_name),
            },
        }

    def _infer_data_source_from_tool_calls(self, tool_calls: List[dict]) -> str:
        tool_names = {str(tc.get("name", "") or "") for tc in tool_calls}
        if "web_search" in tool_names:
            return "web_search"
        if "mcp_call" in tool_names:
            return "mcp"
        if "run_agent_task" in tool_names:
            return "agent"
        return ""

    def _recover_tool_calls_from_response(self, user_text: str, response: Optional[str]) -> List[dict]:
        """LLM이 텍스트로만 '[run_agent_task 호출]' 같은 잔해를 남겼을 때 최소 복구."""
        if not response:
            return []

        recovered: List[dict] = []
        normalized_when = self._extract_schedule_phrase(user_text)

        web_search_patterns = (
            r'web_search\s*\(\s*"([^"]+)"',
            r"web_search\s*\(\s*'([^']+)'",
            r'web_search\s*\(\s*query\s*=\s*"([^"]+)"',
            r"web_search\s*\(\s*query\s*=\s*'([^']+)'",
            r'tools\.web_search\s*\(\s*query\s*=\s*"([^"]+)"',
            r"tools\.web_search\s*\(\s*query\s*=\s*'([^']+)'",
        )
        for pattern in web_search_patterns:
            match = re.search(pattern, response, flags=re.IGNORECASE)
            if not match:
                continue
            recovered.append({
                "id": "ai_command_recover_1",
                "name": "web_search",
                "arguments": {"query": match.group(1).strip(), "max_results": 5},
            })
            return recovered

        if (
            self._is_shutdown_request(user_text)
            and self._is_shutdown_confirmation_response(response)
        ):
            logging.info(
                "[AICommand] 종료 확인성 응답으로 판단해 텍스트 기반 도구 복구를 보류: %s",
                response[:80],
            )
            return recovered

        if re.search(r'set_timer', response, flags=re.IGNORECASE):
            if self._is_shutdown_request(user_text) and normalized_when:
                recovered.append({
                    "id": "ai_command_recover_1",
                    "name": "schedule_task",
                    "arguments": {"goal": "컴퓨터 종료", "when": normalized_when},
                })
                return recovered
            timer_args = self._extract_timer_args_from_response(response)
            if timer_args:
                recovered.append({
                    "id": "ai_command_recover_1",
                    "name": "set_timer",
                    "arguments": timer_args,
                })
                return recovered

        if re.search(r'run_agent_task', response, flags=re.IGNORECASE):
            recovered.append({
                "id": "ai_command_recover_1",
                "name": "run_agent_task",
                "arguments": {"goal": user_text, "explanation": "복합 작업을 실행할게요."},
            })
            return recovered

        if re.search(r'get_screen_status', response, flags=re.IGNORECASE):
            recovered.append({
                "id": "ai_command_recover_1",
                "name": "get_screen_status",
                "arguments": {},
            })
            return recovered

        if re.search(r'(컴퓨터|시스템|pc).*(종료|꺼)', response, flags=re.IGNORECASE) or re.search(r'shutdown', response, flags=re.IGNORECASE):
            if normalized_when:
                recovered.append({
                    "id": "ai_command_recover_1",
                    "name": "schedule_task",
                    "arguments": {"goal": "컴퓨터 종료", "when": normalized_when},
                })
                return recovered
            recovered.append({
                "id": "ai_command_recover_1",
                "name": "shutdown_computer",
                "arguments": {"confirmed": True},
            })
            return recovered

        if re.search(r'list_scheduled_tasks', response, flags=re.IGNORECASE):
            recovered.append({
                "id": "ai_command_recover_1",
                "name": "list_scheduled_tasks",
                "arguments": {},
            })
            return recovered

        shell_match = re.search(r'execute_shell_command\s*[:(]\s*(.+?)(?:\n|\[|$)', response, flags=re.IGNORECASE)
        if shell_match:
            recovered.append({
                "id": "ai_command_recover_1",
                "name": "execute_shell_command",
                "arguments": {
                    "command": shell_match.group(1).strip(),
                    "explanation": "명령을 실행합니다.",
                },
            })
            return recovered

        py_match = re.search(r'execute_python_code\s*[:(]\s*(.+?)(?:\n|\[|$)', response, flags=re.IGNORECASE)
        if py_match:
            recovered.append({
                "id": "ai_command_recover_1",
                "name": "execute_python_code",
                "arguments": {
                    "code": py_match.group(1).strip(),
                    "explanation": "코드를 실행합니다.",
                },
            })
            return recovered

        return recovered

    def _is_shutdown_confirmation_response(self, response: str) -> bool:
        """종료/전원 차단을 실제 실행하지 않고 사용자 재확인을 요청하는 응답인지 판별."""
        normalized = re.sub(r"\s+", " ", (response or "").strip()).lower()
        if not normalized:
            return False

        shutdown_mentions = (
            re.search(r"(컴퓨터|시스템|pc|전원).*(종료|꺼|끄)", normalized, flags=re.IGNORECASE)
            or re.search(r"shutdown", normalized, flags=re.IGNORECASE)
        )
        if not shutdown_mentions:
            return False

        confirmation_patterns = (
            r"(정말|진짜).*(꺼|끄|종료).*(까요|습니까|\?)",
            r"(꺼|끄|종료).*(드릴까요|할까요|해도\s*될까요|하시겠습니까|\?)",
            r"(진행\s*중인\s*작업|저장\s*안|중단됩니다).*(정말|꺼드릴까요|종료할까요|\?)",
            r"(확인|괜찮|준비).*(되면|되셨으면|말씀|답|확인)",
        )
        return any(
            re.search(pattern, normalized, flags=re.IGNORECASE)
            for pattern in confirmation_patterns
        )

    def _extract_schedule_phrase(self, text: str) -> str:
        normalized = (text or "").strip()
        if not normalized:
            return ""
        for pattern in self._SCHEDULE_PATTERNS:
            match = pattern.search(normalized)
            if match:
                return match.group(1).strip()
        return ""

    def _is_shutdown_request(self, text: str) -> bool:
        lowered = (text or "").lower()
        return (
            any(token in lowered for token in self._SHUTDOWN_KEYWORDS)
            and ("종료" in text or "꺼" in text)
        )

    def _extract_timer_args_from_response(self, response: str) -> Optional[dict]:
        match = re.search(
            r'set_timer[^>]*>\s*\{\s*"minutes"\s*:\s*(\d+)\s*,\s*"seconds"\s*:\s*(\d+)(?:\s*,\s*"name"\s*:\s*"([^"]*)")?\s*\}',
            response,
            flags=re.IGNORECASE,
        )
        if not match:
            return None
        return {
            "minutes": int(match.group(1)),
            "seconds": int(match.group(2)),
            "name": (match.group(3) or "").strip(),
        }

    def _maybe_schedule_shutdown_from_goal(self, goal_text: str) -> Optional[str]:
        when = self._extract_schedule_phrase(goal_text)
        if not when:
            return None
        if not self._is_shutdown_request(goal_text):
            return None
        return self._handle_schedule_task({"goal": "컴퓨터 종료", "when": when})

    def _should_escalate_to_agent_task(self, user_text: str, response: Optional[str]) -> bool:
        """도구 호출이 없을 때 복잡한 작업 요청을 에이전트 태스크로 승격할지 판단."""
        normalized = (user_text or "").strip()
        lower = normalized.lower()
        if not normalized:
            return False
        if any(token in lower for token in self._SIMPLE_CHAT_KEYWORDS):
            return False
        if len(normalized) < 8:
            return False

        has_complex_keyword = any(token in normalized for token in self._COMPLEX_TASK_KEYWORDS)
        has_complex_phrase = any(
            phrase in normalized for phrase in (
                "시스템 상태",
                "상태 확인",
                "보안 점검",
                "자체 보안 점검",
                "건강 점검",
                "헬스 체크",
                "폴더 정리",
            )
        )
        if not has_complex_keyword and not has_complex_phrase:
            return False

        generic_response = not response or any(
            phrase in response for phrase in (
                "이해하지 못", "무엇을 도와", "다시 말씀", "잘 모르겠", "죄송합니다",
                "잘 이해가", "정확히 어떤", "좀 더 구체적",
            )
        )
        return generic_response or self.learning_mode_ref.get("enabled", False)

    # ── 실행 ────────────────────────────────────────────────────────────────────

    def execute(self, text: str) -> None:
        self._run_interaction(text, self.tts_wrapper)

    def run_interaction(self, text: str, stream_callback: Optional[Callable[[str], None]] = None) -> str:
        """텍스트 UI용: 실제 도구 실행까지 포함한 응답 문자열 반환."""
        outputs: List[str] = []

        def collect(message: str):
            if message:
                outputs.append(str(message))

        self._run_interaction(text, collect, stream_callback=stream_callback)
        cleaned = [msg.strip() for msg in outputs if msg and msg.strip()]
        return "\n".join(cleaned)

    def _run_interaction(self, text: str, output_callback: Callable[[str], None], stream_callback: Optional[Callable[[str], None]] = None) -> None:
        if not self._exec_lock.acquire(blocking=False):
            logging.warning("AI 명령 실행 중 재진입 시도 무시: %s", text)
            return

        original_tts = self.tts_wrapper
        original_exec_tts = getattr(self.executor, "tts_wrapper", None)
        original_orch_tts = getattr(self.orchestrator, "tts", None)

        try:
            self.tts_wrapper = output_callback
            self.executor.tts_wrapper = output_callback
            self.orchestrator.tts = output_callback
            self._current_goal = text   # self-fix용 목표 텍스트 저장
            response = None
            tool_calls: List[dict] = []
            skill_ctx = self._get_skill_context(text)
            skill_used = self._get_primary_skill_name(skill_ctx)
            data_source = ""
            lang = self._get_current_language()

            if hasattr(self.ai_assistant, 'chat_with_tools'):
                if self.learning_mode_ref.get('enabled'):
                    self._record_user_pattern(text)

                if skill_ctx.get("escalate_to_agent"):
                    tool_calls = [self._build_script_skill_escalation_tool_call(text, skill_ctx)]
                else:
                    response, tool_calls = self._invoke_with_optional_stream(
                        self.ai_assistant.chat_with_tools,
                        text,
                        include_context=True,
                        stream_callback=stream_callback,
                    )

                if not tool_calls:
                    tool_calls = self._recover_tool_calls_from_response(text, response)
                    if tool_calls:
                        logging.warning(
                            "[AICommand] 텍스트 기반 도구 호출 복구: %s",
                            [tc.get("name") for tc in tool_calls],
                        )

                if not tool_calls and self._should_escalate_to_agent_task(text, response):
                    tool_calls = [{
                        "id": "ai_command_escalate_1",
                        "name": "run_agent_task",
                        "arguments": {
                            "goal": text,
                            "explanation": "복합 작업으로 판단되어 단계별 실행으로 전환할게요.",
                        },
                    }]
                    logging.info("[AICommand] 복합 요청을 run_agent_task로 자동 승격: %s", text[:80])

                if tool_calls:
                    data_source = self._infer_data_source_from_tool_calls(tool_calls)
                    # 도구 호출 전 자연스러운 안내 문장만 선행 출력
                    if response and self._should_emit_preface_response(response):
                        self._emit_user_message(response)

                    results = self._execute_tool_calls(tool_calls)

                    non_none = [r for r in results if r is not None]
                    followup = None
                    has_agent_task = any(tc.get("name") == "run_agent_task" for tc in tool_calls)
                    if non_none and hasattr(self.ai_assistant, 'feed_tool_result') and not has_agent_task:
                        followup = self._run_agentic_followup(
                            text,
                            tool_calls,
                            results,
                            stream_callback=stream_callback,
                        )
                    if followup:
                        self._emit_user_message(followup)
                        response = followup
                    elif non_none:
                        rendered_results = [str(result) for result in non_none]
                        for result in rendered_results:
                            self._emit_user_message(result)
                        response = "\n".join(rendered_results)
                else:
                    if response:
                        self._emit_user_message(response)

            elif hasattr(self.ai_assistant, 'chat'):
                response = self._invoke_with_optional_stream(
                    self.ai_assistant.chat,
                    text,
                    include_context=False,
                    stream_callback=stream_callback,
                )
                self._emit_user_message(response)
            else:
                response, _, _ = self.ai_assistant.process_query(text)
                self._emit_user_message(response)

            if response:
                logging.info("AI 응답: %s...", response[:50])

            if response:
                try:
                    from memory.conversation_history import add_conversation
                    add_conversation(
                        text,
                        response,
                        skill_used=skill_used,
                        data_source=data_source,
                        lang=lang,
                    )
                except Exception as exc:
                    logging.debug("대화 기록 저장 생략: %s", exc)

        except AttributeError as e:
            logging.error("AI 어시스턴트가 초기화되지 않았습니다: %s", e)
            self.tts_wrapper("AI 기능을 사용할 수 없습니다.")
        except Exception as e:
            logging.error("AI 응답 생성 오류: %s", e, exc_info=True)
            self.tts_wrapper("응답 생성 중 오류가 발생했습니다.")
        finally:
            self.tts_wrapper = original_tts
            self.executor.tts_wrapper = original_exec_tts
            self.orchestrator.tts = original_orch_tts
            self._exec_lock.release()

    def _execute_tool_calls(self, tool_calls: list) -> List[Optional[str]]:
        """디스패치 테이블 기반으로 tool calls 실행, 결과 리스트 반환"""
        results: List[Optional[str]] = []
        for tc in tool_calls:
            name = tc.get("name", "")
            args = tc.get("arguments", {})
            logging.info("AI tool 실행: %s %s", name, args)

            handler = self._dispatch.get(name)
            if handler:
                try:
                    result = handler(args)
                except Exception as e:
                    logging.error("tool 핸들러 오류 (%s): %s", name, e, exc_info=True)
                    result = f"오류: {e}"
                results.append(result)
            else:
                logging.warning("알 수 없는 tool: %s", name)
                results.append(None)
        return results

    def _run_agentic_followup(
        self,
        original_text: str,
        tool_calls: list,
        results: List[Optional[str]],
        stream_callback: Optional[Callable[[str], None]] = None,
    ) -> Optional[str]:
        """도구 실행 결과를 LLM에 피드백하고 최종 응답 문자열을 반환."""
        try:
            return self._invoke_with_optional_stream(
                self.ai_assistant.feed_tool_result,
                original_text,
                tool_calls,
                results,
                stream_callback=stream_callback,
            )
        except Exception as e:
            logging.error("에이전틱 후속 처리 오류: %s", e, exc_info=True)
            return None

    def _invoke_with_optional_stream(self, func: Callable, *args, stream_callback=None, **kwargs):
        if stream_callback:
            try:
                return func(*args, stream_callback=stream_callback, **kwargs)
            except TypeError as exc:
                message = str(exc)
                if "stream_callback" not in message and "unexpected keyword argument" not in message:
                    raise
        return func(*args, **kwargs)

    def _should_emit_preface_response(self, response: str) -> bool:
        normalized = (response or "").strip()
        if not normalized:
            return False
        if normalized.endswith("...") or normalized in {"...", "(평온)..."}:
            return False
        lowered = normalized.lower()
        if any(token in lowered for token in ("<function=", "shutdown_computer", "get_current_time", "run_agent_task")):
            return False
        if len(normalized) <= 8:
            return False
        return True

    def _record_user_pattern(self, user_input: str):
        try:
            from memory.user_context import get_context_manager
            context_mgr = get_context_manager()
            if any(word in user_input for word in ["날씨", "기온", "온도"]):
                context_mgr.record_command("weather")
            elif any(word in user_input for word in ["음악", "노래", "재생"]):
                context_mgr.record_command("music")
            elif any(word in user_input for word in ["시간", "몇 시"]):
                context_mgr.record_command("time")
        except Exception as e:
            logging.error("패턴 기록 실패: %s", e)
