"""볼륨 제어 명령"""
import re

from agent.decision.semantics import parse_candidate
from commands.base_command import BaseCommand

# 해석기가 받지 않는 기존 고정 표현은 문장 전체가 일치할 때만 처리한다.
_LEGACY_PHRASES = {
    "볼륨키우기": "up",
    "볼륨줄이기": "down",
    "볼륨음소거해제": "unmute",
}


class VolumeCommand(BaseCommand):
    """볼륨 조절 명령"""

    def __init__(self, adjust_volume_func, tts_func):
        self.adjust_volume = adjust_volume_func
        self.tts_wrapper = tts_func

    def matches(self, text: str) -> bool:
        return "볼륨" in text and self._request(text) is not None

    def execute(self, text: str) -> None:
        request = self._request(text)
        if request is not None:
            direction, amount = request
            self.adjust_volume(direction, amount=amount)

    @staticmethod
    def _request(text: str) -> tuple[str, object] | None:
        # "볼륨 올리고 캡처해줘"처럼 다른 동작이 붙거나 부정한 문장은 대화 처리로 넘긴다.
        parsed = parse_candidate(text, "adjust_volume")
        if parsed.parse_success:
            return parsed.arguments["direction"], parsed.arguments.get("amount")
        direction = _LEGACY_PHRASES.get(re.sub(r"[\s.!?]", "", text))
        return (direction, None) if direction else None
