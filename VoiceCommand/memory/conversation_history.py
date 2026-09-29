"""대화 기록 관리."""
import atexit
import json
import logging
import threading
from datetime import datetime, timedelta
from typing import List, Dict, Callable

from core.atomic_io import backup_corrupt_file, write_json_atomic

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
        self._compression_in_progress = False
        self._compression_thread: threading.Thread | None = None
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

    def delete_containing(self, text: str) -> int:
        """특정 문구가 포함된 대화와 요약을 삭제한다."""
        needle = str(text or "").strip().casefold()
        if not needle:
            return 0
        with self._lock:
            remaining = []
            deleted = 0
            for item in self.active:
                if isinstance(item, dict):
                    content = " ".join(
                        str(item.get(field, "") or "") for field in ("user", "ai")
                    )
                else:
                    content = str(item or "")
                if needle in content.casefold():
                    deleted += 1
                else:
                    remaining.append(item)
            summaries = []
            for summary in self.summaries:
                if needle in str(summary or "").casefold():
                    deleted += 1
                else:
                    summaries.append(summary)
            if deleted:
                self.active = remaining
                self.summaries = summaries
                self.save()
            return deleted

    def _compress_oldest(self):
        if len(self.active) <= self.MAX_ACTIVE:
            return
        if not hasattr(self, "_compression_in_progress"):
            self._compression_in_progress = False
        if not hasattr(self, "_compression_thread"):
            self._compression_thread = None
        if self._compression_in_progress:
            return
        to_compress = [dict(item) for item in self.active[:self.COMPRESS_UNIT]]
        self._compression_in_progress = True
        self._compression_thread = threading.Thread(
            target=self._compress_oldest_worker,
            args=(to_compress,),
            daemon=True,
            name="ConversationHistoryCompress",
        )
        self._compression_thread.start()

    def _compress_oldest_worker(self, to_compress: List[Dict[str, object]]) -> None:
        summary = self._summarize_chunk(to_compress)
        with self._lock:
            if self.active[:len(to_compress)] == to_compress:
                if summary:
                    self.summaries.append(summary)
                    self.summaries = self.summaries[-self.MAX_SUMMARIES:]
                self.active = self.active[len(to_compress):]
            self._compression_in_progress = False
            self._compression_thread = None
            needs_more = len(self.active) > self.MAX_ACTIVE
            self._schedule_save()
        if needs_more:
            with self._lock:
                self._compress_oldest()

    def compact_older_than(
        self,
        days: int,
        summarize_fn: Callable[[List[Dict[str, object]]], str],
    ) -> int:
        cutoff = datetime.now() - timedelta(days=days)
        with self._lock:
            snapshot = [dict(item) for item in self.active]
            old_items = []
            remaining = []
            for item in snapshot:
                try:
                    timestamp = datetime.fromisoformat(str(item.get("timestamp", "")))
                except (AttributeError, TypeError, ValueError):
                    remaining.append(item)
                    continue
                if timestamp < cutoff:
                    old_items.append(item)
                else:
                    remaining.append(item)

        if not old_items:
            return 0
        summary = summarize_fn(old_items)
        if not summary:
            return 0

        with self._lock:
            if self.active[:len(snapshot)] != snapshot:
                return 0
            self.summaries.append(summary)
            self.summaries = self.summaries[-self.MAX_SUMMARIES:]
            self.active = remaining + self.active[len(snapshot):]
            self.save()
            return len(old_items)

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

    def _estimate_tokens(self, messages: List[Dict[str, str]]) -> int:
        """대략적인 토큰 수를 계산한다(문자 수 ÷ 3)."""
        total = 0
        for message in messages:
            total += max(1, len(str(message.get("content", "") or "")) // 3)
        return total

    def get_messages_for_context(self, max_tokens: int = 8000) -> List[Dict[str, str]]:
        """토큰 예산 안에서 최신 대화부터 컨텍스트 메시지를 구성한다."""
        with self._lock:
            system_messages: List[Dict[str, str]] = []
            if self.summaries:
                combined = " | ".join(self.summaries[-3:])
                system_messages.append({
                    "role": "system",
                    "content": f"[이전 대화 요약] {combined}",
                })
            chronological: List[Dict[str, str]] = []
            for item in self.active:
                if item.get("user"):
                    chronological.append({"role": "user", "content": str(item["user"])})
                if item.get("ai"):
                    ai_content = str(item["ai"])
                    if len(ai_content) > 2000:
                        ai_content = f"[도구 결과 요약: {len(ai_content)}자]"
                    chronological.append({"role": "assistant", "content": ai_content})

        selected: List[Dict[str, str]] = []
        used = self._estimate_tokens(system_messages)
        for message in reversed(chronological):
            cost = self._estimate_tokens([message])
            if selected and used + cost > max_tokens:
                break
            selected.append(message)
            used += cost
        selected.reverse()
        return system_messages + selected

    def get_recent(self, n: int = 5):
        with self._lock:
            return self.active[-n:]

    def mark_last_response_interrupted(
        self,
        expected_response: str,
        interrupted_response: str,
    ) -> bool:
        """마지막 응답을 중단된 지점으로 갱신한다."""
        expected = str(expected_response or "").strip()
        replacement = str(interrupted_response or "").strip()
        if not replacement:
            return False
        with self._lock:
            for entry in reversed(self.active):
                if not isinstance(entry, dict):
                    continue
                response = str(entry.get("ai", "") or "")
                if expected and expected not in response:
                    continue
                entry["ai"] = replacement
                self._schedule_save()
                return True
        return False

    def _is_internal_entry(self, user_msg: str, ai_response: str) -> bool:
        del ai_response
        normalized = (user_msg or "").strip()
        return any(normalized.startswith(prefix) for prefix in _INTERNAL_USER_PREFIXES)

    def save(self):
        with self._lock:
            self._save_timer = None
            payload = {"active": self.active, "summaries": self.summaries}
            try:
                write_json_atomic(self.file_path, payload, ensure_ascii=False, indent=2)
            except (OSError, TypeError, ValueError) as exc:
                logging.error("대화 기록 저장 실패: %s", exc)

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
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                try:
                    backup_corrupt_file(self.file_path)
                except OSError as backup_error:
                    logging.error("손상된 대화 기록 백업 실패: %s", backup_error)
                self.active = []
                self.summaries = []
                logging.warning("대화 기록 JSON 로드 실패: %s", exc)
            except (OSError, TypeError, ValueError, AttributeError) as exc:
                logging.error("대화 기록 로드 실패: %s", exc)

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
            compression_thread = getattr(self, "_compression_thread", None)
        if timer is not None:
            timer.cancel()
        if compression_thread is not None and compression_thread.is_alive():
            compression_thread.join(timeout=2.0)
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
