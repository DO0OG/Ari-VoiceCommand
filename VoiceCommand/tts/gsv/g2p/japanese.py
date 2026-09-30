"""Genie 일본어 음소 변환기."""

# Genie (MIT), High-Logic, G2P/Japanese/JapaneseG2P.py를 pyopenjtalk-plus로 이식했습니다.

import importlib
import os
import re
from typing import Any

from tts.gsv.model_store import get_model_dir
from tts.gsv.g2p.symbols import symbol_to_id_v2, symbols_v2


_CONSECUTIVE_PUNCTUATION_RE = re.compile(r"([,./?!~…・])\1+")
_JAPANESE_MARKS_RE = re.compile(
    r"[^A-Za-z\d\u3005\u3040-\u30ff\u4e00-\u9fff\uff11-\uff19"
    r"\uff21-\uff3a\uff41-\uff5a\uff66-\uff9d]"
)


def _openjtalk() -> Any:
    dictionary = os.path.join(get_model_dir(), "open_jtalk_dic")
    os.environ["OPEN_JTALK_DICT_DIR"] = dictionary
    return importlib.import_module("pyopenjtalk")


def _numeric_feature(regex: str, label: str) -> int:
    match = re.search(regex, label)
    return int(match.group(1)) if match else -50


def _segment_phones(text: str) -> list[str]:
    openjtalk = _openjtalk()
    labels = openjtalk.make_label(
        openjtalk.run_frontend(text, use_sudachi_kanji_yomi=False)
    )
    phones = []
    for index, label in enumerate(labels):
        match = re.search(r"-(.*?)\+", label)
        phone = match.group(1) if match else ""
        if phone in "AEIOU":
            phone = phone.lower()
        if phone == "sil":
            if index == 0:
                phones.append("^")
            elif index == len(labels) - 1:
                end = _numeric_feature(r"!(\d+)_", label)
                phones.append("?" if end == 1 else "$")
            continue
        if phone == "pau":
            phones.append("_")
            continue
        phones.append(phone)

        a1 = _numeric_feature(r"/A:([0-9\-]+)\+", label)
        a2 = _numeric_feature(r"\+(\d+)\+", label)
        a3 = _numeric_feature(r"\+(\d+)/", label)
        f1 = _numeric_feature(r"/F:(\d+)_", label)
        next_label = labels[index + 1] if index + 1 < len(labels) else ""
        a2_next = _numeric_feature(r"\+(\d+)\+", next_label)
        if a3 == 1 and a2_next == 1 and phone in "aeiouAEIOUNcl":
            phones.append("#")
        elif a1 == 0 and a2_next == a2 + 1 and a2 != f1:
            phones.append("]")
        elif a2 == 1 and a2_next == 2:
            phones.append("[")
    return phones


def japanese_phones(text: str) -> list[str]:
    """일본어 문장을 모델 기호로 바꾼다."""
    normalized = _CONSECUTIVE_PUNCTUATION_RE.sub(r"\1", text.lower())
    segments = _JAPANESE_MARKS_RE.split(normalized)
    marks = _JAPANESE_MARKS_RE.findall(normalized)
    phones: list[str] = []
    for index, segment in enumerate(segments):
        if segment:
            phones.extend(_segment_phones(segment)[1:-1])
        if index < len(marks):
            mark = marks[index].strip()
            if mark:
                phones.append(mark)
    replacements = {
        "：": ",", "；": ",", "，": ",", "。": ".", "！": "!",
        "？": "?", "\n": ".", "·": ",", "、": ",", "...": "…",
    }
    return [replacements.get(phone, phone) for phone in phones]


def japanese_to_phones(text: str) -> list[int]:
    phones = [phone for phone in japanese_phones(text) if phone in symbols_v2]
    return [symbol_to_id_v2[phone] for phone in phones]
