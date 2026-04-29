"""LLM 응답 캐시 유틸리티."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from typing import Optional


DEFAULT_RESPONSE_CACHE_MAX_ITEMS = 50
DEFAULT_RESPONSE_CACHE_TTL_SECONDS = 600


def _coerce_positive_int(value: object, default: int) -> int:
    try:
        coerced = int(value)
    except (TypeError, ValueError):
        return default
    return coerced if coerced > 0 else default


class ResponseCache:
    """최근 응답 캐시."""

    def __init__(
        self,
        max_items: int = DEFAULT_RESPONSE_CACHE_MAX_ITEMS,
        ttl_seconds: int = DEFAULT_RESPONSE_CACHE_TTL_SECONDS,
    ):
        self.max_items = _coerce_positive_int(max_items, DEFAULT_RESPONSE_CACHE_MAX_ITEMS)
        self.ttl_seconds = _coerce_positive_int(ttl_seconds, DEFAULT_RESPONSE_CACHE_TTL_SECONDS)
        self._store: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._lock = threading.RLock()

    @classmethod
    def from_config(cls) -> "ResponseCache":
        """ConfigManager 설정에서 캐시 크기와 TTL을 읽어 생성한다.

        기존 설정 파일 구조는 flat key를 사용하므로 `agent_response_cache_*`
        값을 우선 지원하고, 이후 nested `agent.response_cache_*` 형태가 들어와도
        동일하게 동작하도록 허용한다.
        """
        try:
            from core.config_manager import ConfigManager

            settings = ConfigManager.load_settings()
        except Exception:
            settings = {}

        agent_settings = settings.get("agent", {})
        if not isinstance(agent_settings, dict):
            agent_settings = {}

        ttl = settings.get(
            "agent_response_cache_ttl",
            agent_settings.get("response_cache_ttl", DEFAULT_RESPONSE_CACHE_TTL_SECONDS),
        )
        max_items = settings.get(
            "agent_response_cache_max_size",
            agent_settings.get("response_cache_max_size", DEFAULT_RESPONSE_CACHE_MAX_ITEMS),
        )
        return cls(max_items=max_items, ttl_seconds=ttl)

    def get(self, cache_key: str) -> Optional[str]:
        with self._lock:
            item = self._store.get(cache_key)
            if not item:
                return None
            saved_at, response = item
            if time.time() - saved_at > self.ttl_seconds:
                self._store.pop(cache_key, None)
                return None
            self._store.move_to_end(cache_key)
            return response

    def set(self, cache_key: str, response: str) -> None:
        with self._lock:
            self._store[cache_key] = (time.time(), response)
            self._store.move_to_end(cache_key)
            while len(self._store) > self.max_items:
                self._store.popitem(last=False)


def build_response_cache_key(
    message: str,
    *,
    provider: str,
    model: str,
    system_prompt: str,
    personality: str,
    scenario: str,
    history_instruction: str,
    include_context: bool,
) -> str:
    payload = {
        "message": message,
        "provider": provider,
        "model": model,
        "system_prompt": system_prompt,
        "personality": personality,
        "scenario": scenario,
        "history_instruction": history_instruction,
        "include_context": include_context,
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
