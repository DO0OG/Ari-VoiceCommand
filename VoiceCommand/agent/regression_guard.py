"""전략 성공률 회귀 감지."""
from __future__ import annotations

from dataclasses import dataclass
import threading


@dataclass
class RegressionCheckResult:
    current_success_rate: float
    previous_success_rate: float
    current_total: int
    previous_total: int
    drop: float
    alert_message: str = ""

    @property
    def is_regression(self) -> bool:
        return bool(self.alert_message)


class RegressionGuard:
    ALERT_THRESHOLD = 0.10
    MIN_SAMPLE = 10

    def evaluate(self) -> RegressionCheckResult:
        from agent.strategy_memory import get_strategy_memory

        strategy_memory = get_strategy_memory()
        this_week = strategy_memory.get_stats(days=7)
        last_week = strategy_memory.get_stats(days=7, offset=7)
        current_total = int(this_week.get("total", 0) or 0)
        previous_total = int(last_week.get("total", 0) or 0)
        current_rate = float(this_week.get("success_rate", 0.0) or 0.0)
        previous_rate = float(last_week.get("success_rate", 0.0) or 0.0)
        drop = previous_rate - current_rate

        if current_total < self.MIN_SAMPLE or previous_total < self.MIN_SAMPLE:
            return RegressionCheckResult(
                current_success_rate=current_rate,
                previous_success_rate=previous_rate,
                current_total=current_total,
                previous_total=previous_total,
                drop=drop,
            )

        if drop >= self.ALERT_THRESHOLD:
            return RegressionCheckResult(
                current_success_rate=current_rate,
                previous_success_rate=previous_rate,
                current_total=current_total,
                previous_total=previous_total,
                drop=drop,
                alert_message=(
                    f"이번 주 성공률이 {drop:.0%} 하락했어요 "
                    f"({previous_rate:.0%} → {current_rate:.0%}). 최근 변경 사항을 확인해보세요."
                ),
            )

        return RegressionCheckResult(
            current_success_rate=current_rate,
            previous_success_rate=previous_rate,
            current_total=current_total,
            previous_total=previous_total,
            drop=drop,
        )

    def check(self) -> str | None:
        result = self.evaluate()
        return result.alert_message or None


_guard: RegressionGuard | None = None
_guard_lock = threading.Lock()


def get_regression_guard() -> RegressionGuard:
    global _guard
    if _guard is None:
        with _guard_lock:
            if _guard is None:
                _guard = RegressionGuard()
    return _guard
