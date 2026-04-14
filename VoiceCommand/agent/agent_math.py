"""에이전트 공통 수학 유틸리티."""

from __future__ import annotations

try:
    import numpy as np

    def cosine_similarity(a, b) -> float:
        """두 벡터의 코사인 유사도. numpy 배열 또는 list 모두 수용한다."""
        if a is None or b is None:
            return 0.0
        if not hasattr(a, "__len__") or not hasattr(b, "__len__"):
            return 0.0
        if len(a) == 0 or len(b) == 0 or len(a) != len(b):
            return 0.0
        a_arr = np.asarray(a, dtype=float)
        b_arr = np.asarray(b, dtype=float)
        denom = float(np.linalg.norm(a_arr) * np.linalg.norm(b_arr))
        if denom == 0:
            return 0.0
        return float(np.dot(a_arr, b_arr) / denom)

except ImportError:
    import math

    def cosine_similarity(a, b) -> float:  # type: ignore[misc]
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)
