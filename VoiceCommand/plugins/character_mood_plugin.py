"""
캐릭터 감정/반응 플러그인 — character_widget 사용 예시

제공 기능:
  - 음성 명령: "아리 인사해줘", "아리 춤춰봐", "아리 놀라봐" 등
  - LLM 도구: character_react — LLM이 대화 맥락에 따라 캐릭터 반응을 직접 트리거
  - 트레이 메뉴: "캐릭터 인사" 클릭 시 시간대별 인사 말풍선 표시

context.character_widget 에서 사용한 API:
  widget.say(text, duration=5000)      # 말풍선 표시 (스레드 안전)
  widget.set_emotion(emotion)          # 감정 설정 (스레드 안전)
  widget.hide_speech_bubble()          # 말풍선 숨기기
"""

import logging
from datetime import datetime

PLUGIN_INFO = {
    "name": "character_mood_plugin",
    "version": "0.1.0",
    "api_version": "1.0",
    "description": "캐릭터 위젯 감정·반응 제어 예시 플러그인",
}

# ── 감정 → (애니메이션, 말풍선 텍스트) 매핑 ───────────────────────────────────

_MOOD_TABLE = {
    "기쁨":  ("기쁨",  ["신나요!", "정말 좋아요.", "기분이 좋네요."]),
    "슬픔":  ("슬픔",  ["흑흑...", "조금 우울해요.", "...괜찮아요."]),
    "화남":  ("화남",  ["에잇!", "화났어요!", "왜 그래요!"]),
    "놀람":  ("놀람",  ["헉!", "깜짝이야!", "어어어?!"]),
    "수줍":  ("수줍",  ["으, 쑥스럽잖아요...", "좀 부끄럽네요.", "...왜요."]),
    "진지":  ("진지",  ["집중해볼게요.", "말씀하세요.", "듣고 있어요."]),
    "기대":  ("기대",  ["두근거리네요.", "기대돼요!", "어서 해봐요."]),
    "걱정":  ("걱정",  ["괜찮을까요...", "걱정이 되네요.", "잘 될 거예요."]),
    "평온":  ("평온",  ["느긋하게요.", "좋은 하루예요.", "음..."]),
}

# ── LLM 도구 스키마 ────────────────────────────────────────────────────────────

_REACT_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "character_react",
        "description": (
            "아리 캐릭터의 감정을 변경하고 말풍선을 표시합니다. "
            "대화 맥락에 맞는 감정(기쁨/슬픔/화남/놀람/수줍/진지/기대/걱정/평온)을 "
            "선택하고, 캐릭터가 말할 짧은 텍스트를 지정하세요."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "emotion": {
                    "type": "string",
                    "enum": list(_MOOD_TABLE.keys()),
                    "description": "표현할 감정",
                },
                "message": {
                    "type": "string",
                    "description": "말풍선에 표시할 짧은 텍스트 (선택, 비워두면 기본 문구 사용)",
                },
            },
            "required": ["emotion"],
        },
    },
}

# ── 내부 헬퍼 ────────────────────────────────────────────────────────────────

_widget_ref = None  # register() 에서 주입


def _get_widget():
    return _widget_ref


def _react(emotion: str, message: str = "") -> None:
    """감정 설정 + 말풍선 표시 (워커 스레드에서 호출해도 안전)."""
    widget = _get_widget()
    if widget is None:
        logging.warning("[CharacterMoodPlugin] character_widget 없음 — 반응 건너뜀")
        return

    emotion_key, default_messages = _MOOD_TABLE.get(emotion, ("평온", ["..."]))
    text = message.strip() if message.strip() else __import__("random").choice(default_messages)

    widget.set_emotion(emotion_key)   # 시그널 기반 — 스레드 안전
    widget.say(text, duration=4000)   # 시그널 기반 — 스레드 안전


# ── LLM 도구 핸들러 ───────────────────────────────────────────────────────────

def _handle_character_react(args: dict):
    emotion = args.get("emotion", "평온")
    message = args.get("message", "")
    _react(emotion, message)
    return None  # TTS는 말풍선이 담당하므로 None 반환


# ── 음성 명령 ─────────────────────────────────────────────────────────────────

def _make_mood_command(context):
    from commands.base_command import BaseCommand

    _COMMAND_MAP = {
        ("인사", "안녕"):                ("기쁨",  ""),
        ("춤", "신나"):                  ("기대",  ""),
        ("놀라", "깜짝"):               ("놀람",  ""),
        ("슬퍼", "울어", "흑흑"):       ("슬픔",  ""),
        ("화나", "화내"):               ("화남",  ""),
        ("수줍", "쑥스"):               ("수줍",  ""),
        ("진지", "집중"):               ("진지",  ""),
        ("걱정"):                        ("걱정",  ""),
        ("기뻐", "좋아"):               ("기쁨",  ""),
    }

    class MoodCommand(BaseCommand):
        priority = 42  # TimerCommand(30)보다 낮고 AICommand(100)보다 높음

        def matches(self, text: str) -> bool:
            if "아리" not in text:
                return False
            return any(kw in text for keys in _COMMAND_MAP for kw in keys)

        def execute(self, text: str) -> None:
            for keywords, (emotion, msg) in _COMMAND_MAP.items():
                if any(kw in text for kw in keywords):
                    _react(emotion, msg)
                    return

    return MoodCommand()


# ── 트레이 메뉴 콜백 ──────────────────────────────────────────────────────────

def _on_greeting_click():
    hour = datetime.now().hour
    if 6 <= hour < 12:
        emotion, msg = "기쁨", "좋은 아침이에요. 오늘도 잘 부탁드려요."
    elif 12 <= hour < 14:
        emotion, msg = "기대", "점심 맛있게 드세요~"
    elif 14 <= hour < 18:
        emotion, msg = "평온", "오후도 힘내요!"
    elif 18 <= hour < 22:
        emotion, msg = "진지", "저녁 시간이네요. 오늘 하루 수고하셨어요."
    else:
        emotion, msg = "슬픔", "늦은 시간이에요. 얼른 쉬세요~"
    _react(emotion, msg)


# ── register ─────────────────────────────────────────────────────────────────

def register(context):
    global _widget_ref
    _widget_ref = getattr(context, "character_widget", None)

    if _widget_ref is None:
        logging.warning("[CharacterMoodPlugin] character_widget을 찾을 수 없습니다.")

    # 트레이 메뉴
    if callable(getattr(context, "register_menu_action", None)):
        context.register_menu_action("캐릭터 인사", _on_greeting_click)

    # 음성 명령
    if callable(getattr(context, "register_command", None)):
        context.register_command(_make_mood_command(context))

    # LLM 도구
    if callable(getattr(context, "register_tool", None)):
        context.register_tool(_REACT_TOOL_SCHEMA, _handle_character_react)

    logging.info("[CharacterMoodPlugin] 로드 완료 (widget=%s)", _widget_ref is not None)
    return {
        "message": "character_mood_plugin loaded",
        "has_widget": _widget_ref is not None,
        "moods": list(_MOOD_TABLE.keys()),
    }
