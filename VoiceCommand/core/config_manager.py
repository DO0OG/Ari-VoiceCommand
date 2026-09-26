"""설정 관리 통합 모듈."""
import copy
import json
import logging
import os
import threading
import tempfile
from pathlib import Path
from typing import Callable, Optional, cast

from core.settings_schema import (
    migrate_local_decision_settings,
    normalize_local_decision_settings,
    DEFAULT_SETTINGS as SETTINGS_DEFAULTS,
    SETTINGS_FILE as SETTINGS_FILENAME,
    SETTINGS_TEMPLATE_FILE as SETTINGS_TEMPLATE_FILENAME,
    SENSITIVE_SETTINGS_KEYS,
)
from core.secret_store import SecretStore, SecretStoreError
from core.custom_llm_providers import (
    custom_api_key_name,
    get_custom_providers,
    is_custom_secret_key,
    normalize_custom_provider_settings,
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
    _dotenv_settings: dict[str, str] = {}
    # RLock: set_value → load_settings → save_settings 재진입 허용
    _lock: threading.RLock = threading.RLock()

    @classmethod
    def load_settings(cls) -> SettingsDict:
        """설정 파일 로드. 캐시 적중 시 락 없이 반환(읽기 전용 사용 권장)."""
        if cls._cached_settings is not None:
            return cls._effective_settings()
        with cls._lock:
            # 락 획득 후 재확인 (다른 스레드가 먼저 로드했을 수 있음)
            if cls._cached_settings is not None:
                return cls._effective_settings()
            path = _settings_path()
            cls._load_dotenv(path)
            try:
                original = Path(path).read_bytes()
                settings = json.loads(original.decode("utf-8"))
                if not isinstance(settings, dict):
                    raise ValueError("Invalid settings object")
                logging.info("설정 파일을 로드했습니다.")
            except FileNotFoundError:
                settings = cls._restore_default_settings(path)
                original = b""
            except Exception:
                logging.error("설정 파일을 읽을 수 없어 기본값을 사용합니다.")
                settings = cls.DEFAULT_SETTINGS.copy()
                original = b""
            legacy = cls._secret_values(settings)
            public = cls._public_settings(settings)
            public_source = {key: value for key, value in settings.items() if not cls._is_secret_key(key)}
            public_changed = public != public_source
            has_secret_fields = any(cls._is_secret_key(key) for key in settings)
            store = SecretStore(path)
            store_readable = True
            try:
                stored = store.read()
            except SecretStoreError:
                logging.warning("Encrypted credentials unavailable; environment credentials remain usable")
                store_readable = False
                stored = {}
                legacy = {}
            else:
                merged = {**legacy, **stored}
                if original and (has_secret_fields or public_changed):
                    try:
                        if public_changed or any(cls._is_secret_key(key) and settings.get(key) for key in settings):
                            store.backup(original)
                        if merged != stored:
                            store.write(merged)
                        cls._write_public_settings(path, public)
                    except Exception:
                        logging.warning("Credential migration deferred; original settings preserved; use environment variables if encryption is unavailable")
                stored = merged
            cls._cached_settings = {**cls.DEFAULT_SETTINGS, **public, **stored}
            normalize_custom_provider_settings(cls._cached_settings)
            # 예전 파일은 병합된 기본값이 아니라 파일 자체의 버전으로 구분한다.
            cls._cached_settings["local_decision_settings_version"] = public.get("local_decision_settings_version")
            # 인증값이 아직 파일에 남아 있거나 암호화 저장소를 읽을 수 없으면 파일을 그대로 둔다.
            # 공개 사본에서 인증값이 빠질 수 있기 때문이다. 이때 변경은 이번 실행에만
            # 적용된다.
            if (
                migrate_local_decision_settings(cls._cached_settings)
                and original
                and store_readable
                and not any(cls._is_secret_key(key) for key in settings)
            ):
                try:
                    cls._write_public_settings(path, cls._cached_settings)
                    logging.info("로컬 판단 설정을 현재 기본 규칙으로 옮겼습니다.")
                except Exception:
                    logging.warning("로컬 판단 설정 이전을 저장하지 못해 이번 실행에만 적용합니다.")
            return cls._effective_settings()

    @staticmethod
    def _public_settings(settings: SettingsDict) -> SettingsDict:
        public = {key: value for key, value in settings.items() if not ConfigManager._is_secret_key(key)}
        if "custom_llm_providers" in public:
            public["custom_llm_providers"] = get_custom_providers(public)
        return public

    @staticmethod
    def _is_secret_key(key: object) -> bool:
        return key in SENSITIVE_SETTINGS_KEYS or is_custom_secret_key(key)

    @staticmethod
    def _secret_values(settings: SettingsDict) -> dict[str, str]:
        return {key: value for key, value in settings.items()
                if ConfigManager._is_secret_key(key) and isinstance(value, str) and value}

    @classmethod
    def _load_dotenv(cls, path: str) -> None:
        cls._dotenv_settings = {}
        try:
            from dotenv import dotenv_values
            values = dotenv_values(Path(path).with_name(".env"), interpolate=False)
            cls._dotenv_settings = {key: value for key, value in values.items() if value}
        except Exception:
            logging.warning("Runtime .env could not be read")

    @classmethod
    def _environment_secrets(cls, settings: Optional[SettingsDict] = None) -> dict[str, str]:
        keys = set(SENSITIVE_SETTINGS_KEYS)
        for provider in get_custom_providers(settings or cls._cached_settings or {}):
            keys.add(custom_api_key_name(provider))
        return {key: value for key in keys
                if (value := os.environ.get("ARI_" + key.upper())
                    or cls._dotenv_settings.get("ARI_" + key.upper()))}

    @classmethod
    def _effective_settings(cls) -> SettingsDict:
        return {**(cls._cached_settings or {}), **cls._environment_secrets(cls._cached_settings)}

    @classmethod
    def _restore_default_settings(cls, dest_path: str) -> SettingsDict:
        from core.resource_manager import ResourceManager

        template_src = ResourceManager.get_bundle_path(cls.SETTINGS_TEMPLATE_FILE)
        if os.path.exists(template_src):
            try:
                with open(template_src, "r", encoding="utf-8") as f:
                    settings = {**cls.DEFAULT_SETTINGS, **cast(ConfigManager.SettingsDict, json.load(f))}
                settings = cls._public_settings(settings)
                cls._write_public_settings(dest_path, settings)
                return settings
            except Exception:
                logging.warning("설정 템플릿을 복원할 수 없습니다.")
        return cls.DEFAULT_SETTINGS.copy()

    @classmethod
    def save_settings(cls, settings: SettingsDict) -> bool:
        """설정 파일 저장"""
        with cls._lock:
            path = _settings_path()
            try:
                requested = {key: value for key, value in settings.items() if cls._is_secret_key(key)}
                if any(not isinstance(value, str) for value in requested.values()):
                    raise SecretStoreError("Invalid credential type")
                normalized = cls._normalize_settings(settings)
                cls._load_dotenv(path)
                environment = cls._environment_secrets(normalized)
                requested = {key: value for key, value in requested.items()
                             if value != environment.get(key)}
                original = Path(path).read_bytes() if Path(path).exists() else b""
                previous = json.loads(original.decode("utf-8")) if original else {}
                legacy = cls._secret_values(previous)
                store = SecretStore(path)
                stored = store.read()
                updated = {**legacy, **stored}
                for key, value in requested.items():
                    if value:
                        updated[key] = value
                    else:
                        updated.pop(key, None)
                if "custom_llm_providers" in settings:
                    provider_ids = set(get_custom_providers(normalized))
                    for key in tuple(updated):
                        if is_custom_secret_key(key) and key[:-len("_api_key")] not in provider_ids:
                            updated.pop(key, None)
                if any(cls._is_secret_key(key) and previous.get(key) for key in previous):
                    store.backup(original)
                public = cls._public_settings(normalized)
                rollback = store.path.read_bytes() if store.path.exists() else None
                if updated != stored:
                    store.write(updated)
                try:
                    cls._write_public_settings(path, public)
                except Exception:
                    # 공개 설정 기록이 실패하면 비밀 저장소도 이전 상태로 되돌린다.
                    if updated != stored:
                        store.restore(rollback)
                    raise
                logging.info("설정을 저장했습니다.")
                cls._cached_settings = {**cls.DEFAULT_SETTINGS, **public, **updated}
                return True
            except Exception:
                logging.error("Settings save failed; existing files and encrypted backups were preserved")
                return False

    @classmethod
    def _write_public_settings(cls, path: str, settings: SettingsDict) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=os.path.dirname(path), delete=False) as f:
                temp_path = f.name
                json.dump(cls._public_settings(settings), f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, path)
            temp_path = None
        finally:
            if temp_path is not None:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    @classmethod
    def _normalize_settings(cls, settings: SettingsDict) -> SettingsDict:
        normalized = dict(settings)
        normalize_local_decision_settings(normalized)
        for key, expected in cls.DEFAULT_SETTINGS.items():
            if key not in normalized or expected is None:
                continue
            value = normalized[key]
            if isinstance(expected, bool):
                if not isinstance(value, bool):
                    logging.warning("[ConfigManager] bool 타입 불일치 무시: %s", key)
                    normalized[key] = copy.deepcopy(expected)
            elif isinstance(value, bool) or not isinstance(value, type(expected)):
                logging.warning("[ConfigManager] 타입 불일치 무시: %s", key)
                normalized[key] = copy.deepcopy(expected)
        normalize_custom_provider_settings(normalized)
        return normalized

    @classmethod
    def get_value(cls, key: str, default: object = None) -> object:
        return cls.load_settings().get(key, default)

    @classmethod
    def get(cls, key: str, default: object = None) -> object:
        return cls.get_value(key, default)

    @classmethod
    def set_value(cls, key: str, value: object) -> bool:
        return cls.update_settings(lambda settings: settings.update({key: value}))

    @classmethod
    def update_settings(cls, update: Callable[[SettingsDict], None]) -> bool:
        with cls._lock:
            settings = copy.deepcopy(cls.load_settings())
            update(settings)
            return cls.save_settings(settings)
