"""Deterministic, meaning-preserving Korean utterance variants."""

from __future__ import annotations

import hashlib
import random
import re


_OBJECTS = frozenset(
    """
    chrome discord youtube excel notepad steam 크롬 디스코드 유튜브 유투브 엑셀 액셀 메모장 계산기
    앱 프로그램 창 화면 스크린샷 볼륨 보륨 음량 소리 파일 폴더 문서 타이머 알람 일정 이메일
    메일 사진 이미지 문장 코드 내용 노래 영상 음악 시간 날씨 클립보드 브라우저 검색어
    """.split()
)

_SIMPLE_VERBS = frozenset(
    """
    켜줘 켜주세요 켜줘요 열어줘 열어주세요 열어줘요 닫아줘 닫아주세요 닫아줘요
    꺼줘 꺼주세요 꺼줘요 띄워줘 띄워주세요 실행해줘 실행해주세요 종료해줘 종료해주세요
    보여줘 보여주세요 찾아줘 찾아주세요 읽어줘 읽어주세요 알려줘 알려주세요
    검색해줘 검색해주세요 재생해줘 재생해주세요 캡처해줘 캡처해주세요 설정해줘
    설정해주세요 올려줘 올려주세요 내려줘 내려주세요 켜봐 켜주실래요 켜주라 켜줄래
    열어봐 열어주실래요 닫아봐
    """.split()
) | frozenset(
    {
        "켜 줘", "켜 주세요", "열어 줘", "열어 주세요",
        "닫아 줘", "닫아 주세요", "꺼 줘", "꺼 주세요",
        "띄워 줘", "띄워 주세요",
    }
)

_TRANSCRIPTION_ERRORS = (
    ("켜줘", "겨줘"),
    ("켜줘", "저줘"),
    ("꺼줘", "거줘"),
    ("열어줘", "여러줘"),
    ("닫아줘", "다다줘"),
    ("시간", "시감"),
    ("화면", "하면"),
    ("크롬", "크럼"),
    ("크롬", "크론"),
    ("볼륨", "보륨"),
    ("디스코드", "디스콜드"),
    ("유튜브", "유투브"),
    ("스크린샷", "스크린셧"),
    ("엑셀", "액셀"),
    ("띄워줘", "띠워줘"),
)

_OVERSEGMENTED = (
    ("크롬", "크 롬"),
    ("스크린샷", "스크린 샷"),
    ("디스코드", "디스 코드"),
    ("유튜브", "유 튜브"),
    ("알려줘", "알려 줘"),
    ("열어줘", "열어 줘"),
    ("켜줘", "켜 줘"),
)

_SINO_DIGITS = {
    "영": 0, "공": 0, "일": 1, "이": 2, "삼": 3, "사": 4,
    "오": 5, "육": 6, "칠": 7, "팔": 8, "구": 9,
}
_SINO_PLACES = {"십": 10, "백": 100, "천": 1000}
_SINO_NAMES = {value: key for key, value in _SINO_DIGITS.items() if value}
_SINO_NAME_PATTERN = "[영공일이삼사오육칠팔구십백천]+"
_KOREAN_PARTICLE_PATTERN = r"(?:으로|부터|까지|정도|동안|후에|뒤에|이후|쯤|후|뒤|만|이|가|은|는|을|를|에|로)?"
_WORD_BOUNDARY = r"[\w가-힣]"
_NUMBER_PREFIX = r"[\w가-힣.,+/\-]"
_DIGIT_TIME = re.compile(
    rf"(?<!{_NUMBER_PREFIX})(?P<number>0|[1-9][0-9]{{0,3}})\s*"
    rf"(?P<unit>시간|분|초|시)(?P<particle>{_KOREAN_PARTICLE_PATTERN})(?!{_WORD_BOUNDARY})"
)
_SPOKEN_HOUR_SMALL = {
    1: "한", 2: "두", 3: "세", 4: "네", 5: "다섯",
    6: "여섯", 7: "일곱", 8: "여덟", 9: "아홉",
}
_SPOKEN_HOUR_TENS = {
    20: "스물", 30: "서른", 40: "마흔", 50: "쉰",
    60: "예순", 70: "일흔", 80: "여든", 90: "아흔",
}


