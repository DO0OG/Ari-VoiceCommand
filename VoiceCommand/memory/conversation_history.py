"""대화 기록 관리."""
import json
import logging
from datetime import datetime
from typing import List, Dict


class ConversationHistory:
    """최근 대화와 압축 요약을 함께 관리한다."""

    MAX_ACTIVE = 20
    COMPRESS_UNIT = 5
    MAX_SUMMARIES = 5

    def __init__(self):
        from core.resource_manager import ResourceManager
        self.file_path = ResourceManager.get_writable_path("conversation_history.json")
        self.active: List[Dict[str, str]] = []
        self.summaries: List[str] = []
        self.load()

    def add(self, user_msg: str, ai_response: str):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "user": user_msg,
            "ai": ai_response,
        }
        self.active.append(entry)
        if len(self.active) > self.MAX_ACTIVE:
            self._compress_oldest()
        self.save()

    def _compress_oldest(self):
        if len(self.active) <= self.MAX_ACTIVE:
            return
        to_compress = self.active[:self.COMPRESS_UNIT]
        summary = self._summarize_chunk(to_compress)
        if summary:
            self.summaries.append(summary)
            self.summaries = self.summaries[-self.MAX_SUMMARIES:]
        self.active = self.active[self.COMPRESS_UNIT:]

    def _summarize_chunk(self, items: List[Dict[str, str]]) -> str:
        if not items:
            return ""
        parts = []
        for item in items:
            user = (item.get("user") or "").strip()
            ai = (item.get("ai") or "").strip()
            if not user and not ai:
                continue
            parts.append(f"U:{user[:80]} / A:{ai[:100]}")
        return " | ".join(parts[:5])

    def get_messages_for_llm(self) -> List[Dict[str, str]]:
        messages: List[Dict[str, str]] = []
        if self.summaries:
            combined = " | ".join(self.summaries[-3:])
            messages.append({
                "role": "system",
                "content": f"[이전 대화 요약] {combined}",
            })
        for item in self.active:
            if item.get("user"):
                messages.append({"role": "user", "content": item["user"]})
            if item.get("ai"):
                messages.append({"role": "assistant", "content": item["ai"]})
        return messages

    def get_recent(self, n: int = 5):
        return self.active[-n:]

    def save(self):
        payload = {"active": self.active, "summaries": self.summaries}
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"대화 기록 저장 실패: {e}")

    def load(self):
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, list):
                self.active = list(payload)[-self.MAX_ACTIVE:]
                self.summaries = []
            else:
                self.active = list(payload.get("active", []))[-self.MAX_ACTIVE:]
                self.summaries = list(payload.get("summaries", []))[-self.MAX_SUMMARIES:]
            logging.info(f"대화 기록 로드: active={len(self.active)}, summaries={len(self.summaries)}")
        except FileNotFoundError:
            logging.info("새 대화 기록 시작")
        except Exception as e:
            logging.error(f"대화 기록 로드 실패: {e}")


_history = ConversationHistory()


def add_conversation(user_msg, ai_response):
    _history.add(user_msg, ai_response)


def get_conversation_history() -> ConversationHistory:
    return _history
