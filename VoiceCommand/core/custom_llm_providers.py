"""사용자 지정 OpenAI 호환 제공자 메타데이터 검증."""

from __future__ import annotations

import re
from urllib.parse import urlsplit


_PROVIDER_ID = re.compile(r"custom_[0-9a-f]{32}\Z")
_CUSTOM_SECRET_KEY = re.compile(r"custom_[0-9a-f]{32}_api_key\Z")


def _valid_base_url(value: object) -> bool:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(c.isspace() for c in value)
    ):
        return False
    if "?" in value or "#" in value:
        return False
    try:
        parsed = urlsplit(value)
        _ = parsed.port
        return (
            parsed.scheme.lower() in {"http", "https"}
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not parsed.netloc.endswith(":")
        )
    except ValueError:
        return False


def get_custom_providers(settings: dict[str, object]) -> dict[str, dict[str, str]]:
    """유효한 제공자만 허용 필드로 반환한다."""
    metadata = settings.get("custom_llm_providers")
    if not isinstance(metadata, dict):
        return {}

    providers = {}
    for provider, details in metadata.items():
        if (
            not isinstance(provider, str)
            or not _PROVIDER_ID.fullmatch(provider)
            or not isinstance(details, dict)
        ):
            continue
        label = details.get("label")
        base_url = details.get("base_url")
        default_model = details.get("default_model")
        if (
            not isinstance(label, str)
            or not label.strip()
            or not _valid_base_url(base_url)
            or not isinstance(default_model, str)
        ):
            continue
        providers[provider] = {
            "label": label,
            "base_url": base_url,
            "default_model": default_model,
        }
    return providers


def custom_api_key_name(provider: str) -> str:
    if not isinstance(provider, str) or not _PROVIDER_ID.fullmatch(provider):
        raise ValueError("Invalid custom provider id")
    return f"{provider}_api_key"


def is_custom_secret_key(key: object) -> bool:
    return isinstance(key, str) and _CUSTOM_SECRET_KEY.fullmatch(key) is not None


def normalize_custom_provider_settings(settings: dict[str, object]) -> None:
    """잘못되거나 삭제된 사용자 제공자 선택을 되돌린다.

    기본 제공자는 groq로, 역할 제공자는 빈 값("기본 제공자와 동일")으로 돌린다.
    """
    providers = get_custom_providers(settings)
    if "custom_llm_providers" in settings:
        settings["custom_llm_providers"] = providers

    for provider_key, model_key, fallback in (
        ("llm_provider", "llm_model", "groq"),
        ("llm_planner_provider", "llm_planner_model", ""),
        ("llm_execution_provider", "llm_execution_model", ""),
    ):
        provider = settings.get(provider_key)
        if isinstance(provider, str) and provider.startswith("custom_") and provider not in providers:
            settings[provider_key] = fallback
            settings[model_key] = ""
