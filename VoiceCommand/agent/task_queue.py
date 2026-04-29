"""에이전트 작업 비동기 큐.

낮은 우선순위의 장기 작업을 백그라운드로 보내고, 긴급 작업은 더 높은
우선순위로 먼저 실행할 수 있게 하는 경량 큐 구현이다.
"""

from __future__ import annotations

import itertools
import logging
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

logger = logging.getLogger(__name__)

TaskCallable = Callable[[threading.Event], object]


def _noop_runner(_cancel_event: threading.Event) -> None:
    """셧다운 sentinel용 no-op runner."""


@dataclass
class AgentQueuedTask:
    task_id: str
    goal: str
    runner: TaskCallable
    priority: int = 50
    created_at: float = field(default_factory=time.time)
    cancel_event: threading.Event = field(default_factory=threading.Event)


@dataclass
class AgentTaskResult:
    task_id: str
    goal: str
    status: str
    result: object = None
    error: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0


class AgentTaskQueue:
    """PriorityQueue + worker thread 기반 에이전트 작업 큐."""

    def __init__(self, max_workers: int = 2):
        self.max_workers = max(1, int(max_workers or 1))
        self._queue: queue.PriorityQueue[tuple[int, int, AgentQueuedTask]] = queue.PriorityQueue()
        self._counter = itertools.count()
        self._pending: dict[str, AgentQueuedTask] = {}
        self._running: dict[str, AgentQueuedTask] = {}
        self._results: dict[str, AgentTaskResult] = {}
        self._lock = threading.RLock()
        self._shutdown = threading.Event()
        self._workers = [
            threading.Thread(
                target=self._worker_loop,
                name=f"ari-agent-task-queue-{idx}",
                daemon=True,
            )
            for idx in range(self.max_workers)
        ]
        for worker in self._workers:
            worker.start()

    def submit(
        self,
        goal: str,
        runner: TaskCallable,
        *,
        priority: int = 50,
        task_id: Optional[str] = None,
    ) -> str:
        if not callable(runner):
            raise TypeError("runner must be callable")
        task = AgentQueuedTask(
            task_id=task_id or uuid.uuid4().hex,
            goal=str(goal or ""),
            runner=runner,
            priority=int(priority),
        )
        with self._lock:
            self._pending[task.task_id] = task
        self._queue.put((task.priority, next(self._counter), task))
        return task.task_id

    def cancel(self, task_id: str) -> bool:
        """대기 또는 실행 중인 작업에 취소 신호를 보낸다."""
        with self._lock:
            task = self._pending.get(task_id) or self._running.get(task_id)
            if task is None:
                return False
            task.cancel_event.set()
            return True

    def cancel_current(self, task_id: Optional[str] = None) -> int:
        """실행 중인 작업 전체 또는 지정 작업에 취소 신호를 보낸다."""
        with self._lock:
            running = list(self._running.values())
            if task_id is not None:
                running = [task for task in running if task.task_id == task_id]
            for task in running:
                task.cancel_event.set()
            return len(running)

    def status(self, task_id: str) -> str:
        with self._lock:
            if task_id in self._pending:
                return "pending"
            if task_id in self._running:
                return "running"
            result = self._results.get(task_id)
            return result.status if result else "unknown"

    def result(self, task_id: str) -> Optional[AgentTaskResult]:
        with self._lock:
            return self._results.get(task_id)

    def shutdown(self, *, cancel_pending: bool = True) -> None:
        if cancel_pending:
            with self._lock:
                for task in list(self._pending.values()) + list(self._running.values()):
                    task.cancel_event.set()
        self._shutdown.set()
        for _ in self._workers:
            self._queue.put((10**9, next(self._counter), AgentQueuedTask("", "", _noop_runner)))
        for worker in self._workers:
            worker.join(timeout=1.0)

    def _worker_loop(self) -> None:
        while not self._shutdown.is_set():
            try:
                _, _, task = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                if not task.task_id:
                    continue
                self._run_task(task)
            finally:
                self._queue.task_done()

    def _run_task(self, task: AgentQueuedTask) -> None:
        with self._lock:
            if self._pending.pop(task.task_id, None) is None:
                return
            if task.cancel_event.is_set():
                self._results[task.task_id] = AgentTaskResult(
                    task_id=task.task_id,
                    goal=task.goal,
                    status="cancelled",
                    finished_at=time.time(),
                )
                return
            self._running[task.task_id] = task

        started_at = time.time()
        try:
            result = task.runner(task.cancel_event)
            status = "cancelled" if task.cancel_event.is_set() else "completed"
            task_result = AgentTaskResult(
                task_id=task.task_id,
                goal=task.goal,
                status=status,
                result=result,
                started_at=started_at,
                finished_at=time.time(),
            )
        except Exception as exc:
            logger.exception("[AgentTaskQueue] 작업 실패: %s", task.goal[:80])
            task_result = AgentTaskResult(
                task_id=task.task_id,
                goal=task.goal,
                status="failed",
                error=str(exc),
                started_at=started_at,
                finished_at=time.time(),
            )
        with self._lock:
            self._running.pop(task.task_id, None)
            self._results[task.task_id] = task_result
