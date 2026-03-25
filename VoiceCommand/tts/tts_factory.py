import logging
from core.config_manager import ConfigManager

_TTS_SIGNATURE_KEYS = (
    "tts_mode",
    "fish_api_key",
    "fish_reference_id",
    "cosyvoice_reference_text",
    "cosyvoice_speed",
    "openai_tts_api_key",
    "openai_api_key",
    "openai_tts_voice",
    "openai_tts_model",
    "elevenlabs_api_key",
    "elevenlabs_voice_id",
    "elevenlabs_model_id",
    "edge_tts_voice",
    "edge_tts_rate",
)


def build_tts_signature(settings=None):
    """현재 TTS 설정의 비교용 시그니처."""
    settings = settings or ConfigManager.load_settings()
    return tuple(settings.get(key) for key in _TTS_SIGNATURE_KEYS)


def create_tts_provider():
    """tts_mode 설정에 따라 적절한 TTS 제공자 인스턴스를 생성"""
    settings = ConfigManager.load_settings()
    tts_mode = settings.get("tts_mode", "fish")

    if tts_mode == "local":
        try:
            from tts.cosyvoice_tts import CosyVoiceTTS
            provider = CosyVoiceTTS(
                reference_text=settings.get("cosyvoice_reference_text", ""),
                speed=float(settings.get("cosyvoice_speed", 0.9)),
            )
            logging.info("CosyVoice3 로컬 TTS 초기화 완료")
            return provider, "local"
        except Exception as e:
            logging.error(f"CosyVoice3 초기화 실패, Fish Audio로 fallback: {e}")
            tts_mode = "fish"

    if tts_mode == "openai_tts":
        try:
            from tts.tts_openai import OpenAITTS
            provider = OpenAITTS(
                api_key=settings.get("openai_tts_api_key", "") or settings.get("openai_api_key", ""),
                voice=settings.get("openai_tts_voice", "nova"),
                model=settings.get("openai_tts_model", "tts-1"),
            )
            logging.info("OpenAI TTS 초기화 완료")
            return provider, "openai_tts"
        except Exception as e:
            logging.error(f"OpenAI TTS 초기화 실패, Fish Audio로 fallback: {e}")
            tts_mode = "fish"

    if tts_mode == "elevenlabs":
        try:
            from tts.tts_elevenlabs import ElevenLabsTTS
            provider = ElevenLabsTTS(
                api_key=settings.get("elevenlabs_api_key", ""),
                voice_id=settings.get("elevenlabs_voice_id", ""),
                model_id=settings.get("elevenlabs_model_id", "eleven_multilingual_v2"),
            )
            logging.info("ElevenLabs TTS 초기화 완료")
            return provider, "elevenlabs"
        except Exception as e:
            logging.error(f"ElevenLabs TTS 초기화 실패, Fish Audio로 fallback: {e}")
            tts_mode = "fish"

    if tts_mode == "edge":
        try:
            from tts.tts_edge import EdgeTTS
            provider = EdgeTTS(
                voice=settings.get("edge_tts_voice", "ko-KR-SunHiNeural"),
                rate=settings.get("edge_tts_rate", "+0%"),
            )
            logging.info("Edge TTS 초기화 완료")
            return provider, "edge"
        except Exception as e:
            logging.error(f"Edge TTS 초기화 실패, Fish Audio로 fallback: {e}")
            tts_mode = "fish"

    # 기본값: Fish Audio
    api_key = settings.get("fish_api_key", "")
    if not api_key:
        logging.warning("Fish API key가 설정되지 않았습니다")
    
    from tts.fish_tts_ws import FishTTSWebSocket
    provider = FishTTSWebSocket(
        api_key=api_key,
        reference_id=settings.get("fish_reference_id", "")
    )
    logging.info("Fish Audio TTS 초기화 완료")
    return provider, "fish"
