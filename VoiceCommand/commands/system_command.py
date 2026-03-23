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
        direct_keywords = (
            "컴퓨터 꺼줘",
            "컴퓨터 꺼 줘",
            "컴퓨터 종료",
            "컴퓨터 종료해줘",
            "컴퓨터 종료해 줘",
            "컴퓨터 종료해달라",
            "컴퓨터 종료해 달라",
            "컴퓨터 종료해 주세요",
            "시스템 종료",
            "시스템 종료해줘",
            "pc 종료",
            "전원 꺼",
            "shutdown",
        )
        if any(keyword in normalized for keyword in direct_keywords):
            return True

        has_target = any(token in normalized for token in ("컴퓨터", "pc", "시스템", "전원"))
        has_shutdown_verb = any(token in normalized for token in ("종료", "꺼", "끄"))
        has_request = any(token in normalized for token in ("줘", "주라", "주세요", "해", "해줘", "해 달라", "해달라"))
        return has_target and has_shutdown_verb and has_request

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
