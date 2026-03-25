"""
능동적 스케줄러 (Proactive Scheduler) — Phase 3.4 고도화
지정 시각 알람, 주제 기반 선제 제안, 예약 작업 관리를 담당합니다.
"""
import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Any

_SCHEDULE_FILE = os.path.join(os.path.dirname(__file__), "scheduled_tasks.json")
_TICK_INTERVAL = 30
_MAX_TASKS = 50

@dataclass
class ScheduledTask:
    task_id: str
    goal: str
    schedule_desc: str
    next_run: str         # ISO format
    task_type: str = "agent" # "agent" | "alarm" | "suggestion"
    repeat: bool = False
    repeat_seconds: int = 0
    repeat_rule: str = ""
    except_dates: List[str] = field(default_factory=list)
    alarm_sound: str = ""
    enabled: bool = True
    last_run: str = ""
    last_result: str = ""

class ProactiveScheduler:
    """사용자의 컨텍스트를 학습하여 선제적으로 제안하고 지정 시각에 작업을 수행합니다."""

    def __init__(self, tts_func: Optional[Callable] = None):
        self.tts = tts_func
        self._tasks: Dict[str, ScheduledTask] = {}
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._orchestrator_func: Optional[Callable] = None
        self._load()
        self._start_ticker()

    def set_orchestrator_func(self, func: Callable):
        self._orchestrator_func = func

    # ── 스케줄 관리 ────────────────────────────────────────────────────────────

    def schedule(self, goal: str, next_run_dt: datetime, desc: str, 
                 task_type: str = "agent", repeat: bool = False, repeat_sec: int = 0,
                 repeat_rule: str = "", except_dates: Optional[List[str]] = None,
                 alarm_sound: str = "") -> str:
        task_id = str(uuid.uuid4())[:8]
        task = ScheduledTask(
            task_id=task_id, goal=goal, schedule_desc=desc,
            next_run=next_run_dt.isoformat(), task_type=task_type,
            repeat=repeat, repeat_seconds=repeat_sec,
            repeat_rule=repeat_rule,
            except_dates=list(except_dates or []),
            alarm_sound=alarm_sound,
        )
        with self._lock:
            self._tasks[task_id] = task
            self._save()
        logging.info(f"[Scheduler] 새 작업 등록: {task_id} ({desc})")
        return task_id

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            if task_id in self._tasks:
                del self._tasks[task_id]; self._save(); return True
        return False

    def list_tasks(self) -> List[ScheduledTask]:
        with self._lock:
            return [t for t in self._tasks.values() if t.enabled]

    # ── 선제적 제안 (Phase 3.4 핵심) ──────────────────────────────────────────

    def get_proactive_suggestions(self) -> List[Dict[str, str]]:
        """사용자 컨텍스트(주제, 빈도)를 분석하여 할 일을 제안합니다."""
        from memory.user_context import get_context_manager
        ctx_mgr = get_context_manager()
        ctx = ctx_mgr.context
        
        suggestions = []
        now = datetime.now()
        
        # 1. 주제 기반 제안
        topics = ctx.get("conversation_topics", {})
        if topics:
            top_topic = max(topics.items(), key=lambda x: x[1])[0]
            if topics[top_topic] >= 3:
                suggestions.append({
                    "type": "topic",
                    "text": f"최근 '{top_topic}'에 대해 자주 대화하셨네요. 관련 정보를 더 찾아드릴까요?",
                    "goal": f"최근 관심사인 '{top_topic}'에 대한 최신 뉴스나 유용한 정보를 정리해줘"
                })
        for topic_item in ctx_mgr.get_topic_recommendations(limit=2, include_strategy=True):
            topic_name = topic_item.split(":", 1)[0]
            suggestions.append({
                "type": "topic_strategy",
                "text": f"최근 주제 '{topic_name}'와 관련된 반복 전략이 보여요. 이어서 정리해드릴까요?",
                "goal": f"최근 주제 '{topic_name}' 관련 작업 이어서 정리해줘",
            })

        # 2. 시간대/습관 기반 제안
        hour = now.hour
        habitual_commands = ctx_mgr.get_time_based_suggestions(hour=hour, limit=2)
        for cmd in habitual_commands:
            suggestions.append({
                "type": "habit",
                "text": f"이 시간대에는 '{cmd}' 관련 요청이 많았어요. 바로 도와드릴까요?",
                "goal": cmd,
            })

        if 7 <= hour <= 9:
            suggestions.append({
                "type": "routine",
                "text": "좋은 아침이에요! 오늘 날씨와 주요 뉴스를 요약해 드릴까요?",
                "goal": "오늘 날씨와 주요 뉴스 요약 브리핑"
            })
        elif 22 <= hour <= 23:
            suggestions.append({
                "type": "routine",
                "text": "오늘 하루 수고 많으셨어요. 내일 날씨를 미리 확인해 드릴까요?",
                "goal": "내일 날씨와 기온 확인"
            })

        deduped = []
        seen_goals = set()
        for item in suggestions:
            goal = item.get("goal", "")
            if goal in seen_goals:
                continue
            deduped.append(item)
            seen_goals.add(goal)
        return deduped[:5]

    # ── 내부 실행 로직 ────────────────────────────────────────────────────────

    def _start_ticker(self):
        threading.Thread(target=self._tick_loop, daemon=True, name="SchedulerTicker").start()

    def _tick_loop(self):
        while not self._stop_event.wait(timeout=_TICK_INTERVAL):
            self._check_due_tasks()

    def _check_due_tasks(self):
        now = datetime.now()
        due = []
        with self._lock:
            for tid, t in list(self._tasks.items()):
                if not t.enabled:
                    continue
                try:
                    dt = datetime.fromisoformat(t.next_run)
                    if self._is_except_date(t, dt.date().isoformat()):
                        if t.repeat:
                            t.next_run = self._compute_next_run(t, dt, now).isoformat()
                        else:
                            t.enabled = False
                        continue
                    if now >= dt:
                        due.append(t)
                        t.last_run = now.isoformat()
                        if t.repeat:
                            t.next_run = self._compute_next_run(t, dt, now).isoformat()
                        else:
                            t.enabled = False
                except Exception as exc:
                    logging.debug(f"[Scheduler] 작업 시간 해석 실패: {tid} ({exc})")
            if due:
                self._save()

        for t in due:
            threading.Thread(target=self._execute_task, args=(t,), daemon=True).start()

    def _execute_task(self, task: ScheduledTask):
        if task.task_type == "alarm":
            message = f"(기쁨) 알람 시간이에요! 요청하신 '{task.goal}' 시각입니다."
            if task.alarm_sound:
                message += f" 알림 사운드: {task.alarm_sound}"
            if self.tts: self.tts(message)
            return

        logging.info(f"[Scheduler] 작업 실행: {task.goal}")
        if self.tts: self.tts(f"(진지) 예약된 작업을 시작할게요: {task.goal}")
        
        if not self._orchestrator_func: return

        try:
            res = self._orchestrator_func(task.goal)
            summary = getattr(res, "summary_kr", "작업 완료")
            with self._lock:
                if task.task_id in self._tasks: self._tasks[task.task_id].last_result = summary
            if self.tts: self.tts(summary)
        except Exception as e:
            logging.error(f"[Scheduler] 실행 실패: {e}")

    def _load(self):
        if os.path.exists(_SCHEDULE_FILE):
            try:
                with open(_SCHEDULE_FILE, encoding="utf-8") as f:
                    data = json.load(f)
                self._tasks = {it["task_id"]: self._normalize_task(it) for it in data}
            except Exception as e:
                logging.warning(f"[Scheduler] 로드 실패: {e}")

    def _save(self):
        try:
            data = [asdict(t) for t in list(self._tasks.values())[:_MAX_TASKS]]
            with open(_SCHEDULE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"[Scheduler] 저장 실패: {e}")

    def _normalize_task(self, raw: Dict[str, Any]) -> ScheduledTask:
        payload = dict(raw)
        payload.setdefault("repeat_rule", "")
        payload.setdefault("except_dates", [])
        payload.setdefault("alarm_sound", "")
        return ScheduledTask(**payload)

    def _is_except_date(self, task: ScheduledTask, date_text: str) -> bool:
        return date_text in set(task.except_dates or [])

    def _compute_next_run(self, task: ScheduledTask, last_due: datetime, now: datetime) -> datetime:
        if task.repeat_rule == "daily":
            next_run = last_due + timedelta(days=1)
        elif task.repeat_rule == "weekly":
            next_run = last_due + timedelta(days=7)
        elif task.repeat_rule == "hourly":
            next_run = last_due + timedelta(hours=1)
        elif task.repeat_seconds > 0:
            next_run = now + timedelta(seconds=task.repeat_seconds)
        else:
            next_run = now + timedelta(days=1)
        while self._is_except_date(task, next_run.date().isoformat()):
            if task.repeat_rule == "weekly":
                next_run += timedelta(days=7)
            elif task.repeat_rule == "hourly":
                next_run += timedelta(hours=1)
            else:
                next_run += timedelta(days=1)
        return next_run

_instance: Optional[ProactiveScheduler] = None

def get_scheduler(tts_func: Optional[Callable] = None) -> ProactiveScheduler:
    global _instance
    if _instance is None:
        _instance = ProactiveScheduler(tts_func)
    elif tts_func:
        _instance.tts = tts_func
    return _instance
