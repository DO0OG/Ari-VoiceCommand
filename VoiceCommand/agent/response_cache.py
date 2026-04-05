"""LLM 응답 캐시 유틸리티."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from typing import Optional


class ResponseCache:
    """최근 응답 캐시."""

    def __init__(self, max_items: int = 50, ttl_seconds: int = 600):
        self.max_items = max_items
        self.ttl_seconds = ttl_seconds
        self._store: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._lock = threading.RLock()

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
