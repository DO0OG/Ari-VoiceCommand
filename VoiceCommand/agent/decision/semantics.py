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

# Korean and Japanese grammars match against text with all spaces removed.
_KO_REQ = (
    r"(?:줘|줘요|주라|줄래|줄래요|주세요|주실래요|주시겠어요|주겠니|줄수있어|줄수있어요|"
    r"봐|봐줘|봐요)?"
)
_JA_REQ = (
    r"(?:て|てね|てよ|てください|てくれる|てくれない|てくれますか|てくれませんか|"
    r"てもらえる|てもらえますか|てもらえない|てほしい|て欲しい|ていただけますか|"
    r"ていただけませんか)"
)
_EN_NUMBER = r"\d{1,3}|five|ten|fifteen|twenty|twenty[\s-]five|thirty|forty|fifty"
_EN_NUMBER_WORDS = {
    "five": 5, "ten": 10, "fifteen": 15, "twenty": 20, "twenty-five": 25,
    "thirty": 30, "forty": 40, "fifty": 50,
}

_GRAMMARS: dict[str, dict[str, tuple[str, ...]]] = {
    "get_current_time": {
        "ko": (
            r"(?:지금|현재)?몇시(?:야|예요|에요|지|인지|인가요|니)?",
            r"(?:지금|현재)?몇시인지(?:좀)?(?:알려|말해)" + _KO_REQ,
            r"(?:지금|현재)(?:시간|시각)",
            r"(?:지금|현재)?(?:시간|시각)(?:을|를|이|좀)*(?:알려|말해|확인해)" + _KO_REQ,
            r"(?:지금)?시계(?:를|좀)*(?:확인해|봐)" + _KO_REQ,
        ),
        "en": (
            r"what\s+time\s+is\s+it(?:\s+(?:now|right\s+now))?",
            r"what(?:'s|\s+is)\s+the\s+(?:current\s+)?time(?:\s+(?:now|right\s+now))?",
            r"(?:tell|show|give)\s+me\s+(?:the\s+)?(?:current\s+)?time(?:\s+now)?",
            r"(?:tell\s+me\s+)?what\s+time\s+it\s+is(?:\s+now)?",
            r"check\s+(?:the\s+)?(?:current\s+)?time",
            r"check\s+(?:the\s+)?clock",
            r"(?:the\s+)?current\s+time",
            r"do\s+you\s+(?:know|have)\s+the\s+time",
            r"time\s+check",
        ),
        "ja": (
            r"(?:今|現在)?何時(?:ですか|だ|なの|か)?",
            r"(?:今|現在)?何時か(?:教え|確認し)" + _JA_REQ,
            r"(?:今の|現在の|今|現在)?(?:時刻|時間)(?:を)?(?:教え|確認し)" + _JA_REQ,
            r"現在時刻",
            r"時計(?:を)?(?:確認し|見)" + _JA_REQ,
        ),
    },
    "get_running_apps": {
        "ko": (
            r"(?:지금|현재)?(?:실행중인|실행중|켜져있는|켜진|열려있는|열린|돌아가는|떠있는)?"
            r"(?:앱|어플|프로그램|프로세스|애플리케이션)(?:들)?(?:목록|리스트)?(?:을|를|좀)*"
            r"(?:보여|알려|확인해|나열해)" + _KO_REQ,
            r"(?:지금|현재)?(?:뭐가|어떤앱이|어떤프로그램이)(?:켜져|실행되고|돌아가고|열려)있는지"
            r"(?:좀)?(?:보여|알려|확인해)" + _KO_REQ,
        ),
        "en": (
            r"(?:list|show(?:\s+me)?|display|check)\s+(?:all\s+)?(?:the\s+)?(?:currently\s+)?"
            r"(?:running|open|active)\s+(?:apps?|applications?|programs?|processes?)",
            r"tell\s+me\s+(?:which|what)\s+(?:apps?|applications?|programs?|processes?)\s+"
            r"are\s+(?:currently\s+)?(?:running|open)(?:\s+(?:now|right\s+now))?",
            r"(?:which|what)\s+(?:apps?|applications?|programs?|processes?)\s+are\s+"
            r"(?:currently\s+)?(?:running|open)(?:\s+(?:now|right\s+now))?",
            r"what(?:'s|\s+is)\s+(?:currently\s+)?running(?:\s+(?:now|right\s+now))?",
            r"(?:list|show(?:\s+me)?|display)\s+(?:all\s+)?(?:the\s+)?(?:apps?|applications?|programs?|processes?)\s+"
            r"(?:that\s+are|which\s+are|currently)\s+(?:running|open)",
            r"(?:list|show(?:\s+me)?|display|check)\s+(?:the\s+)?list\s+of\s+(?:currently\s+)?"
            r"(?:running|open|active)\s+(?:apps?|applications?|programs?|processes?)",
        ),
        "ja": (
            r"(?:現在|今)?(?:実行中|起動中|開いている|開いてる|動いている|動いてる)(?:の)?"
            r"(?:アプリ|プログラム|プロセス|アプリケーション)(?:一覧)?(?:を)?"
            r"(?:教え|見せ|確認し)" + _JA_REQ,
            r"(?:現在|今)?何が(?:起動|実行|動い)(?:している|してる|ている|てる)か"
            r"(?:教え|見せ|確認し)" + _JA_REQ,
        ),
    },
    "take_screenshot": {
        "ko": (
            r"(?:지금|현재)?(?:의)?(?:화면|스크린샷|스샷)(?:을|를|좀)*"
            r"(?:(?:캡처|캡쳐|촬영)(?:해|해서저장해)|찍어)" + _KO_REQ,
            r"(?:지금|현재)?(?:의)?화면(?:을|를)?스크린샷으로(?:찍어|저장해)" + _KO_REQ,
            r"(?:지금|현재)?(?:의)?(?:화면|화면캡처|스크린샷|스샷)(?:을|를|좀)*(?:그대로)?저장해"
            + _KO_REQ,
        ),
        "en": (
            r"(?:take|grab)\s+(?:a\s+)?(?:screenshot|screen\s*shot)"
            r"(?:\s+of\s+(?:the\s+)?(?:current\s+|whole\s+|entire\s+)?screen)?",
            r"(?:take\s+and\s+)?save\s+(?:a\s+)?(?:screenshot|screen\s*shot)",
            r"capture\s+(?:the\s+)?(?:current\s+|whole\s+|entire\s+)?screen",
            r"save\s+(?:the\s+)?(?:current\s+)?screen",
            r"screenshot\s+(?:the\s+)?screen",
        ),
        "ja": (
            r"(?:今の|現在の)?(?:画面|スクリーンショット|スクショ)(?:を)?(?:そのまま)?"
            r"(?:キャプチャし|保存し|撮っ)" + _JA_REQ,
            r"(?:今の|現在の)?画面(?:を)?(?:スクリーンショット|スクショ)(?:を)?撮っ" + _JA_REQ,
            r"(?:今の|現在の)?画面キャプチャ(?:を)?(?:し|保存し)" + _JA_REQ,
            r"(?:今の|現在の)?画面(?:を)?キャプチャして保存し" + _JA_REQ,
            r"(?:今の|現在の)?(?:画面(?:を)?)?(?:スクリーンショット|スクショ)し" + _JA_REQ,
        ),
    },
    "adjust_volume": {
        "ko": (
            r"(?:볼륨|음량|소리)(?:을|를|좀|이|가)*"
            r"(?:(?P<amount>\d{1,3})(?:퍼센트|%)?(?:만큼|정도)?)?(?:좀|조금|더|살짝)*"
            r"(?P<direction>올려|높여|키워|크게해|내려|낮춰|줄여|작게해)" + _KO_REQ,
            r"(?:볼륨|음량|소리)(?:을|를)?(?P<direction>올려|높여|키워|내려|낮춰|줄여)"
            r"(?P<amount>\d{1,3})(?:퍼센트|%)?" + _KO_REQ,
            r"(?:(?:볼륨|음량|소리)(?:을|를|좀)*)?(?P<direction>음소거|무음)(?:으로)?(?:해)?" + _KO_REQ,
        ),
        "en": (
            r"(?P<direction>increase|raise|lower|decrease|reduce|turn\s+up|turn\s+down)"
            r"\s+(?:the\s+)?(?:volume|sound)"
            r"(?:\s+(?:by\s+)?(?P<amount>" + _EN_NUMBER + r")\s*(?:%|percent)?)?",
            r"turn\s+(?:the\s+)?(?:volume|sound)\s+(?P<direction>up|down)"
            r"(?:\s+by\s+(?P<amount>" + _EN_NUMBER + r")\s*(?:%|percent)?)?",
            r"(?:volume|sound)\s+(?P<direction>up|down)",
            r"(?P<direction>mute|silence)(?:\s+(?:the\s+)?(?:volume|sound|audio))?",
        ),
        "ja": (
            r"(?:音量|ボリューム|音)(?:を)?(?:(?P<amount>\d{1,3})(?:%|パーセント)?)?"
            r"(?:少し|ちょっと|もう少し)?(?P<direction>上げ|下げ)" + _JA_REQ,
            r"(?:音量|ボリューム|音)(?:を)?(?:少し|ちょっと|もう少し)?"
            r"(?P<direction>高く|大きく|低く|小さく)し" + _JA_REQ,
            r"(?:(?:音量|ボリューム|音)(?:を)?)?(?P<direction>ミュート|消音)(?:にし|し)" + _JA_REQ,
            r"(?:(?:音量|ボリューム|音)(?:を)?)?(?P<direction>ミュート|消音)",
        ),
    },
}

