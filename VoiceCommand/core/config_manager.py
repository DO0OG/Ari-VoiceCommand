"""설정 관리 통합 모듈."""
import copy
import json
import logging
import os
import threading
import shutil
from typing import Optional, cast

from core.settings_schema import (
    DEFAULT_SETTINGS as SETTINGS_DEFAULTS,
    SETTINGS_FILE as SETTINGS_FILENAME,
    SETTINGS_TEMPLATE_FILE as SETTINGS_TEMPLATE_FILENAME,
)


def _settings_path() -> str:
    from core.resource_manager import ResourceManager
    return ResourceManager.get_writable_path(SETTINGS_FILENAME)


class ConfigManager:
    """설정 파일 관리 클래스"""

    SettingsDict = dict[str, object]

    SETTINGS_FILE = SETTINGS_FILENAME
    SETTINGS_TEMPLATE_FILE = SETTINGS_TEMPLATE_FILENAME
    DEFAULT_SETTINGS = SETTINGS_DEFAULTS
    _cached_settings: Optional[SettingsDict] = None
    # RLock: set_value → load_settings → save_settings 재진입 허용
    _lock: threading.RLock = threading.RLock()

    @classmethod
    def load_settings(cls) -> SettingsDict:
        """설정 파일 로드. 캐시 적중 시 락 없이 반환(읽기 전용 사용 권장)."""
        if cls._cached_settings is not None:
            return dict(cls._cached_settings)
        with cls._lock:
            # 락 획득 후 재확인 (다른 스레드가 먼저 로드했을 수 있음)
            if cls._cached_settings is not None:
                return dict(cls._cached_settings)
            path = _settings_path()
            try:
                with open(path, "r", encoding="utf-8") as f:
                    settings = cast(ConfigManager.SettingsDict, json.load(f))
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
            return dict(cls._cached_settings)

    @classmethod
    def _restore_default_settings(cls, dest_path: str) -> SettingsDict:
        from core.resource_manager import ResourceManager

        template_src = ResourceManager.get_bundle_path(cls.SETTINGS_TEMPLATE_FILE)
        if os.path.exists(template_src):
            try:
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                shutil.copy2(template_src, dest_path)
                logging.info("설정 템플릿을 사용자 런타임 경로로 복사했습니다.")
                with open(dest_path, "r", encoding="utf-8") as f:
                    return {**cls.DEFAULT_SETTINGS, **cast(ConfigManager.SettingsDict, json.load(f))}
            except Exception as e:
                logging.warning(f"설정 템플릿 복사 실패: {e}")
        return cls.DEFAULT_SETTINGS.copy()

    @classmethod
    def save_settings(cls, settings: SettingsDict) -> bool:
        """설정 파일 저장"""
        with cls._lock:
            path = _settings_path()
            try:
                normalized = cls._normalize_settings(settings)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(normalized, f, indent=2, ensure_ascii=False)
                logging.info("설정을 저장했습니다.")
                cls._cached_settings = dict(normalized)
                return True
            except Exception as e:
                logging.error(f"설정 저장 실패: {e}")
                return False

    @classmethod
    def _normalize_settings(cls, settings: SettingsDict) -> SettingsDict:
        normalized = dict(settings)
        for key, expected in cls.DEFAULT_SETTINGS.items():
            if key not in normalized or expected is None:
                continue
            value = normalized[key]
            if type(value) is not type(expected):
                logging.warning("[ConfigManager] 타입 불일치 무시: %s=%r", key, value)
                normalized[key] = copy.deepcopy(expected)
        return normalized

    @classmethod
    def get_value(cls, key: str, default: object = None) -> object:
        return cls.load_settings().get(key, default)

    @classmethod
    def get(cls, key: str, default: object = None) -> object:
        return cls.get_value(key, default)

    @classmethod
    def set_value(cls, key: str, value: object) -> bool:
        settings = dict(cls.load_settings())
        settings[key] = value
        return cls.save_settings(settings)
