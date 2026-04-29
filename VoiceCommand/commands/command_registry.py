"""명령 레지스트리"""
from typing import Callable, List
import logging
from commands.base_command import BaseCommand, CommandResult
from memory.user_context import get_context_manager
from commands.learning_command import LearningCommand
from commands.timer_command import TimerCommand
from commands.weather_command import WeatherCommand
from commands.volume_command import VolumeCommand
from commands.time_command import TimeCommand
from commands.calculator_command import CalculatorCommand
from commands.ai_command import AICommand
from commands.youtube_command import YoutubeCommand
from commands.system_command import SystemCommand
from commands.memory_command import MemoryCommand


class CommandRegistry:
    """명령 레지스트리"""

    def __init__(self, ai_assistant, weather_service, timer_manager,
                 adjust_volume_func, tts_func, learning_mode_ref,
                 emit_event: Callable[[str, dict], None] | None = None):
        """
        명령 레지스트리 초기화

        Args:
            ai_assistant: AI 어시스턴트 인스턴스
            weather_service: 날씨 서비스 인스턴스
            timer_manager: 타이머 매니저 인스턴스
            adjust_volume_func: 볼륨 조절 함수
            tts_func: TTS 함수
            learning_mode_ref: 학습 모드 상태 참조 (dict)
        """
        commands: List[BaseCommand] = [
            LearningCommand(tts_func, learning_mode_ref),
            YoutubeCommand(tts_func),
            TimerCommand(timer_manager, tts_func),
            WeatherCommand(weather_service, tts_func),
            VolumeCommand(adjust_volume_func, tts_func),
            SystemCommand(tts_func),
            TimeCommand(tts_func),
            CalculatorCommand(tts_func),
            MemoryCommand(tts_func),
            AICommand(ai_assistant, tts_func, learning_mode_ref),
        ]
        # priority 기준 정렬: 낮을수록 먼저 매칭
        self.commands: List[BaseCommand] = sorted(commands, key=lambda c: c.priority)
        self._emit_event = emit_event

    def set_event_emitter(self, emit_event: Callable[[str, dict], None] | None) -> None:
        self._emit_event = emit_event

    def execute(self, text: str) -> CommandResult:
        """텍스트에 맞는 명령 찾아서 실행"""
        context_manager = get_context_manager()

        for command in self.commands:
            if command.matches(text):
                logging.info(f"[CommandRegistry] 매칭 명령: {command.__class__.__name__} / 입력: {text}")
                # 명령어 유형 기록 (클래스 이름에서 'Command' 제외)
                cmd_type = command.__class__.__name__.replace("Command", "").lstrip("_").lower()
                try:
                    context_manager.record_command(cmd_type, {"input": text})
                except Exception as e:
                    logging.warning(f"[CommandRegistry] 사용자 컨텍스트 기록 실패: {e}")
                
                raw_result = command.execute(text)
                result = raw_result if isinstance(raw_result, CommandResult) else CommandResult(success=raw_result is not False)
                self._publish_command_event(text, command, cmd_type, result)
                return result
        result = CommandResult(success=False, response="")
        self._publish_command_event(text, None, "", result)
        return result

    def register_command(self, command: BaseCommand) -> None:
        """런타임에 명령을 추가하고 priority 순서를 유지한다."""
        self.commands.append(command)
        self.commands.sort(key=lambda c: c.priority)

    def unregister_command(self, command: BaseCommand) -> None:
        """런타임에 추가된 명령을 제거한다."""
        self.commands = [item for item in self.commands if item is not command]

    def _publish_command_event(
        self,
        text: str,
        command: BaseCommand | None,
        cmd_type: str,
        result: CommandResult,
    ) -> None:
        if not self._emit_event:
            return
        try:
            self._emit_event(
                "command.executed",
                {
                    "input": text,
                    "command_type": cmd_type,
                    "command_class": command.__class__.__name__ if command else "",
                    "success": result.success,
                    "response": result.response,
                    "data": result.data or {},
                },
            )
        except Exception as exc:
            logging.debug("[CommandRegistry] 이벤트 발행 실패: %s", exc)
