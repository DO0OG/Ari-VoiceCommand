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
    켜줘 켜주세요 켜줘요 켜 줘 켜 주세요 열어줘 열어주세요 열어줘요 열어 줘 열어 주세요
    닫아줘 닫아주세요 실행해줘 실행해주세요 종료해줘 종료해주세요 보여줘 보여주세요 찾아줘
    찾아주세요 읽어줘 읽어주세요 알려줘 알려주세요 검색해줘 검색해주세요 재생해줘 재생해주세요
    캡처해줘 캡처해주세요 설정해줘 설정해주세요 올려줘 올려주세요 내려줘 내려주세요
    """.split()
) | frozenset({"켜 줘", "켜 주세요", "열어 줘", "열어 주세요", "닫아 줘", "꺼 줘"})

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

_NUMERIC_PHRASES = (
    ("5분", "오 분"),
    ("5시", "다섯 시"),
    ("10초", "십 초"),
    ("1시간", "한 시간"),
    ("30분", "삼십 분"),
    ("삼십분", "30분"),
    ("50", "오십"),
    ("다섯 시", "5시"),
    ("오 분", "5분"),
    ("십 초", "10초"),
    ("한 시간", "1시간"),
    ("삼십 분", "30분"),
    ("30분", "삼십분"),
    ("오십", "50"),
)

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
    for source, target in _NUMERIC_PHRASES:
        pattern = re.compile(rf"(?<![\w]){re.escape(source)}(?P<particle>으로|로|이|가|은|는|을|를|에|부터|까지)?(?![\w])")
        candidate = pattern.sub(lambda match: target + (match.group("particle") or ""), text, count=1)
        if candidate != text:
            variants.append(candidate)
    return variants


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

    pairs = [(first, second) for first in operation_order for second in operation_order if first != second]
    rng.shuffle(pairs)
    composed: list[tuple[str, str]] = []
    composed_seen = set(seen)
    composition_cap = max(8, min(24, limit * 2))
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
    chosen = singles[: max(0, limit - composition_count)]
    chosen.extend(composed[:composition_count])
    if len(chosen) < limit:
        chosen.extend(composed[composition_count : composition_count + limit - len(chosen)])
    rng.shuffle(chosen)
    return chosen[:limit]
