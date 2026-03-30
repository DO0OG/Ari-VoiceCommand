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

    def run_all(self):
        return {
            "facts": self.consolidate_facts(),
            "strategies": self.consolidate_strategies(),
            "conversations": self.summarize_old_conversations(),
        }


_consolidator: MemoryConsolidator | None = None


def get_memory_consolidator() -> MemoryConsolidator:
    global _consolidator
    if _consolidator is None:
        _consolidator = MemoryConsolidator()
    return _consolidator
