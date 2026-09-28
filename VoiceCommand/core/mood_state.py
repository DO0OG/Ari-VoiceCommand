"""캐릭터의 기분을 감쇠하고 저장한다."""

import json
import logging
import math
import os
import threading
import time

from core.atomic_io import backup_corrupt_file, write_json_atomic
from core.resource_manager import ResourceManager


_HALF_LIFE_SECONDS = 2 * 60 * 60
_RETURN_THRESHOLD_SECONDS = 30 * 60
_BIG_CHANGE_THRESHOLD = 0.2
_BIG_MOTION_COOLDOWN_SECONDS = 60


class MoodState:
    """valence와 arousal을 중립값으로 서서히 되돌린다."""

    def __init__(self, path: str | None = None, clock=time.time):
        self._clock = clock
        self._lock = threading.RLock()
        self._path = path
        self._valence = 0.0
        self._arousal = 0.0
        self._updated_at = self._clock()
        self._last_significant_change_at = None
        self._last_big_motion_at = None

        if self._path is None:
            try:
                self._path = ResourceManager.get_writable_path("mood_state.json")
            except (OSError, TypeError, ValueError) as exc:
                logging.warning("기분 상태 저장 경로를 사용할 수 없습니다: %s", exc)
        self._load()

    def _load(self) -> None:
        if not self._path or not os.path.isfile(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if not isinstance(payload, dict):
                raise ValueError("기분 상태 형식이 올바르지 않습니다.")
            values = (
                payload.get("valence"),
                payload.get("arousal"),
                payload.get("updated_at"),
            )
            if any(isinstance(value, bool) for value in values):
                raise ValueError("기분 상태 값이 올바르지 않습니다.")
            valence, arousal, updated_at = (float(value) for value in values)
            if not all(math.isfinite(value) for value in (valence, arousal, updated_at)):
                raise ValueError("기분 상태 값이 유한하지 않습니다.")
        except json.JSONDecodeError as exc:
            logging.warning("손상된 기분 상태를 기본값으로 시작합니다: %s", exc)
            self._backup_corrupt_state()
            return
        except (
            OSError,
            OverflowError,
            TypeError,
            ValueError,
        ) as exc:
            logging.warning("기분 상태를 읽지 못해 기본값으로 시작합니다: %s", exc)
            if not isinstance(exc, OSError):
                self._backup_corrupt_state()
            return

        self._valence = self._clamp(valence, -1.0, 1.0)
        self._arousal = self._clamp(arousal, 0.0, 1.0)
        self._updated_at = updated_at

    def _backup_corrupt_state(self) -> None:
        if not self._path:
            return
        try:
            backup_corrupt_file(self._path)
        except OSError as exc:
            logging.warning("손상된 기분 상태 백업 실패: %s", exc)

    @staticmethod
    def _clamp(value: float, minimum: float, maximum: float) -> float:
        return max(minimum, min(maximum, value))

    def _values_at(self, now: float) -> tuple[float, float]:
        elapsed = max(0.0, now - self._updated_at)
        decay = math.pow(0.5, elapsed / _HALF_LIFE_SECONDS)
        return self._valence * decay, self._arousal * decay

    def values(self, now: float | None = None) -> tuple[float, float]:
        """현재 시각에 감쇠한 두 값을 반환한다."""
        with self._lock:
            return self._values_at(self._clock() if now is None else now)

    def _apply(self, valence_delta: float, arousal_delta: float, now: float) -> None:
        with self._lock:
            valence, arousal = self._values_at(now)
            self._valence = self._clamp(valence + valence_delta, -1.0, 1.0)
            self._arousal = self._clamp(arousal + arousal_delta, 0.0, 1.0)
            self._updated_at = now
            actual_change = math.hypot(
                self._valence - valence,
                self._arousal - arousal,
            )
            if actual_change >= _BIG_CHANGE_THRESHOLD:
                self._last_significant_change_at = now
            self._save()

    def record_interaction(
        self,
        *,
        praised: bool = False,
        criticized: bool = False,
        late_night_long_use: bool = False,
        now: float | None = None,
    ) -> None:
        """대화, 칭찬, 심야 장시간 사용을 반영한다."""
        valence_delta = 0.02
        arousal_delta = 0.03
        if praised:
            valence_delta += 0.22
            arousal_delta += 0.08
        if criticized:
            valence_delta -= 0.22
            arousal_delta += 0.08
        if late_night_long_use:
            valence_delta -= 0.24
            arousal_delta += 0.12
        self._apply(
            valence_delta,
            arousal_delta,
            self._clock() if now is None else now,
        )

    def record_away_return(
        self,
        away_seconds: int,
        now: float | None = None,
    ) -> None:
        """긴 이탈 뒤 복귀를 반영한다."""
        if away_seconds < _RETURN_THRESHOLD_SECONDS:
            return
        self._apply(0.1, 0.24, self._clock() if now is None else now)

    def record_task_result(self, achieved: bool, now: float | None = None) -> None:
        """작업 성공이나 실패를 반영한다."""
        if achieved:
            valence_delta, arousal_delta = 0.12, 0.08
        else:
            valence_delta, arousal_delta = -0.16, 0.08
        self._apply(
            valence_delta,
            arousal_delta,
            self._clock() if now is None else now,
        )

    def claim_big_motion(self, now: float | None = None) -> bool:
        """큰 기분 변화 직후 쿨다운을 지키며 한 번만 허용한다."""
        current = self._clock() if now is None else now
        with self._lock:
            if self._last_significant_change_at is None:
                return False
            if current - self._last_significant_change_at > _BIG_MOTION_COOLDOWN_SECONDS:
                return False
            if (
                self._last_big_motion_at is not None
                and current - self._last_big_motion_at < _BIG_MOTION_COOLDOWN_SECONDS
            ):
                return False
            self._last_big_motion_at = current
            return True

    def _save(self) -> None:
        if not self._path:
            return
        try:
            write_json_atomic(
                self._path,
                {
                    "valence": self._valence,
                    "arousal": self._arousal,
                    "updated_at": self._updated_at,
                },
                ensure_ascii=False,
                indent=2,
            )
        except (OSError, TypeError, ValueError) as exc:
            logging.warning("기분 상태 저장 실패: %s", exc)


_mood_state: MoodState | None = None
_mood_state_lock = threading.Lock()


def initialize_mood_state() -> MoodState:
    """앱 시작 시 저장된 기분 상태를 읽는다."""
    global _mood_state
    if _mood_state is None:
        with _mood_state_lock:
            if _mood_state is None:
                _mood_state = MoodState()
    return _mood_state


def get_mood_state() -> MoodState | None:
    """초기화된 기분 상태를 반환한다."""
    return _mood_state
