from commands.base_command import BaseCommand
import logging
import re
import threading
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Tuple
from autonomous_executor import get_executor, ExecutionResult
from agent_orchestrator import get_orchestrator, AgentRunResult


class AICommand(BaseCommand):
    """AI 어시스턴트 대화 명령 (기본/fallback)"""

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
            from proactive_scheduler import get_scheduler
            self.scheduler = get_scheduler(tts_func)
            self.scheduler.set_orchestrator_func(self.orchestrator.run)
        except Exception as e:
            logging.warning(f"[AICommand] 스케줄러 초기화 실패: {e}")
            self.scheduler = None

        self._dispatch = self._build_dispatch_table()

    def matches(self, text: str) -> bool:
        return True

    # ── 디스패치 테이블 ─────────────────────────────────────────────────────────

    def _build_dispatch_table(self) -> Dict[str, Callable]:
        return {
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
            "schedule_task":            self._handle_schedule_task,
            "cancel_scheduled_task":    self._handle_cancel_scheduled_task,
            "list_scheduled_tasks":     self._handle_list_scheduled_tasks,
        }

    # ── 핸들러들 ────────────────────────────────────────────────────────────────

    def _handle_play_youtube(self, args: dict) -> Optional[str]:
        from VoiceCommand import execute_command
        query = args.get("query", "").strip()
        if not query:
            self.tts_wrapper("어떤 음악이나 영상을 재생할까요?")
            return None
        execute_command(f"유튜브 {query} 재생")
        return None

    def _handle_set_timer(self, args: dict) -> Optional[str]:
        from VoiceCommand import execute_command
        minutes = int(args.get("minutes", 0))
        seconds = int(args.get("seconds", 0))
        if minutes > 0 and seconds > 0:
            execute_command(f"{minutes}분 {seconds}초 타이머")
        elif minutes > 0:
            execute_command(f"{minutes}분 타이머")
        elif seconds > 0:
            execute_command(f"{seconds}초 타이머")
        else:
            self.tts_wrapper("타이머 시간을 말씀해 주세요.")
        return None

    def _handle_cancel_timer(self, args: dict) -> Optional[str]:
        from VoiceCommand import execute_command
        execute_command("타이머 취소")
        return None

    def _handle_get_weather(self, args: dict) -> Optional[str]:
        from VoiceCommand import execute_command
        execute_command("날씨 알려줘")
        return None

    def _handle_adjust_volume(self, args: dict) -> Optional[str]:
        from VoiceCommand import execute_command
        direction = args.get("direction", "up")
        cmd_map = {"up": "볼륨 올려", "down": "볼륨 내려", "mute": "볼륨 음소거"}
        execute_command(cmd_map.get(direction, "볼륨 올려"))
        return None

    def _handle_get_current_time(self, args: dict) -> Optional[str]:
        from VoiceCommand import execute_command
        execute_command("지금 몇 시야")
        return None

    def _handle_shutdown_computer(self, args: dict) -> Optional[str]:
        from VoiceCommand import execute_command
        execute_command("컴퓨터 종료")
        return None

    def _handle_get_screen_status(self, args: dict) -> Optional[str]:
        """현재 화면 상태 (작업표시줄, 전체화면 등) 정보를 수집하여 반환"""
        try:
            from VoiceCommand import character_widget
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
        goal = args.get("goal", "").strip()
        if not goal:
            return None
        self.tts_wrapper("복잡한 목표를 단계별로 처리할게요.")
        run_result: AgentRunResult = self.orchestrator.run(goal)
        return self._agent_run_to_korean(run_result)

    def _handle_web_search(self, args: dict) -> Optional[str]:
        """인터넷 검색 후 결과 반환"""
        query = args.get("query", "").strip()
        if not query:
            return None
        max_results = int(args.get("max_results", 5))
        try:
            from web_tools import web_search
            result = web_search(query, max_results=max_results)
            return f"[웹 검색 결과]\n{result}\n\n지시사항: 위 검색 결과를 바탕으로 사용자의 원래 질문에 대해 구어체로 3문장 이내로 요약하여 자연스럽게 대답해주세요."
        except Exception as e:
            logging.error(f"web_search 오류: {e}")
            return f"검색 오류: {e}"

    def _handle_web_fetch(self, args: dict) -> Optional[str]:
        """URL 내용 가져오기"""
        url = args.get("url", "").strip()
        if not url:
            return None
        try:
            from web_tools import web_fetch
            result = web_fetch(url)
            return result
        except Exception as e:
            logging.error(f"web_fetch 오류: {e}")
            return f"페이지 로드 오류: {e}"

    def _handle_schedule_task(self, args: dict) -> Optional[str]:
        """작업 예약"""
        goal = args.get("goal", "").strip()
        when = args.get("when", "").strip()
        if not goal or not when:
            return "예약할 작업과 시간을 알려주세요."

        if self.scheduler is None:
            return "스케줄러를 사용할 수 없습니다."

        next_run, repeat, repeat_seconds = self._parse_schedule(when)
        if next_run is None:
            return f"'{when}' 시간 표현을 이해하지 못했어요. '30분 후', '매일 오전 9시' 형식으로 말씀해 주세요."

        task_id = self.scheduler.schedule(
            goal=goal,
            next_run_dt=next_run,
            schedule_desc=when,
            repeat=repeat,
            repeat_seconds=repeat_seconds,
        )
        repeat_str = " (반복)" if repeat else ""
        return f"작업 예약 완료 (ID: {task_id}){repeat_str}. {next_run.strftime('%m월 %d일 %H시 %M분')}에 실행됩니다."

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
                time_str = dt.strftime("%m/%d %H:%M")
            except Exception:
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

        # "N초 후"
        m = re.search(r'(\d+)\s*초\s*후', when_kr)
        if m:
            return now + timedelta(seconds=int(m.group(1))), False, 0

        # "N분 후"
        m = re.search(r'(\d+)\s*분\s*후', when_kr)
        if m:
            return now + timedelta(minutes=int(m.group(1))), False, 0

        # "N시간 후"
        m = re.search(r'(\d+)\s*시간\s*후', when_kr)
        if m:
            return now + timedelta(hours=int(m.group(1))), False, 0

        # "N일 후"
        m = re.search(r'(\d+)\s*일\s*후', when_kr)
        if m:
            return now + timedelta(days=int(m.group(1))), False, 0
            
        # "매시간" (1시간 마다 반복)
        if "매시간" in when_kr.replace(" ", ""):
            return now + timedelta(hours=1), True, 3600

        # "매일 [오전|오후] N시 [M분]" → 반복 (매 24시간)
        m = re.search(r'매일\s*(오전|오후)?\s*(\d{1,2})시(?:\s*(\d{1,2})분)?', when_kr)
        if m:
            ampm, hour_s, min_s = m.group(1), int(m.group(2)), int(m.group(3) or 0)
            hour = hour_s
            if ampm == "오후" and hour < 12:
                hour += 12
            elif ampm is None and hour < 7:  # 모호한 경우 오전 가정
                pass
            target = now.replace(hour=hour, minute=min_s, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            return target, True, 86400

        # "내일 [오전|오후] N시 [M분]"
        m = re.search(r'내일\s*(오전|오후)?\s*(\d{1,2})시(?:\s*(\d{1,2})분)?', when_kr)
        if m:
            ampm, hour_s, min_s = m.group(1), int(m.group(2)), int(m.group(3) or 0)
            hour = hour_s
            if ampm == "오후" and hour < 12:
                hour += 12
            target = (now + timedelta(days=1)).replace(hour=hour, minute=min_s, second=0, microsecond=0)
            return target, False, 0

        # "[오늘] [오전|오후] N시 [M분]"
        m = re.search(r'(?:오늘\s*)?(오전|오후)?\s*(\d{1,2})시(?:\s*(\d{1,2})분)?', when_kr)
        if m:
            ampm, hour_s, min_s = m.group(1), int(m.group(2)), int(m.group(3) or 0)
            hour = hour_s
            if ampm == "오후" and hour < 12:
                hour += 12
            target = now.replace(hour=hour, minute=min_s, second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            return target, False, 0

        return None, False, 0

    # ── 결과 변환 ────────────────────────────────────────────────────────────────

    def _result_to_korean(self, result: ExecutionResult) -> Optional[str]:
        if not result.success:
            if result.error == "사용자 취소":
                return "사용자가 실행을 취소했습니다."
            return f"실행 실패: {result.error[:80]}" if result.error else "실행에 실패했습니다."
        if result.output:
            return f"실행 완료. 출력: {result.output[:200]}"
        return "실행이 완료되었습니다."

    def _agent_run_to_korean(self, run: AgentRunResult) -> str:
        steps_done = len(run.step_results)
        if run.achieved:
            return f"목표 달성 완료 ({steps_done}단계, {run.total_iterations}회 반복). {run.summary_kr}"
        return f"목표 달성 실패 ({run.total_iterations}회 시도). {run.summary_kr}"

    def _recover_tool_calls_from_response(self, user_text: str, response: Optional[str]) -> List[dict]:
        """LLM이 텍스트로만 '[run_agent_task 호출]' 같은 잔해를 남겼을 때 최소 복구."""
        if not response:
            return []

        recovered: List[dict] = []

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

    # ── 실행 ────────────────────────────────────────────────────────────────────

    def execute(self, text: str) -> None:
        self._run_interaction(text, self.tts_wrapper)

    def run_interaction(self, text: str) -> str:
        """텍스트 UI용: 실제 도구 실행까지 포함한 응답 문자열 반환."""
        outputs: List[str] = []

        def collect(message: str):
            if message:
                outputs.append(str(message))

        self._run_interaction(text, collect)
        cleaned = [msg.strip() for msg in outputs if msg and msg.strip()]
        return "\n".join(cleaned)

    def _run_interaction(self, text: str, output_callback: Callable[[str], None]) -> None:
        if not self._exec_lock.acquire(blocking=False):
            logging.warning(f"AI 명령 실행 중 재진입 시도 무시: {text}")
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

            if hasattr(self.ai_assistant, 'chat_with_tools'):
                if self.learning_mode_ref.get('enabled'):
                    self._record_user_pattern(text)

                response, tool_calls = self.ai_assistant.chat_with_tools(text, include_context=True)

                if not tool_calls:
                    tool_calls = self._recover_tool_calls_from_response(text, response)
                    if tool_calls:
                        logging.warning(
                            "[AICommand] 텍스트 기반 도구 호출 복구: %s",
                            [tc.get("name") for tc in tool_calls],
                        )

                if tool_calls:
                    # AI 텍스트 응답 먼저 TTS (경로/명령어 잔해 없는 자연어만)
                    if response:
                        self.tts_wrapper(response)
                    else:
                        for tc in tool_calls:
                            exp = tc.get("arguments", {}).get("explanation", "")
                            if exp:
                                self.tts_wrapper(exp)
                                break
                        else:
                            self.tts_wrapper("명령을 실행할게요.")

                    results = self._execute_tool_calls(tool_calls)

                    # 에이전틱 루프: 실행 결과를 LLM에 피드백하여 최종 응답 TTS
                    non_none = [r for r in results if r is not None]
                    if non_none and hasattr(self.ai_assistant, 'feed_tool_result'):
                        self._run_agentic_followup(text, tool_calls, results)
                else:
                    if response:
                        self.tts_wrapper(response)

            elif hasattr(self.ai_assistant, 'chat'):
                response = self.ai_assistant.chat(text, include_context=False)
                self.tts_wrapper(response)
            else:
                response, _, _ = self.ai_assistant.process_query(text)
                self.tts_wrapper(response)

            if response:
                logging.info(f"AI 응답: {response[:50]}...")

            if response:
                try:
                    from conversation_history import add_conversation
                    add_conversation(text, response)
                except Exception:
                    pass

        except AttributeError as e:
            logging.error(f"AI 어시스턴트가 초기화되지 않았습니다: {e}")
            self.tts_wrapper("AI 기능을 사용할 수 없습니다.")
        except Exception as e:
            logging.error(f"AI 응답 생성 오류: {e}", exc_info=True)
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
            logging.info(f"AI tool 실행: {name} {args}")

            handler = self._dispatch.get(name)
            if handler:
                try:
                    result = handler(args)
                except Exception as e:
                    logging.error(f"tool 핸들러 오류 ({name}): {e}", exc_info=True)
                    result = f"오류: {e}"
                results.append(result)
            else:
                logging.warning(f"알 수 없는 tool: {name}")
                results.append(None)
        return results

    def _run_agentic_followup(self, original_text: str, tool_calls: list, results: List[Optional[str]]):
        """도구 실행 결과를 LLM에 피드백하고 최종 응답을 TTS"""
        try:
            followup = self.ai_assistant.feed_tool_result(original_text, tool_calls, results)
            if followup:
                self.tts_wrapper(followup)
        except Exception as e:
            logging.error(f"에이전틱 후속 처리 오류: {e}", exc_info=True)

    def _record_user_pattern(self, user_input: str):
        try:
            from user_context import get_context_manager
            context_mgr = get_context_manager()
            if any(word in user_input for word in ["날씨", "기온", "온도"]):
                context_mgr.record_command("weather")
            elif any(word in user_input for word in ["음악", "노래", "재생"]):
                context_mgr.record_command("music")
            elif any(word in user_input for word in ["시간", "몇 시"]):
                context_mgr.record_command("time")
        except Exception as e:
            logging.error(f"패턴 기록 실패: {e}")
