"""타이머 관리 모듈."""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field


@dataclass
class TimerEntry:
    name: str
    minutes: float
    callback: callable
    created_at: float = field(default_factory=time.time)
    order: int = 0

    def __post_init__(self):
        delay_seconds = max(0.0, self.minutes * 60)
        self.deadline = self.created_at + delay_seconds
        self._timer = threading.Timer(delay_seconds, self.callback)
        self._timer.daemon = True
        self._timer.start()

    def cancel(self):
        self._timer.cancel()

    def remaining_seconds(self) -> float:
        return max(0.0, self.deadline - time.time())


class TimerManager:
    """복수 타이머 관리 클래스."""

    _MAX_TIMERS = 10

    def __init__(self, tts_callback=None):
        self._timers: dict[str, TimerEntry] = {}
        self._lock = threading.Lock()
        self.tts_callback = tts_callback or (lambda x: logging.info(x))
        self._order_counter = 0

    def set_timer(self, minutes: float, name: str = "") -> str:
        with self._lock:
            normalized_name = (name or "").strip() or self._auto_name()
            replacing = normalized_name in self._timers
            if not replacing and len(self._timers) >= self._MAX_TIMERS:
                raise ValueError(f"타이머는 최대 {self._MAX_TIMERS}개까지 설정할 수 있습니다.")
            if replacing:
                self._timers[normalized_name].cancel()

            label = self.format_duration_label(minutes)
            self._order_counter += 1
            entry = TimerEntry(
                name=normalized_name,
                minutes=minutes,
                callback=lambda timer_name=normalized_name, timer_label=label: self._on_alarm(timer_name, timer_label),
                order=self._order_counter,
            )
            self._timers[normalized_name] = entry

        if normalized_name.startswith("타이머 "):
            self.tts_callback(f"{label} 타이머를 설정했습니다.")
        else:
            self.tts_callback(f"'{normalized_name}' 타이머를 설정했습니다. ({label})")
        logging.info("타이머 설정: %s (%s)", normalized_name, label)
        return normalized_name

    def cancel(self):
        self.cancel_timer()

    def cancel_timer(self, name: str = "") -> bool:
        with self._lock:
            target_name = (name or "").strip()
            if not target_name:
                if not self._timers:
                    self.tts_callback("현재 실행 중인 타이머가 없습니다.")
                    return False
                target_name = max(self._timers, key=lambda key: self._timers[key].order)
            entry = self._timers.pop(target_name, None)
            if entry is None:
                self.tts_callback(f"'{target_name}' 타이머를 찾지 못했습니다.")
                return False
            entry.cancel()

        if target_name.startswith("타이머 "):
            self.tts_callback("타이머가 취소되었습니다.")
        else:
            self.tts_callback(f"'{target_name}' 타이머를 취소했습니다.")
        return True

    def get_remaining_time(self):
        with self._lock:
            if not self._timers:
                return None
            latest = max(self._timers.values(), key=lambda item: item.order)
            return latest.remaining_seconds()

    def list_timers(self) -> list[dict]:
        with self._lock:
            return [
                {"name": name, "remaining_seconds": entry.remaining_seconds()}
                for name, entry in sorted(self._timers.items(), key=lambda item: item[1].order)
            ]

    def parse_timer_command(self, command):
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

    @staticmethod
    def format_duration_label(total_minutes: float) -> str:
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

    def _on_alarm(self, name: str, label: str):
        with self._lock:
            self._timers.pop(name, None)
        if name.startswith("타이머 "):
            message = f"{label} 타이머가 완료되었습니다."
        else:
            message = f"'{name}' 타이머가 완료되었습니다."
        self.tts_callback(message)
        logging.info("타이머 완료: %s", name)

    def _auto_name(self) -> str:
        existing = set(self._timers.keys())
        index = 1
        while f"타이머 {index}" in existing:
            index += 1
        return f"타이머 {index}"