def _spoken_hour(number: int) -> str | None:
    if number in _SPOKEN_HOUR_SMALL:
        return _SPOKEN_HOUR_SMALL[number]
    if number == 10:
        return "열"
    if 11 <= number <= 19:
        return "열" + _SPOKEN_HOUR_SMALL[number - 10]
    if number == 20:
        return "스무"
    tens, ones = divmod(number, 10)
    prefix = _SPOKEN_HOUR_TENS.get(tens * 10)
    if prefix and ones:
        return prefix + _SPOKEN_HOUR_SMALL[ones]
    if prefix:
        return prefix
    return None


_SPOKEN_HOURS = {number: _spoken_hour(number) for number in range(1, 100)}
_SPOKEN_HOUR_VALUES = {word: number for number, word in _SPOKEN_HOURS.items()}
_SPOKEN_HOUR_PATTERN = "|".join(
    re.escape(value) for value in sorted(_SPOKEN_HOUR_VALUES, key=len, reverse=True)
)
_SPOKEN_TIME = re.compile(
    rf"(?<!{_NUMBER_PREFIX})(?P<number>(?:{_SPOKEN_HOUR_PATTERN}|{_SINO_NAME_PATTERN}))\s*"
    rf"(?P<unit>시간|분|초|시)(?P<particle>{_KOREAN_PARTICLE_PATTERN})(?!{_WORD_BOUNDARY})"
)
_DIGIT_SCALAR = re.compile(
    rf"(?<!{_NUMBER_PREFIX})(?P<number>0|[1-9][0-9]{{0,3}})"
    rf"(?P<particle>(?:으로|부터|까지|이|가|은|는|을|를|에|로))"
    rf"(?!{_WORD_BOUNDARY})"
)
_SPOKEN_SCALAR = re.compile(
    rf"(?<!{_NUMBER_PREFIX})(?P<number>{_SINO_NAME_PATTERN})"
    rf"(?P<particle>(?:으로|부터|까지|이|가|은|는|을|를|에|로))"
    rf"(?!{_WORD_BOUNDARY})"
)
_SAFE_SCALAR_CONTEXTS = (
    "볼륨", "음량", "소리", "밝기", "화면", "크기",
    "용량", "온도", "속도", "퍼센트",
)


def _sino_number(value: int) -> str:
    if value == 0:
        return "영"
    result = []
    remainder = value
    for place, syllable in ((1000, "천"), (100, "백"), (10, "십")):
        digit, remainder = divmod(remainder, place)
        if digit:
            if digit != 1:
                result.append(_SINO_NAMES[digit])
            result.append(syllable)
    if remainder:
        result.append(_SINO_NAMES[remainder])
    return "".join(result)


def _parse_sino_number(value: str) -> int | None:
    if value in ("영", "공"):
        return 0
    total = 0
    current = None
    for syllable in value:
        if syllable in _SINO_DIGITS:
            current = _SINO_DIGITS[syllable]
        elif syllable in _SINO_PLACES:
            total += (current or 1) * _SINO_PLACES[syllable]
            current = None
        else:
            return None
    number = total + (current or 0)
    return number if 0 <= number <= 9999 and _sino_number(number) == value else None



