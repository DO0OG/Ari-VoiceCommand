"""메모리 정리 및 압축."""
from __future__ import annotations

import logging
import sqlite3
import threading
from datetime import date as date_type, datetime, time, timedelta

_CONVERSATION_INDEX_RETENTION_DAYS = 180
_DIGEST_RETENTION_DAYS = 90
_USER_ENTRY_PREFIX = "\uC0AC\uC6A9\uC790: "
_ASSISTANT_ENTRY_PREFIX = "\uC544\uB9AC: "
_OPTIONAL_SOURCE_ERRORS = (
    AttributeError, ImportError, OSError, RuntimeError, TypeError, ValueError
)


class MemoryConsolidator:
    def consolidate_facts(self):
        from memory.user_context import get_context_manager
        ctx = get_context_manager()
        ctx.optimize_memory()
        return len(ctx.context.get("facts", {}))

    def consolidate_strategies(self):
        from agent.strategy_memory import get_strategy_memory
        memory = get_strategy_memory()
        memory._prune()
        return len(memory._records)

    def summarize_old_conversations(self, days_ago: int = 14):
        from memory.conversation_history import get_conversation_history
        from memory.memory_index import get_memory_index

        history = get_conversation_history()
        compacted = history.compact_older_than(days_ago, history._summarize_chunk)
        get_memory_index().prune_conversations_older_than(
            _CONVERSATION_INDEX_RETENTION_DAYS
        )
        return compacted

    def collect_insights(self):
        from agent.episode_memory import get_episode_memory
        from agent.strategy_memory import get_strategy_memory

        repeated_failures = get_strategy_memory().get_repeated_failures(min_count=2)
        recent_failures = [
            episode for episode in get_episode_memory().get_recent_episodes(limit=10)
            if not episode.achieved
        ]
        return {
            "repeated_failures": repeated_failures[:3],
            "recent_failure_count": len(recent_failures),
        }

    def build_daily_digest(self, date: date_type | datetime | str) -> bool:
        try:
            from memory.memory_index import get_memory_index
            from i18n.translator import _, get_language

            if isinstance(date, datetime):
                target_day = date.date()
            elif isinstance(date, date_type):
                target_day = date
            else:
                target_day = date_type.fromisoformat(str(date)[:10])
            start = datetime.combine(target_day, time.min)
            end = datetime.combine(target_day, time.max)
            index = get_memory_index()
            indexed_rows = index.search_by_date(start, end)
            if any(
                getattr(row, "entry_type", "") == "digest"
                and self._is_timestamp_in_day(
                    getattr(row, "timestamp", ""), start, end
                )
                for row in indexed_rows
            ):
                return False

            records = []
            seen_conversations = set()
            for row in indexed_rows:
                if getattr(row, "entry_type", "") != "conversation":
                    continue
                content = str(getattr(row, "content", "") or "").strip()
                if not content or not self._is_timestamp_in_day(
                    getattr(row, "timestamp", ""), start, end
                ):
                    continue
                key = self._conversation_key(content)
                if key and key not in seen_conversations:
                    records.append(content)
                    seen_conversations.add(key)

            try:
                from memory.conversation_history import get_conversation_history

                history = get_conversation_history()
                for item in getattr(history, "active", []):
                    if not isinstance(item, dict) or not self._is_timestamp_in_day(
                        item.get("timestamp", ""), start, end
                    ):
                        continue
                    user = str(item.get("user", "") or "").strip()
                    assistant = str(item.get("ai", "") or "").strip()
                    content = (
                        f"{_USER_ENTRY_PREFIX}{user}\n"
                        f"{_ASSISTANT_ENTRY_PREFIX}{assistant}"
                    ).strip()
                    key = self._conversation_key(content)
                    if (user or assistant) and key not in seen_conversations:
                        records.append(content)
                        seen_conversations.add(key)
            except _OPTIONAL_SOURCE_ERRORS as exc:
                logging.debug("Daily digest conversation collection skipped: %s", exc)

            try:
                from agent.episode_memory import get_episode_memory

                episodes = get_episode_memory().get_recent_episodes(limit=120)
                for episode in episodes:
                    if not self._is_timestamp_in_day(
                        getattr(episode, "timestamp", ""), start, end
                    ):
                        continue
                    outcome = _("success") if getattr(episode, "achieved", False) else _("failure")
                    details = [
                        str(getattr(episode, "goal", "") or "").strip(),
                        str(getattr(episode, "summary", "") or "").strip(),
                    ]
                    details.extend(
                        str(getattr(episode, field, "") or "").strip()
                        for field in ("failure_kind", "state_change_summary", "policy_summary")
                    )
                    content = " | ".join(part for part in details if part)
                    if content:
                        records.append(
                            _("Episode ({outcome}): {content}").format(
                                outcome=outcome, content=content
                            )
                        )
            except _OPTIONAL_SOURCE_ERRORS as exc:
                logging.debug("Daily digest episode collection skipped: %s", exc)

            try:
                from memory.user_context import get_context_manager

                context = get_context_manager().context
                for command in context.get("last_commands", []):
                    if not isinstance(command, dict) or not self._is_timestamp_in_day(
                        command.get("timestamp", ""), start, end
                    ):
                        continue
                    content = " ".join(
                        part for part in (
                            str(command.get("command", "") or "").strip(),
                            str(command.get("params", "") or "").strip(),
                        ) if part
                    )
                    if content:
                        records.append(_("Local command: {content}").format(content=content))
            except _OPTIONAL_SOURCE_ERRORS as exc:
                logging.debug("Daily digest command collection skipped: %s", exc)

            try:
                from agent.proactive_scheduler import get_scheduler

                # ponytail: 날짜별 실행 기록 상한은 1000건; 더 많아지면 페이지 조회를 추가
                task_runs = get_scheduler().get_task_runs(
                    since=start, until=end, limit=1000
                )
                for run in task_runs:
                    if not self._is_timestamp_in_day(
                        run.get("finished_at", ""), start, end
                    ):
                        continue
                    content = " | ".join(
                        part for part in (
                            str(run.get("goal", "") or "").strip(),
                            str(run.get("summary", "") or "").strip(),
                            str(run.get("error", "") or "").strip(),
                        ) if part
                    )
                    if content:
                        outcome = _("success") if run.get("success") else _("failure")
                        records.append(
                            _("Scheduled run ({outcome}): {content}").format(
                                outcome=outcome, content=content
                            )
                        )
            except _OPTIONAL_SOURCE_ERRORS as exc:
                logging.debug("Daily digest scheduled run collection skipped: %s", exc)

            if not records:
                return False

            from memory.sensitive_patterns import is_sensitive_memory_text

            records = [
                record for record in records
                if not is_sensitive_memory_text(record)
            ]
            if not records:
                return False

            from agent.llm_provider import get_llm_provider

            provider = get_llm_provider()
            if (
                provider is None
                or not callable(getattr(provider, "chat", None))
                or not callable(getattr(provider, "_has_any_client", None))
                or not provider._has_any_client()
            ):
                return False
            keywords_label = _("Keywords:")
            prompt = _(
                "Create a daily digest for {date} in UI language {language}. "
                "Write 3-5 sentences, then a keyword line labeled {keywords_label}. "
                "Use only the records below."
            ).format(
                date=target_day.isoformat(),
                language=get_language(),
                keywords_label=keywords_label,
            )
            digest = str(provider.chat(
                f"{prompt}\n\n" + "\n".join(records),
                include_context=False,
                save_history=False,
                include_history=False,
            ) or "").strip()
            keywords = digest.partition(keywords_label)[2].strip()
            if (
                not digest
                or keywords_label not in digest
                or not keywords
                or is_sensitive_memory_text(digest)
            ):
                return False
            return bool(index.index_digest(target_day, digest))
        except Exception as exc:
            # 선택 기능 오류가 다른 기억 정리를 막지 않게 한다.
            logging.warning("Daily digest generation skipped: %s", exc)
            return False

    @staticmethod
    def _is_timestamp_in_day(value, start: datetime, end: datetime) -> bool:
        try:
            timestamp = datetime.fromisoformat(str(value))
        except (OverflowError, TypeError, ValueError):
            return False
        if timestamp.tzinfo is not None:
            timestamp = timestamp.astimezone().replace(tzinfo=None)
        return start <= timestamp <= end

    @staticmethod
    def _conversation_key(content: str) -> str:
        normalized = str(content or "")
        if normalized.startswith(_USER_ENTRY_PREFIX):
            normalized = normalized[len(_USER_ENTRY_PREFIX):]
        assistant_prefix = f"\n{_ASSISTANT_ENTRY_PREFIX}"
        normalized = normalized.replace(assistant_prefix, "\n", 1)
        return " ".join(normalized.split()).casefold()

    def run_all(self, days_ago: int = 14):
        result = {
            "facts": self.consolidate_facts(),
            "strategies": self.consolidate_strategies(),
            "conversations": self.summarize_old_conversations(days_ago=days_ago),
            "insights": self.collect_insights(),
        }
        self.build_daily_digest(datetime.now().date() - timedelta(days=1))
        try:
            from memory.memory_index import get_memory_index

            get_memory_index().prune_digests_older_than(days=_DIGEST_RETENTION_DAYS)
        except (ImportError, OSError, RuntimeError, sqlite3.Error, TypeError, ValueError) as exc:
            logging.warning("Old digest cleanup skipped: %s", exc)
        return result


_consolidator: MemoryConsolidator | None = None
_consolidator_lock = threading.Lock()


def get_memory_consolidator() -> MemoryConsolidator:
    global _consolidator
    if _consolidator is None:
        with _consolidator_lock:
            if _consolidator is None:
                _consolidator = MemoryConsolidator()
    return _consolidator
