"""
타이머 관리 모듈
일반 타이머와 종료 타이머 지원
"""
import logging
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
        def timer_thread():
            if self.active_timer and datetime.now() >= self.active_timer["end_time"]:
                self.tts_callback(f"{minutes}분 타이머가 완료되었습니다.")
                self.active_timer = None
            elif self.active_timer:
                # 새 타이머를 active_timer에 갱신해야 cancel()이 계속 유효함
                new_timer = threading.Timer(1, timer_thread)
                self.active_timer["timer"] = new_timer
                new_timer.start()

        if self.active_timer:
            self.active_timer["timer"].cancel()

        end_time = datetime.now() + timedelta(minutes=minutes)
        self.active_timer = {
            "timer": threading.Timer(1, timer_thread),
            "end_time": end_time
        }
        self.active_timer["timer"].start()
        self.tts_callback(f"{minutes}분 타이머를 설정했습니다.")
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
        명령어에서 타이머 시간 추출

        Args:
            command: 명령어 문자열 (예: "10분 타이머")

        Returns:
            int: 추출된 시간 (분), 실패 시 None
        """
        try:
            minutes = int("".join(filter(str.isdigit, command)))
            return minutes
        except ValueError:
            return None
