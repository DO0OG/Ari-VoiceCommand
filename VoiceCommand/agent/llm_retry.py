"""LLM 호출 재시도 판단 공통 유틸리티."""

from __future__ import annotations

import logging
import re

_LLM_RETRYABLE_ERROR_RE = re.compile(
    r"(429|resource_exhausted|quota exceeded|rate limit|retry in|retrydelay|temporar|timeout|overloaded|too many requests)",
    re.IGNORECASE,
)
_LLM_RETRY_DELAY_RE_LIST = (
    re.compile(r"retry in\s*([\d.]+)\s*s", re.IGNORECASE),
    re.compile(r"retrydelay['\"]?\s*[:=]\s*['\"]?([\d.]+)\s*s", re.IGNORECASE),
    re.compile(r"'retryDelay':\s*'([\d.]+)s'", re.IGNORECASE),
)


def is_retryable_llm_error(error: Exception) -> bool:
    return bool(_LLM_RETRYABLE_ERROR_RE.search(str(error or "")))


def extract_retry_delay_seconds(error: Exception, attempt: int) -> float:
    text = str(error or "")
    for pattern in _LLM_RETRY_DELAY_RE_LIST:
        match = pattern.search(text)
        if match:
            try:
                return max(0.5, min(float(match.group(1)), 60.0))
            except Exception as exc:
                logging.debug("[LLM] 재시도 지연 파싱 실패, 다음 패턴 확인: %s", exc)
                continue
    return min(2.0 * (attempt + 1), 10.0)