_LEADING_FILLERS = {
    "ko": (
        r"^(?:(?:음+|어+|아+|저기요?|그거|그|혹시|미안한데|미안하지만|죄송한데|죄송하지만|"
        r"가능하면|제발|그냥|저)(?:\s*[,，]\s*|\s+))+"
    ),
    "en": (
        r"^(?:(?:um+|uh+|so|well|hey|ok(?:ay)?|sorry|please|just|if\s+you\s+can|"
        r"(?:could|can|would|will)\s+you(?:\s+please)?(?:\s+just)?)\b\s*,?\s*)+"
    ),
    "ja": (
        r"^(?:(?:あの|あのー|えっと|ええと|えー|ちょっと|すみませんが|すみません|"
        r"できれば|悪いけど|ねえ)\s*[、,]?\s*)+"
    ),
}
_TRAILING_FILLERS = {
    "ko": r"(?:\s*좀)+$",
    "en": r"(?:\s*,?\s*\b(?:please|thanks|thank\s+you|for\s+me))+$",
    "ja": r"(?:\s*(?:ね|よ|な))+$",
}
_JA_REQUEST_NEGATIVE = r"(?:くれ|もらえ)(?:ない|ません)"

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


def _strip_fillers(value: str, language: str) -> str:
    """Remove hesitation and politeness words that never add an action."""
    previous = None
    while previous != value:
        previous = value
        value = re.sub(_LEADING_FILLERS[language], "", value, flags=re.IGNORECASE).strip()
        value = re.sub(_TRAILING_FILLERS[language], "", value, flags=re.IGNORECASE).strip()
        value = re.sub(r"[!?！？。．.,、]+$", "", value).strip()
    return value


