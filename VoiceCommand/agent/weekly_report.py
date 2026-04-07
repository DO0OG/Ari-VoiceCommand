"""주간 자기개선 리포트 생성."""
from __future__ import annotations

from datetime import datetime, timedelta
import threading
from i18n.translator import _


class WeeklyReport:
    def generate(self, days: int = 7) -> str:
        from agent.strategy_memory import get_strategy_memory
        from agent.skill_library import get_skill_library
        from agent.proactive_scheduler import get_scheduler
        from agent.learning_metrics import get_learning_metrics
        from agent.regression_guard import get_regression_guard
        from memory.user_context import get_context_manager

        strategy_memory = get_strategy_memory()
        skills = get_skill_library().list_skills()
        scheduler = get_scheduler()
        ctx = get_context_manager()
        learning_metrics = get_learning_metrics()
        regression_guard = get_regression_guard()

        stats = strategy_memory.get_stats(days=days)
        total = stats["total"]
        success_count = stats["success"]
        fail_count = stats["fail"]
        success_rate = int(stats["success_rate"] * 100) if total else 0

        compiled_skills = [s for s in skills if s.compiled]
        low_confidence = [s for s in skills if s.confidence < 0.5]
        fact_count = len(ctx.context.get("facts", {}))
        repeated_failures = strategy_memory.get_repeated_failures(min_count=2)
        recent_task_runs = self._recent_task_runs(scheduler.get_task_runs(limit=30), days=days)
        task_success = len([item for item in recent_task_runs if item.get("success")])
        task_fail = len(recent_task_runs) - task_success

        lines = [
            _("이번 주 자기개선 리포트예요!"),
            _("완료 작업 {total}건 (성공 {success}건, 성공률 {rate}%, 실패 {fail}건)").format(
                total=total, success=success_count, rate=success_rate, fail=fail_count
            ),
            _("활성 스킬 {total}개 (컴파일 완료 {compiled}개)").format(
                total=len(skills), compiled=len(compiled_skills)
            ),
            _("기억 중인 사실 {count}개").format(count=fact_count),
        ]
        if recent_task_runs:
            lines.append(
                _("예약 작업 {total}건 처리 (성공 {success}건, 실패 {fail}건)").format(
                    total=len(recent_task_runs), success=task_success, fail=task_fail
                )
            )
        if repeated_failures:
            top_failures = ", ".join(_("{kind} {count}회").format(kind=kind, count=count) for kind, count in repeated_failures[:3])
            lines.append(_("반복 실패 패턴: ") + top_failures)
        
        metric_lines = learning_metrics.get_report_lines(limit=3)
        if metric_lines:
            lines.append(_("학습 기여도: ") + " / ".join(metric_lines))
        
        regression_alert = regression_guard.check()
        if regression_alert:
            lines.append(_("회귀 경고: ") + regression_alert)

        suggestions = []
        if fail_count >= 3 and success_rate < 60:
            suggestions.append(_("실패율이 높습니다. 복잡한 목표를 더 작은 단계로 나눠보세요."))
        if low_confidence:
            suggestions.append(
                _("신뢰도 낮은 스킬 {count}개 ({names})를 재학습하거나 비활성화하세요.").format(
                    count=len(low_confidence), names=", ".join(s.name for s in low_confidence[:3])
                )
            )
        if len(compiled_skills) == 0 and len(skills) >= 3:
            suggestions.append(_("반복 스킬이 아직 컴파일되지 않았습니다. 자주 쓰는 작업을 반복해 최적화를 유도하세요."))
        if recent_task_runs and task_fail >= 2:
            suggestions.append(_("예약 작업 실패가 누적되고 있습니다. next_run과 실패 원인을 함께 점검하세요."))

        if suggestions:
            lines.append(_("개선 제안: ") + " / ".join(suggestions))

        return " ".join(lines)

    def _parse_started_at(self, row: dict) -> datetime | None:
        started_at_raw = row.get("started_at", "")
        if not started_at_raw:
            return None
        try:
            return datetime.fromisoformat(str(started_at_raw))
        except ValueError:
            return None

    def _recent_task_runs(self, rows: list[dict], days: int = 7) -> list[dict]:
        cutoff = datetime.now() - timedelta(days=max(int(days or 0), 0))
        recent = []
        for row in rows or []:
            started_at = self._parse_started_at(row)
            if started_at is None:
                continue
            if started_at >= cutoff:
                recent.append(row)
        return recent


_weekly_report: WeeklyReport | None = None
_weekly_report_lock = threading.Lock()


def get_weekly_report() -> WeeklyReport:
    global _weekly_report
    if _weekly_report is None:
        with _weekly_report_lock:
            if _weekly_report is None:
                _weekly_report = WeeklyReport()
    return _weekly_report
