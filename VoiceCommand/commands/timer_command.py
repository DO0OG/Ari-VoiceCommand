"""타이머 명령"""
from commands.base_command import BaseCommand
import logging


class TimerCommand(BaseCommand):
    """타이머 명령"""
    priority = 30

    def __init__(self, timer_manager, tts_func):
        self.timer_manager = timer_manager
        self.tts_wrapper = tts_func

    def matches(self, text: str) -> bool:
        return "타이머" in text

    def execute(self, text: str) -> None:
        if "취소" in text or "끄기" in text or "중지" in text:
            self.timer_manager.cancel()
        else:
            minutes = self.timer_manager.parse_timer_command(text)
            if minutes:
                self.timer_manager.set_timer(minutes)
            else:
                self.tts_wrapper("타이머 시간을 정확히 말씀해 주세요.")
