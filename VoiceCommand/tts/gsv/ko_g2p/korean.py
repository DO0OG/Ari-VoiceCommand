"""GPT-SoVITS 한국어 발음 변환."""

# GPT-SoVITS (MIT), RVC-Boss, GPT_SoVITS/text/korean.py의 변환 규칙을 이식했습니다.

import os
import re

from jamo import h2j, j2hcj
import ko_pron

from tts.gsv.g2p.symbols import symbols_v2
from tts.gsv.ko_g2p import numerals, regular, special, utils


_CLASSIFIERS = (
    "군데 권 개 그루 닢 대 두 마리 모 모금 뭇 발 발짝 방 번 벌 보루 살 수 술 시 "
    "쌈 움큼 정 짝 채 척 첩 축 켤레 톨 통"
)
_LATIN_TO_HANGUL = tuple(
    (re.compile(letter, re.IGNORECASE), pronunciation)
    for letter, pronunciation in (
        ("a", "에이"), ("b", "비"), ("c", "시"), ("d", "디"), ("e", "이"),
        ("f", "에프"), ("g", "지"), ("h", "에이치"), ("i", "아이"),
        ("j", "제이"), ("k", "케이"), ("l", "엘"), ("m", "엠"), ("n", "엔"),
        ("o", "오"), ("p", "피"), ("q", "큐"), ("r", "아르"), ("s", "에스"),
        ("t", "티"), ("u", "유"), ("v", "브이"), ("w", "더블유"),
        ("x", "엑스"), ("y", "와이"), ("z", "제트"),
    )
)
_SPLIT_VOWELS = {
    "ㅘ": "ㅗㅏ", "ㅙ": "ㅗㅐ", "ㅚ": "ㅗㅣ", "ㅝ": "ㅜㅓ",
    "ㅞ": "ㅜㅔ", "ㅟ": "ㅜㅣ", "ㅢ": "ㅡㅣ", "ㅑ": "ㅣㅏ",
    "ㅒ": "ㅣㅐ", "ㅕ": "ㅣㅓ", "ㅖ": "ㅣㅔ", "ㅛ": "ㅣㅗ", "ㅠ": "ㅣㅜ",
}
_IPA_REPLACEMENTS = (
    ("t͡ɕ", "ʧ"), ("d͡ʑ", "ʥ"), ("ɲ", "n^"), ("ɕ", "ʃ"), ("ʷ", "w"),
    ("ɭ", "l`"), ("ʎ", "ɾ"), ("ɣ", "ŋ"), ("ɰ", "ɯ"), ("ʝ", "j"),
    ("ʌ", "ə"), ("ɡ", "g"), ("\u031a", "#"), ("\u0348", "="),
    ("\u031e", ""), ("\u0320", ""), ("\u0339", ""),
)


def latin_to_hangul(text: str) -> str:
    for pattern, pronunciation in _LATIN_TO_HANGUL:
        text = pattern.sub(pronunciation, text)
    return text


def _number_to_hangul(text: str) -> str:
    for number, classifier in set(re.findall(r"(\d[\d,]*)([가-힣]+)", text)):
        if classifier.startswith(tuple(_CLASSIFIERS.split())):
            pronunciation = numerals.process_num(number, sino=False)
        else:
            pronunciation = numerals.process_num(number, sino=True)
        text = text.replace(f"{number}{classifier}", f"{pronunciation}{classifier}")
    for digit, name in zip("0123456789", "영일이삼사오육칠팔구"):
        text = text.replace(digit, name)
    return text


def _idioms(text: str) -> str:
    path = os.path.join(os.path.dirname(__file__), "idioms.txt")
    with open(path, encoding="utf-8") as source:
        for line in source:
            line = line.split("#", 1)[0].strip()
            if "===" in line:
                pattern, replacement = line.split("===", 1)
                text = re.sub(pattern, replacement, text)
    return text


def _apply_rules(text: str) -> str:
    text = h2j(text)
    # 형태소 주석 생략으로 일부 용언 예외를 구분하지 못하는 한계가 있다.
    for rule in (
        special.jyeo,
        special.ye,
        special.consonant_ui,
        special.josa_ui,
        special.vowel_ui,
        special.jamo,
        special.rieulgiyeok,
        special.rieulbieub,
        special.verb_nieun,
        special.balb,
        special.palatalize,
        special.modifying_rieul,
    ):
        text = rule(text)
    text = re.sub(r"/[PJEB]", "", text)
    for pattern, replacement, _rule_ids in utils.parse_table():
        text = re.sub(pattern, replacement, text)
    for rule in (regular.link1, regular.link2, regular.link3, regular.link4):
        text = rule(text)
    return text


def _fix_rule_edge_case(text: str) -> str:
    fixed = []
    index = 0
    while index < len(text) - 4:
        if text[index : index + 3] in {"ㅇㅡㄹ", "ㄹㅡㄹ"} and text[index + 3 : index + 4] == " ":
            fixed.append(text[index : index + 3] + " ㄴ")
            index += 5
        else:
            fixed.append(text[index])
            index += 1
    return "".join(fixed) + text[index:]


def _divide_hangul(text: str) -> str:
    text = j2hcj(h2j(text))
    for combined, divided in _SPLIT_VOWELS.items():
        text = text.replace(combined, divided)
    return text


def korean_to_ipa(text: str) -> str:
    """ko_pron을 사용해 한국어 발음을 IPA로 바꾼다."""
    text = _apply_rules(_number_to_hangul(latin_to_hangul(text)))
    result = ko_pron.romanise(utils.compose(text), "ipa").split("] ~ [")[0]
    for original, replacement in _IPA_REPLACEMENTS:
        result = result.replace(original, replacement)
    return result.replace("ʧ", "tʃ").replace("ʥ", "dʑ")


def korean_g2p(text: str) -> list[str]:
    """한국어 문장을 모델 음소 기호로 바꾼다."""
    text = latin_to_hangul(_idioms(text))
    text = _number_to_hangul(text)
    text = _fix_rule_edge_case(j2hcj(h2j(_apply_rules(text))))
    text = utils.compose(text)
    text = _divide_hangul(text)
    text = re.sub(r"([ㄱ-ㅣ])$", r"\1.", text)
    punctuation = {
        "：": ",", "；": ",", "，": ",", "。": ".", "！": "!",
        "？": "?", "\n": ".", "·": ",", "、": ",", "...": "…",
        " ": "空",
    }
    return [
        symbol if (symbol := punctuation.get(char, char)) in symbols_v2 else "停"
        for char in text
    ]


def korean_to_phones(text: str) -> list[str]:
    return korean_g2p(text)
