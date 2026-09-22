"""문자 n-gram 기반 CPU 전용 분류와 실패 시 기존 경로 유지."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import io
import json
import math
from pathlib import Path
import time
import unicodedata
import zlib

import numpy as np

from agent.decision.candidates import (
    candidate_names as registry_candidate_names,
    is_direct_allowed,
)
from agent.llm_router import get_llm_router


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


class LocalDecisionEngine:
    """요청 시에만 분류하고 불확실하거나 지원되지 않은 요청은 넘긴다."""

    def __init__(self, model_dir: str | Path):
        self.model_dir = model_dir
        self._load_attempted = False
        self._scorer: LinearScorer | None = None
        self.last_decision: DecisionResult | None = None

    def choice(self, state: str) -> DecisionResult | None:
        """기존 복합 요청 규칙을 먼저 적용하고 최대 한 번 추론한다."""
        try:
            if not isinstance(state, str) or not state.strip():
                return None
            if get_llm_router().route(state).task_type != "simple_chat":
                return None
            if not self._load_attempted:
                self._load_attempted = True
                self._scorer = LinearScorer(self.model_dir)
            if self._scorer is None:
                return None
            return self._scorer.predict(state)
        except Exception:
            return None

    def try_fast_path(self, text: str) -> None:
        """통합 지점: 직접 실행은 Phase 5의 검증된 인자 파서 도입까지 보류한다."""
        self.last_decision = None
        try:
            from core.config_manager import ConfigManager

            mode = ConfigManager.get("local_decision_mode", "shadow")
            if not isinstance(mode, str) or mode not in {"off", "shadow", "fast", "adaptive"}:
                mode = "shadow"
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
            decision = self.choice(text)
            if decision is None:
                return None
            self.last_decision = decision
            if mode == "shadow":
                return None
            direct_allowed = is_direct_allowed(decision.choice, mode)
            if (
                decision.choice == UNKNOWN
                or not math.isfinite(decision.confidence)
                or not math.isfinite(decision.margin)
                or decision.confidence < threshold
                or decision.margin < 0.30
                or not direct_allowed
            ):
                return None
            # 인자 파서와 안전 정책이 검증되기 전에는 어떤 도구도 직접 실행하지 않는다.
            return None
        except Exception:
            return None
