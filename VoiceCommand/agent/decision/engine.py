"""문자 n-gram 기반 CPU 전용 분류와 실패 시 기존 경로 유지."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import io
import json
import math
from pathlib import Path
import threading
import time
import unicodedata
import zlib

import numpy as np

from agent.decision.candidates import (
    candidate_names as registry_candidate_names,
    is_direct_allowed,
)
from agent.decision.semantics import is_multi_intent, parse_candidate


UNKNOWN = "unknown_or_complex"


def candidate_names() -> tuple[str, ...]:
    """Return the registered candidate names with the abstain label last."""
    return registry_candidate_names()


def hash_features(text: str, buckets: int = 8192) -> tuple[np.ndarray, np.ndarray]:
    """Unicode 2~5 gram을 안정적인 해시와 L2 정규화로 변환한다."""
    normalized = " ".join(unicodedata.normalize("NFKC", text).casefold().split())
    counts = Counter(
        zlib.crc32(normalized[start:start + size].encode("utf-8")) % buckets
        for size in range(2, 6)
        for start in range(len(normalized) - size + 1)
    )
    indices = np.fromiter(counts, dtype=np.intp)
    values = np.fromiter(counts.values(), dtype=np.float32)
    norm = np.linalg.norm(values)
    if norm:
        values /= norm
    return indices, values


def softmax(logits: np.ndarray, temperature: float = 1.0) -> np.ndarray:
    """마지막 축을 따라 수치적으로 안정된 보정 확률을 반환한다."""
    if not math.isfinite(temperature) or temperature <= 0:
        raise ValueError("Invalid temperature")
    values = np.asarray(logits, dtype=np.float64)
    if not np.isfinite(values).all():
        raise ValueError("Non-finite logits")
    values = (values - values.max(axis=-1, keepdims=True)) / temperature
    exponentials = np.exp(values)
    return exponentials / exponentials.sum(axis=-1, keepdims=True)


@dataclass(frozen=True)
class DecisionResult:
    choice: str
    probabilities: dict[str, float]
    confidence: float
    margin: float
    source: str
    latency_ms: float


@dataclass(frozen=True)
class FastPathResult:
    """검증을 마친 단일 실행 요청과 판정 근거만 담는다."""

    tool_name: str
    arguments: dict[str, object]
    confidence: float
    margin: float
    source: str
    parse_success: bool


class LinearScorer:
    """검증한 수치 파일만 읽고 한 번의 선형 계산으로 분류한다."""

    def __init__(self, model_dir: str | Path):
        directory = Path(model_dir)
        config = json.loads((directory / "config.json").read_text(encoding="utf-8"))
        self.labels = tuple(config["labels"])
        self.buckets = config["buckets"]
        self.temperature = float(config["temperature"])
        if (
            config["version"] != 1
            or self.labels != candidate_names()
            or type(self.buckets) is not int
            or not 1 <= self.buckets <= 65536
            or not math.isfinite(self.temperature)
            or self.temperature <= 0
            or not config["dataset_version"]
            or not config["calibration_version"]
        ):
            raise ValueError("Unsupported configuration")
        payload = (directory / "weights.npz").read_bytes()
        if hashlib.sha256(payload).hexdigest() != config["sha256"]:
            raise ValueError("Checksum mismatch")
        self.sha256 = config["sha256"]
        with np.load(io.BytesIO(payload), allow_pickle=False) as arrays:
            self.weights = arrays["weights"].astype(np.float32)
            self.bias = arrays["bias"].astype(np.float32)
        if (
            self.weights.shape != (len(self.labels), self.buckets)
            or self.bias.shape != (len(self.labels),)
            or not np.isfinite(self.weights).all()
            or not np.isfinite(self.bias).all()
        ):
            raise ValueError("Invalid weights")

    def predict(self, text: str) -> DecisionResult:
        """전체 후보의 확률, 최고 확률과 차이를 반환한다."""
        started = time.perf_counter()
        if not isinstance(text, str) or not text.strip() or len(text) > 4096:
            raise ValueError("Unsupported input")
        indices, values = hash_features(text, self.buckets)
        logits = (self.weights[:, indices] * values).sum(axis=1) + self.bias
        probabilities = softmax(logits, self.temperature)
        order = np.argsort(probabilities)
        best = int(order[-1])
        return DecisionResult(
            choice=self.labels[best],
            probabilities=dict(zip(self.labels, map(float, probabilities))),
            confidence=float(probabilities[best]),
            margin=float(probabilities[best] - probabilities[order[-2]]),
            source="linear",
            latency_ms=(time.perf_counter() - started) * 1000,
        )


_MODES = frozenset({"off", "shadow", "fast", "adaptive"})
# Local, text-free counters. They reset with the process or reset_diagnostics()
# and are never fed back into training.
_COUNTERS = (
    "decision_total",
    "fast_selected",
    "fast_executed",
    "parser_rejected",
    "multi_intent_rejected",
    "llm_fallback",
    "execution_failed",
    "llm_calls_saved",
    "possible_correction",
)
# ponytail: only volume has an opposite direction to detect; add other tools when they get one.
_CORRECTION_WINDOW_S = 20.0
_OPPOSITE_DIRECTION = {"up": "down", "down": "up"}


def _configured_mode() -> str:
    from core.config_manager import ConfigManager

    mode = ConfigManager.get("local_decision_mode", "shadow")
    return mode if isinstance(mode, str) and mode in _MODES else "shadow"


def _disabled_reason() -> str:
    """Explain without user text why a local choice would not run directly."""
    from core.config_manager import ConfigManager

    mode = _configured_mode()
    if mode == "off":
        return "mode_off"
    if ConfigManager.get("local_decision_engine_enabled", True) is not True:
        return "engine_disabled"
    if mode == "shadow":
        return "shadow_mode"
    if ConfigManager.get("local_decision_direct_execution", False) is not True:
        return "direct_execution_off"
    return ""


class LocalDecisionEngine:
    """요청 시에만 분류하고 불확실하거나 지원되지 않은 요청은 넘긴다."""

    def __init__(self, model_dir: str | Path):
        self.model_dir = model_dir
        self._load_attempted = False
        self._scorer: LinearScorer | None = None
        self.last_decision: DecisionResult | None = None
        self._lock = threading.Lock()
        self._counters = dict.fromkeys(_COUNTERS, 0)
        self._error_code = ""
        self._last_volume: tuple[str, float] | None = None

    def record(self, name: str) -> None:
        """Increment one diagnostic counter."""
        with self._lock:
            self._counters[name] += 1

    def metrics(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counters)

    def health(self) -> dict[str, str]:
        """Load state, last error code and the reason direct execution is off."""
        with self._lock:
            scorer = self._scorer
            attempted = self._load_attempted
            error_code = self._error_code
        if scorer is not None:
            state = "ready"
        else:
            state = "error" if attempted else "not_loaded"
        try:
            reason = _disabled_reason()
        except Exception:
            reason = "settings_unavailable"
        if state == "error" and not reason:
            reason = "model_unavailable"
        return {
            "state": state,
            "error_code": error_code,
            "disabled_reason": reason,
            "model_sha256": scorer.sha256 if scorer is not None else "",
        }

    def reload(self) -> None:
        """Retry loading on the next request. Failed loads are never retried on their own."""
        with self._lock:
            self._load_attempted = False
            self._scorer = None
            self._error_code = ""

    def reset_diagnostics(self) -> None:
        with self._lock:
            self._counters = dict.fromkeys(_COUNTERS, 0)
            self._error_code = ""
            self._last_volume = None

    def note_executed(self, result: FastPathResult) -> None:
        """Count a completed direct run and remember a volume change for correction hints."""
        with self._lock:
            self._counters["fast_executed"] += 1
            self._counters["llm_calls_saved"] += 1
            direction = result.arguments.get("direction")
            if result.tool_name == "adjust_volume" and direction in _OPPOSITE_DIRECTION:
                self._last_volume = (str(direction), time.monotonic())

    def _note_possible_correction(self, text: str, decision: DecisionResult) -> None:
        with self._lock:
            last = self._last_volume
        if last is None or decision.choice != "adjust_volume":
            return
        direction, executed_at = last
        if time.monotonic() - executed_at > _CORRECTION_WINDOW_S:
            return
        parsed = parse_candidate(text, "adjust_volume")
        if parsed.arguments.get("direction") == _OPPOSITE_DIRECTION[direction]:
            with self._lock:
                self._counters["possible_correction"] += 1
                self._last_volume = None

    def choice(self, state: str) -> DecisionResult | None:
        """전용 복합 요청 검사를 먼저 적용하고 최대 한 번 추론한다."""
        try:
            if not isinstance(state, str) or not state.strip():
                return None
            if is_multi_intent(state):
                self.record("multi_intent_rejected")
                return None
            if not self._load_attempted:
                self._load_attempted = True
                try:
                    self._scorer = LinearScorer(self.model_dir)
                except Exception:
                    self._error_code = "model_load_failed"
                    return None
            if self._scorer is None:
                return None
            return self._scorer.predict(state)
        except Exception:
            self._error_code = "prediction_failed"
            return None

    def try_fast_path(self, text: str) -> FastPathResult | None:
        """분류와 의미 해석, 허용 정책이 모두 일치할 때만 실행 요청을 반환한다."""
        self.last_decision = None
        counted = False
        try:
            from core.config_manager import ConfigManager

            mode = _configured_mode()
            if mode == "off":
                return None
            if ConfigManager.get("local_decision_engine_enabled", True) is not True:
                return None
            if ConfigManager.get("local_decision_backend", "linear") != "linear":
                return None
            threshold = ConfigManager.get("local_decision_threshold", 0.92)
            if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
                return None
            if not math.isfinite(threshold) or not 0 <= threshold <= 1:
                return None
            self.record("decision_total")
            counted = True
            decision = self.choice(text)
            if decision is None:
                return self._fallback()
            self.last_decision = decision
            self._note_possible_correction(text, decision)
            if mode == "shadow":
                return self._fallback()
            # 모드와 별개로 직접 실행 설정이 명시적으로 켜져 있어야 한다.
            if ConfigManager.get("local_decision_direct_execution", False) is not True:
                return self._fallback()
            direct_allowed = is_direct_allowed(decision.choice, mode)
            if (
                decision.choice == UNKNOWN
                or not math.isfinite(decision.confidence)
                or not math.isfinite(decision.margin)
                or decision.confidence < threshold
                or decision.margin < 0.30
                or not direct_allowed
            ):
                return self._fallback()
            parsed = parse_candidate(text, decision.choice)
            if not parsed.parse_success:
                self.record("parser_rejected")
                return self._fallback()
            self.record("fast_selected")
            return FastPathResult(
                tool_name=decision.choice,
                arguments=dict(parsed.arguments),
                confidence=decision.confidence,
                margin=decision.margin,
                source=decision.source,
                parse_success=parsed.parse_success,
            )
        except Exception:
            self._error_code = "fast_path_failed"
            return self._fallback() if counted else None

    def _fallback(self) -> None:
        self.record("llm_fallback")
        return None
