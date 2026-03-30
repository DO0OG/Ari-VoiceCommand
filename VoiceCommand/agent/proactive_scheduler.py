"""
능동적 스케줄러 (Proactive Scheduler) — Phase 3.4 고도화
지정 시각 알람, 주제 기반 선제 제안, 예약 작업 관리를 담당합니다.
AriScheduler(구 scheduler.py) 기능을 통합 — SchedulerPanel UI와 호환.
"""
import json
import logging
import os
import re
import threading
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional, Any

_SCHEDULE_FILE: str = ""  # _init_schedule_file() 에서 설정
_TICK_INTERVAL = 30
_MAX_TASKS = 50

def _init_schedule_file() -> str:
    try:
        from core.resource_manager import ResourceManager
        return ResourceManager.get_writable_path("scheduled_tasks.json")
    except Exception:
        return os.path.join(os.path.dirname(__file__), "scheduled_tasks.json")

@dataclass
class ScheduledTask:
    task_id: str
    goal: str
    schedule_expr: str        # 자연어 스케줄 표현 (구: schedule_desc)
    next_run: str             # ISO format
    name: str = ""            # 작업 이름 (선택, SchedulerPanel UI용)
    task_type: str = "agent"  # "agent" | "alarm" | "suggestion"
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

    _WEEKDAY_KO = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}

    def __init__(self, tts_func: Optional[Callable] = None):
        global _SCHEDULE_FILE
        if not _SCHEDULE_FILE:
            _SCHEDULE_FILE = _init_schedule_file()
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
                 alarm_sound: str = "", name: str = "") -> str:
        task_id = str(uuid.uuid4())[:8]
        task = ScheduledTask(
            task_id=task_id, goal=goal, schedule_expr=desc,
            next_run=next_run_dt.isoformat(), name=name, task_type=task_type,
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

    def add_task(self, name: str, goal: str, schedule_expr: str) -> ScheduledTask:
        """SchedulerPanel UI 호환 인터페이스. 자연어 스케줄 표현으로 작업 추가."""
        next_run = self._calc_next_run(schedule_expr)
        repeat = bool(re.search(r"매일|매주|평일|\d+분마다|\d+시간마다", schedule_expr))
        repeat_rule = ""
        repeat_sec = 0
        if re.search(r"매일|평일", schedule_expr):
            repeat_rule = "daily"; repeat_sec = 86400
        elif re.search(r"매주", schedule_expr):
            repeat_rule = "weekly"; repeat_sec = 86400 * 7
        elif m := re.search(r"(\d+)분마다", schedule_expr):
            repeat_sec = int(m.group(1)) * 60
        elif m := re.search(r"(\d+)시간마다", schedule_expr):
            repeat_sec = int(m.group(1)) * 3600
        task_id = self.schedule(
            goal=goal, next_run_dt=next_run, desc=schedule_expr,
            repeat=repeat, repeat_sec=repeat_sec, repeat_rule=repeat_rule, name=name,
        )
        with self._lock:
            return self._tasks[task_id]

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            if task_id in self._tasks:
                del self._tasks[task_id]; self._save(); return True
        return False

    def cancel_task(self, task_id: str) -> bool:
        return self.cancel(task_id)

    def remove_task(self, task_id: str) -> bool:
        """cancel 의 SchedulerPanel 호환 alias."""
        return self.cancel(task_id)

    def toggle_task(self, task_id: str) -> bool:
        """작업 활성화/비활성화 전환."""
        with self._lock:
            if task_id not in self._tasks:
                return False
            self._tasks[task_id].enabled = not self._tasks[task_id].enabled
            self._save()
        return True

    def run_task_now(self, task_id: str) -> bool:
        """작업 즉시 실행 (SchedulerPanel 수동 실행 버튼용)."""
        with self._lock:
            task = self._tasks.get(task_id)
        if task:
            threading.Thread(target=self._execute_task, args=(task,), daemon=True).start()
            return True
        return False

    def list_tasks(self) -> List[ScheduledTask]:
        with self._lock:
            return list(self._tasks.values())

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

    def check_missed_tasks_on_startup(self):
        """앱 시작 시 놓친 반복 작업을 보충 실행."""
        now = datetime.now()
        missed: List[ScheduledTask] = []
        with self._lock:
            for task in self._tasks.values():
                if not task.enabled or not task.last_run:
                    continue
                try:
                    last = datetime.fromisoformat(task.last_run)
                except Exception:
                    continue
                elapsed = (now - last).total_seconds()
                threshold = {
                    "daily": 86400,
                    "weekly": 86400 * 7,
                    "hourly": 3600,
                }.get(task.repeat_rule, 86400 if task.repeat else 0)
                if threshold and elapsed > threshold:
                    missed.append(task)

        for task in missed:
            logging.info(f"[Scheduler] 놓친 작업 보충 실행: {task.goal}")
            threading.Thread(
                target=self._execute_task,
                args=(task,),
                daemon=True,
                name=f"MissedTask-{task.task_id}",
            ).start()

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

    def _calc_next_run(self, expr: str) -> datetime:
        """자연어 스케줄 표현 → 다음 실행 datetime 계산 (AriScheduler 호환)."""
        now = datetime.now().replace(second=0, microsecond=0)
        expr = expr.strip()
        m = re.search(r"매일\s*(\d{1,2})[시:]\s*(\d{0,2})", expr)
        if m:
            h, mi = int(m.group(1)), int(m.group(2) or "0")
            t = now.replace(hour=h, minute=mi)
            if t <= now: t += timedelta(days=1)
            return t
        m = re.search(r"매주\s*([월화수목금토일])요일?\s*(\d{1,2})[시:]\s*(\d{0,2})", expr)
        if m:
            wd = self._WEEKDAY_KO.get(m.group(1), 0)
            h, mi = int(m.group(2)), int(m.group(3) or "0")
            days_ahead = (wd - now.weekday()) % 7
            t = now.replace(hour=h, minute=mi) + timedelta(days=days_ahead)
            if t <= now: t += timedelta(weeks=1)
            return t
        m = re.search(r"평일\s*(\d{1,2})[시:]\s*(\d{0,2})", expr)
        if m:
            h, mi = int(m.group(1)), int(m.group(2) or "0")
            candidate = now.replace(hour=h, minute=mi)
            if candidate <= now: candidate += timedelta(days=1)
            while candidate.weekday() >= 5: candidate += timedelta(days=1)
            return candidate
        m = re.search(r"(\d+)\s*분마다", expr)
        if m: return now + timedelta(minutes=int(m.group(1)))
        m = re.search(r"(\d+)\s*시간마다", expr)
        if m: return now + timedelta(hours=int(m.group(1)))
        logging.warning(f"[Scheduler] 스케줄 파싱 실패 ({expr!r}), 24시간 후 실행")
        return now + timedelta(days=1)

    def _normalize_task(self, raw: Dict[str, Any]) -> ScheduledTask:
        payload = dict(raw)
        payload.setdefault("repeat_rule", "")
        payload.setdefault("except_dates", [])
        payload.setdefault("alarm_sound", "")
        payload.setdefault("name", "")
        # 구버전 schedule_desc 필드 마이그레이션
        if "schedule_desc" in payload and "schedule_expr" not in payload:
            payload["schedule_expr"] = payload.pop("schedule_desc")
        elif "schedule_desc" in payload:
            payload.pop("schedule_desc")
        # dataclass 필드에 없는 키 제거
        valid_fields = {f.name for f in ScheduledTask.__dataclass_fields__.values()}
        payload = {k: v for k, v in payload.items() if k in valid_fields}
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
