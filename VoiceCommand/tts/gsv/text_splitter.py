"""Genie 문장 분할기."""

# Genie (MIT), High-Logic, Utils/TextSplitter.py에서 분할 규칙을 이식했습니다.

import re
from typing import Pattern


_END_CHARS = frozenset("。！？….!?")
_PUNCTUATION = _END_CHARS | frozenset("，、；：——,;:“”‘’\"'")
_PUNCTUATION_PATTERN: Pattern[str] = re.compile(
    "((?:" + "|".join(re.escape(char) for char in _PUNCTUATION) + ")+)"
)


def _effective_length(text: str) -> int:
    return sum(1 if ord(char) < 128 else 2 for char in text if char not in _PUNCTUATION)


def _flush(sentences: list[str], text: str) -> None:
    candidate = text.strip()
    if candidate and _effective_length(candidate) > 0:
        sentences.append(candidate)
    elif candidate and sentences:
        sentences[-1] += candidate


def split_text(text: str, max_chars: int = 40, min_chars: int = 5) -> list[str]:
    """문장 경계를 우선해 긴 입력을 자른다."""
    if not text:
        return []

    segments = _PUNCTUATION_PATTERN.split(text.replace("\n", ""))
    sentences: list[str] = []
    buffer = ""
    for segment in segments:
        if not segment:
            continue

        if segment[0] in _PUNCTUATION:
            buffer += segment
            effective_length = _effective_length(buffer)
            if any(char in _END_CHARS for char in segment):
                if effective_length >= min_chars:
                    sentences.append(buffer.strip())
                    buffer = ""
            elif effective_length >= max_chars:
                sentences.append(buffer.strip())
                buffer = ""
            continue

        buffer += segment
    _flush(sentences, buffer)
    return sentences
