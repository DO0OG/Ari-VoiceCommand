"""시간 안내 명령"""
from agent.decision.semantics import parse_candidate
from commands.base_command import BaseCommand
from datetime import datetime
import logging
from i18n.translator import _


class TimeCommand(BaseCommand):
    """현재 시간 안내 명령"""

    def __init__(self, tts_func):
        self.tts_wrapper = tts_func

    def matches(self, text: str) -> bool:
        # "파리는 지금 몇 시야"처럼 다른 대상이나 동작이 붙은 문장은 대화 처리로 넘긴다.
        return _("몇 시야") in text and parse_candidate(text, "get_current_time").parse_success

    def execute(self, text: str) -> None:
        time_str = self.get_current_time()
        response = _("현재 시간은 {time}입니다.").format(time=time_str)
        self.tts_wrapper(response)
        logging.info(f"현재 시간 안내: {response}")

    @staticmethod
    def get_current_time():
        now = datetime.now()
        if now.hour < 12:
            am_pm = _("오전")
            hour = now.hour
        else:
            am_pm = _("오후")
            hour = now.hour - 12 if now.hour > 12 else 12
        return _("{am_pm} {hour}시 {minute}분").format(
            am_pm=am_pm, hour=hour, minute=now.minute
        )
