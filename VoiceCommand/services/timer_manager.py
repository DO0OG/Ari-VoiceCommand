"""
타이머 관리 모듈
일반 타이머와 종료 타이머 지원
"""
import logging
import re
import threading
from datetime import datetime, timedelta


class TimerManager:
    """타이머 관리 클래스"""

    def __init__(self, tts_callback=None):
        """
        Args:
            tts_callback: TTS 출력을 위한 콜백 함수
        """
        self.active_timer = None
        self.tts_callback = tts_callback or (lambda x: print(x))

    def set_timer(self, minutes):
        """
        일반 타이머 설정

        Args:
            minutes: 타이머 시간 (분)
        """
        if self.active_timer:
            self.active_timer["timer"].cancel()

        total_seconds = minutes * 60
        end_time = datetime.now() + timedelta(seconds=total_seconds)

        def format_duration_label(total_minutes):
            mins = int(total_minutes)
            secs = round((total_minutes - mins) * 60)
            if secs == 60:
                mins += 1
                secs = 0
            if mins > 0 and secs > 0:
                return f"{mins}분 {secs}초"
            if mins > 0:
                return f"{mins}분"
            return f"{secs}초"

        label = format_duration_label(minutes)

        def on_timer_expired():
            self.active_timer = None
            self.tts_callback(f"{label} 타이머가 완료되었습니다.")
            logging.info(f"타이머 완료: {label}")

        timer = threading.Timer(total_seconds, on_timer_expired)
        timer.daemon = True
        self.active_timer = {
            "timer": timer,
            "end_time": end_time
        }
        timer.start()
        self.tts_callback(f"{label} 타이머를 설정했습니다.")
        logging.info(f"타이머 설정: {minutes}분 ({end_time.strftime('%H:%M:%S')}까지)")

    def cancel(self):
        """활성 타이머 취소"""
        if self.active_timer:
            self.active_timer["timer"].cancel()
            self.active_timer = None
            self.tts_callback("타이머가 취소되었습니다.")
        else:
            self.tts_callback("현재 실행 중인 타이머가 없습니다.")

    def get_remaining_time(self):
        """
        남은 시간 조회

        Returns:
            float: 남은 시간 (초), 타이머 없으면 None
        """
        if self.active_timer:
            remaining = (self.active_timer["end_time"] - datetime.now()).total_seconds()
            return max(0, remaining)
        return None

    def parse_timer_command(self, command):
        """
        명령어에서 타이머 시간을 분 단위로 추출.
        '1분 30초', '2시간 30분', '90초' 등 복합 표현 지원.

        Args:
            command: 명령어 문자열 (예: "10분 타이머")

        Returns:
            float: 추출된 시간 (분), 실패 시 None
        """
        normalized = re.sub(r"\s+", " ", command or "").strip()
        total_minutes = 0.0
        found = False

        hours_match = re.search(r'(\d+)\s*시간', normalized)
        minutes_match = re.search(r'(\d+)\s*분', normalized)
        seconds_match = re.search(r'(\d+)\s*초', normalized)

        if hours_match:
            total_minutes += int(hours_match.group(1)) * 60
            found = True
        if minutes_match:
            total_minutes += int(minutes_match.group(1))
            found = True
        if seconds_match:
            total_minutes += int(seconds_match.group(1)) / 60
            found = True

        return total_minutes if found else None
