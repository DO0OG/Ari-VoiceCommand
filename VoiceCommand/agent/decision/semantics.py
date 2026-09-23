"""짧고 단일한 요청의 의미와 인자를 결정적으로 확인한다."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import unicodedata

from agent.decision.candidates import DIRECT_ALLOWLIST


DIRECT_CANDIDATES = DIRECT_ALLOWLIST
# Parsed so their meaning can be checked and measured, but never run directly:
# they stay out of the direct allowlist until they pass the release gate.
TIER_B_CANDIDATES = frozenset({"get_weather", "set_timer", "cancel_timer", "launch_app"})
PARSED_CANDIDATES = frozenset(DIRECT_CANDIDATES) | TIER_B_CANDIDATES


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
            r"(?:教え|見せ|確認し|表示し)" + _JA_REQ,
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
            r"capture\s+(?:a\s+)?(?:screenshot|screen\s*shot)",
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
    "set_timer": {
        "ko": (
            r"(?P<minutes>\d{1,3})분(?:(?P<seconds>\d{1,2})초)?(?:짜리)?(?:으로|로)?타이머(?:를|좀)*"
            r"(?:맞춰|설정해|켜|시작해|걸어|해)" + _KO_REQ,
            r"(?P<seconds>\d{1,3})초(?:짜리)?(?:으로|로)?타이머(?:를|좀)*"
            r"(?:맞춰|설정해|켜|시작해|걸어|해)" + _KO_REQ,
            r"타이머(?:를|좀)*(?P<minutes>\d{1,3})분(?:(?P<seconds>\d{1,2})초)?(?:으로|로)?"
            r"(?:맞춰|설정해|걸어|해)" + _KO_REQ,
        ),
        "en": (
            r"(?:set|start)\s+(?:a\s+)?timer\s+for\s+(?P<minutes>\d{1,3})\s+minutes?"
            r"(?:\s+and\s+(?P<seconds>\d{1,2})\s+seconds?)?",
            r"(?:set|start)\s+(?:a\s+)?timer\s+for\s+(?P<seconds>\d{1,3})\s+seconds?",
            r"(?:set|start)\s+(?:a\s+)?(?P<minutes>\d{1,3})[\s-]minutes?\s+timer",
        ),
        "ja": (
            r"(?P<minutes>\d{1,3})分(?:(?P<seconds>\d{1,2})秒)?(?:の)?タイマー(?:を)?"
            r"(?:セットし|かけ|設定し|始め|スタートし)" + _JA_REQ,
            r"(?P<seconds>\d{1,3})秒(?:の)?タイマー(?:を)?(?:セットし|かけ|設定し|始め|スタートし)" + _JA_REQ,
            r"タイマー(?:を)?(?P<minutes>\d{1,3})分(?:(?P<seconds>\d{1,2})秒)?(?:に|で)?"
            r"(?:セットし|設定し|かけ)" + _JA_REQ,
        ),
    },
    "cancel_timer": {
        "ko": (
            r"(?:지금|진행중인|설정한|맞춘)?타이머(?:를|좀)*(?:취소해|꺼|멈춰|중지해|끝내|없애)" + _KO_REQ,
        ),
        "en": (r"(?:cancel|stop|clear|turn\s+off)\s+(?:the\s+|my\s+)?timer",),
        "ja": (r"タイマー(?:を)?(?:キャンセルし|止め|停止し|解除し|消し)" + _JA_REQ,),
    },
    # Only the current weather: the handler takes a place, not a day or a comparison.
    "get_weather": {
        "ko": (
            r"(?!.*(?:내일|어제|모레|주말|다음주|비교|아침|오전|오후|저녁|밤|나중))(?:지금|오늘)?"
            r"(?:(?P<location>[가-힣]{2,8}?)(?:의)?)?(?:지금|오늘)?날씨(?:는|가|를|좀)*"
            r"(?:어때(?:요)?|알려" + _KO_REQ + r"|확인해" + _KO_REQ + r")",
        ),
        "en": (
            r"(?!.*\b(?:tomorrow|yesterday|tonight|weekend|week|compare|and|morning|afternoon|evening|later)\b)"
            r"(?:what(?:'s|\s+is)\s+the\s+weather(?:\s+like)?|how(?:'s|\s+is)\s+the\s+weather"
            r"|(?:tell\s+me|check|show\s+me)\s+the\s+weather)"
            r"(?:\s+(?:in|for)\s+(?P<location>[a-z][a-z .'-]{0,30}?))?(?:\s+(?:today|now|right\s+now))?",
        ),
        "ja": (
            r"(?!.*(?:明日|昨日|明後日|週末|来週|比べ|比較|朝|午前|午後|夕方|夜|後で))(?:今日の|今の)?"
            r"(?:(?P<location>[一-龯ァ-ヺー]{1,8})の)?(?:今日の|今の)?天気(?:は)?"
            r"(?:どう(?:ですか)?|(?:を)?教え" + _JA_REQ + r")",
        ),
    },
    "launch_app": {
        "ko": (r"(?P<app>.{1,30}?)(?:을|를|좀)*(?:열어|실행해|켜|띄워)" + _KO_REQ,),
        "en": (
            r"(?:open|launch|start|run)\s+(?:the\s+|up\s+)?(?P<app>[a-z0-9][a-z0-9 .+-]{0,40}?)"
            r"(?:\s+(?:app|application|program))?",
        ),
        "ja": (r"(?P<app>.{1,30}?)(?:を)?(?:開い|起動し|立ち上げ)" + _JA_REQ,),
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

_UNSAFE_CONTEXT_ACTIONS = {
    "ko": (r"삭제|지워|전송|보내|구매|결제|포맷|초기화|종료",),
    "en": (r"\b(?:delete|erase|remove|send|purchase|buy|format|reset|shut\s+down)\b",),
    "ja": (r"削除|消去|送信|購入|支払|フォーマット|初期化|終了",),
}

_SAFE_CONTEXTS = {
    "en": (
        r"(?:for|before)\s+(?:(?:my|the|this|our)\s+)?(?:meeting|call|presentation|class|work|task|travel(?:\s+notes?)?|notes?|report|recording|conversation|discussion)",
        r"because\s+(?:the\s+)?(?:room|dialogue|recording|presentation|conversation|video)\s+(?:is|was|seems|sounds|stays)\s+(?:clear|quiet|loud|hard\s+to\s+hear|easy\s+to\s+hear)",
        r"so\s+(?:that\s+)?(?:I|we)\s+can\s+(?:focus|hear(?:\s+clearly)?|listen(?:\s+better)?|read(?:\s+clearly)?|understand)",
        r"to\s+(?:document|record|reference)\s+(?:this|the|my)\s+(?:issue|work|notes?|meeting)",
    ),
    "ko": (
        r"(?:회의|통화|발표|수업|업무|작업|여행|메모|기록|대화|토론|문서|자료|오류|문제)(?:\s*(?:내용|준비|상황|자료|기록|작성))?(?:을|를|의)?\s*(?:위해(?:서)?|때문에|하려고|목적으로)",
        r"(?:회의\s*내용|오류\s*상황)(?:을|를)\s*(?:적어두|기록하)려고",
        r"영상\s*소리(?:가)?\s*(?:커서|높아서|작아서)",
    ),
    "ja": (
        r"(?:会議|通話|発表|授業|作業|旅行|メモ|記録|会話|議論|資料|問題|エラー|動画|音声)(?:(?:の)?(?:準備|内容|記録|資料))?(?:の)?(?:ために|ため|ので|ように|用に)",
        r"動画の音が大きいので",
    ),
}

_CANDIDATE_ALIASES: dict[str, dict[str, tuple[tuple[str, str], ...]]] = {
    "adjust_volume": {
        "ko": ((r"(?<![가-힣])(?:(?:시스템|출력|재생|스피커|전체)(?:의|\s+)?){1,2}(?:음량|볼륨|소리|레벨)(?=(?:을|를|은|는|이|가|[^가-힣]|$))", "볼륨"),),
        "en": (
            (r"(?<![a-z0-9])(?:(?:system|output|playback|speaker|overall)\s+){0,2}(?:audio|sound|volume)(?:\s+(?:level|output))?(?![a-z0-9])", "volume"),
            (r"(?<![a-z0-9])speaker\s+output(?![a-z0-9])", "volume"),
        ),
        "ja": ((r"(?:(?:システム|出力|再生|スピーカー|全体)(?:の)?){1,2}(?:音量|ボリューム|音声|サウンド|レベル)(?=を|は|が|も|の|$|[、,。\s])", "音量"),),
    },
    "get_current_time": {
        "ko": ((r"(?<![가-힣])(?:(?:내\s*지역|이\s*지역)(?:의)?\s*)?(?:현지(?:의)?\s*)?(?:현재\s*)?(?:시간|시각)(?=(?:을|를|은|는|이|가|[^가-힣]|$))", "현재시간"),),
        "en": ((r"(?<![a-z0-9])(?:current\s+)?local\s+(?:time|clock)(?:\s+(?:here|in\s+my\s+area))?(?![a-z0-9])", "current time"),),
        "ja": ((r"(?:(?:この)?地域の)?(?:現地の?|現在の?)(?:時間|時刻)(?=を|は|が|$|[、,。\s])", "現在時刻"),),
    },
    "take_screenshot": {
        "ko": ((r"(?<![가-힣])(?:디스플레이|화면)(?:을|를)?(?:의|\s+)?(?:이미지|사진|스냅샷)(?:로)?(?=[을를은는이가]|[^가-힣]|$)|스샷(?=[을를은는이가]|[^가-힣]|$)", "스크린샷"),),
        "en": (
            (r"(?<![a-z0-9])(?:screen\s+image|display\s+(?:image|snapshot)|snapshot|screen\s+capture)(?![a-z0-9])", "screenshot"),
        ),
        "ja": ((r"(?<![ぁ-んァ-ン一-龯])(?:ディスプレイ|画面|スクリーン)(?:の)?(?:画像|イメージ|スナップショット)|スナップショット(?=を|で|$|[、,。\s])", "スクリーンショット"),),
    },
    "get_running_apps": {
        "ko": (
            (r"(?<![가-힣])(?:실행\s*상태인|작동\s*중인|활성\s*상태인)(?=[가-힣\s]|$)", "실행중인"),
            (r"(?<![가-힣])(?:소프트웨어|소프트)(?=[을를은는이가]|[^가-힣]|$)", "앱"),
        ),
        "en": (),
        "ja": (
            (r"(?:稼働中|動作中|実行状態の|アクティブな)(?=の|アプリ|プログラム|プロセス|ソフト|$)", "実行中"),
            (r"(?:ソフトウェア|ソフト)(?=を|一覧|$|[、,。\s])", "アプリ"),
        ),
    },
}

_CONTEXT_PREFIXES = {
    "ko": (r"(?P<context>.{1,72}?(?:하기\s*위해|위해(?:서)?|때문에|려고|목적으로|라서|아서|어서|니까|커서|작아서))\s*[,，]?\s*(?P<core>.+)",),
    "en": (r"(?P<context>(?:for|before|because|so\s+that)\s+[^,;]{1,72}),\s*(?P<core>.+)",),
    "ja": (r"(?P<context>.{1,72}?(?:ために|ため|ので|ように|用に))[、,]?\s*(?P<core>.+)",),
}
_CONTEXT_SUFFIXES = {
    "ko": (r"(?P<core>.+?)[、,]?\s+(?P<context>.{1,72}?(?:하기\s*위해|위해(?:서)?|때문에|려고|목적으로|수\s*있도록|라서|아서|어서|니까|커서|작아서))",),
    "en": (r"(?P<core>.+?)\s+(?P<context>(?:for|so(?:\s+that)?|because|before|to)\s+[^,;.!?]{1,72})",),
    "ja": (r"(?P<core>.+?)(?:[、,]\s*|\s+)(?P<context>.{1,72}?(?:ために|ため|ので|ように|用に))",),
}

_CONTEXT_QUANTITY = re.compile(
    r"(?:\d|\b(?:one|two|three|four|five|ten|twenty)\s+(?:seconds?|minutes?|hours?|percent)\b|"
    r"초|분|시간|퍼센트|秒|分|時間|パーセント)",
    flags=re.IGNORECASE,
)


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


def is_multi_intent(text: str) -> bool:
    """Flag requests that clearly chain several actions before any scoring.

    This replaces the general conversation router as the pre-check, so word
    collisions such as an app named "Code" no longer skip local scoring.
    """
    if not isinstance(text, str) or not text.strip() or len(text) > 4096:
        return False
    value = _normalise(text)
    language = detect_language(value)
    if language not in _CONNECTORS:
        return False
    value = _strip_fillers(value, language)
    safe_context_views = _context_views(value, language)
    if safe_context_views:
        return any(
            connector_count(view, language) and action_anchor_count(view, language) > 1
            for view in safe_context_views
        )
    return bool(connector_count(value, language) and action_anchor_count(value, language) > 1)


def _grammar_match(value: str, candidate: str, language: str) -> re.Match[str] | None:
    subject = value.replace(" ", "") if language in {"ko", "ja"} else value
    for pattern in _GRAMMARS.get(candidate, {}).get(language, ()):
        match = re.fullmatch(pattern, subject, flags=re.IGNORECASE)
        if match:
            return match
    return None


def _candidate_aliases(value: str, candidate: str, language: str) -> str:
    for pattern, replacement in _CANDIDATE_ALIASES.get(candidate, {}).get(language, ()):
        value = re.sub(pattern, replacement, value, flags=re.IGNORECASE)
    if candidate == "get_current_time" and language == "en":
        value = re.sub(r"\bcurrent\s+current\s+time\b", "current time", value, flags=re.IGNORECASE)
    return value


def _display_variant(value: str, candidate: str, language: str) -> str:
    if candidate != "get_running_apps":
        return value
    if language == "en":
        return re.sub(
            r"\s+(?:as|in)\s+(?:a\s+)?(?:(?:complete|full|detailed)\s+)?(?:list|bullet\s+points)(?:\s+form)?$",
            "",
            value,
            flags=re.IGNORECASE,
        ).strip()
    if language == "ko":
        value = re.sub(r"(?:빠짐없이|누락\s*없이|전부|모두)", "", value)
        value = re.sub(r"(앱|어플|프로그램|프로세스|애플리케이션)(?:들)?(?:을|를)\s*(?=(?:목록|리스트))", r"\1", value)
        value = re.sub(r"(?:리스트|목록)(?:으로|로|형태로)", "목록", value)
        return value.strip()
    value = re.sub(r"(アプリケーション|アプリ|プログラム|プロセス)(を)(?=(?:漏れなく|すべて|全部)?(?:一覧|リスト))", r"\1", value)
    value = re.sub(r"(?:一覧|リスト)(?:で|として|形式で)", "一覧", value)
    value = re.sub(r"(?:漏れなく|すべて|全部)", "", value)
    return value.strip()


def _safe_context_clause(context: str, language: str) -> bool:
    value = context.strip(" \t,，。、")
    if not value or len(value) > 72 or _CONTEXT_QUANTITY.search(value):
        return False
    if _has_any(value, _NEGATIONS[language]) or _has_any(value, _UNSAFE_CONTEXT_ACTIONS[language]):
        return False

    return any(re.fullmatch(pattern, value, flags=re.IGNORECASE) for pattern in _SAFE_CONTEXTS[language])


def _context_views(value: str, language: str) -> list[str]:
    views = []
    for pattern in _CONTEXT_PREFIXES[language] + _CONTEXT_SUFFIXES[language]:
        match = re.fullmatch(pattern, value, flags=re.IGNORECASE)
        if not match or not _safe_context_clause(match.group("context"), language):
            continue
        core = match.group("core").strip(" \t,，。、")
        if core and core not in views:
            views.append(core)
    return views


def _candidate_grammar_match_with_view(
    value: str, candidate: str, language: str
) -> tuple[re.Match[str] | None, str]:
    if candidate not in DIRECT_CANDIDATES:
        return _grammar_match(value, candidate, language), value
    views = [value, *_context_views(value, language)]
    for view in views:
        display = _display_variant(view, candidate, language)
        match = _grammar_match(_candidate_aliases(view, candidate, language), candidate, language)
        if match:
            return match, view
        if display and display != view:
            match = _grammar_match(_candidate_aliases(display, candidate, language), candidate, language)
            if match:
                return match, view
    return None, value


def _candidate_grammar_match(value: str, candidate: str, language: str) -> re.Match[str] | None:
    match, _ = _candidate_grammar_match_with_view(value, candidate, language)
    return match


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


def _known_app(name: str) -> str:
    """Return the alias the launch handler already knows, or "" when unresolved."""
    from agent.automation_helpers import _APP_ALIAS_CANDIDATES

    key = re.sub(r"\s+", "", name.casefold())
    for alias in _APP_ALIAS_CANDIDATES:
        if re.sub(r"\s+", "", alias.casefold()) == key:
            return alias
    return ""


def _tier_b_arguments(match: re.Match[str], candidate: str) -> tuple[dict[str, object], bool]:
    values = match.groupdict()
    if candidate == "set_timer":
        minutes = int(values.get("minutes") or 0)
        seconds = int(values.get("seconds") or 0)
        return {"minutes": minutes, "seconds": seconds}, minutes * 60 + seconds > 0
    if candidate == "get_weather":
        return {"location": (values.get("location") or "").strip()}, True
    if candidate == "launch_app":
        app = _known_app(values.get("app") or "")
        return ({"name": app}, True) if app else ({}, False)
    return {}, True


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
    match, matched_view = _candidate_grammar_match_with_view(value, candidate, language)
    # Count residual actions on the exact core whose surrounding context was
    # fully validated against the harmless-context allowlist. Negation checks
    # below still use the original text.
    anchors = action_anchor_count(matched_view, language)
    connectors = connector_count(matched_view, language)
    target_match = bool(match)
    negation_text = re.sub(_JA_REQUEST_NEGATIVE, "", value) if language == "ja" else value
    if language == "ja" and candidate == "get_running_apps":
        negation_text = negation_text.replace("漏れなく", "")
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
    if candidate in TIER_B_CANDIDATES and match is not None:
        arguments, argument_ok = _tier_b_arguments(match, candidate)
    contradiction = contradiction or argument_conflict
    intent_confirmed = target_match and argument_ok
    valid = bool(match) and argument_ok
    if candidate not in PARSED_CANDIDATES:
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
    "PARSED_CANDIDATES",
    "TIER_B_CANDIDATES",
    "SemanticParse",
    "action_anchor_count",
    "connector_count",
    "detect_language",
    "is_multi_intent",
    "parse_candidate",
]
