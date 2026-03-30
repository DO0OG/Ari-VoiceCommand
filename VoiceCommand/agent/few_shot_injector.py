"""성공 전략 few-shot 주입."""
from __future__ import annotations


class FewShotInjector:
    MAX_EXAMPLES = 3

    def get_examples(self, goal: str) -> str:
        try:
            from agent.strategy_memory import get_strategy_memory
            records = get_strategy_memory().search_similar_records(goal, limit=self.MAX_EXAMPLES)
        except Exception:
            return ""

        successful = [record for record in records if record.success and record.steps_desc]
        if not successful:
            return ""

        lines = ["[유사 작업 성공 사례]"]
        for record in successful[:self.MAX_EXAMPLES]:
            lines.append(f"목표: {record.goal_summary[:80]}")
            lines.append(f"접근: {' -> '.join(record.steps_desc[:3])}")
            if record.lesson:
                lines.append(f"주의: {record.lesson[:100]}")
            lines.append("")
        return "\n".join(lines).strip()


_injector: FewShotInjector | None = None


def get_few_shot_injector() -> FewShotInjector:
    global _injector
    if _injector is None:
        _injector = FewShotInjector()
    return _injector
