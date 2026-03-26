"""
자율 작업 스케줄러 (Autonomous Task Scheduler)
자연어 스케줄 표현으로 반복 작업을 자동 실행합니다.

사용 예:
    scheduler = get_scheduler(orchestrator_func=orchestrator.run)
    task = scheduler.add_task("뉴스 요약", "최신 뉴스를 요약해서 저장해줘", "매일 09:00")
    scheduler.start()

지원 스케줄 표현:
    "매일 HH:MM"         → 매일 지정 시각
    "매주 요일 HH:MM"    → 매주 지정 요일·시각  (월·화·수·목·금·토·일)
    "N분마다"            → N분 간격 (테스트용)
    "N시간마다"          → N시간 간격
"""
import json
import logging
import os
import re
import threading
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import QThread, Signal

logger = logging.getLogger(__name__)


# ── 데이터 클래스 ─────────────────────────────────────────────────────────────

@dataclass
class ScheduledTask:
    task_id: str
    name: str
    goal: str
    schedule_expr: str          # 자연어 스케줄 표현 (예: "매일 09:00")
    next_run: str               # ISO 8601 형식 다음 실행 시각
    enabled: bool = True
    last_run: Optional[str] = None
    run_count: int = 0
    last_result: str = ""


# ── 스케줄러 ──────────────────────────────────────────────────────────────────

