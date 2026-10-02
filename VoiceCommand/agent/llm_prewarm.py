"""현재 LLM 제공자의 연결을 백그라운드에서 예열한다."""

import logging
import threading
import time

_COOLDOWN_SECONDS = 5 * 60
_OPENAI_COMPATIBLE_PROVIDERS = frozenset({
    "gemini",
    "groq",
    "mistral",
    "nvidia_nim",
    "ollama",
    "openai",
    "openrouter",
})
_SUPPORTED_PROVIDERS = _OPENAI_COMPATIBLE_PROVIDERS | {"anthropic"}
_state_lock = threading.Lock()
_last_success_at: dict[tuple[str, str, str], float] = {}
_in_flight: set[tuple[str, str, str]] = set()


def _warm_client(key, client):
    try:
        from core.VoiceCommand import is_session_lock_blocked

        if is_session_lock_blocked():
            return
        client.models.list()
    except Exception as exc:
        logging.debug(
            "LLM 연결 예열 실패 (%s): %s", key[0], type(exc).__name__
        )
    else:
        with _state_lock:
            _last_success_at[key] = time.monotonic()
    finally:
        with _state_lock:
            _in_flight.discard(key)


def prewarm_current_llm_connection() -> bool:
    """설정과 잠금 상태를 확인한 뒤 예열 요청을 예약한다."""
    try:
        from core.config_manager import ConfigManager

        if not ConfigManager.get("llm_prewarm_enabled", True):
            return False

        from core.VoiceCommand import is_session_lock_blocked

        if is_session_lock_blocked():
            return False

        from agent.llm_provider import get_llm_provider

        llm_provider = get_llm_provider()
        if hasattr(llm_provider, "get_role_target"):
            client, provider, model = llm_provider.get_role_target("default")
        else:
            provider = getattr(llm_provider, "provider", "")
            model = getattr(llm_provider, "model", "")
            client = getattr(llm_provider, "client", None)
        provider_id = str(provider or "")
        if provider_id not in _SUPPORTED_PROVIDERS:
            return False

        model = str(model or "")
        if not client or not model:
            return False
        base_url = str(getattr(client, "base_url", "") or "")
        if not base_url:
            base_url = str(
                getattr(llm_provider, "provider_configs", {}).get(provider_id, {}).get("base_url", "") or ""
            )
        key = (provider_id, model, base_url)
        models = getattr(client, "models", None)
        list_models = getattr(models, "list", None)
        if not callable(list_models):
            return False

        now = time.monotonic()
        with _state_lock:
            last_success = _last_success_at.get(key)
            if (
                key in _in_flight
                or last_success is not None
                and now - last_success < _COOLDOWN_SECONDS
            ):
                return False
            _in_flight.add(key)

        try:
            thread = threading.Thread(
                target=_warm_client,
                args=(key, client),
                daemon=True,
            )
            thread.start()
        except RuntimeError as exc:
            with _state_lock:
                _in_flight.discard(key)
            logging.debug(
                "LLM 연결 예열 예약 실패 (%s): %s",
                provider_id,
                type(exc).__name__,
            )
            return False
        return True
    except Exception as exc:
        logging.debug("LLM 연결 예열을 생략했습니다: %s", type(exc).__name__)
        return False
