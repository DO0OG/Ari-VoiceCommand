from __future__ import annotations

"""
FACT 신뢰도 업데이트 엔진.
"""

from dataclasses import dataclass
import logging
import math
import threading

_source_weight_lock = threading.Lock()

SOURCE_WEIGHTS: dict[str, float] = {
    "user": 1.0,
    "assistant": 0.7,
    "learned": 0.5,
    "inferred": 0.4,
    "external": 0.6,
}
DEFAULT_SOURCE_WEIGHT = 0.6
_MIN_SOURCE_WEIGHT = 0.2
_MAX_SOURCE_WEIGHT = 1.2

REINFORCE_BASE = 0.08
REINFORCE_DECAY = 0.015
CONFLICT_PENALTY_BASE = 0.12
CONFLICT_ESCALATION = 0.04
MAX_CONFLICT_PENALTY = 0.30
MIN_CONFIDENCE = 0.05
MAX_CONFIDENCE = 1.0
DECAY_RATE_PER_30_DAYS = 0.95


@dataclass
class TrustUpdateResult:
    new_confidence: float
    delta: float
    action: str
    reason: str


def compute_reinforcement(prior: float, source: str, reinforcement_count: int) -> TrustUpdateResult:
    sw = SOURCE_WEIGHTS.get(source, DEFAULT_SOURCE_WEIGHT)
    base = REINFORCE_BASE * sw
    bonus = REINFORCE_DECAY * math.log2(1 + min(reinforcement_count, 10)) * sw
    posterior = min(prior + base + bonus, MAX_CONFIDENCE)
    return TrustUpdateResult(posterior, posterior - prior, "reinforce", "재확인으로 신뢰도 강화")


def compute_conflict_update(prior: float, new_confidence: float, prior_source: str, new_source: str, conflict_count: int) -> TrustUpdateResult:
    prior_sw = SOURCE_WEIGHTS.get(prior_source, DEFAULT_SOURCE_WEIGHT)
    new_sw = SOURCE_WEIGHTS.get(new_source, DEFAULT_SOURCE_WEIGHT)
    if new_sw >= prior_sw and new_confidence > prior + 0.2:
        posterior = min(new_confidence * 0.9, MAX_CONFIDENCE)
        return TrustUpdateResult(posterior, posterior - prior, "conflict_replace", "더 신뢰도 높은 새 정보로 교체")
    if abs(new_confidence - prior) <= 0.2:
        blended = (new_confidence * new_sw + prior * prior_sw) / max(new_sw + prior_sw, 1e-6)
        penalty = min(CONFLICT_PENALTY_BASE + CONFLICT_ESCALATION * conflict_count, MAX_CONFLICT_PENALTY)
        posterior = max(blended - penalty, MIN_CONFIDENCE)
        return TrustUpdateResult(posterior, posterior - prior, "conflict_blend", "충돌 정보를 보수적으로 혼합")
    if prior_sw > new_sw and prior > new_confidence + 0.1:
        posterior = max(prior - 0.05, MIN_CONFIDENCE)
        return TrustUpdateResult(posterior, posterior - prior, "conflict_resist", "기존 고신뢰 정보 유지")
    posterior = max(min((prior + new_confidence) / 2.0, MAX_CONFIDENCE) - 0.08, MIN_CONFIDENCE)
    return TrustUpdateResult(posterior, posterior - prior, "conflict_blend", "충돌 정보 재평가")


def compute_decay(prior: float, days_since_update: int, access_count: int = 0) -> TrustUpdateResult:
    periods = max(days_since_update // 30, 0)
    decay_modifier = 1.0 - min(access_count * 0.02, 0.3)
    decay = DECAY_RATE_PER_30_DAYS ** (periods * decay_modifier)
    posterior = max(prior * decay, MIN_CONFIDENCE)
    return TrustUpdateResult(posterior, posterior - prior, "decay", "시간 경과에 따른 감쇠")


def should_remove(confidence: float, conflict_count: int, last_updated_days: int) -> bool:
    return confidence < 0.12 or (conflict_count >= 5 and confidence < 0.25) or (last_updated_days > 365 and confidence < 0.30)


def batch_decay(facts: dict, current_time) -> dict:
    updated = {}
    for key, payload in (facts or {}).items():
        try:
            updated_at = payload.get("updated_at")
            if not updated_at:
                updated[key] = payload
                continue
            days = max((current_time - __import__("datetime").datetime.fromisoformat(updated_at)).days, 0)
            result = compute_decay(
                float(payload.get("confidence", 0.7)),
                days,
                int(payload.get("access_count", 0)),
            )
            if should_remove(result.new_confidence, int(payload.get("conflict_count", 0)), days):
                continue
            new_payload = dict(payload)
            new_payload["confidence"] = round(result.new_confidence, 2)
            updated[key] = new_payload
        except Exception as exc:
            logging.debug("batch_decay 오류 (key=%s): %s", key, exc)
            updated[key] = payload
    return updated


def update_source_weight(source: str, was_correct: bool) -> float:
    with _source_weight_lock:
        current = SOURCE_WEIGHTS.get(source, DEFAULT_SOURCE_WEIGHT)
        delta = 0.03 if was_correct else -0.05
        SOURCE_WEIGHTS[source] = max(_MIN_SOURCE_WEIGHT, min(_MAX_SOURCE_WEIGHT, round(current + delta, 2)))
        return SOURCE_WEIGHTS[source]


if __name__ == "__main__":
    print(compute_reinforcement(0.5, "user", 3))
