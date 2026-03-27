"""시스템 제어 명령 (종료, 재시작 등)"""
import logging
import re
import subprocess
import sys
from datetime import datetime, timedelta
from typing import Optional, Tuple

from commands.base_command import BaseCommand


# Windows shutdown /s /t 최대값
_WIN_MAX_SHUTDOWN_DELAY = 315360000


class SystemCommand(BaseCommand):
    """컴퓨터 종료 및 재시작 명령"""
    priority = 10

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
            "컴퓨터 재시작",
            "재부팅",
            "restart",
            "종료 취소",
            "종료 안 해",
            "shutdown cancel",
        )
        if any(keyword in normalized for keyword in direct_keywords):
            return True

        has_target = any(token in normalized for token in ("컴퓨터", "pc", "시스템", "전원"))
        has_system_action = any(token in normalized for token in ("종료", "꺼", "끄", "재시작", "재부팅", "restart"))
        has_request = any(token in normalized for token in ("줘", "주라", "주세요", "해", "해줘", "해 달라", "해달라"))
        return has_target and has_system_action and has_request

    def _parse_scheduled_time(self, text: str) -> Tuple[Optional[int], str]:
        """
        텍스트에서 예약 시간을 파싱해 (delay_seconds, display_str)를 반환.
        즉시 실행이어야 하면 (None, '') 반환.
        """
        now = datetime.now()
        normalized = re.sub(r"\s+", " ", text or "").strip()

        # 상대 시간: N초/분/시간 후|뒤 (복합 표현 지원: "1시간 30분 뒤" 등)
        relative_patterns = [
            (r'(\d+)\s*시간\s*(?:후|뒤)', 3600),
            (r'(\d+)\s*분\s*(?:후|뒤)', 60),
            (r'(\d+)\s*초\s*(?:후|뒤)', 1),
        ]
        total_delay = 0
        for pattern, sec_per_unit in relative_patterns:
            m = re.search(pattern, normalized)
            if m:
                total_delay += int(m.group(1)) * sec_per_unit
        if total_delay > 0:
            target = now + timedelta(seconds=total_delay)
            return total_delay, _format_time_kr(target)

        # 절대 시간: [오전|오후] N시 [M분] 에
        m = re.search(r'(오전|오후)?\s*(\d{1,2})시(?:\s*(\d{1,2})분)?\s*에?', normalized)
        if m:
            ampm = m.group(1)
            hour = int(m.group(2))
            minute = int(m.group(3) or 0)

            if ampm == "오후" and hour != 12:
                hour += 12
            elif ampm == "오전" and hour == 12:
                hour = 0

            if 0 <= hour <= 23 and 0 <= minute <= 59:
                target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if target <= now:
                    target += timedelta(days=1)
                delay = int((target - now).total_seconds())
                return delay, _format_time_kr(target)

        return None, ""

    def execute(self, text: str) -> None:
        normalized = (text or "").lower()

        if any(k in normalized for k in ("취소", "cancel", "안 해", "안해")):
            if any(k in normalized for k in ("종료", "shutdown", "꺼")):
                self._cancel_shutdown()
                return

        if any(k in normalized for k in ("재시작", "재부팅", "restart")):
            delay_seconds, time_str = self._parse_scheduled_time(text)
            if delay_seconds is not None and delay_seconds > 0:
                self._schedule_restart(delay_seconds, time_str)
            else:
                self._restart_immediate()
            return

        delay_seconds, time_str = self._parse_scheduled_time(text)
        if delay_seconds is not None and delay_seconds > 0:
            self._schedule_shutdown(delay_seconds, time_str)
        else:
            self._shutdown_immediate()

    def _schedule_shutdown(self, delay_seconds: int, time_str: str) -> None:
        logging.info(f"시스템 종료 예약: {delay_seconds}초 후 ({time_str})")
        self.tts_wrapper(f"{time_str}에 컴퓨터를 종료할게요.")
        try:
            if sys.platform == "win32":
                win_delay = min(delay_seconds, _WIN_MAX_SHUTDOWN_DELAY)
                subprocess.run(  # nosec B603 - controlled system command
                    ["shutdown", "/s", "/t", str(win_delay)], check=False
                )
            else:
                # Linux/Mac: shutdown +N minutes (최소 단위 1분)
                minutes = max(1, delay_seconds // 60)
                subprocess.run(  # nosec B603 - controlled system command
                    ["shutdown", f"+{minutes}"], check=False
                )
        except Exception as e:
            logging.error(f"시스템 종료 예약 실패: {e}")
            self.tts_wrapper("시스템 종료 예약에 실패했습니다.")

    def _shutdown_immediate(self) -> None:
        self.tts_wrapper("컴퓨터를 종료합니다. 잠시만 기다려 주세요.")
        logging.info("시스템 종료 명령 실행")
        try:
            if sys.platform == "win32":
                subprocess.run(  # nosec B603 - controlled system command
                    ["shutdown", "/s", "/t", "10"], check=False
                )
            else:
                subprocess.run(  # nosec B603 - controlled system command
                    ["shutdown", "-h", "now"], check=False
                )
        except Exception as e:
            logging.error(f"시스템 종료 명령 실패: {e}")
            self.tts_wrapper("시스템 종료 명령 실행에 실패했습니다.")

    def _cancel_shutdown(self) -> None:
        logging.info("시스템 종료 취소 명령 실행")
        try:
            if sys.platform == "win32":
                result = subprocess.run(["shutdown", "/a"], check=False, capture_output=True)  # nosec B603
                if result.returncode != 0:
                    logging.warning(f"종료 취소 실패 (returncode={result.returncode}): {result.stderr.decode(errors='ignore').strip()}")
                    self.tts_wrapper("현재 예약된 종료가 없거나 취소에 실패했습니다.")
                    return
            else:
                result = subprocess.run(["shutdown", "-c"], check=False, capture_output=True)  # nosec B603
                if result.returncode != 0:
                    logging.warning(f"종료 취소 실패 (returncode={result.returncode})")
                    self.tts_wrapper("현재 예약된 종료가 없거나 취소에 실패했습니다.")
                    return
        except Exception as e:
            logging.error(f"종료 취소 실패: {e}")
            self.tts_wrapper("종료 취소 명령 실행에 실패했습니다.")
            return
        self.tts_wrapper("종료 예약을 취소했습니다.")

    def _restart_immediate(self) -> None:
        self.tts_wrapper("컴퓨터를 재시작합니다. 잠시만 기다려 주세요.")
        logging.info("시스템 재시작 명령 실행")
        try:
            if sys.platform == "win32":
                subprocess.run(["shutdown", "/r", "/t", "10"], check=False)  # nosec B603
            else:
                subprocess.run(["reboot"], check=False)  # nosec B603
        except Exception as e:
            logging.error(f"시스템 재시작 명령 실패: {e}")
            self.tts_wrapper("시스템 재시작 명령 실행에 실패했습니다.")

    def _schedule_restart(self, delay_seconds: int, time_str: str) -> None:
        logging.info(f"시스템 재시작 예약: {delay_seconds}초 후 ({time_str})")
        self.tts_wrapper(f"{time_str}에 컴퓨터를 재시작할게요.")
        try:
            if sys.platform == "win32":
                win_delay = min(delay_seconds, _WIN_MAX_SHUTDOWN_DELAY)
                subprocess.run(["shutdown", "/r", "/t", str(win_delay)], check=False)  # nosec B603
            else:
                minutes = max(1, delay_seconds // 60)
                subprocess.run(["shutdown", "-r", f"+{minutes}"], check=False)  # nosec B603
        except Exception as e:
            logging.error(f"시스템 재시작 예약 실패: {e}")
            self.tts_wrapper("시스템 재시작 예약에 실패했습니다.")


def _format_time_kr(dt: datetime) -> str:
    ampm = "오전" if dt.hour < 12 else "오후"
    hour = dt.hour if dt.hour <= 12 else dt.hour - 12
    if hour == 0:
        hour = 12
    if dt.minute:
        return f"{ampm} {hour}시 {dt.minute}분"
    return f"{ampm} {hour}시"
