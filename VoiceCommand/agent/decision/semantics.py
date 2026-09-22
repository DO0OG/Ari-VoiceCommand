"""짧고 단일한 요청의 의미와 인자를 결정적으로 확인한다."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import unicodedata

from agent.decision.candidates import DIRECT_ALLOWLIST


DIRECT_CANDIDATES = DIRECT_ALLOWLIST


@dataclass(frozen=True)
class SemanticParse:
    candidate: str
    language: str
    arguments: dict[str, object] = field(default_factory=dict)
    valid: bool = False
    intent_confirmed: bool = False
    contradiction: bool = False
    residual_action: bool = False

    @property
    def parse_success(self) -> bool:
        return bool(
            self.valid
            and self.intent_confirmed
            and not self.contradiction
            and not self.residual_action
        )


_JAPANESE_MARKERS = (
    "今何時", "時計", "時刻", "現在時刻", "実行中", "起動中", "画面",
    "音量", "撮って", "撮る", "開いて", "閉じて", "教えて", "見せて",
)

_GRAMMARS: dict[str, dict[str, tuple[str, ...]]] = {
    "get_current_time": {
        "ko": (
            r"(?:지금\s+|현재\s+)?몇\s*시(?:야|인지)?",
            r"(?:지금\s+|현재\s+)?(?:현재\s*)?(?:시간|시각|시계)(?:을|를|이|가|은|는)?"
            r"(?:\s*(?:좀\s*)?(?:알려|말해|확인)(?:\s*(?:줘|주라|주세요|주시겠어요|줘요))?)?",
        ),
        "en": (
            r"(?:please\s+)?(?:what(?:\s+is)?\s+the\s+time|what\s+time\s+is\s+it|"
            r"what's\s+the\s+time|current\s+time|tell\s+(?:me\s+)?(?:the\s+)?time|"
            r"check\s+(?:the\s+)?(?:current\s+)?time|what\s+time|time\s+please)"
            r"(?:\s+please)?",
        ),
        "ja": (
            r"(?:今(?:の)?|現在の)?(?:何時|時刻|時計|時間)(?:を)?"
            r"(?:教えて|確認して|言って)?(?:ください)?",
        ),
    },
    "get_running_apps": {
        "ko": (
            r"(?:지금\s+|현재\s+)?(?:(?:실행\s*중|켜져\s*있는|열려\s*있는)\s*인?\s*)?"
            r"(?:앱|프로그램|프로세스)(?:\s*(?:목록|리스트))?(?:을|를)?\s*"
            r"(?:보여|알려|확인|나열)(?:\s*(?:줘|주세요|해줘|해|주시겠어요))?",
            r"(?:지금\s+)?뭐가\s*켜져\s*있는지\s*(?:보여|알려|확인)(?:\s*줘)?",
        ),
        "en": (
            r"(?:please\s+)?(?:list|show)\s+(?:the\s+)?(?:currently\s+)?"
            r"(?:running|open)\s+(?:apps?|applications?|programs?|processes?)"
            r"(?:\s+please)?",
            r"(?:please\s+)?tell\s+me\s+(?:which\s+)?(?:apps?|applications?|"
            r"programs?)\s+are\s+(?:currently\s+)?(?:running|open)(?:\s+please)?",
            r"(?:please\s+)?what(?:'s|\s+is)\s+running(?:\s+please)?",
        ),
        "ja": (
            r"(?:現在|今)?(?:実行中|起動中|開いている)(?:の)?"
            r"(?:アプリ|プログラム|プロセス)(?:一覧)?(?:を)?"
            r"(?:教えて|見せて|確認して)(?:ください)?",
            r"(?:現在|今)?何が起動しているか(?:教えて|見せて|確認して)(?:ください)?",
        ),
    },
    "take_screenshot": {
        "ko": (
            r"(?:지금\s+|현재\s+)?(?:화면|스크린\s*샷)(?:을|를)?"
            r"\s*(?:캡처|찍|촬영)(?:해|해서\s*저장)?"
            r"(?:\s*(?:줘|주세요|해줘|해|주시겠어요))?",
            r"(?:지금\s+|현재\s+)?(?:화면|스크린\s*샷)(?:을|를)?\s*"
            r"(?:그대로\s*)?저장(?:해|해서)?(?:\s*(?:줘|주세요|해줘))?",
        ),
        "en": (
            r"(?:please\s+)?take\s+(?:a\s+)?screenshot(?:\s+please)?",
            r"(?:please\s+)?capture\s+(?:the\s+)?(?:current\s+)?screen(?:\s+please)?",
            r"(?:please\s+)?save\s+(?:the\s+)?screen(?:\s+please)?",
        ),
        "ja": (
            r"(?:今の|現在の)?(?:画面を)?(?:スクリーンショット|スクリーンショト)"
            r"(?:を)?撮って(?:ください)?",
            r"(?:今の|現在の)?画面をキャプチャして(?:ください)?",
            r"(?:今の|現在の)?画面を保存して(?:ください)?",
        ),
    },
    "adjust_volume": {
        "ko": (
            r"(?:볼륨|음량|소리)(?:을|를)?\s*"
            r"(?P<amount>\d{1,3})\s*(?:퍼센트|%)?\s*(?P<direction>올려|높여|키워|내려|낮춰|줄여)"
            r"(?:\s*(?:줘|주세요|해줘|해|주시겠어요))?",
            r"(?:볼륨|음량|소리)(?:을|를)?\s*(?P<direction>올려|높여|키워|내려|낮춰|줄여)"
            r"\s*(?P<amount>\d{1,3})\s*(?:퍼센트|%)?"
            r"(?:\s*(?:줘|주세요|해줘|해))?",
            r"(?:(?:볼륨|음량|소리)(?:을|를)?\s*)?(?P<direction>음소거|무음)"
            r"(?:\s*(?:해|해줘|해주세요|해 주세요))?",
        ),
        "en": (
            r"(?:please\s+)?(?:increase|raise|lower|decrease|turn\s+up|turn\s+down)"
            r"\s+(?:the\s+)?(?:volume|sound)(?:\s+by)?\s*"
            r"(?P<amount>\d{1,3})\s*%(?:\s+please)?",
            r"(?:please\s+)?(?:mute|silence)\s+(?:the\s+)?(?:volume|sound)"
            r"(?:\s+please)?",
        ),
        "ja": (
            r"(?:音量|ボリューム)(?:を)?\s*(?P<amount>\d{1,3})\s*%?\s*"
            r"(?P<direction>上げ|高く|下げ|低く)(?:て|てください)?",
            r"(?:(?:音量|ボリューム)(?:を)?\s*)?(?P<direction>ミュート|消音)"
            r"(?:して|してください)?",
        ),
    },
}

_ACTION_ANCHORS: dict[str, dict[str, tuple[str, ...]]] = {
    "time": {
        "ko": (r"시간", r"시각", r"몇\s*시", r"시계"),
        "en": (r"\btime\b", r"\bclock\b"),
        "ja": (r"何時", r"時刻", r"時計", r"時間"),
    },
    "apps": {
        "ko": (r"앱", r"프로그램", r"프로세스", r"실행\s*중", r"켜져"),
        "en": (r"\b(?:running|open)\s+(?:apps?|applications?|programs?|processes?)\b", r"\brunning\b"),
        "ja": (r"アプリ", r"プログラム", r"プロセス", r"実行中", r"起動中"),
    },
    "screenshot": {
        "ko": (r"스크린\s*샷", r"화면", r"캡처", r"촬영"),
        "en": (r"\bscreens?hots?\b", r"\bscreen\s+shot\b", r"\bcapture\b"),
        "ja": (r"スクリーンショット", r"画面", r"キャプチャ", r"撮"),
    },
    "volume": {
        "ko": (r"볼륨", r"음량", r"소리", r"음소거", r"무음"),
        "en": (r"\bvolume\b", r"\bsound\b", r"\bmute\b", r"\bsilence\b"),
        "ja": (r"音量", r"ボリューム", r"ミュート", r"消音"),
    },
    "open": {
        "ko": (r"열어", r"켜", r"띄워", r"실행해"),
        "en": (r"\bopen\b", r"\blaunch\b", r"\bstart\b"),
        "ja": (r"開い", r"起動", r"立ち上げ"),
    },
    "close": {
        "ko": (r"닫아", r"꺼", r"종료"),
        "en": (r"\bclose\b", r"\bquit\b", r"\bexit\b", r"\bshut\b"),
        "ja": (r"閉じ", r"終了", r"閉め"),
    },
    "search": {
        "ko": (r"검색", r"찾아"),
        "en": (r"\bsearch\b", r"\bfind\b", r"\blook\s+for\b"),
        "ja": (r"検索", r"探し", r"調べ"),
    },
    "play": {
        "ko": (r"재생", r"틀어"),
        "en": (r"\bplay\b",),
        "ja": (r"再生", r"流し"),
    },
    "window": {
        "ko": (r"창",),
        "en": (r"\bwindow\b",),
        "ja": (r"ウィンドウ", r"窓"),
    },
    "monitor": {
        "ko": (r"모니터", r"두\s*번째\s*화면"),
        "en": (r"\b(?:second|third|another|next)\s+monitor\b", r"\bmonitor\s*[23]\b"),
        "ja": (r"(?:第二|第三|別の)\s*モニター", r"モニター\s*[23]"),
    },
}

_CONNECTORS = {
    "ko": (r"그리고", r"하고(?:\s*나서)?", r"해서", r"한\s*뒤", r"뒤에", r"다음에"),
    "en": (r"\band\b", r"\bthen\b", r"\bafter\s+(?:that|this)\b", r"\bbefore\b"),
    "ja": (r"そして", r"それから", r"その後", r"あとで", r"てから", r"ながら"),
}

_NEGATIONS = {
    "ko": (r"하지\s*마", r"하지말", r"말고", r"않고", r"않은"),
    "en": (r"\b(?:do\s+not|don't|never|without)\b",),
    "ja": (r"ないで", r"なく", r"ずに", r"ではなく", r"ない"),
}


def _normalise(text: str) -> str:
    value = unicodedata.normalize("NFKC", text).strip()
    value = re.sub(r"\s+", " ", value)
    return re.sub(r"[!?！？。．.,、]+$", "", value).strip()


def detect_language(text: str) -> str:
    value = _normalise(text)
    if re.search(r"[가-힣]", value):
        return "ko"
    if re.search(r"[ぁ-ゖァ-ヺ]", value) or any(marker in value for marker in _JAPANESE_MARKERS):
        return "ja"
    if re.search(r"[A-Za-z]", value):
        return "en"
    if re.search(r"[一-龯々]", value):
        return "ja"
    return ""


def _has_any(value: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, value, flags=re.IGNORECASE) for pattern in patterns)


def connector_count(text: str, language: str | None = None) -> int:
    value = _normalise(text)
    language = language or detect_language(value)
    if language not in _CONNECTORS:
        return 0
    count = sum(len(re.findall(pattern, value, flags=re.IGNORECASE)) for pattern in _CONNECTORS[language])
    if language == "en":
        count += value.count(",")
    if language == "ja":
        count += value.count("、")
    return count


def action_anchor_count(text: str, language: str | None = None) -> int:
    value = _normalise(text)
    language = language or detect_language(value)
    if language not in {"ko", "en", "ja"}:
        return 0
    return sum(
        1
        for patterns in _ACTION_ANCHORS.values()
        if _has_any(value, patterns[language])
    )


def _grammar_match(value: str, candidate: str, language: str) -> re.Match[str] | None:
    for pattern in _GRAMMARS.get(candidate, {}).get(language, ()):
        match = re.fullmatch(pattern, value, flags=re.IGNORECASE)
        if match:
            return match
    return None


def _target_group(candidate: str) -> str:
    return {
        "get_current_time": "time",
        "get_running_apps": "apps",
        "take_screenshot": "screenshot",
        "adjust_volume": "volume",
    }.get(candidate, "")


def _volume_arguments(match: re.Match[str] | None, candidate: str) -> tuple[dict[str, object], bool, bool]:
    if candidate != "adjust_volume" or match is None:
        return {}, bool(match), False
    values = match.groupdict()
    direction = str(values.get("direction") or "").casefold()
    if not direction:
        phrase = match.group(0).casefold()
        if re.search(r"\b(?:increase|raise|turn\s+up)\b", phrase):
            direction = "up"
        elif re.search(r"\b(?:lower|decrease|turn\s+down)\b", phrase):
            direction = "down"
        elif re.search(r"\b(?:mute|silence)\b", phrase):
            direction = "mute"
    if direction in {"올려", "높여", "키워", "上げ", "高く"}:
        direction = "up"
    elif direction in {"내려", "낮춰", "줄여", "下げ", "低く"}:
        direction = "down"
    elif direction in {"음소거", "무음", "ミュート", "消音"} or not direction:
        direction = "mute"
    raw_amount = values.get("amount")
    if direction == "mute":
        return {"direction": "mute", "amount": 100}, True, False
    if raw_amount is None:
        return {}, False, True
    amount = int(raw_amount)
    if not 1 <= amount <= 100:
        return {}, False, True
    return {"direction": direction, "amount": amount}, True, False


def parse_candidate(text: str, candidate: str) -> SemanticParse:
    """후보 하나가 문장 전체를 설명하는지와 필요한 인자를 확인한다."""
    if not isinstance(text, str) or not text.strip() or len(text) > 4096:
        return SemanticParse(candidate, "")
    value = _normalise(text)
    language = detect_language(value)
    if language not in {"ko", "en", "ja"}:
        return SemanticParse(candidate, language)

    target = _target_group(candidate)
    match = _grammar_match(value, candidate, language)
    anchors = action_anchor_count(value, language)
    connectors = connector_count(value, language)
    target_match = bool(match)
    contradiction = _has_any(value, _NEGATIONS[language])
    if candidate == "focus_window" and _has_any(value, _ACTION_ANCHORS["close"][language]):
        contradiction = True
    if target and _has_any(value, _ACTION_ANCHORS["close"][language] + _ACTION_ANCHORS["open"][language]):
        contradiction = contradiction or not target_match
    residual = bool(anchors > 1 or (connectors and anchors > 1))
    if target and not target_match:
        residual = True
    arguments, argument_ok, argument_conflict = _volume_arguments(match, candidate)
    contradiction = contradiction or argument_conflict
    intent_confirmed = target_match and argument_ok
    valid = bool(match) and argument_ok
    if candidate not in DIRECT_CANDIDATES:
        intent_confirmed = False
        residual = True
    return SemanticParse(
        candidate=candidate,
        language=language,
        arguments=arguments,
        valid=valid,
        intent_confirmed=intent_confirmed,
        contradiction=contradiction,
        residual_action=residual,
    )


__all__ = [
    "DIRECT_CANDIDATES",
    "SemanticParse",
    "action_anchor_count",
    "connector_count",
    "detect_language",
    "parse_candidate",
]
