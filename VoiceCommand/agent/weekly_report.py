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
        success_count = len([r for r in records if r.success])
        fail_count = total - success_count
        success_rate = int((success_count / total) * 100) if total else 0

        compiled_skills = [s for s in skills if s.compiled]
        low_confidence = [s for s in skills if s.confidence < 0.5]
        fact_count = len(ctx.context.get("facts", {}))

        lines = [
            "이번 주 자기개선 리포트예요!",
            "완료 작업 %d건 (성공률 %d%%, 실패 %d건)" % (total, success_rate, fail_count),
            "활성 스킬 %d개 (컴파일 완료 %d개)" % (len(skills), len(compiled_skills)),
            "기억 중인 사실 %d개" % fact_count,
        ]

        suggestions = []
        if fail_count >= 3 and success_rate < 60:
            suggestions.append("실패율이 높습니다. 복잡한 목표를 더 작은 단계로 나눠보세요.")
        if low_confidence:
            suggestions.append(
                "신뢰도 낮은 스킬 %d개 (%s)를 재학습하거나 비활성화하세요."
                % (len(low_confidence), ", ".join(s.name for s in low_confidence[:3]))
            )
        if len(compiled_skills) == 0 and len(skills) >= 3:
            suggestions.append("반복 스킬이 아직 컴파일되지 않았습니다. 자주 쓰는 작업을 반복해 최적화를 유도하세요.")

        if suggestions:
            lines.append("개선 제안: " + " / ".join(suggestions))

        return " ".join(lines)


_weekly_report: WeeklyReport | None = None


def get_weekly_report() -> WeeklyReport:
    global _weekly_report
    if _weekly_report is None:
        _weekly_report = WeeklyReport()
    return _weekly_report
