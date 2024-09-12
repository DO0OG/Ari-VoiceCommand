"""볼륨 제어 명령"""
from commands.base_command import BaseCommand
import logging


class VolumeCommand(BaseCommand):
    """볼륨 조절 명령"""

    def __init__(self, adjust_volume_func, tts_func):
        self.adjust_volume = adjust_volume_func
        self.tts_wrapper = tts_func

    def matches(self, text: str) -> bool:
        return "볼륨" in text

    def execute(self, text: str) -> None:
        if "키우기" in text or "올려" in text:
            self.adjust_volume(0.1)
        elif "줄이기" in text or "내려" in text:
            self.adjust_volume(-0.1)
        elif "음소거 해제" in text:
            self.adjust_volume(0)
        elif "음소거" in text:
            self.adjust_volume(-1)
