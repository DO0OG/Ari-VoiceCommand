"""타이머 명령"""
from commands.base_command import BaseCommand
import re


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
            name = self._extract_timer_name(text)
            self.timer_manager.cancel_timer(name=name)
        elif "남은" in text or "얼마" in text or "확인" in text:
            timers = self.timer_manager.list_timers()
            if not timers:
                self.tts_wrapper("현재 실행 중인 타이머가 없습니다.")
            else:
                target = timers[-1]
                name = target["name"]
                remaining = target["remaining_seconds"]
                mins = int(remaining // 60)
                secs = int(remaining % 60)
                prefix = "타이머" if name.startswith("타이머 ") else f"'{name}' 타이머"
                if mins > 0 and secs > 0:
                    self.tts_wrapper(f"{prefix} {mins}분 {secs}초 남았습니다.")
                elif mins > 0:
                    self.tts_wrapper(f"{prefix} {mins}분 남았습니다.")
                else:
                    self.tts_wrapper(f"{prefix} {secs}초 남았습니다.")
        else:
            minutes = self.timer_manager.parse_timer_command(text)
            if minutes is not None:
                self.timer_manager.set_timer(minutes, name=self._extract_timer_name(text))
            else:
                self.tts_wrapper("타이머 시간을 정확히 말씀해 주세요.")

    @staticmethod
    def _extract_timer_name(text: str) -> str:
        match = re.search(r'["\']([^"\']+)["\']\s*타이머', text)
        if match:
            return match.group(1).strip()
        named_match = re.search(r'([가-힣a-zA-Z0-9 _-]+)\s*타이머', text)
        if not named_match:
            return ""
        candidate = named_match.group(1).strip()
        return "" if any(token in candidate for token in ("취소", "남은", "얼마", "확인")) else candidate
