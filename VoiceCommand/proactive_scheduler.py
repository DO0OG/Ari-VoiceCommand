"""
능동적 스케줄러 (Proactive Scheduler)
사용자 호출 없이도 지정된 시각에 자율적으로 작업을 실행합니다.

사용 예:
  scheduler.schedule("오늘 날씨 요약해서 말해줘", "매일 오전 9시")
  scheduler.schedule("작업 디렉토리 정리해줘", "30분 후")
"""
import dataclasses
import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Tuple

_SCHEDULE_FILE = os.path.join(os.path.dirname(__file__), "scheduled_tasks.json")
_TICK_INTERVAL = 30   # 초: 예약 작업 체크 주기
_MAX_TASKS = 50


@dataclass
class ScheduledTask:
    task_id: str
    goal: str
    schedule_desc: str    # 원문 ("매일 오전 9시" 등)
    next_run: str         # ISO datetime
    repeat: bool = False
    repeat_seconds: int = 0
    enabled: bool = True
    last_run: str = ""
    last_result: str = ""


class ProactiveScheduler:
    """지정된 시각에 에이전트 작업을 자율 실행하는 스케줄러"""

    def __init__(self, tts_func: Optional[Callable] = None):
        self.tts = tts_func
        self._tasks: Dict[str, ScheduledTask] = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._orchestrator_func: Optional[Callable] = None
        self._load()
        self._start_ticker()

    # ── 공개 API ──────────────────────────────────────────────────────────────

    def set_orchestrator_func(self, func: Callable):
        """ai_command에서 orchestrator.run을 주입 (순환 임포트 방지용 늦은 바인딩)"""
        self._orchestrator_func = func

    def schedule(
        self,
        goal: str,
        next_run_dt: datetime,
        schedule_desc: str,
        repeat: bool = False,
        repeat_seconds: int = 0,
    ) -> str:
        """작업을 등록하고 task_id를 반환합니다."""
        task_id = str(uuid.uuid4())[:8]
        task = ScheduledTask(
            task_id=task_id,
            goal=goal,
            schedule_desc=schedule_desc,
            next_run=next_run_dt.isoformat(),
            repeat=repeat,
            repeat_seconds=repeat_seconds,
        )
        with self._lock:
            self._tasks[task_id] = task
            self._save()
        logging.info(f"[Scheduler] 예약: {task_id} / {schedule_desc} / {next_run_dt.strftime('%Y-%m-%d %H:%M')}")
        return task_id

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            if task_id in self._tasks:
                del self._tasks[task_id]
                self._save()
                return True
        return False

    def list_tasks(self) -> List[ScheduledTask]:
        with self._lock:
            return [t for t in self._tasks.values() if t.enabled]

    def stop(self):
        """백그라운드 스레드를 정지합니다."""
        self._stop_event.set()

    # ── 내부 ──────────────────────────────────────────────────────────────────

    def _start_ticker(self):
        t = threading.Thread(target=self._tick_loop, daemon=True, name="ProactiveScheduler")
        t.start()

    def _tick_loop(self):
        while not self._stop_event.wait(timeout=_TICK_INTERVAL):
            self._check_due_tasks()

    def _check_due_tasks(self):
        now = datetime.now()
        due: List[ScheduledTask] = []

        with self._lock:
            for task in list(self._tasks.values()):
                if not task.enabled:
                    continue
                try:
                    next_run = datetime.fromisoformat(task.next_run)
                except Exception:
                    continue
                if now >= next_run:
                    due.append(task)
                    task.last_run = now.isoformat()
                    if task.repeat and task.repeat_seconds > 0:
                        task.next_run = (now + timedelta(seconds=task.repeat_seconds)).isoformat()
                    else:
                        task.enabled = False
            self._save()

        # 락 밖에서 실행 (교착 방지)
        for task in due:
            threading.Thread(
                target=self._execute_task,
                args=(task,),
                daemon=True,
                name=f"ScheduledTask-{task.task_id}",
            ).start()

    def _execute_task(self, task: ScheduledTask):
        logging.info(f"[Scheduler] 실행: {task.task_id} / {task.goal[:50]}")
        if self.tts:
            self.tts(f"예약된 작업을 실행할게요. {task.goal[:30]}")

        if not self._orchestrator_func:
            logging.warning("[Scheduler] orchestrator_func 미설정, 건너뜀")
            return

        try:
            result = self._orchestrator_func(task.goal)
            summary = getattr(result, "summary_kr", str(result))[:200]
            with self._lock:
                if task.task_id in self._tasks:
                    self._tasks[task.task_id].last_result = summary
                self._save()
            if self.tts and summary:
                self.tts(summary)
        except Exception as e:
            logging.error(f"[Scheduler] 실행 오류 ({task.task_id}): {e}")

    def _load(self):
        try:
            if not os.path.exists(_SCHEDULE_FILE):
                return
            with open(_SCHEDULE_FILE, encoding="utf-8") as f:
                data = json.load(f)
            now = datetime.now()
            for item in data:
                task = ScheduledTask(**item)
                # 과거 일회성 작업은 복구하지 않음
                if not task.repeat:
                    try:
                        if datetime.fromisoformat(task.next_run) < now:
                            continue
                    except Exception:
                        continue
                self._tasks[task.task_id] = task
            logging.info(f"[Scheduler] {len(self._tasks)}개 작업 복구")
        except Exception as e:
            logging.warning(f"[Scheduler] 로드 실패: {e}")

    def _save(self):
        try:
            tasks = list(self._tasks.values())[:_MAX_TASKS]
            with open(_SCHEDULE_FILE, "w", encoding="utf-8") as f:
                json.dump([asdict(t) for t in tasks], f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.warning(f"[Scheduler] 저장 실패: {e}")


# ── 싱글톤 ─────────────────────────────────────────────────────────────────────

_scheduler: Optional[ProactiveScheduler] = None


def get_scheduler(tts_func: Optional[Callable] = None) -> ProactiveScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = ProactiveScheduler(tts_func)
    elif tts_func:
        _scheduler.tts = tts_func
    return _scheduler
