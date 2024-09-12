"""학습 모드 명령"""
from commands.base_command import BaseCommand
import logging


class LearningCommand(BaseCommand):
    """학습 모드 제어 명령"""

    def __init__(self, tts_func, learning_mode_ref):
        self.tts_wrapper = tts_func
        self.learning_mode_ref = learning_mode_ref

    def matches(self, text: str) -> bool:
        return "학습 모드" in text

    def execute(self, text: str) -> None:
        if "비활성화" in text or "종료" in text:
            self.learning_mode_ref['enabled'] = False
            self.tts_wrapper("스마트 어시스턴트 모드가 비활성화되었습니다.")
        elif "활성화" in text or "시작" in text:
            self.learning_mode_ref['enabled'] = True
            self.tts_wrapper("스마트 어시스턴트 모드가 활성화되었습니다. 이제 제가 명령어를 자동으로 실행하고 주인님의 패턴을 학습하겠습니다.")
