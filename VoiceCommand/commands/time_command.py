"""시간 안내 명령"""
from commands.base_command import BaseCommand
from datetime import datetime
import logging


class TimeCommand(BaseCommand):
    """현재 시간 안내 명령"""

    def __init__(self, tts_func):
        self.tts_wrapper = tts_func

    def matches(self, text: str) -> bool:
        return "몇 시야" in text

    def execute(self, text: str) -> None:
        time_str = self.get_current_time()
        response = f"현재 시간은 {time_str}입니다."
        self.tts_wrapper(response)
        logging.info(f"현재 시간 안내: {response}")

    @staticmethod
    def get_current_time():
        now = datetime.now()
        if now.hour < 12:
            am_pm = "오전"
            hour = now.hour
        else:
            am_pm = "오후"
            hour = now.hour - 12 if now.hour > 12 else 12
        return f"{am_pm} {hour}시 {now.minute}분"
