"""메모리 정리 및 압축."""
from __future__ import annotations

import threading

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
        return history.compact_older_than(days_ago, history._summarize_chunk)

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
_consolidator_lock = threading.Lock()


def get_memory_consolidator() -> MemoryConsolidator:
    global _consolidator
    if _consolidator is None:
        with _consolidator_lock:
            if _consolidator is None:
                _consolidator = MemoryConsolidator()
    return _consolidator