def _grammar_match(value: str, candidate: str, language: str) -> re.Match[str] | None:
    subject = value.replace(" ", "") if language in {"ko", "ja"} else value
    for pattern in _GRAMMARS.get(candidate, {}).get(language, ()):
        match = re.fullmatch(pattern, subject, flags=re.IGNORECASE)
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
    direction = re.sub(r"\s+", " ", str(values.get("direction") or "").casefold())
    if direction in {"up", "increase", "raise", "turn up", "올려", "높여", "키워", "크게해",
                     "上げ", "高く", "大きく"}:
        direction = "up"
    elif direction in {"down", "lower", "decrease", "reduce", "turn down", "내려", "낮춰",
                       "줄여", "작게해", "下げ", "低く", "小さく"}:
        direction = "down"
    elif direction in {"mute", "silence", "음소거", "무음", "ミュート", "消音"}:
        direction = "mute"
    else:
        return {}, False, True
    if direction == "mute":
        return {"direction": "mute", "amount": 100}, True, False
    raw_amount = values.get("amount")
    # Without an amount the existing handler applies its default step.
    if raw_amount is None:
        return {"direction": direction}, True, False
    raw_amount = re.sub(r"[\s-]+", "-", raw_amount.casefold())
    amount = _EN_NUMBER_WORDS.get(raw_amount)
    if amount is None:
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
    value = _strip_fillers(value, language)
    if not value:
        return SemanticParse(candidate, language)
    match = _grammar_match(value, candidate, language)
    anchors = action_anchor_count(value, language)
    connectors = connector_count(value, language)
    target_match = bool(match)
    negation_text = re.sub(_JA_REQUEST_NEGATIVE, "", value) if language == "ja" else value
    contradiction = _has_any(negation_text, _NEGATIONS[language])
    if candidate == "focus_window" and _has_any(value, _ACTION_ANCHORS["close"][language]):
        contradiction = True
    if target and _has_any(value, _ACTION_ANCHORS["close"][language] + _ACTION_ANCHORS["open"][language]):
        contradiction = contradiction or not target_match
    # A full grammar match consumes the whole sentence as one action, so extra
    # anchors inside it ("open" in "list the open apps") belong to that action.
    residual = bool(connectors and anchors > 1)
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
