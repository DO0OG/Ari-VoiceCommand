"""설정 기반으로 TTS 제공자를 생성하고 서명을 계산하는 팩토리."""

import logging
import os
from core.config_manager import ConfigManager

_TTS_SIGNATURE_KEYS = (
    "tts_mode",
    "fish_api_key",
    "fish_reference_id",
    "cosyvoice_reference_text",
    "cosyvoice_speed",
    "cosyvoice_dir",
    "tts_reference_wav",
    "tts_volume",
    "openai_compat_tts_base_url",
    "openai_compat_tts_api_key",
    "openai_compat_tts_model",
    "openai_compat_tts_voice",
    "openai_compat_tts_clone_mode",
    "openai_compat_tts_emotion_mode",
    "fish_model",
    "openai_tts_api_key",
    "openai_api_key",
    "openai_tts_voice",
    "openai_tts_model",
    "openai_tts_custom_voice_id",
    "elevenlabs_api_key",
    "elevenlabs_voice_id",
    "elevenlabs_model_id",
    "edge_tts_voice",
    "edge_tts_rate",
    "tts_emotion_enabled",
    "tts_sentence_timeout_seconds",
    "tts_cache_max_bytes",
)


def build_tts_signature(settings=None):
    """현재 TTS 설정의 비교용 시그니처."""
    settings = settings or ConfigManager.load_settings()
    return tuple(settings.get(key) for key in _TTS_SIGNATURE_KEYS)


def create_tts_provider(settings=None):
    """tts_mode 설정에 따라 적절한 TTS 제공자 인스턴스를 생성"""
    settings = settings or ConfigManager.load_settings()
    tts_mode = settings.get("tts_mode", "edge")

    if tts_mode == "local":
        try:
            from tts.cosyvoice_tts import CosyVoiceTTS
            from tts.voice_reference import get_reference_text, get_reference_wav
            # 설정 화면에서 아직 저장하지 않은 경로로 시험 재생할 때도 그 경로를 쓴다.
            configured_dir = settings.get("cosyvoice_dir", "")
            provider = CosyVoiceTTS(
                reference_wav=get_reference_wav(settings),
                reference_text=get_reference_text(settings),
                speed=float(settings.get("cosyvoice_speed", 0.9)),
                cosyvoice_dir=configured_dir if configured_dir and os.path.isdir(configured_dir) else None,
            )
            logging.info("CosyVoice3 로컬 TTS 초기화 완료")
            return provider, "local"
        except Exception as e:
            logging.error(f"CosyVoice3 초기화 실패, Edge TTS로 fallback: {e}")
            tts_mode = "edge"

    if tts_mode == "openai_compat_tts":
        try:
            from i18n.translator import get_language
            from tts.tts_openai_compat import OpenAICompatTTS
            from tts.voice_reference import get_reference_text, get_reference_wav

            provider = OpenAICompatTTS(
                base_url=settings.get("openai_compat_tts_base_url", ""),
                api_key=settings.get("openai_compat_tts_api_key", ""),
                model=settings.get("openai_compat_tts_model", ""),
                voice=settings.get("openai_compat_tts_voice", ""),
                clone_mode=settings.get("openai_compat_tts_clone_mode", "none"),
                emotion_mode=settings.get("openai_compat_tts_emotion_mode", "instructions"),
                reference_wav=get_reference_wav(settings),
                reference_text=get_reference_text(settings),
                emotion_enabled=settings.get("tts_emotion_enabled", True),
                language=get_language(),
            )
            logging.info("OpenAI 호환 TTS 초기화 완료")
            return provider, "openai_compat_tts"
        except Exception as e:
            logging.error("OpenAI 호환 TTS 초기화 실패, Edge TTS로 fallback: %s", e)
            tts_mode = "edge"

    if tts_mode == "openai_tts":
        try:
            from tts.tts_openai import OpenAITTS
            provider = OpenAITTS(
                api_key=settings.get("openai_tts_api_key", "") or settings.get("openai_api_key", ""),
                voice=settings.get("openai_tts_voice", "nova"),
                model=settings.get("openai_tts_model", "tts-1"),
                emotion_enabled=settings.get("tts_emotion_enabled", True),
                custom_voice_id=settings.get("openai_tts_custom_voice_id", ""),
            )
            logging.info("OpenAI TTS 초기화 완료")
            return provider, "openai_tts"
        except Exception as e:
            logging.error(f"OpenAI TTS 초기화 실패, Edge TTS로 fallback: {e}")
            tts_mode = "edge"

    if tts_mode == "elevenlabs":
        try:
            from tts.tts_elevenlabs import ElevenLabsTTS
            provider = ElevenLabsTTS(
                api_key=settings.get("elevenlabs_api_key", ""),
                voice_id=settings.get("elevenlabs_voice_id", ""),
                model_id=settings.get("elevenlabs_model_id", "eleven_multilingual_v2"),
                emotion_enabled=settings.get("tts_emotion_enabled", True),
            )
            logging.info("ElevenLabs TTS 초기화 완료")
            return provider, "elevenlabs"
        except Exception as e:
            logging.error(f"ElevenLabs TTS 초기화 실패, Edge TTS로 fallback: {e}")
            tts_mode = "edge"

    if tts_mode == "fish":
        api_key = settings.get("fish_api_key", "")
        if api_key:
            try:
                from tts.fish_tts_ws import FishTTSWebSocket
                provider = FishTTSWebSocket(
                    api_key=api_key,
                    reference_id=settings.get("fish_reference_id", ""),
                    model=settings.get("fish_model", "s2.1-pro-free"),
                )
                logging.info("Fish Audio TTS 초기화 완료")
                return provider, "fish"
            except Exception as e:
                logging.error(f"Fish Audio TTS 초기화 실패, Edge TTS로 fallback: {e}")
                tts_mode = "edge"
        else:
            logging.warning("Fish API key가 없어 Edge TTS로 자동 전환합니다.")
            tts_mode = "edge"

    # 기본 및 Fallback: Edge TTS (무료 & 고품질)
    try:
        from tts.tts_edge import EdgeTTS
        provider = EdgeTTS(
            voice=settings.get("edge_tts_voice", "ko-KR-SunHiNeural"),
            rate=settings.get("edge_tts_rate", "+0%"),
            emotion_enabled=settings.get("tts_emotion_enabled", True),
            synthesis_timeout_seconds=settings.get("tts_sentence_timeout_seconds", 10),
            cache_max_bytes=settings.get("tts_cache_max_bytes", 50 * 1024 * 1024),
        )
        logging.info("Edge TTS 초기화 완료")
        return provider, "edge"
    except Exception as e:
        logging.error(f"Edge TTS 초기화 실패: {e}")
        raise