_ENDING_ALTERNATIVES = (
    ("주실래요", ("줘", "주세요", "줘요", "주라", "줄래")),
    ("해 주세요", ("해줘", "해줘요", "해줄래", "해주라", "해봐", "해")),
    ("해 줘요", ("해줘", "해 주세요", "해줄래", "해주라", "해봐", "해")),
    ("해 줘", ("해줘요", "해 주세요", "해줄래", "해주라", "해봐", "해")),
    ("해줘요", ("해줘", "해 주세요", "해줄래", "해주라", "해봐", "해")),
    ("해주세요", ("해줘", "해 주세요", "해줄래", "해주라", "해봐", "해")),
    ("해줄래", ("해줘", "해 주세요", "해주라", "해봐", "해")),
    ("해주라", ("해줘", "해 주세요", "해줄래", "해봐", "해")),
    ("해봐", ("해줘", "해 주세요", "해줄래", "해주라", "해")),
    ("해줘", ("해줘요", "해 주세요", "해줄래", "해주라", "해봐", "해")),
    ("켜봐", ("켜줘", "켜 주세요", "켜주실래요", "켜주라", "켜")),
    ("주세요", ("줘", "줘요", "주라", "줄래", "주실래요")),
    ("줘요", ("줘", "주세요", "주라", "줄래", "주실래요")),
    ("줘", ("줘요", "주세요", "주라", "줄래", "주실래요", "봐")),
    ("봐", ("줘", "주세요", "주실래요", "주라")),
    ("해", ("해줘", "해 주세요", "해줄래", "해주라", "해봐")),
)


def _particle_omissions(text: str) -> list[str]:
    variants: list[str] = []
    for match in re.finditer(r"\S+", text):
        token = match.group()
        particle = re.fullmatch(r"(.+?)(을|를)([.!?]*)", token)
        if not particle or particle.group(1).casefold() not in _OBJECTS:
            continue
        variants.append(text[: match.start()] + particle.group(1) + particle.group(3) + text[match.end() :])
    return variants


def _verb_endings(text: str) -> list[str]:
    core = text.rstrip(".!?。！？")
    punctuation = text[len(core) :]
    for ending, alternatives in _ENDING_ALTERNATIVES:
        if core.endswith(ending):
            stem = core[: -len(ending)]
            if not stem or not re.search(r"[가-힣]$", stem):
                continue
            return [stem + alternative + punctuation for alternative in alternatives]
    return []


def _object_and_particle(token: str) -> tuple[str, str] | None:
    match = re.fullmatch(r"(.+?)(을|를)", token)
    if match and match.group(1).casefold() in _OBJECTS:
        return match.group(1), match.group(2)
    return None


def _object_token(token: str) -> bool:
    return token.casefold() in _OBJECTS or _object_and_particle(token) is not None


def _inversions(text: str) -> list[str]:
    match = re.fullmatch(r"([^\s]+)\s+(.+?)([.!?。！？]*)", text.strip())
    if not match or match.group(2).strip() not in _SIMPLE_VERBS:
        return []
    if not _object_token(match.group(1)):
        return []
    return [f"{match.group(2).strip()} {match.group(1)}{match.group(3)}"]


def _softeners(text: str) -> list[str]:
    variants = []
    if not re.match(r"^(?:저기|음|혹시)(?:\s|$)", text):
        variants.append("혹시 " + text)
        variants.append("저기 " + text)
    for filler in ("어, 그거 ", "음, 그거 ", "아, 그거 "):
        if not text.startswith(("어, 그거 ", "음, 그거 ", "아, 그거 ")):
            variants.append(filler + text)
    for softener in ("미안한데 ", "가능하면 "):
        if not text.startswith(("미안한데 ", "가능하면 ")):
            variants.append(softener + text)
    match = re.search(r"\S+(?:[.!?。！？]*)$", text)
    if match and "좀" not in text.split():
        variants.append(text[: match.start()] + "좀 " + text[match.start() :])
    return variants


def _repetitions(text: str) -> list[str]:
    variants = []
    if not text.startswith(("음, 음 ", "음 음 ")):
        variants.append("음, 음 " + text)
    for source, target in (("크롬", "크 크롬"), ("디스코드", "디 디스코드"), ("유튜브", "유 유튜브")):
        if source in text:
            variants.append(text.replace(source, target, 1))
    return variants


