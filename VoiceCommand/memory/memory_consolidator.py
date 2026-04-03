"""메모리 정리 및 압축."""
from __future__ import annotations

from datetime import datetime, timedelta


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
        history = get_conversation_history()
        cutoff = datetime.now() - timedelta(days=days_ago)
        remaining = []
        old_items = []
        for item in history.active:
            try:
                timestamp = datetime.fromisoformat(item.get("timestamp", ""))
            except Exception:
                remaining.append(item)
                continue
            if timestamp < cutoff:
                old_items.append(item)
            else:
                remaining.append(item)
        if old_items:
            summary = history._summarize_chunk(old_items)
            if summary:
                history.summaries.append(summary)
                history.summaries = history.summaries[-history.MAX_SUMMARIES:]
        history.active = remaining[-history.MAX_ACTIVE:]
        history.save()
        return len(old_items)

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

    def run_all(self, days_ago: int = 14):
        return {
            "facts": self.consolidate_facts(),
            "strategies": self.consolidate_strategies(),
            "conversations": self.summarize_old_conversations(days_ago=days_ago),
            "insights": self.collect_insights(),
        }


_consolidator: MemoryConsolidator | None = None


def get_memory_consolidator() -> MemoryConsolidator:
    global _consolidator
    if _consolidator is None:
        _consolidator = MemoryConsolidator()
    return _consolidator
