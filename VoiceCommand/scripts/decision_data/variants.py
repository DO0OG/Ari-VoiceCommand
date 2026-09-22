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
    """Generate a bounded, deterministic set of Korean-only variants."""

    if (
        not isinstance(text, str)
        or not text.strip()
        or not isinstance(language, str)
        or language.casefold() not in {"ko", "korean"}
        or limit <= 0
    ):
        return []

    digest = hashlib.sha256(f"{seed}\0{text}".encode("utf-8")).digest()
    rng = random.Random(int.from_bytes(digest[:8], "big"))
    operation_order = list(range(len(_OPERATIONS)))
    rng.shuffle(operation_order)

    groups: dict[int, list[str]] = {}
    for index, (_, transform) in enumerate(_OPERATIONS):
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
                singles.append((values[depth], _OPERATIONS[index][0]))

    composed: list[tuple[str, str]] = []
    composed_seen = set(seen)
    composition_cap = max(8, min(24, limit * 2))
    operation_indexes = {name: index for index, (name, _) in enumerate(_OPERATIONS)}
    numeric_index = operation_indexes["numeric_transcription"]
    if groups[numeric_index]:
        for second_name in ("verb_ending", "softener"):
            second_index = operation_indexes[second_name]
            for middle in groups[numeric_index][:2]:
                candidates = _unique(_OPERATIONS[second_index][1](middle), middle)
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
        candidates = _unique(_OPERATIONS[second][1](middle), middle)
        if not candidates:
            continue
        rng.shuffle(candidates)
        result = candidates[0]
        if result in composed_seen:
            continue
        composed_seen.add(result)
        composed.append((result, f"composed:{_OPERATIONS[first][0]}+{_OPERATIONS[second][0]}"))
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
