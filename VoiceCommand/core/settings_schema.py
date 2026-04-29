"""설정 스키마와 템플릿 메타데이터."""

from __future__ import annotations

SETTINGS_FILE = "ari_settings.json"
SETTINGS_TEMPLATE_FILE = "ari_settings.template.json"

SENSITIVE_SETTINGS_KEYS = (
    "groq_api_key",
    "openai_api_key",
    "anthropic_api_key",
    "mistral_api_key",
    "gemini_api_key",
    "openrouter_api_key",
    "nvidia_nim_api_key",
    "fish_api_key",
    "fish_reference_id",
    "openai_tts_api_key",
    "elevenlabs_api_key",
)

DEFAULT_SETTINGS = {
    # ── LLM 제공자 ──────────────────────────────────────────────────────
    "llm_provider": "groq",
    "llm_model": "",
    "llm_planner_provider": "",   # 비워두면 기본 제공자와 동일
    "llm_planner_model": "",
    "llm_execution_provider": "",  # 비워두면 기본 제공자와 동일
    "llm_execution_model": "",
    "groq_api_key": "",
    "openai_api_key": "",
    "anthropic_api_key": "",
    "mistral_api_key": "",
    "gemini_api_key": "",
    "openrouter_api_key": "",
    "nvidia_nim_api_key": "",
    "ollama_base_url": "http://localhost:11434/v1",
    # ── TTS 제공자 ──────────────────────────────────────────────────────
    "tts_mode": "fish",            # fish | local | openai_tts | elevenlabs | edge
    "fish_api_key": "",
    "fish_reference_id": "",
    "cosyvoice_reference_text": "",
    "cosyvoice_speed": 0.9,
    "cosyvoice_dir": "",           # CosyVoice 설치 경로 (빈 값이면 자동 탐색)
    "openai_tts_api_key": "",
    "openai_tts_voice": "nova",    # alloy | echo | fable | onyx | nova | shimmer
    "openai_tts_model": "tts-1",   # tts-1 | tts-1-hd
    "elevenlabs_api_key": "",
    "elevenlabs_voice_id": "",
    "elevenlabs_model_id": "eleven_multilingual_v2",
    "edge_tts_voice": "ko-KR-SunHiNeural",
    "edge_tts_rate": "+0%",
    # ── 캐릭터 / RP ─────────────────────────────────────────────────────
    "personality": "",
    "scenario": "",
    "system_prompt": "",
    "history_instruction": "",
    # ── 기타 ────────────────────────────────────────────────────────────
    "microphone": "",
    "stt_provider": "google",
    "whisper_model": "small",
    "whisper_device": "auto",
    "whisper_compute_type": "int8",
    "wake_words": ["아리야", "시작"],
    "stt_energy_threshold": 300,
    "stt_dynamic_energy": True,
    "tts_speed": 1.0,
    "tts_volume": 1.0,
    "tts_fallback_provider": "edge",
    "ui_theme_preset": "default",
    "ui_theme_scale": 1.0,
    "ui_font_family": "",
    "language": "ko",               # 인터페이스 언어 (ko | en | ja)
    # ── 캐릭터 위젯 확장 기능 ────────────────────────────────────────────────
    "affinity_points": 0,
    "affinity_level": 0,
    "affinity_total_clicks": 0,
    "affinity_total_pets": 0,
    "affinity_total_chats": 0,
    "affinity_last_login": "",      # YYYY-MM-DD
    "focus_app_reaction_enabled": True,
    "system_monitor_enabled": True,
    "user_birthday": "",            # MM-DD
    "special_date_events_enabled": True,
    # ── AI 고도화 (Phase 1-5) ────────────────────────────────────────────
    "llm_router_enabled": True,          # LLMRouter 작업 유형별 자동 라우팅
    "agent_response_cache_ttl": 600,     # LLM 응답 캐시 만료 시간(초)
    "agent_response_cache_max_size": 50, # LLM 응답 캐시 최대 항목 수
    "few_shot_max_examples": 3,          # FewShotInjector 최대 예시 수
    "skill_library_enabled": True,       # SkillLibrary 성공 패턴 자동 추출
    "reflection_engine_enabled": True,   # ReflectionEngine 실패 자동 반성
    "memory_consolidation_days": 14,     # MemoryConsolidator 압축 기준 (일)
    "weekly_report_enabled": True,       # 주간 자기개선 리포트 (ProactiveScheduler 등록)
}

_TTS_VOICE_BY_LANG = {
    "ko": "ko-KR-SunHiNeural",
    "en": "en-US-JennyNeural",
    "ja": "ja-JP-NanamiNeural",
}


def get_default_edge_tts_voice() -> str:
    """언어 설정에 따른 기본 Edge TTS 음성을 반환한다."""
    try:
        from i18n.translator import get_language
        lang = get_language()
        return _TTS_VOICE_BY_LANG.get(lang, "ko-KR-SunHiNeural")
    except Exception:
        return "ko-KR-SunHiNeural"
