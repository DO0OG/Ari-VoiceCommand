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
        return "타이머" in text or "알람" in text

    def execute(self, text: str) -> None:
        if "취소" in text or "끄기" in text or "중지" in text:
            self.timer_manager.cancel()
        elif "남은" in text or "얼마" in text or "확인" in text:
            remaining = self.timer_manager.get_remaining_time()
            if remaining is None:
                self.tts_wrapper("현재 실행 중인 타이머가 없습니다.")
            else:
                mins = int(remaining // 60)
                secs = int(remaining % 60)
                if mins > 0 and secs > 0:
                    self.tts_wrapper(f"타이머 {mins}분 {secs}초 남았습니다.")
                elif mins > 0:
                    self.tts_wrapper(f"타이머 {mins}분 남았습니다.")
                else:
                    self.tts_wrapper(f"타이머 {secs}초 남았습니다.")
        else:
            minutes = self.timer_manager.parse_timer_command(text)
            if minutes is not None:
                self.timer_manager.set_timer(minutes)
            else:
                self.tts_wrapper("타이머 시간을 정확히 말씀해 주세요.")