class AriScheduler(QThread):
    """60초 간격으로 예약 작업을 확인하고 오케스트레이터에 위임하는 스케줄러."""

    task_triggered  = Signal(str, str)        # task_id, goal
    task_completed  = Signal(str, str, bool)  # task_id, result, success
    tasks_changed   = Signal()                # UI 갱신 트리거

    _CHECK_INTERVAL_MS = 60_000              # 1분

    def __init__(
        self,
        tasks_file: str = "scheduled_tasks.json",
        orchestrator_func: Optional[Callable] = None,
    ):
        super().__init__()
        self.orchestrator_func = orchestrator_func
        self.tasks: Dict[str, ScheduledTask] = {}
        self._lock = threading.Lock()
        self._tasks_file = self._resolve_path(tasks_file)
        self._load_tasks()

    # ── QThread 진입점 ────────────────────────────────────────────────────────

    def run(self) -> None:
        """1분 루프: 예약된 작업이 도래했으면 실행."""
        while not self.isInterruptionRequested():
            self._check_due_tasks()
            self.msleep(self._CHECK_INTERVAL_MS)

    # ── 공개 API ──────────────────────────────────────────────────────────────

    def add_task(self, name: str, goal: str, schedule_expr: str) -> ScheduledTask:
        """새 예약 작업 추가. 자연어 스케줄 파싱 후 저장."""
        next_run = self._calc_next_run(schedule_expr)
        task = ScheduledTask(
            task_id=uuid.uuid4().hex[:8],
            name=name,
            goal=goal,
            schedule_expr=schedule_expr,
            next_run=next_run.isoformat(),
        )
        with self._lock:
            self.tasks[task.task_id] = task
        self._save_tasks()
        self.tasks_changed.emit()
        logger.info(f"[Scheduler] 작업 추가: {name!r} ({schedule_expr}) → 다음 실행 {next_run.strftime('%Y-%m-%d %H:%M')}")
        return task

    def remove_task(self, task_id: str) -> bool:
        """작업 삭제."""
        with self._lock:
            if task_id not in self.tasks:
                return False
            del self.tasks[task_id]
        self._save_tasks()
        self.tasks_changed.emit()
        return True

    def toggle_task(self, task_id: str) -> bool:
        """작업 활성화/비활성화 전환."""
        with self._lock:
            if task_id not in self.tasks:
                return False
            self.tasks[task_id].enabled = not self.tasks[task_id].enabled
        self._save_tasks()
        self.tasks_changed.emit()
        return True

    def list_tasks(self) -> List[ScheduledTask]:
        """현재 등록된 모든 작업 목록 반환."""
        with self._lock:
            return list(self.tasks.values())

    def run_task_now(self, task_id: str) -> bool:
        """특정 작업을 즉시 실행 (테스트/수동 실행용)."""
        with self._lock:
            task = self.tasks.get(task_id)
        if task:
            threading.Thread(target=self._execute_task, args=(task,), daemon=True).start()
            return True
        return False

    def parse_schedule(self, expr: str) -> Optional[str]:
        """자연어 스케줄 표현을 정규화된 형태로 반환. 파싱 불가 시 None."""
        try:
            dt = self._calc_next_run(expr)
            return dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            return None

    # ── 내부: 실행 ────────────────────────────────────────────────────────────

    def _check_due_tasks(self) -> None:
        now = datetime.now()
        with self._lock:
            due = [
                t for t in self.tasks.values()
                if t.enabled and datetime.fromisoformat(t.next_run) <= now
            ]
        for task in due:
            threading.Thread(target=self._execute_task, args=(task,), daemon=True).start()

    def _execute_task(self, task: ScheduledTask) -> None:
        logger.info(f"[Scheduler] 실행 시작: {task.name!r} | 목표: {task.goal}")
        self.task_triggered.emit(task.task_id, task.goal)

        result_text = ""
        success = False
        try:
            if self.orchestrator_func:
                run_result = self.orchestrator_func(task.goal)
                success = getattr(run_result, "achieved", False)
                result_text = getattr(run_result, "summary_kr", "")
            else:
                result_text = "오케스트레이터가 연결되지 않았습니다."
        except Exception as e:
            result_text = f"오류: {e}"
            logger.error(f"[Scheduler] 실행 오류 ({task.name}): {e}")

        with self._lock:
            if task.task_id in self.tasks:
                self.tasks[task.task_id].last_run = datetime.now().isoformat()
                self.tasks[task.task_id].run_count += 1
                self.tasks[task.task_id].last_result = result_text[:200]
                next_dt = self._calc_next_run(task.schedule_expr)
                self.tasks[task.task_id].next_run = next_dt.isoformat()

        self._save_tasks()
        self.tasks_changed.emit()
        self.task_completed.emit(task.task_id, result_text, success)
        logger.info(f"[Scheduler] 완료: {task.name!r} | 성공={success}")

    # ── 내부: 스케줄 파싱 ────────────────────────────────────────────────────

    _WEEKDAY_KO = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}

    def _calc_next_run(self, expr: str) -> datetime:
        """자연어 스케줄 → 다음 실행 datetime 계산."""
        now = datetime.now().replace(second=0, microsecond=0)
        expr = expr.strip()

        # ── 매일 HH:MM / 매일 HH시 MM분 ──────────────────────────────────
        m = re.search(r"매일\s*(\d{1,2})[시:]\s*(\d{0,2})", expr)
        if m:
            h, mi = int(m.group(1)), int(m.group(2) or "0")
            target = now.replace(hour=h, minute=mi)
            if target <= now:
                target += timedelta(days=1)
            return target

        # ── 매주 요일 HH:MM ──────────────────────────────────────────────
        m = re.search(r"매주\s*([월화수목금토일])요일?\s*(\d{1,2})[시:]\s*(\d{0,2})", expr)
        if m:
            wd = self._WEEKDAY_KO.get(m.group(1), 0)
            h, mi = int(m.group(2)), int(m.group(3) or "0")
            days_ahead = (wd - now.weekday()) % 7
            target = now.replace(hour=h, minute=mi) + timedelta(days=days_ahead)
            if target <= now:
                target += timedelta(weeks=1)
            return target

        # ── 평일(월–금) 매일 HH:MM ───────────────────────────────────────
        m = re.search(r"평일\s*(\d{1,2})[시:]\s*(\d{0,2})", expr)
        if m:
            h, mi = int(m.group(1)), int(m.group(2) or "0")
            candidate = now.replace(hour=h, minute=mi)
            if candidate <= now:
                candidate += timedelta(days=1)
            while candidate.weekday() >= 5:  # 토, 일 건너뜀
                candidate += timedelta(days=1)
            return candidate

        # ── N분마다 ──────────────────────────────────────────────────────
        m = re.search(r"(\d+)\s*분마다", expr)
        if m:
            return now + timedelta(minutes=int(m.group(1)))

        # ── N시간마다 ────────────────────────────────────────────────────
        m = re.search(r"(\d+)\s*시간마다", expr)
        if m:
            return now + timedelta(hours=int(m.group(1)))

        # ── 기본: 24시간 후 ──────────────────────────────────────────────
        logger.warning(f"[Scheduler] 스케줄 파싱 실패 ({expr!r}), 24시간 후 실행")
        return now + timedelta(days=1)

    # ── 내부: 영속성 ─────────────────────────────────────────────────────────

    @staticmethod
    def _resolve_path(filename: str) -> str:
        try:
            from core.resource_manager import ResourceManager
            return ResourceManager.get_writable_path(filename)
        except Exception:
            return filename

    def _load_tasks(self) -> None:
        if not os.path.exists(self._tasks_file):
            return
        try:
            with open(self._tasks_file, "r", encoding="utf-8") as f:
                items = json.load(f)
            for item in items:
                t = ScheduledTask(**{k: v for k, v in item.items() if k in ScheduledTask.__dataclass_fields__})
                self.tasks[t.task_id] = t
            logger.info(f"[Scheduler] {len(self.tasks)}개 작업 로드 완료")
        except Exception as e:
            logger.error(f"[Scheduler] 작업 로드 실패: {e}")

    def _save_tasks(self) -> None:
        try:
            with open(self._tasks_file, "w", encoding="utf-8") as f:
                with self._lock:
                    data = [asdict(t) for t in self.tasks.values()]
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[Scheduler] 작업 저장 실패: {e}")


# ── 싱글톤 ────────────────────────────────────────────────────────────────────

_scheduler: Optional[AriScheduler] = None


def get_scheduler(orchestrator_func: Optional[Callable] = None) -> AriScheduler:
    """AriScheduler 싱글톤 반환. 처음 호출 시 인스턴스 생성."""
    global _scheduler
    if _scheduler is None:
        _scheduler = AriScheduler(orchestrator_func=orchestrator_func)
    elif orchestrator_func is not None and _scheduler.orchestrator_func is None:
        _scheduler.orchestrator_func = orchestrator_func
    return _scheduler
