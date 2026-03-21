"""AI 어시스턴트 명령 (fallback)"""
from commands.base_command import BaseCommand
import logging
import re

# 도구 실행 중 재진입 방지 플래그
_tool_executing = False


class AICommand(BaseCommand):
    """AI 어시스턴트 대화 명령 (기본/fallback)"""

    def __init__(self, ai_assistant, tts_func, learning_mode_ref):
        self.ai_assistant = ai_assistant
        self.tts_wrapper = tts_func
        self.learning_mode_ref = learning_mode_ref

    def matches(self, text: str) -> bool:
        # 항상 True (fallback 명령)
        return True

    def execute(self, text: str) -> None:
        global _tool_executing
        try:
            response = None

            # 도구 실행 중 재진입 시 → 알 수 없는 명령으로 처리
            if _tool_executing:
                logging.warning(f"도구 실행 중 매핑되지 않은 명령: {text}")
                return

            # 스마트 어시스턴트 모드 활성화 시 → tool calling 사용
            if self.learning_mode_ref['enabled'] and hasattr(self.ai_assistant, 'chat_with_tools'):
                self._record_user_pattern(text)
                response, tool_calls = self.ai_assistant.chat_with_tools(text, include_context=True)

                if tool_calls:
                    # 도구 호출 시 AI 응답이 있으면 먼저 말하고 없으면 기본 멘트
                    if response:
                        self.tts_wrapper(response)
                    else:
                        self.tts_wrapper("명령을 실행할게요.")
                    self._execute_tool_calls(tool_calls)
                else:
                    self.tts_wrapper(response)

            elif hasattr(self.ai_assistant, 'chat'):
                response = self.ai_assistant.chat(text, include_context=False)
                self.tts_wrapper(response)
            else:
                response, _, _ = self.ai_assistant.process_query(text)
                self.tts_wrapper(response)

            if response:
                logging.info(f"AI 응답: {response[:50]}...")

            # 대화 기록 저장
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

    def _record_user_pattern(self, user_input):
        """사용자 패턴 기록"""
        try:
            from user_context import get_context_manager
            context_mgr = get_context_manager()

            # 간단한 명령어 분류
            if any(word in user_input for word in ["날씨", "기온", "온도"]):
                context_mgr.record_command("weather")
            elif any(word in user_input for word in ["음악", "노래", "재생"]):
                context_mgr.record_command("music")
            elif any(word in user_input for word in ["시간", "몇 시"]):
                context_mgr.record_command("time")

        except Exception as e:
            logging.error(f"패턴 기록 실패: {e}")

    def _execute_tool_calls(self, tool_calls: list):
        """AI가 결정한 tool call 목록을 실제 명령으로 실행"""
        global _tool_executing
        from VoiceCommand import execute_command

        _tool_executing = True
        try:
            for tc in tool_calls:
                name = tc.get("name", "")
                args = tc.get("arguments", {})
                logging.info(f"AI tool 실행: {name} {args}")

                if name == "play_youtube":
                    query = args.get("query", "").strip()
                    if not query:
                        self.tts_wrapper("어떤 음악이나 영상을 재생할까요?")
                        continue
                    execute_command(f"유튜브 {query} 재생")

                elif name == "set_timer":
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

                elif name == "cancel_timer":
                    execute_command("타이머 취소")

                elif name == "get_weather":
                    execute_command("날씨 알려줘")

                elif name == "adjust_volume":
                    direction = args.get("direction", "up")
                    if direction == "up":
                        execute_command("볼륨 올려")
                    elif direction == "down":
                        execute_command("볼륨 내려")
                    elif direction == "mute":
                        execute_command("볼륨 음소거")

                elif name == "get_current_time":
                    execute_command("지금 몇 시야")

                else:
                    logging.warning(f"알 수 없는 tool: {name}")
        finally:
            _tool_executing = False