def _transcription_errors(text: str) -> list[str]:
    return [text.replace(source, target, 1) for source, target in _TRANSCRIPTION_ERRORS if source in text]


def _spacing_loss(text: str) -> list[str]:
    compact = re.sub(r"\s+", "", text)
    return [compact] if compact and compact != text else []


def _spacing_oversegmentation(text: str) -> list[str]:
    return [text.replace(source, target, 1) for source, target in _OVERSEGMENTED if source in text]


def _numeric_transcriptions(text: str) -> list[str]:
    variants = []
    for match in _DIGIT_TIME.finditer(text):
        number = int(match.group("number"))
        unit = match.group("unit")
        spoken = _SPOKEN_HOURS.get(number) if unit in ("시간", "시") else _sino_number(number)
        if spoken is None:
            continue
        suffix = match.group("particle") or ""
        for rendered in (spoken + " " + unit + suffix, spoken + unit + suffix):
            variants.append(text[:match.start()] + rendered + text[match.end():])

    for match in _SPOKEN_TIME.finditer(text):
        number_text = match.group("number")
        unit = match.group("unit")
        number = (
            _SPOKEN_HOUR_VALUES.get(number_text)
            if unit in ("시간", "시")
            else _parse_sino_number(number_text)
        )
        if number is not None:
            rendered = str(number) + unit + (match.group("particle") or "")
            variants.append(text[:match.start()] + rendered + text[match.end():])

    for match in _DIGIT_SCALAR.finditer(text):
        rendered = _sino_number(int(match.group("number"))) + match.group("particle")
        variants.append(text[:match.start()] + rendered + text[match.end():])

    if any(context in text for context in _SAFE_SCALAR_CONTEXTS):
        for match in _SPOKEN_SCALAR.finditer(text):
            number = _parse_sino_number(match.group("number"))
            if number is not None:
                rendered = str(number) + match.group("particle")
                variants.append(text[:match.start()] + rendered + text[match.end():])
    return _unique(variants, text)


def _punctuation_removal(text: str) -> list[str]:
    candidate = re.sub(r"[,，;；:：.!?。！？…]+(?=\s|$)", "", text).strip()
    return [candidate] if candidate and candidate != text else []


_EN_ARTICLES = re.compile(r"\b(?:the|a|an|my)\s+(?=[A-Za-z0-9])", re.IGNORECASE)
_EN_REQUEST_PREFIXES = (
    "could you please ", "can you please ", "would you please ",
    "could you ", "can you ", "would you ", "please ",
)
_EN_TRANSCRIPTION_ERRORS = (
    ("chrome", "chrom"),
    ("chrome", "crome"),
    ("discord", "discort"),
    ("youtube", "youtub"),
    ("volume", "volumn"),
    ("excel", "excell"),
    ("steam", "steem"),
    ("whale", "wale"),
    ("minutes", "minuts"),
    ("minute", "minut"),
    ("screenshot", "screenshoot"),
    ("calculator", "calcuator"),
    ("notepad", "notpad"),
)
_EN_OVERSEGMENTED = (
    ("youtube", "you tube"),
    ("screenshot", "screen shot"),
    ("notepad", "note pad"),
    ("discord", "dis cord"),
)
_EN_STUTTER_WORDS = ("chrome", "discord", "youtube", "excel", "steam", "notepad", "calculator")
_EN_SMALL_NUMBERS = (
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
    "seventeen", "eighteen", "nineteen",
)
_EN_TENS = {
    20: "twenty", 30: "thirty", 40: "forty", 50: "fifty",
    60: "sixty", 70: "seventy", 80: "eighty", 90: "ninety",
}


