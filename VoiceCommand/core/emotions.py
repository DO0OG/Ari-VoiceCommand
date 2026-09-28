"""감정 태그와 표현 매핑의 단일 정의."""

import re


EMOTION_CATALOG = {
    "기쁨": {
        "aliases": ("happy", "joy", "嬉しい", "喜び"),
        "emoji": "😊",
        "animations": ("walk", "idle"),
        "jump": True,
        "pet": True,
        "cosyvoice": "bright",
        "edge_rate": 5,
        "edge_pitch": 3,
        "openai": "Speak with a cheerful, upbeat tone.",
        "elevenlabs": (-0.05, 0.08),
    },
    "슬픔": {
        "aliases": ("sad", "sadness", "悲しい", "悲しみ"),
        "emoji": "😭",
        "animations": ("sit", "sleep"),
        "cosyvoice": "sad",
        "edge_rate": -5,
        "edge_pitch": -2,
        "openai": "Speak gently with a subdued, sympathetic tone.",
        "elevenlabs": (0.04, 0.02),
    },
    "화남": {
        "aliases": ("angry", "anger", "怒り", "怒った"),
        "emoji": "💢",
        "animations": ("surprised",),
        "cosyvoice": "bright",
        "edge_rate": 3,
        "edge_pitch": 1,
        "openai": "Speak with restrained frustration.",
        "elevenlabs": (-0.04, 0.06),
    },
    "놀람": {
        "aliases": ("surprised", "surprise", "驚き", "びっくり"),
        "emoji": "😲",
        "animations": ("surprised",),
        "cosyvoice": "surprised",
        "edge_rate": 3,
        "edge_pitch": 2,
        "openai": "Speak with a lightly surprised tone.",
        "elevenlabs": (-0.04, 0.06),
    },
    "평온": {
        "aliases": ("calm", "neutral", "serene", "穏やか", "平穏"),
        "emoji": "☕",
        "animations": ("idle", "sit"),
        "default": True,
        "cosyvoice": "neutral",
        "edge_rate": 0,
        "edge_pitch": 0,
        "openai": "Speak in a calm, neutral tone.",
        "elevenlabs": (0.0, 0.0),
    },
    "수줍": {
        "aliases": ("shy", "embarrassed", "照れ", "恥ずかしい"),
        "emoji": "☺️",
        "animations": ("sit", "idle"),
        "pet": True,
        "cosyvoice": "shy",
        "edge_rate": -2,
        "edge_pitch": -1,
        "openai": "Speak softly and a little bashfully.",
        "elevenlabs": (0.02, 0.04),
    },
    "기대": {
        "aliases": ("excited", "anticipation", "期待", "楽しみ"),
        "emoji": "✨",
        "animations": ("walk", "idle"),
        "jump": True,
        "cosyvoice": "bright",
        "edge_rate": 5,
        "edge_pitch": 3,
        "openai": "Speak with restrained anticipation.",
        "elevenlabs": (-0.05, 0.08),
    },
    "진지": {
        "aliases": ("serious", "focused", "seriousness", "真剣"),
        "emoji": "🧐",
        "animations": ("sit",),
        "cosyvoice": "neutral",
        "edge_rate": -3,
        "edge_pitch": 0,
        "openai": "Speak in a measured, serious tone.",
        "elevenlabs": (0.06, 0.02),
    },
    "걱정": {
        "aliases": ("worried", "worry", "anxious", "心配", "不安"),
        "emoji": "😟",
        "animations": ("sit", "idle"),
        "cosyvoice": "sad",
        "edge_rate": -5,
        "edge_pitch": -2,
        "openai": "Speak gently with concern.",
        "elevenlabs": (0.04, 0.02),
    },
}

DEFAULT_EMOTION = next(
    name for name, details in EMOTION_CATALOG.items() if details.get("default")
)
EMOTION_NAMES = tuple(EMOTION_CATALOG)
EMOTION_ALIASES = {
    alias.casefold(): name
    for name, details in EMOTION_CATALOG.items()
    for alias in (name, *details["aliases"])
}
_EMOTION_PATTERN_NAMES = "|".join(
    sorted((re.escape(name) for name in EMOTION_ALIASES), key=len, reverse=True)
)
EMOTION_PATTERN = re.compile(rf"[\(\[]({_EMOTION_PATTERN_NAMES})[\)\]]", re.IGNORECASE)
EMOTION_EMOJI = {
    name: details["emoji"] for name, details in EMOTION_CATALOG.items()
}
PET_EMOTIONS = tuple(
    name for name, details in EMOTION_CATALOG.items() if details.get("pet")
)

_EMOTION_TAGS = " ".join(f"({name})" for name in EMOTION_NAMES)
_EMOTION_INSTRUCTIONS = {
    "ko": "[감정 표현]\n응답 맨 앞에 감정 태그를 자연스럽게 붙이세요: " + _EMOTION_TAGS,
    "en": "[Emotion Tags]\nStart your response with a Korean emotion tag: " + _EMOTION_TAGS,
    "ja": "[感情タグ]\n返答の先頭に韓国語の感情タグを付けてください: " + _EMOTION_TAGS,
}


def normalize_emotion(emotion: str | None) -> str:
    """감정 별칭을 표준 태그로 바꾼다."""
    if not emotion:
        return DEFAULT_EMOTION
    return EMOTION_ALIASES.get(str(emotion).casefold(), DEFAULT_EMOTION)


def get_emotion_details(emotion: str | None) -> dict:
    """표준 태그의 표현 설정을 반환한다."""
    return EMOTION_CATALOG[normalize_emotion(emotion)]


def get_emotion_instruction(language: str) -> str:
    """언어별 감정 태그 지시문을 반환한다."""
    return _EMOTION_INSTRUCTIONS.get(language, _EMOTION_INSTRUCTIONS["ko"])


def parse_emotion_text(text: str) -> tuple[str, str]:
    """첫 감정 태그를 고르고 알려진 태그를 문장에서 제거한다."""
    text = text or ""
    match = EMOTION_PATTERN.search(text)
    emotion = normalize_emotion(match.group(1)) if match else DEFAULT_EMOTION
    pure_text = EMOTION_PATTERN.sub("", text)
    pure_text = re.sub(r"\s+", " ", pure_text).strip()
    return emotion, pure_text
