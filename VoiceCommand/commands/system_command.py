"""시스템 제어 명령 (종료, 재시작 등)"""
import logging
import re
import subprocess
import sys
from datetime import datetime, timedelta
from typing import Optional, Tuple

from commands.base_command import BaseCommand
from i18n.translator import _


# Windows shutdown /s /t 최대값
_WIN_MAX_SHUTDOWN_DELAY = 315360000


class SystemCommand(BaseCommand):
    """컴퓨터 종료 및 재시작 명령"""
    priority = 10

    def __init__(self, tts_func):
        self.tts_wrapper = tts_func

    def matches(self, text: str) -> bool:
        normalized = re.sub(r"\s+", " ", text or "").strip().lower()
        # 트리거 키워드 (번역 적용)
        direct_keywords = (
            _("컴퓨터 꺼줘"),
            _("컴퓨터 꺼 줘"),
            _("컴퓨터 종료"),
            _("컴퓨터 종료해줘"),
            _("시스템 종료"),
            _("전원 꺼"),
            "shutdown",
            _("컴퓨터 재시작"),
            _("재부팅"),
            "restart",
            _("종료 취소"),
            _("종료 안 해"),
        )
        if any(keyword in normalized for keyword in direct_keywords):
            return True

        has_target = any(token in normalized for token in (_("컴퓨터"), "pc", _("시스템"), _("전원")))
        has_system_action = any(token in normalized for token in (_("종료"), _("꺼"), _("끄"), _("재시작"), _("재부팅"), "restart"))
        has_request = any(token in normalized for token in (_("줘"), _("주세요"), _("해줘"), _("해달라")))
        return has_target and has_system_action and has_request

    def _parse_scheduled_time(self, text: str) -> Tuple[Optional[int], str]:
        """
        텍스트에서 예약 시간을 파싱해 (delay_seconds, display_str)를 반환.
        """
        now = datetime.now()
        normalized = re.sub(r"\s+", " ", text or "").strip()

        # 상대 시간 (번역 적용)
        relative_patterns = [
            (r'(\d+)\s*' + _("시간") + r'\s*(?:' + _("후") + r'|' + _("뒤") + r')', 3600),
            (r'(\d+)\s*' + _("분") + r'\s*(?:' + _("후") + r'|' + _("뒤") + r')', 60),
            (r'(\d+)\s*' + _("초") + r'\s*(?:' + _("후") + r'|' + _("뒤") + r')', 1),
        ]
        total_delay = 0
        for pattern, sec_per_unit in relative_patterns:
            m = re.search(pattern, normalized)
            if m:
                total_delay += int(m.group(1)) * sec_per_unit
        if total_delay > 0:
            target = now + timedelta(seconds=total_delay)
            return total_delay, _format_time(target)

        # 절대 시간
        m = re.search(r'(' + _("오전") + r'|' + _("오후") + r')?\s*(\d{1,2})' + _("시") + r'(?:\s*(\d{1,2})' + _("분") + r')?\s*' + _("에") + r'?', normalized)
        if m:
            ampm = m.group(1)
            hour = int(m.group(2))
            minute = int(m.group(3) or 0)

            if ampm == _("오후") and hour != 12:
                hour += 12
            elif ampm == _("오전") and hour == 12:
                hour = 0

            if 0 <= hour <= 23 and 0 <= minute <= 59:
                target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                if target <= now:
                    target += timedelta(days=1)
                delay = int((target - now).total_seconds())
                return delay, _format_time(target)

        return None, ""

    def execute(self, text: str) -> None:
        normalized = (text or "").lower()

        if any(k in normalized for k in (_("취소"), "cancel", _("안 해"))):
            if any(k in normalized for k in (_("종료"), "shutdown", _("꺼"))):
                self._cancel_shutdown()
                return

        if any(k in normalized for k in (_("재시작"), _("재부팅"), "restart")):
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
        self.tts_wrapper(_("{time}에 컴퓨터를 종료할게요.").format(time=time_str))
        try:
            if sys.platform == "win32":
                win_delay = min(delay_seconds, _WIN_MAX_SHUTDOWN_DELAY)
                subprocess.run(["shutdown", "/s", "/t", str(win_delay)], check=False)
            else:
                minutes = max(1, delay_seconds // 60)
                subprocess.run(["shutdown", f"+{minutes}"], check=False)
        except Exception as e:
            logging.error(f"시스템 종료 예약 실패: {e}")
            self.tts_wrapper(_("시스템 종료 예약에 실패했습니다."))

    def _shutdown_immediate(self) -> None:
        self.tts_wrapper(_("컴퓨터를 종료합니다. 잠시만 기다려 주세요."))
        logging.info("시스템 종료 명령 실행")
        try:
            if sys.platform == "win32":
                subprocess.run(["shutdown", "/s", "/t", "10"], check=False)
            else:
                subprocess.run(["shutdown", "-h", "now"], check=False)
        except Exception as e:
            logging.error(f"시스템 종료 명령 실패: {e}")
            self.tts_wrapper(_("시스템 종료 명령 실행에 실패했습니다."))

    def _cancel_shutdown(self) -> None:
        logging.info("시스템 종료 취소 명령 실행")
        try:
            if sys.platform == "win32":
                result = subprocess.run(["shutdown", "/a"], check=False, capture_output=True)
                if result.returncode != 0:
                    self.tts_wrapper(_("현재 예약된 종료가 없거나 취소에 실패했습니다."))
                    return
            else:
                result = subprocess.run(["shutdown", "-c"], check=False, capture_output=True)
                if result.returncode != 0:
                    self.tts_wrapper(_("현재 예약된 종료가 없거나 취소에 실패했습니다."))
                    return
        except Exception as e:
            logging.error(f"종료 취소 실패: {e}")
            self.tts_wrapper(_("종료 취소 명령 실행에 실패했습니다."))
            return
        self.tts_wrapper(_("종료 예약을 취소했습니다."))

    def _restart_immediate(self) -> None:
        self.tts_wrapper(_("컴퓨터를 재시작합니다. 잠시만 기다려 주세요."))
        logging.info("시스템 재시작 명령 실행")
        try:
            if sys.platform == "win32":
                subprocess.run(["shutdown", "/r", "/t", "10"], check=False)
            else:
                subprocess.run(["reboot"], check=False)
        except Exception as e:
            logging.error(f"시스템 재시작 명령 실패: {e}")
            self.tts_wrapper(_("시스템 재시작 명령 실행에 실패했습니다."))

    def _schedule_restart(self, delay_seconds: int, time_str: str) -> None:
        logging.info(f"시스템 재시작 예약: {delay_seconds}초 후 ({time_str})")
        self.tts_wrapper(_("{time}에 컴퓨터를 재시작할게요.").format(time=time_str))
        try:
            if sys.platform == "win32":
                win_delay = min(delay_seconds, _WIN_MAX_SHUTDOWN_DELAY)
                subprocess.run(["shutdown", "/r", "/t", str(win_delay)], check=False)
            else:
                minutes = max(1, delay_seconds // 60)
                subprocess.run(["shutdown", "-r", f"+{minutes}"], check=False)
        except Exception as e:
            logging.error(f"시스템 재시작 예약 실패: {e}")
            self.tts_wrapper(_("시스템 재시작 예약에 실패했습니다."))


def _format_time(dt: datetime) -> str:
    ampm = _("오전") if dt.hour < 12 else _("오후")
    hour = dt.hour if dt.hour <= 12 else dt.hour - 12
    if hour == 0:
        hour = 12
    if dt.minute:
        return _("{ampm} {hour}시 {minute}분").format(ampm=ampm, hour=hour, minute=dt.minute)
    return _("{ampm} {hour}시").format(ampm=ampm, hour=hour)