def _en_number_word(number: int) -> str | None:
    """Spell 0-100 the way a speaker would; other values stay as digits."""
    if number < 0 or number > 100:
        return None
    if number < 20:
        return _EN_SMALL_NUMBERS[number]
    if number == 100:
        return "one hundred"
    tens, ones = divmod(number, 10)
    word = _EN_TENS[tens * 10]
    return f"{word}-{_EN_SMALL_NUMBERS[ones]}" if ones else word


_EN_NUMBER_VALUES = {
    word: number
    for number in range(0, 101)
    for word in (_en_number_word(number),)
    if word is not None
}
_EN_NUMBER_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(word) for word in sorted(_EN_NUMBER_VALUES, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)
_EN_DIGIT_PATTERN = re.compile(r"(?<![\w.,\-/])(0|[1-9][0-9]?|100)(?![\w.,\-/:])")


def _match_case(sample: str, target: str) -> str:
    """Reuse the casing of the text that was matched."""
    if sample.isupper() and len(sample) > 1:
        return target.upper()
    if sample[:1].isupper():
        return target[:1].upper() + target[1:]
    return target


def _en_replacements(text: str, table: tuple[tuple[str, str], ...]) -> list[str]:
    variants = []
    for source, target in table:
        match = re.search(rf"\b{re.escape(source)}\b", text, re.IGNORECASE)
        if match:
            replacement = _match_case(match.group(), target)
            variants.append(text[: match.start()] + replacement + text[match.end() :])
    return variants


def _en_article_omissions(text: str) -> list[str]:
    return [text[: match.start()] + text[match.end() :] for match in _EN_ARTICLES.finditer(text)]


def _en_request_forms(text: str) -> list[str]:
    stripped = text.strip()
    core = stripped.rstrip(".!?")
    punctuation = stripped[len(core) :]
    lowered = core.casefold()
    body = core
    for prefix in _EN_REQUEST_PREFIXES:
        if lowered.startswith(prefix):
            body = core[len(prefix) :]
            break
    else:
        if lowered.endswith(" please"):
            body = core[: -len(" please")]
    body = body.strip()
    if not body or not body[:1].isalpha():
        return []
    lower_body = body[:1].lower() + body[1:]
    upper_body = body[:1].upper() + body[1:]
    return [
        value + punctuation
        for value in (
            upper_body,
            "Please " + lower_body,
            "Could you " + lower_body,
            "Can you " + lower_body,
            upper_body + " please",
        )
    ]


def _en_softeners(text: str) -> list[str]:
    stripped = text.strip()
    if not stripped or not stripped[:1].isalpha():
        return []
    if re.match(r"^(?:um|uh|so|sorry|hey|just|if)\b", stripped, re.IGNORECASE):
        return []
    lower = stripped[:1].lower() + stripped[1:]
    return [prefix + lower for prefix in ("Um, ", "Uh, ", "So, ", "Sorry, ", "If you can, ", "Just ")]


def _en_repetitions(text: str) -> list[str]:
    stripped = text.strip()
    variants = []
    if stripped[:1].isalpha() and not re.match(r"^um,?\s*um\b", stripped, re.IGNORECASE):
        variants.append("Um, um, " + stripped[:1].lower() + stripped[1:])
    for word in _EN_STUTTER_WORDS:
        match = re.search(rf"\b{re.escape(word)}\b", text, re.IGNORECASE)
        if match:
            found = match.group()
            variants.append(text[: match.start()] + found[:2] + "- " + found + text[match.end() :])
    return variants


def _en_transcription_errors(text: str) -> list[str]:
    return _en_replacements(text, _EN_TRANSCRIPTION_ERRORS)


def _en_spacing_oversegmentation(text: str) -> list[str]:
    return _en_replacements(text, _EN_OVERSEGMENTED)


def _en_spacing_loss(text: str) -> list[str]:
    return _en_replacements(text, tuple((target, source) for source, target in _EN_OVERSEGMENTED))


def _en_case_variation(text: str) -> list[str]:
    lowered = text.lower()
    return [lowered] if lowered != text else []


