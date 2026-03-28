"""설정 관리 통합 모듈"""
import json
import logging
import os
import threading
from typing import Optional, Dict, Any


def _settings_path() -> str:
    from core.resource_manager import ResourceManager
    return ResourceManager.get_writable_path("ari_settings.json")


class ConfigManager:
    """설정 파일 관리 클래스"""

    SETTINGS_FILE = "ari_settings.json"
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
    }
    _cached_settings: Optional[Dict[str, Any]] = None
    # RLock: set_value → load_settings → save_settings 재진입 허용
    _lock: threading.RLock = threading.RLock()

    @classmethod
    def load_settings(cls) -> Dict[str, Any]:
        """설정 파일 로드. 캐시 적중 시 락 없이 반환(읽기 전용 사용 권장)."""
        if cls._cached_settings is not None:
            return cls._cached_settings
        with cls._lock:
            # 락 획득 후 재확인 (다른 스레드가 먼저 로드했을 수 있음)
            if cls._cached_settings is not None:
                return cls._cached_settings
            path = _settings_path()
            try:
                with open(path, "r", encoding="utf-8") as f:
                    settings = json.load(f)
                logging.info("설정 파일을 로드했습니다.")
                cls._cached_settings = {**cls.DEFAULT_SETTINGS, **settings}
            except FileNotFoundError:
                cls._cached_settings = cls._restore_default_settings(path)
            except json.JSONDecodeError as e:
                logging.error(f"설정 파일 파싱 오류: {e}")
                cls._cached_settings = cls.DEFAULT_SETTINGS.copy()
            except Exception as e:
                logging.error(f"설정 로드 중 예외 발생: {e}")
                cls._cached_settings = cls.DEFAULT_SETTINGS.copy()
            return cls._cached_settings

    @classmethod
    def _restore_default_settings(cls, dest_path: str) -> Dict[str, Any]:
        import sys, shutil
        if getattr(sys, 'frozen', False):
            bundle_src = os.path.join(sys._MEIPASS, cls.SETTINGS_FILE)
            if os.path.exists(bundle_src):
                try:
                    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                    shutil.copy2(bundle_src, dest_path)
                    logging.info("기본 설정 파일을 appdata로 복사했습니다.")
                    with open(dest_path, "r", encoding="utf-8") as f:
                        return {**cls.DEFAULT_SETTINGS, **json.load(f)}
                except Exception as e:
                    logging.warning(f"기본 설정 복사 실패: {e}")
        return cls.DEFAULT_SETTINGS.copy()

    @classmethod
    def save_settings(cls, settings: Dict[str, Any]) -> bool:
        """설정 파일 저장"""
        with cls._lock:
            path = _settings_path()
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(settings, f, indent=2, ensure_ascii=False)
                logging.info("설정을 저장했습니다.")
                cls._cached_settings = dict(settings)
                return True
            except Exception as e:
                logging.error(f"설정 저장 실패: {e}")
                return False

    @classmethod
    def get_value(cls, key: str, default: Any = None) -> Any:
        return cls.load_settings().get(key, default)

    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        return cls.get_value(key, default)

    @classmethod
    def set_value(cls, key: str, value: Any) -> bool:
        settings = dict(cls.load_settings())
        settings[key] = value
        return cls.save_settings(settings)
