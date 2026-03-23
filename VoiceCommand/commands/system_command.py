"""시스템 제어 명령 (종료, 재시작 등)"""
import os
import logging
import re
import subprocess
import sys
from commands.base_command import BaseCommand

class SystemCommand(BaseCommand):
    """컴퓨터 종료 및 재시작 명령"""

    def __init__(self, tts_func):
        self.tts_wrapper = tts_func

    def matches(self, text: str) -> bool:
        normalized = re.sub(r"\s+", " ", text or "").strip().lower()
        shutdown_keywords = (
            "컴퓨터 꺼줘",
            "컴퓨터 꺼 줘",
            "컴퓨터 종료",
            "컴퓨터 종료해줘",
            "컴퓨터 종료해 줘",
            "시스템 종료",
            "pc 종료",
            "전원 꺼",
            "shutdown",
        )
        return any(keyword in normalized for keyword in shutdown_keywords)

    def execute(self, text: str) -> None:
        normalized = re.sub(r"\s+", " ", text or "").strip().lower()
        if not self.matches(normalized):
            return

        self.tts_wrapper("컴퓨터를 종료합니다. 잠시만 기다려 주세요.")
        logging.info("시스템 종료 명령 실행")

        try:
            if sys.platform == "win32":
                subprocess.run(["shutdown", "/s", "/t", "10"], check=False)  # nosec B603 - controlled system command
            else:
                subprocess.run(["shutdown", "-h", "now"], check=False)  # nosec B603 - controlled system command
        except Exception as e:
            logging.error(f"시스템 종료 명령 실패: {e}")
            self.tts_wrapper("시스템 종료 명령 실행에 실패했습니다.")