def _en_numeric_transcriptions(text: str) -> list[str]:
    variants = []
    for match in _EN_NUMBER_PATTERN.finditer(text):
        variants.append(
            text[: match.start()] + str(_EN_NUMBER_VALUES[match.group().casefold()]) + text[match.end() :]
        )
    for match in _EN_DIGIT_PATTERN.finditer(text):
        word = _en_number_word(int(match.group()))
        if word:
            variants.append(text[: match.start()] + word + text[match.end() :])
    return _unique(variants, text)


_JA_PARTICLE = re.compile(r"(?<=[\u3040-\u30ff\u4e00-\u9fffA-Za-z0-9])を")
_JA_ENDING_ALTERNATIVES = (
    ("てください", ("て", "てくれる？", "てくれない？", "てよ", "てね")),
    ("てくれる？", ("て", "てください", "てくれない？", "てよ", "てね")),
    ("てくれない？", ("て", "てください", "てくれる？", "てよ", "てね")),
    ("てね", ("て", "てください", "てくれる？", "てくれない？", "てよ")),
    ("てよ", ("て", "てください", "てくれる？", "てくれない？", "てね")),
    ("て", ("てください", "てくれる？", "てくれない？", "てよ", "てね")),
)
_JA_SOFTENERS = ("えっと、", "あの、", "すみませんが、", "できれば", "ちょっと")
_JA_TRANSCRIPTION_ERRORS = (
    ("クローム", "クロム"),
    ("ディスコード", "ディスコート"),
    ("ユーチューブ", "ユーチュブ"),
    ("スクリーンショット", "スクリーンショト"),
    ("メモ帳", "メモ張"),
    ("電卓", "電択"),
    ("音量", "音料"),
    ("時間", "時感"),
    ("画面", "我面"),
    ("天気", "転記"),
    ("エクセル", "エクセール"),
)
_JA_STUTTER = (
    ("クローム", "ク、クローム"),
    ("ディスコード", "ディ、ディスコード"),
    ("ユーチューブ", "ユ、ユーチューブ"),
    ("スクリーンショット", "ス、スクリーンショット"),
)
_JA_DIGIT_NAMES = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五",
                   6: "六", 7: "七", 8: "八", 9: "九"}
_JA_UNIT = r"(?P<unit>時間|分|秒|時|回|個|件)"
_JA_DIGIT_NUMBER = re.compile(rf"(?<![\w.,\-/])(?P<number>0|[1-9][0-9]{{0,3}})\s*{_JA_UNIT}")
_JA_KANJI_NUMBER = re.compile(rf"(?P<number>[〇一二三四五六七八九十百千]+)\s*{_JA_UNIT}")


def _ja_number(value: int) -> str:
    if value == 0:
        return "〇"
    result = []
    remainder = value
    for place, character in ((1000, "千"), (100, "百"), (10, "十")):
        digit, remainder = divmod(remainder, place)
        if digit:
            if digit != 1:
                result.append(_JA_DIGIT_NAMES[digit])
            result.append(character)
    if remainder:
        result.append(_JA_DIGIT_NAMES[remainder])
    return "".join(result)


def _parse_ja_number(value: str) -> int | None:
    if value == "〇":
        return 0
    names = {name: digit for digit, name in _JA_DIGIT_NAMES.items()}
    places = {"十": 10, "百": 100, "千": 1000}
    total = 0
    current = None
    for character in value:
        if character in names:
            current = names[character]
        elif character in places:
            total += (current or 1) * places[character]
            current = None
        else:
            return None
    number = total + (current or 0)
    return number if 0 <= number <= 9999 and _ja_number(number) == value else None


def _ja_particle_omissions(text: str) -> list[str]:
    return [text[: match.start()] + text[match.end() :] for match in _JA_PARTICLE.finditer(text)]


