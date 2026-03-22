"""시스템 제어 명령 (종료, 재시작 등)"""
import os
import subprocess
import logging
import sys
from commands.base_command import BaseCommand

class SystemCommand(BaseCommand):
    """컴퓨터 종료 및 재시작 명령"""

    def __init__(self, tts_func):
        self.tts_wrapper = tts_func

    def matches(self, text: str) -> bool:
        return any(word in text for word in ["컴퓨터 종료", "시스템 종료", "PC 종료", "컴퓨터 꺼줘"])

    def execute(self, text: str) -> None:
        if any(word in text for word in ["종료", "꺼줘"]):
            self.tts_wrapper("컴퓨터를 종료합니다. 잠시만 기다려 주세요.")
            logging.info("시스템 종료 명령 실행")
            
            # Windows 종료 명령 (10초 후 종료하여 TTS가 나올 시간을 줌)
            if sys.platform == "win32":
                os.system("shutdown /s /t 10")
            else:
                # Linux/macOS (sudo 권한이 필요할 수 있음)
                os.system("sudo shutdown -h now")
