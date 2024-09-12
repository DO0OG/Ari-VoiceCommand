"""명령 레지스트리"""
from typing import List
import logging
from commands.base_command import BaseCommand
from commands.learning_command import LearningCommand
from commands.timer_command import TimerCommand
from commands.weather_command import WeatherCommand
from commands.volume_command import VolumeCommand
from commands.time_command import TimeCommand
from commands.calculator_command import CalculatorCommand
from commands.ai_command import AICommand
from commands.youtube_command import YoutubeCommand


class CommandRegistry:
    """명령 레지스트리"""

    def __init__(self, ai_assistant, weather_service, timer_manager,
                 adjust_volume_func, tts_func, learning_mode_ref):
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
        self.commands: List[BaseCommand] = [
            LearningCommand(tts_func, learning_mode_ref),
            YoutubeCommand(tts_func),
            TimerCommand(timer_manager, tts_func),
            WeatherCommand(weather_service, tts_func),
            VolumeCommand(adjust_volume_func, tts_func),
            TimeCommand(tts_func),
            CalculatorCommand(tts_func),
            AICommand(ai_assistant, tts_func, learning_mode_ref),  # 마지막 (fallback)
        ]

    def execute(self, text: str) -> None:
        """텍스트에 맞는 명령 찾아서 실행"""
        for command in self.commands:
            if command.matches(text):
                command.execute(text)
                return

        # 이 코드는 실행되지 않음 (AICommand가 항상 매칭)
        logging.warning(f"매칭되는 명령이 없습니다: {text}")