def _ja_verb_endings(text: str) -> list[str]:
    core = text.rstrip(".!?。！？")
    punctuation = text[len(core) :]
    for ending, alternatives in _JA_ENDING_ALTERNATIVES:
        if core.endswith(ending):
            stem = core[: -len(ending)]
            if not stem or not re.search(r"[\u3040-\u30ff\u4e00-\u9fff]$", stem):
                continue
            return [stem + alternative + punctuation for alternative in alternatives]
    return []


def _ja_softeners(text: str) -> list[str]:
    if text.startswith(_JA_SOFTENERS):
        return []
    return [softener + text for softener in _JA_SOFTENERS]


def _ja_repetitions(text: str) -> list[str]:
    variants = []
    if not text.startswith("えっと、えっと"):
        variants.append("えっと、えっと、" + text)
    variants.extend(text.replace(source, target, 1) for source, target in _JA_STUTTER if source in text)
    return variants


def _ja_transcription_errors(text: str) -> list[str]:
    return [text.replace(source, target, 1) for source, target in _JA_TRANSCRIPTION_ERRORS if source in text]


def _ja_spacing_oversegmentation(text: str) -> list[str]:
    variants = [text[: match.end()] + " " + text[match.end() :] for match in _JA_PARTICLE.finditer(text)]
    core = text.rstrip("。！？.!?")
    for ending in ("てください", "て"):
        if core.endswith(ending) and len(core) > len(ending):
            index = len(core) - len(ending)
            variants.append(text[:index] + " " + text[index:])
            break
    return variants


def _ja_numeric_transcriptions(text: str) -> list[str]:
    variants = []
    for match in _JA_DIGIT_NUMBER.finditer(text):
        rendered = _ja_number(int(match.group("number"))) + match.group("unit")
        variants.append(text[: match.start()] + rendered + text[match.end() :])
    for match in _JA_KANJI_NUMBER.finditer(text):
        number = _parse_ja_number(match.group("number"))
        if number is not None:
            variants.append(text[: match.start()] + str(number) + match.group("unit") + text[match.end() :])
    return _unique(variants, text)



_OPERATIONS = (
    ("particle_omission", _particle_omissions),
    ("verb_ending", _verb_endings),
    ("object_verb_inversion", _inversions),
    ("softener", _softeners),
    ("repetition", _repetitions),
    ("transcription_error", _transcription_errors),
    ("spacing_loss", _spacing_loss),
    ("spacing_oversegmentation", _spacing_oversegmentation),
    ("numeric_transcription", _numeric_transcriptions),
    ("punctuation_removal", _punctuation_removal),
)


_EN_OPERATIONS = (
    ("article_omission", _en_article_omissions),
    ("verb_ending", _en_request_forms),
    ("softener", _en_softeners),
    ("repetition", _en_repetitions),
    ("transcription_error", _en_transcription_errors),
    ("spacing_loss", _en_spacing_loss),
    ("spacing_oversegmentation", _en_spacing_oversegmentation),
    ("case_variation", _en_case_variation),
    ("numeric_transcription", _en_numeric_transcriptions),
    ("punctuation_removal", _punctuation_removal),
)

_JA_OPERATIONS = (
    ("particle_omission", _ja_particle_omissions),
    ("verb_ending", _ja_verb_endings),
    ("softener", _ja_softeners),
    ("repetition", _ja_repetitions),
    ("transcription_error", _ja_transcription_errors),
    ("spacing_loss", _spacing_loss),
    ("spacing_oversegmentation", _ja_spacing_oversegmentation),
    ("numeric_transcription", _ja_numeric_transcriptions),
    ("punctuation_removal", _punctuation_removal),
)

_LANGUAGE_OPERATIONS = {
    "ko": _OPERATIONS, "korean": _OPERATIONS,
    "en": _EN_OPERATIONS, "english": _EN_OPERATIONS,
    "ja": _JA_OPERATIONS, "japanese": _JA_OPERATIONS,
}

