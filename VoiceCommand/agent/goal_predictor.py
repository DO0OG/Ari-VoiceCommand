"""과거 유사 전략을 바탕으로 목표 위험도를 예측합니다."""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import List


@dataclass
class PredictionResult:
    estimated_success_rate: float
    risk_factors: List[str] = field(default_factory=list)
    sample_size: int = 0
    supporting_goals: List[str] = field(default_factory=list)
    warning_kr: str = ""

    @property
    def is_high_risk(self) -> bool:
        return bool(self.warning_kr)


class GoalPredictor:
    @staticmethod
    def _has_repeated_failure_signal(items: List[str]) -> bool:
        for item in items:
            match = re.search(r"(\d+)회", str(item))
            if match and int(match.group(1)) >= 2:
                return True
        return False

    def predict(self, goal: str, limit: int = 10) -> PredictionResult:
        from agent.strategy_memory import get_strategy_memory

        records = get_strategy_memory().search_similar_records(goal, limit=limit)
        if not records:
            return PredictionResult(estimated_success_rate=0.5, sample_size=0)

        success_count = len([record for record in records if record.success])
        sample_size = len(records)
        failed_records = [record for record in records if not record.success]
        failure_counts = Counter(
            str(record.failure_kind or "execution_failed")
            for record in failed_records
        )
        risk_factors = [
            f"{failure_kind} {count}회"
            for failure_kind, count in failure_counts.most_common(3)
        ]
        for record in failed_records:
            lesson = str(record.lesson or "").strip()
            if lesson and lesson not in risk_factors:
                risk_factors.append(lesson[:120])
            if len(risk_factors) >= 4:
                break

        estimated_success_rate = success_count / sample_size if sample_size else 0.5
        return PredictionResult(
            estimated_success_rate=estimated_success_rate,
            risk_factors=risk_factors,
            sample_size=sample_size,
            supporting_goals=[record.goal_summary[:80] for record in records[:3]],
        )

    def warn_if_high_risk(self, goal: str, limit: int = 10) -> PredictionResult:
        result = self.predict(goal, limit=limit)
        if result.sample_size < 3:
            return result

        warning = ""
        success_percent = int(result.estimated_success_rate * 100)
        top_risk = result.risk_factors[0] if result.risk_factors else ""
        if result.estimated_success_rate < 0.35:
            warning = f"유사 작업 {result.sample_size}건의 성공률이 {success_percent}%로 낮습니다."
        elif result.estimated_success_rate < 0.5 and self._has_repeated_failure_signal(result.risk_factors):
            warning = f"유사 작업의 실패 패턴이 반복되고 있습니다. 현재 성공률은 {success_percent}%입니다."
        if warning and top_risk:
            warning = f"{warning} 특히 {top_risk} 위험이 자주 보였습니다."

        result.warning_kr = warning
        return result


_predictor: GoalPredictor | None = None


def get_goal_predictor() -> GoalPredictor:
    global _predictor
    if _predictor is None:
        _predictor = GoalPredictor()
    return _predictor
