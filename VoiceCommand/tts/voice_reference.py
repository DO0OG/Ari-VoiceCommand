"""TTS 제공자가 함께 쓰는 참조 WAV와 대본 경로."""

import os


def _settings(settings: dict | None) -> dict:
    if settings is not None:
        return settings
    try:
        from core.config_manager import ConfigManager

        return ConfigManager.load_settings()
    except (ImportError, OSError, TypeError, ValueError):
        return {}


def get_reference_wav(settings: dict | None = None) -> str:
    """사용자 지정 WAV를 우선하고, 없으면 기존 AppData/번들 규칙을 쓴다."""
    configured = str(_settings(settings).get("tts_reference_wav", "") or "").strip()
    if configured:
        return configured

    from core.resource_manager import ResourceManager

    appdata_path = ResourceManager.get_writable_path("reference.wav")
    if os.path.exists(appdata_path):
        return appdata_path
    return ResourceManager.get_bundle_path("reference.wav")


def get_reference_text(settings: dict | None = None) -> str:
    """기존 CosyVoice 참조 대본 설정을 공통으로 돌려준다."""
    return str(_settings(settings).get("cosyvoice_reference_text", "") or "")
