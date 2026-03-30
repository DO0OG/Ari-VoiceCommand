"""주간 자기개선 리포트 생성."""
from __future__ import annotations


class WeeklyReport:
    def generate(self) -> str:
        from agent.strategy_memory import get_strategy_memory
        from agent.skill_library import get_skill_library
        from memory.user_context import get_context_manager

        strategy_memory = get_strategy_memory()
        skills = get_skill_library().list_skills()
        ctx = get_context_manager()

        records = getattr(strategy_memory, "_records", [])
        total = len(records)
        success = len([record for record in records if record.success])
        success_rate = int((success / total) * 100) if total else 0

        return (
            "이번 주 리포트예요! "
            f"완료한 작업 {total}건, 성공률 {success_rate}%. "
            f"활성 스킬 {len(skills)}개, "
            f"기억하고 있는 사실 {len(ctx.context.get('facts', {}))}개예요."
        )


_weekly_report: WeeklyReport | None = None


def get_weekly_report() -> WeeklyReport:
    global _weekly_report
    if _weekly_report is None:
        _weekly_report = WeeklyReport()
    return _weekly_report
