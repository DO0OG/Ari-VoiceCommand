"""CosyVoice TTS 순수 유틸.

Qt, PyAudio, subprocess 의존 없이 테스트 가능한 텍스트 정규화와
PCM 버퍼 유틸만 분리합니다.
"""
from __future__ import annotations

import re
from collections import deque
from functools import lru_cache


_NATIVE_HOURS = [
    "",
    "한",
    "두",
    "세",
    "네",
    "다섯",
    "여섯",
    "일곱",
    "여덟",
    "아홉",
    "열",
    "열한",
    "열두",
]
_SINO_ONES = ["", "일", "이", "삼", "사", "오", "육", "칠", "팔", "구"]
_DIGIT_NAMES = ["영", "일", "이", "삼", "사", "오", "육", "칠", "팔", "구"]


def _sino(n: int) -> str:
    """정수를 한자어 수사 문자열로 변환 (0~9999)."""
    if n < 0:
        return "마이너스 " + _sino(abs(n))
    if n == 0:
        return "영"
    if n > 9999:
        return "".join(_DIGIT_NAMES[int(d)] for d in str(n))

    result = ""
    if n >= 1000:
        thousands = n // 1000
        result += ("" if thousands == 1 else _SINO_ONES[thousands]) + "천"
        n %= 1000
    if n >= 100:
        hundreds = n // 100
        result += ("" if hundreds == 1 else _SINO_ONES[hundreds]) + "백"
        n %= 100
    if n >= 10:
        tens = n // 10
        result += ("" if tens == 1 else _SINO_ONES[tens]) + "십"
        n %= 10
    if n > 0:
        result += _SINO_ONES[n]
    return result


def _normalize_text(text: str) -> str:
    """TTS 전 숫자를 한국어 발음으로 변환."""

    def repl_hour(match: re.Match[str]) -> str:
        hour = int(match.group(1))
        return (_NATIVE_HOURS[hour] if 1 <= hour <= 12 else _sino(hour)) + "시"

    text = re.sub(r"(\d{1,2})시", repl_hour, text)
    text = re.sub(r"(\d{1,2})분", lambda match: _sino(int(match.group(1))) + "분", text)
    text = re.sub(r"(\d{1,2})초", lambda match: _sino(int(match.group(1))) + "초", text)
    text = re.sub(r"\d+", lambda match: _sino(int(match.group(0))), text)
    return text


@lru_cache(maxsize=256)
def _normalize_text_cached(text: str) -> str:
    return _normalize_text(text)


class _PCMChunkBuffer:
    """콜백 재생용 PCM 청크 버퍼."""

    def __init__(self):
        self._chunks = deque()
        self._size = 0

    def clear(self) -> None:
        self._chunks.clear()
        self._size = 0

    def append(self, data: bytes) -> None:
        if not data:
            return
        self._chunks.append(data)
        self._size += len(data)

    def pop_bytes(self, nbytes: int) -> bytes:
        if nbytes <= 0 or self._size <= 0:
            return b""

        remaining = nbytes
        parts = []
        while remaining > 0 and self._chunks:
            chunk = self._chunks[0]
            if len(chunk) <= remaining:
                parts.append(chunk)
                self._chunks.popleft()
                self._size -= len(chunk)
                remaining -= len(chunk)
            else:
                parts.append(chunk[:remaining])
                self._chunks[0] = chunk[remaining:]
                self._size -= remaining
                remaining = 0
        return b"".join(parts)

    @property
    def size(self) -> int:
        return self._size
