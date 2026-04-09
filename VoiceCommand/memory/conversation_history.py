"""대화 기록 관리."""
import atexit
import json
import logging
import threading
from datetime import datetime
from typing import List, Dict, Optional

_INTERNAL_USER_PREFIXES = (
    "당신은 AI 에이전트 스킬을 Python 함수로 컴파일합니다.",
)


class ConversationHistory:
    """최근 대화와 압축 요약을 함께 관리한다."""

    MAX_ACTIVE = 20
    COMPRESS_UNIT = 5
    MAX_SUMMARIES = 5

    def __init__(self):
        from core.resource_manager import ResourceManager
        self.file_path = ResourceManager.get_writable_path("conversation_history.json")
        self.active: List[Dict[str, object]] = []
        self.summaries: List[str] = []
        self._lock = threading.RLock()
        self._save_timer: threading.Timer | None = None
        self._save_delay_seconds = 0.15
        self.load()

    def add(
        self,
        user_msg: str,
        ai_response: str,
        *,
        skill_used: str = "",
        data_source: str = "",
        lang: str = "",
    ):
        if self._is_internal_entry(user_msg, ai_response):
            return
        with self._lock:
            entry = {
                "timestamp": datetime.now().isoformat(),
                "user": user_msg,
                "ai": ai_response,
                "skill_used": skill_used,
                "data_source": data_source,
                "lang": lang,
            }
            self.active.append(entry)
            if len(self.active) > self.MAX_ACTIVE:
                self._compress_oldest()
            self._schedule_save()

    def _compress_oldest(self):
        if len(self.active) <= self.MAX_ACTIVE:
            return
        to_compress = self.active[:self.COMPRESS_UNIT]
        summary = self._summarize_chunk(to_compress)
        if summary:
            self.summaries.append(summary)
            self.summaries = self.summaries[-self.MAX_SUMMARIES:]
        self.active = self.active[self.COMPRESS_UNIT:]

    def _summarize_chunk(self, items: List[Dict[str, object]]) -> str:
        if not items:
            return ""
        fallback = self._fallback_summarize(items)
        if not fallback:
            return ""
        try:
            from agent.llm_provider import get_llm_provider

            transcript = "\n".join(
                f"사용자: {(item.get('user') or '').strip()}\n아리: {(item.get('ai') or '').strip()}"
                for item in items
                if (item.get("user") or "").strip() or (item.get("ai") or "").strip()
            ).strip()
            if not transcript:
                return fallback
            summary = get_llm_provider().chat(
                "다음 대화를 핵심만 2문장으로 요약하세요. "
                "불필요한 수식어 없이 한국어로만 답하고, 가능하면 사용자의 요청과 아리의 핵심 응답을 함께 보존하세요.\n\n"
                f"{transcript}",
                include_context=False,
                save_history=False,
            )
            cleaned = str(summary or "").strip()
            return cleaned or fallback
        except Exception as exc:
            logging.debug("대화 요약 LLM 폴백 사용: %s", exc)
            return fallback

    def _fallback_summarize(self, items: List[Dict[str, object]]) -> str:
        parts = []
        for item in items:
            user = (item.get("user") or "").strip()
            ai = (item.get("ai") or "").strip()
            if not user and not ai:
                continue
            user_summary = self._extract_key_text(user, 60)
            ai_summary = self._extract_key_text(ai, 80)
            parts.append(f"Q:{user_summary} → A:{ai_summary}")
        if not parts:
            return ""
        return f"[대화요약 {len(parts)}건] " + " | ".join(parts[:4])

    def _extract_key_text(self, text: str, max_len: int) -> str:
        """첫 문장 또는 의미 단위 추출 — 단순 truncation 대신 문장 경계 우선."""
        text = (text or "").strip()
        if not text:
            return ""
        for sep in ("。", ". ", "? ", "! ", ".\n", "?\n", "!\n"):
            idx = text.find(sep)
            if 0 < idx < max_len:
                candidate = text[: idx + len(sep)].strip()
                if len(candidate) >= 4:
                    return candidate
        if len(text) <= max_len:
            return text
        truncated = text[:max_len]
        last_space = truncated.rfind(" ")
        if last_space > max_len // 2:
            return truncated[:last_space] + "…"
        return truncated + "…"

    def get_messages_for_llm(self) -> List[Dict[str, str]]:
        with self._lock:
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
        with self._lock:
            return self.active[-n:]

    def _is_internal_entry(self, user_msg: str, ai_response: str) -> bool:
        del ai_response
        normalized = (user_msg or "").strip()
        return any(normalized.startswith(prefix) for prefix in _INTERNAL_USER_PREFIXES)

    def save(self):
        with self._lock:
            self._save_timer = None
            payload = {"active": self.active, "summaries": self.summaries}
            try:
                with open(self.file_path, "w", encoding="utf-8") as f:
                    json.dump(payload, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logging.error("대화 기록 저장 실패: %s", e)

    def load(self):
        with self._lock:
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                if isinstance(payload, list):
                    self.active = list(payload)[-self.MAX_ACTIVE:]
                    self.summaries = []
                else:
                    self.active = list(payload.get("active", []))[-self.MAX_ACTIVE:]
                    self.summaries = list(payload.get("summaries", []))[-self.MAX_SUMMARIES:]
                self.active = [
                    item for item in self.active
                    if not self._is_internal_entry(item.get("user", ""), item.get("ai", ""))
                ][-self.MAX_ACTIVE:]
                logging.info(
                    "대화 기록 로드: active=%s, summaries=%s",
                    len(self.active),
                    len(self.summaries),
                )
            except FileNotFoundError:
                logging.info("새 대화 기록 시작")
            except Exception as e:
                logging.error("대화 기록 로드 실패: %s", e)

    def _schedule_save(self) -> None:
        with self._lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
            self._save_timer = threading.Timer(self._save_delay_seconds, self.save)
            self._save_timer.daemon = True
            self._save_timer.start()

    def flush(self) -> None:
        with self._lock:
            timer = self._save_timer
            self._save_timer = None
        if timer is not None:
            timer.cancel()
        self.save()


_history = ConversationHistory()


def add_conversation(
    user_msg,
    ai_response,
    *,
    skill_used: str = "",
    data_source: str = "",
    lang: str = "",
):
    _history.add(
        user_msg,
        ai_response,
        skill_used=skill_used,
        data_source=data_source,
        lang=lang,
    )


def get_conversation_history() -> ConversationHistory:
    return _history


atexit.register(_history.flush)
