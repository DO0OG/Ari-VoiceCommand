"""사실 기억 제안을 원자적으로 보관한다."""

import hashlib
import json
import logging
import os
import threading
from datetime import datetime

from core.atomic_io import backup_corrupt_file, write_json_atomic

_MAX_SUGGESTIONS = 100
_MAX_SEEN_IDS = 500
_SUGGESTION_TYPES = {"fact", "preference"}


class FactSuggestionStore:
    """승인 전 기억 제안과 처리 수를 관리한다."""

    def __init__(self, path: str | None = None):
        if path is None:
            from core.resource_manager import ResourceManager

            path = ResourceManager.get_writable_path("fact_suggestions.json")
        self.path = os.fspath(path)
        self._lock = threading.RLock()
        self._data = self._load()

    def _empty(self) -> dict:
        return {"suggestions": [], "seen_ids": [], "approved": 0, "rejected": 0}

    def _load(self) -> dict:
        if not os.path.exists(self.path):
            return self._empty()
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                raw = json.load(handle)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            try:
                backup_corrupt_file(self.path)
            except OSError as backup_error:
                logging.warning("손상된 제안 파일 백업 실패: %s", backup_error)
            logging.warning("제안 파일을 읽지 못했습니다: %s", exc)
            return self._empty()
        except (OSError, TypeError, ValueError) as exc:
            logging.warning("제안 파일을 읽지 못했습니다: %s", exc)
            return self._empty()

        if not isinstance(raw, dict):
            return self._empty()
        data = self._empty()
        suggestions = raw.get("suggestions", [])
        if isinstance(suggestions, list):
            for item in suggestions[-_MAX_SUGGESTIONS:]:
                normalized = self._normalize(item)
                if normalized:
                    data["suggestions"].append(normalized)
        seen_ids = raw.get("seen_ids", [])
        if isinstance(seen_ids, list):
            data["seen_ids"] = [
                value for value in seen_ids[-_MAX_SEEN_IDS:] if isinstance(value, str)
            ]
        for key in ("approved", "rejected"):
            try:
                data[key] = max(0, int(raw.get(key, 0)))
            except (TypeError, ValueError, OverflowError):
                pass
        return data

    @staticmethod
    def _identity(item: dict) -> str:
        identity = "\0".join(
            str(item.get(key, ""))
            for key in ("type", "key", "value", "kind")
        )
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()

    def _normalize(self, item: object) -> dict | None:
        if not isinstance(item, dict):
            return None
        suggestion_type = item.get("type")
        if not isinstance(suggestion_type, str) or suggestion_type not in _SUGGESTION_TYPES:
            return None
        key = str(item.get("key", "")).strip()[:80]
        value = str(item.get("value", "")).strip()[:300]
        evidence = str(item.get("evidence", "")).strip()[:60]
        kind = str(item.get("kind", "")).strip()
        valid_kind = (
            kind in {"stable", "state", "plan"}
            if suggestion_type == "fact"
            else kind == ""
        )
        if not key or not value or not evidence or not valid_kind:
            return None
        try:
            confidence = float(item.get("confidence", 0.8))
        except (TypeError, ValueError, OverflowError):
            return None
        if not 0.0 <= confidence <= 1.0:
            return None
        normalized = {
            "type": suggestion_type,
            "key": key,
            "value": value,
            "kind": kind,
            "evidence": evidence,
            "confidence": confidence,
            "created_at": str(item.get("created_at", "")) or datetime.now().isoformat(),
        }
        normalized["id"] = self._identity(normalized)
        return normalized

    def _save(self) -> bool:
        try:
            write_json_atomic(self.path, self._data, ensure_ascii=False, indent=2)
        except (OSError, TypeError, ValueError) as exc:
            logging.warning("제안 파일 저장 실패: %s", exc)
            return False
        return True

    def add_suggestions(self, suggestions: list[dict]) -> int:
        with self._lock:
            previous = self._data
            current = self._data["suggestions"]
            seen = set(self._data["seen_ids"])
            seen.update(item["id"] for item in current)
            added = []
            for candidate in suggestions:
                normalized = self._normalize(candidate)
                if not normalized or normalized["id"] in seen:
                    continue
                added.append(normalized)
                seen.add(normalized["id"])
            if not added:
                return 0
            self._data = {
                **self._data,
                "suggestions": (current + added)[-_MAX_SUGGESTIONS:],
                "seen_ids": list(
                    dict.fromkeys(
                        self._data["seen_ids"]
                        + [item["id"] for item in added]
                    )
                )[-_MAX_SEEN_IDS:],
            }
            if not self._save():
                self._data = previous
                return 0
            return len(added)

    def get_suggestions(self) -> list[dict]:
        with self._lock:
            return [dict(item) for item in self._data["suggestions"]]

    def get_suggestion(self, suggestion_id: str) -> dict | None:
        with self._lock:
            for item in self._data["suggestions"]:
                if item["id"] == suggestion_id:
                    return dict(item)
        return None

    def get_stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "approved": self._data["approved"],
                "rejected": self._data["rejected"],
            }

    def resolve(self, suggestion_id: str, approved: bool) -> dict | None:
        with self._lock:
            previous = self._data
            selected = next(
                (
                    item for item in self._data["suggestions"]
                    if item["id"] == suggestion_id
                ),
                None,
            )
            if selected is None:
                return None
            remaining = [
                item for item in self._data["suggestions"]
                if item["id"] != suggestion_id
            ]
            decision = "approved" if approved else "rejected"
            seen_ids = list(
                dict.fromkeys(self._data["seen_ids"] + [suggestion_id])
            )[-_MAX_SEEN_IDS:]
            self._data = {
                **self._data,
                "suggestions": remaining,
                "seen_ids": seen_ids,
                decision: self._data[decision] + 1,
            }
            if not self._save():
                self._data = previous
                return None
            return dict(selected)


_store: FactSuggestionStore | None = None
_store_lock = threading.Lock()


def get_fact_suggestion_store() -> FactSuggestionStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = FactSuggestionStore()
    return _store