def _unique(values: list[str], original: str) -> list[str]:
    seen = {original}
    output = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            output.append(value)
    return output


def generate_variants(
    text: str,
    language: str,
    *,
    seed: int = 131,
    limit: int = 12,
) -> list[tuple[str, str]]:
    """Generate a bounded, deterministic variant set for a supported language."""

    if (
        not isinstance(text, str)
        or not text.strip()
        or not isinstance(language, str)
        or limit <= 0
    ):
        return []
    operations = _LANGUAGE_OPERATIONS.get(language.casefold())
    if operations is None:
        return []

    digest = hashlib.sha256(f"{seed}\0{text}".encode("utf-8")).digest()
    # 재현 가능한 순서가 요구사항이므로 요약값에서 유도한 고정 seed를 쓴다.
    # 보안 목적이 아니며 암호학적 난수로 바꾸면 결과를 재현할 수 없다.
    rng = random.Random(int.from_bytes(digest[:8], "big"))  # nosec B311
    operation_order = list(range(len(operations)))
    rng.shuffle(operation_order)

    groups: dict[int, list[str]] = {}
    for index, (_, transform) in enumerate(operations):
        values = _unique(transform(text), text)
        rng.shuffle(values)
        groups[index] = values

    singles: list[tuple[str, str]] = []
    seen = {text}
    for depth in range(max((len(values) for values in groups.values()), default=0)):
        for index in operation_order:
            values = groups[index]
            if depth < len(values) and values[depth] not in seen:
                seen.add(values[depth])
                singles.append((values[depth], operations[index][0]))

    composed: list[tuple[str, str]] = []
    composed_seen = set(seen)
    composition_cap = max(8, min(24, limit * 2))
    operation_indexes = {name: index for index, (name, _) in enumerate(operations)}
    numeric_index = operation_indexes["numeric_transcription"]
    if groups[numeric_index]:
        for second_name in ("verb_ending", "softener"):
            second_index = operation_indexes[second_name]
            for middle in groups[numeric_index][:2]:
                candidates = _unique(operations[second_index][1](middle), middle)
                if candidates:
                    result = candidates[0]
                    if result not in composed_seen:
                        composed_seen.add(result)
                        composed.append(
                            (result, f"composed:numeric_transcription+{second_name}")
                        )
                    break

    pairs = [(first, second) for first in operation_order for second in operation_order if first != second]
    rng.shuffle(pairs)
    for first, second in pairs:
        if not groups[first]:
            continue
        middle = groups[first][0]
        candidates = _unique(operations[second][1](middle), middle)
        if not candidates:
            continue
        rng.shuffle(candidates)
        result = candidates[0]
        if result in composed_seen:
            continue
        composed_seen.add(result)
        composed.append((result, f"composed:{operations[first][0]}+{operations[second][0]}"))
        if len(composed) >= composition_cap:
            break

    composition_count = min(4, max(1, limit // 4), max(0, limit - 1)) if limit >= 3 else 0
    priority_singles = []
    priority_names = (
        ("numeric_transcription", "verb_ending", "softener")
        if groups[numeric_index] else ()
    )
    for name in priority_names:
        index = operation_indexes[name]
        if groups[index]:
            candidate = (groups[index][0], name)
            if candidate[0] not in {value for value, _ in priority_singles}:
                priority_singles.append(candidate)
    chosen = priority_singles[: max(0, limit - composition_count)]
    chosen_texts = {value for value, _ in chosen}
    chosen.extend(
        (value, kind)
        for value, kind in singles
        if value not in chosen_texts
    )
    chosen = chosen[: max(0, limit - composition_count)]
    chosen.extend(composed[:composition_count])
    if len(chosen) < limit:
        chosen.extend(composed[composition_count : composition_count + limit - len(chosen)])
    rng.shuffle(chosen)
    return chosen[:limit]
