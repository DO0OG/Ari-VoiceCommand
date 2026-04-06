"""CosyVoice TTS 순수 유틸.

Qt, PyAudio, subprocess 의존 없이 테스트 가능한 텍스트 정규화와
PCM 버퍼 유틸만 분리합니다.
"""
from __future__ import annotations

import re
from collections import deque
from functools import lru_cache

_SENT_PERIOD = re.compile(r'(?<!\.)[.。](?=[ \t\n]|$)')
_SPACE_RE = re.compile(r"\s+")
_TRAILING_PUNCT_RE = re.compile(r"([.!?…。！？]+)$")
_BREATH_CONNECTORS = {
    "그리고",
    "그런데",
    "그래서",
    "그러니까",
    "하지만",
    "다만",
    "또",
    "또한",
    "대신",
    "혹은",
    "아니면",
}
_BREATH_COMMA_CHARS = ",;:，、"
_BREATH_MIN_COMPACT_LEN = 22
_BREATH_MIN_PREFIX_LEN = 8
_BREATH_MIN_SUFFIX_LEN = 6
_SEGMENT_MAX_COMPACT_LEN = 28
_SEGMENT_MIN_PREFIX_LEN = 8
_SEGMENT_MIN_SUFFIX_LEN = 6


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


def _compact_len(text: str) -> int:
    return len(text.replace(" ", ""))


def _split_with_punctuation(text: str) -> list[str]:
    if not text:
        return []

    parts = re.split(r"([.!?…。！？]+)", text)
    sentences: list[str] = []
    for idx in range(0, len(parts), 2):
        body = parts[idx].strip()
        punct = parts[idx + 1] if idx + 1 < len(parts) else ""
        sentence = f"{body}{punct}".strip()
        if sentence:
            sentences.append(sentence)
    return sentences


def _insert_breath_comma(sentence: str) -> str:
    trailing_match = _TRAILING_PUNCT_RE.search(sentence)
    trailing = trailing_match.group(1) if trailing_match else ""
    body = sentence[:-len(trailing)] if trailing else sentence
    body = body.strip()
    if not body or any(char in body for char in _BREATH_COMMA_CHARS):
        return sentence

    words = body.split()
    if len(words) < 3 or _compact_len(body) < _BREATH_MIN_COMPACT_LEN:
        return sentence

    for idx, word in enumerate(words[1:], start=1):
        prefix = " ".join(words[:idx])
        suffix = " ".join(words[idx:])
        if (
            word in _BREATH_CONNECTORS
            and _compact_len(prefix) >= _BREATH_MIN_PREFIX_LEN
            and _compact_len(suffix) >= _BREATH_MIN_SUFFIX_LEN
        ):
            return f"{prefix}, {suffix}{trailing}"

    target = _compact_len(body) / 2
    best_idx = None
    best_distance = None

    for idx in range(1, len(words)):
        prefix = " ".join(words[:idx])
        suffix = " ".join(words[idx:])
        prefix_len = _compact_len(prefix)
        suffix_len = _compact_len(suffix)
        if prefix_len < _BREATH_MIN_PREFIX_LEN or suffix_len < _BREATH_MIN_SUFFIX_LEN:
            continue
        distance = abs(prefix_len - target)
        if best_distance is None or distance < best_distance:
            best_idx = idx
            best_distance = distance

    if best_idx is None:
        return sentence

    prefix = " ".join(words[:best_idx])
    suffix = " ".join(words[best_idx:])
    return f"{prefix}, {suffix}{trailing}"


def inject_breath_cues(text: str) -> str:
    """긴 문장에만 약한 쉼표를 넣어 자연스러운 호흡감을 유도한다."""
    normalized = _SPACE_RE.sub(" ", text or "").strip()
    if not normalized:
        return normalized

    sentences = _split_with_punctuation(normalized)
    if not sentences:
        return normalized

    return " ".join(_insert_breath_comma(sentence) for sentence in sentences)


def _split_long_segment(sentence: str) -> list[str]:
    trailing_match = _TRAILING_PUNCT_RE.search(sentence)
    trailing = trailing_match.group(1) if trailing_match else ""
    body = sentence[:-len(trailing)] if trailing else sentence
    body = body.strip()
    if not body or _compact_len(body) <= _SEGMENT_MAX_COMPACT_LEN:
        return [sentence.strip()]

    parts = re.split(r"([,;:，、])", body)
    segments: list[str] = []
    current = ""

    for idx in range(0, len(parts), 2):
        clause = parts[idx].strip()
        punct = parts[idx + 1] if idx + 1 < len(parts) else ""
        piece = f"{clause}{punct}".strip()
        if not piece:
            continue

        candidate = f"{current} {piece}".strip() if current else piece
        if current and _compact_len(candidate) > _SEGMENT_MAX_COMPACT_LEN:
            segments.append(current.strip())
            current = piece
        else:
            current = candidate

    if current:
        segments.append(current.strip())

    if len(segments) == 1:
        words = body.split()
        if len(words) < 4:
            return [sentence.strip()]
        target = _compact_len(body) / 2
        best_idx = None
        best_distance = None
        for idx in range(1, len(words)):
            prefix = " ".join(words[:idx])
            suffix = " ".join(words[idx:])
            prefix_len = _compact_len(prefix)
            suffix_len = _compact_len(suffix)
            if prefix_len < _SEGMENT_MIN_PREFIX_LEN or suffix_len < _SEGMENT_MIN_SUFFIX_LEN:
                continue
            distance = abs(prefix_len - target)
            if best_distance is None or distance < best_distance:
                best_idx = idx
                best_distance = distance
        if best_idx is None:
            return [sentence.strip()]
        segments = [
            " ".join(words[:best_idx]).strip(),
            " ".join(words[best_idx:]).strip(),
        ]

    if trailing:
        segments[-1] = f"{segments[-1]}{trailing}"
    return [segment for segment in segments if segment]


def split_tts_segments(text: str) -> list[str]:
    """로컬 TTS용 응답을 자연스러운 길이의 세그먼트들로 분할한다."""
    normalized = _SPACE_RE.sub(" ", text or "").strip()
    if not normalized:
        return []

    sentences = _split_with_punctuation(normalized)
    if not sentences:
        return [normalized]

    segments: list[str] = []
    for sentence in sentences:
        segments.extend(_split_long_segment(sentence))
    return segments or [normalized]


def apply_emotion_prosody(text: str, emotion: str) -> str:
    """zero_shot TTS에서 감정에 맞는 prosody를 구두점 변환으로 유도."""
    if not text or emotion in ("평온", "진지"):
        return text
    if emotion in ("기쁨", "기대", "화남"):
        return _SENT_PERIOD.sub("!", text)
    if emotion in ("슬픔", "걱정"):
        return _SENT_PERIOD.sub("...", text)
    if emotion == "수줍":
        return _SENT_PERIOD.sub("~", text)
    if emotion == "놀람":
        return _SENT_PERIOD.sub("?!", text)
    return text

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
