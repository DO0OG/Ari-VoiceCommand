"""설정 관리 통합 모듈"""
import json
import logging
import os
from typing import Optional, Dict, Any


def _settings_path() -> str:
    from resource_manager import ResourceManager
    return ResourceManager.get_writable_path("ari_settings.json")


class ConfigManager:
    """설정 파일 관리 클래스"""

    SETTINGS_FILE = "ari_settings.json"
    DEFAULT_SETTINGS = {
        # ── LLM 제공자 ──────────────────────────────────────────────────────
        "llm_provider": "groq",        # groq | openai | anthropic | mistral | gemini | openrouter
        "llm_model": "",               # 비워두면 제공자별 기본 모델 사용
        "groq_api_key": "",
        "openai_api_key": "",
        "anthropic_api_key": "",
        "mistral_api_key": "",
        "gemini_api_key": "",
        "openrouter_api_key": "",
        # ── TTS 제공자 ──────────────────────────────────────────────────────
        "tts_mode": "fish",            # fish | local | openai_tts | elevenlabs | edge
        "fish_api_key": "",
        "fish_reference_id": "",
        "cosyvoice_reference_text": "",
        "cosyvoice_speed": 0.9,
        "openai_tts_api_key": "",      # 비워두면 openai_api_key 공용
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
        "tts_speed": 1.0,
        "tts_volume": 1.0,
    }
    _cached_settings: Optional[Dict[str, Any]] = None

    @classmethod
    def load_settings(cls) -> Dict[str, Any]:
        """설정 파일 로드"""
        if cls._cached_settings is not None:
            return dict(cls._cached_settings)
        path = _settings_path()
        try:
            with open(path, "r", encoding="utf-8") as f:
                settings = json.load(f)
            logging.info("설정 파일을 로드했습니다.")
            cls._cached_settings = {**cls.DEFAULT_SETTINGS, **settings}
            return dict(cls._cached_settings)
        except FileNotFoundError:
            cls._cached_settings = cls._restore_default_settings(path)
            return dict(cls._cached_settings)
        except json.JSONDecodeError as e:
            logging.error(f"설정 파일 파싱 오류: {e}")
            cls._cached_settings = cls.DEFAULT_SETTINGS.copy()
            return dict(cls._cached_settings)
        except Exception as e:
            logging.error(f"설정 로드 중 예외 발생: {e}")
            cls._cached_settings = cls.DEFAULT_SETTINGS.copy()
            return dict(cls._cached_settings)

    @classmethod
    def _restore_default_settings(cls, dest_path: str) -> Dict[str, Any]:
        """기본 설정 복구. 기본적으로는 조용히 메모리 기본값을 사용한다."""
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
        """특정 설정 값 가져오기"""
        settings = cls.load_settings()
        return settings.get(key, default)

    @classmethod
    def set_value(cls, key: str, value: Any) -> bool:
        """특정 설정 값 저장"""
        settings = cls.load_settings()
        settings[key] = value
        return cls.save_settings(settings)
