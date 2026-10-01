import json
import os
import unittest
import tempfile
import threading
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock, patch


from agent.proactive_scheduler import ProactiveScheduler, ScheduledTask, ScheduledTaskRun


class ProactiveSchedulerTests(unittest.TestCase):
    def test_successful_maintenance_is_logged_without_tts(self):
        scheduler = ProactiveScheduler.__new__(ProactiveScheduler)
        scheduler.tts = Mock()
        scheduler._finalize_task_run = Mock()
        task = ScheduledTask(
            task_id="maintenance",
            goal="메모리 정리",
            schedule_expr="매일 오전 3시 30분",
            next_run="",
            task_type="maintenance",
        )
        consolidator = Mock()
        consolidator.run_all.return_value = {
            "facts": 2,
            "strategies": 1,
            "conversations": 0,
        }

        with (
            patch("core.config_manager.ConfigManager.get", return_value=14),
            patch(
                "memory.memory_consolidator.get_memory_consolidator",
                return_value=consolidator,
            ),
        ):
            scheduler._execute_task(task)

        scheduler.tts.assert_not_called()
        scheduler._finalize_task_run.assert_called_once()

    def test_due_tasks_wait_until_activity_allows_them(self):
        scheduler = ProactiveScheduler.__new__(ProactiveScheduler)
        scheduler._activity_state_lock = threading.Lock()
        scheduler._activity_locked = False
        scheduler._activity_away = False
        scheduler._activity_quiet = False
        scheduler._claim_due_tasks = Mock(return_value=[])

        scheduler.set_activity_state(away=True)
        scheduler._check_due_tasks()
        scheduler.check_missed_tasks_on_startup()
        scheduler._claim_due_tasks.assert_not_called()

        scheduler.set_activity_state(away=False, quiet=True)
        scheduler._check_due_tasks()
        scheduler._claim_due_tasks.assert_not_called()

        scheduler.set_activity_state(quiet=False)
        scheduler._check_due_tasks()
        scheduler._claim_due_tasks.assert_called_once()

    def test_activity_return_summary_reports_waiting_and_upcoming_tasks(self):
        scheduler = ProactiveScheduler.__new__(ProactiveScheduler)
        scheduler._lock = threading.Lock()
        now = datetime.now()
        scheduler._tasks = {
            "due": ScheduledTask(
                task_id="due",
                goal="보고서",
                schedule_expr="오늘 오전",
                next_run=(now - timedelta(minutes=1)).isoformat(),
                name="보고서 확인",
            ),
            "upcoming": ScheduledTask(
                task_id="upcoming",
                goal="일정",
                schedule_expr="내일 오전",
                next_run=(now + timedelta(days=1)).isoformat(),
                name="내일 일정",
            ),
        }

        with tempfile.TemporaryDirectory() as tmp:
            scheduler._schedule_run_log_file = os.path.join(tmp, "runs.jsonl")
            scheduler._run_log_lock = threading.Lock()
            scheduler._append_task_run(
                ScheduledTaskRun(
                    task_id="done",
                    goal="완료 작업",
                    task_type="agent",
                    started_at=(now - timedelta(minutes=12)).isoformat(),
                    finished_at=(now - timedelta(minutes=10)).isoformat(),
                    success=True,
                    summary="완료",
                )
            )
            scheduler._append_task_run(
                ScheduledTaskRun(
                    task_id="activity_ide_long_use",
                    goal="IDE 알림",
                    task_type="activity",
                    started_at=(now - timedelta(minutes=8)).isoformat(),
                    finished_at=(now - timedelta(minutes=7)).isoformat(),
                    success=True,
                    summary="알림 표시",
                )
            )
            with patch(
                "agent.proactive_scheduler._",
                side_effect=lambda text, **values: text.format(**values),
            ):
                summary = scheduler.activity_return_summary(30 * 60)

        self.assertIn("완료 1건", summary)
        self.assertIn("대기 1건", summary)
        self.assertIn("내일 일정", summary)
        self.assertEqual(scheduler.activity_return_summary(29 * 60), "")

    def test_ide_long_use_reminder_is_once_daily_and_waits_while_away(self):
        scheduler = ProactiveScheduler.__new__(ProactiveScheduler)
        scheduler._activity_state_lock = threading.Lock()
        scheduler._activity_locked = False
        scheduler._activity_away = True
        scheduler._activity_quiet = False

        with tempfile.TemporaryDirectory() as tmp:
            scheduler._schedule_run_log_file = os.path.join(tmp, "runs.jsonl")
            scheduler._run_log_lock = threading.Lock()
            with patch("agent.proactive_scheduler._", return_value="쉬어 가세요"):
                self.assertEqual(
                    scheduler.activity_ide_long_use_message(3 * 60 * 60),
                    "",
                )
                scheduler.set_activity_state(away=False)
                self.assertEqual(
                    scheduler.activity_ide_long_use_message(3 * 60 * 60),
                    "쉬어 가세요",
                )
                self.assertEqual(
                    scheduler.activity_ide_long_use_message(4 * 60 * 60),
                    "",
                )

            runs = scheduler.get_task_runs(task_id="activity_ide_long_use")
            self.assertEqual(len(runs), 1)

    def test_scheduler_instances_keep_distinct_storage_paths(self):
        with patch("agent.proactive_scheduler._init_schedule_file", side_effect=["first.json", "second.json"]):
            with patch("agent.proactive_scheduler._init_schedule_log_file", side_effect=["first.log", "second.log"]):
                with patch.object(ProactiveScheduler, "_start_ticker"):
                    first = ProactiveScheduler()
                    second = ProactiveScheduler()

        self.assertEqual(first._schedule_file, "first.json")
        self.assertEqual(second._schedule_file, "second.json")
        self.assertEqual(first._schedule_run_log_file, "first.log")
        self.assertEqual(second._schedule_run_log_file, "second.log")

    def test_compute_next_run_respects_daily_repeat_and_except_dates(self):
        scheduler = ProactiveScheduler.__new__(ProactiveScheduler)
        task = ScheduledTask(
            task_id="a",
            goal="알람",
            schedule_expr="매일 오전 9시",
            next_run="2026-03-25T09:00:00",
            repeat=True,
            repeat_rule="daily",
            except_dates=["2026-03-26"],
        )

        next_run = scheduler._compute_next_run(
            task,
            datetime(2026, 3, 25, 9, 0, 0),
            datetime(2026, 3, 25, 9, 0, 0),
        )

        self.assertEqual(next_run, datetime(2026, 3, 27, 9, 0, 0))

    def test_schedule_cleans_inactive_tasks_before_enforcing_limit(self):
        scheduler = ProactiveScheduler.__new__(ProactiveScheduler)
        scheduler._lock = threading.Lock()
        scheduler._tasks = {
            str(number): ScheduledTask(
                task_id=str(number),
                goal="작업",
                schedule_expr="매일 9시",
                # 1번은 실행 시각 전에 수동 실행한 뒤 일시중지한 예약이다.
                next_run="2099-03-25T09:00:00" if number == 1 else "2026-03-25T09:00:00",
                enabled=number not in (0, 1),
                last_run="2026-03-24T09:00:00" if number in (0, 1) else "",
            )
            for number in range(50)
        }
        scheduler._save = Mock()

        task_id = scheduler.schedule("새 작업", datetime(2026, 3, 25, 10), "10시")

        self.assertEqual(len(scheduler._tasks), 50)
        self.assertNotIn("0", scheduler._tasks)
        self.assertIn("1", scheduler._tasks)
        self.assertIn(task_id, scheduler._tasks)
        scheduler._save.assert_called_once()

    def test_schedule_reports_limit_when_all_existing_tasks_are_active(self):
        scheduler = ProactiveScheduler.__new__(ProactiveScheduler)
        scheduler._lock = threading.Lock()
        scheduler._tasks = {
            str(number): ScheduledTask(
                task_id=str(number),
                goal="작업",
                schedule_expr="매일 9시",
                next_run="2026-03-25T09:00:00",
            )
            for number in range(50)
        }
        scheduler._save = Mock()

        with self.assertRaisesRegex(ValueError, "예약 작업이 가득 찼습니다"):
            scheduler.schedule("새 작업", datetime(2026, 3, 25, 10), "10시")

        self.assertEqual(len(scheduler._tasks), 50)
        scheduler._save.assert_not_called()

    def test_save_keeps_all_legacy_tasks_above_limit(self):
        scheduler = ProactiveScheduler.__new__(ProactiveScheduler)
        with tempfile.TemporaryDirectory() as tmp:
            scheduler._schedule_file = os.path.join(tmp, "scheduled_tasks.json")
            scheduler._tasks = {
                str(number): ScheduledTask(
                    task_id=str(number),
                    goal="작업",
                    schedule_expr="매일 9시",
                    next_run="2026-03-25T09:00:00",
                )
                for number in range(51)
            }

            scheduler._save()

            with open(scheduler._schedule_file, encoding="utf-8") as handle:
                self.assertEqual(len(json.load(handle)), 51)

    def test_add_task_persists_weekday_repeat_rule(self):
        scheduler = ProactiveScheduler.__new__(ProactiveScheduler)
        scheduler._lock = threading.Lock()
        scheduler._tasks = {}
        scheduler._save = Mock()

        task = scheduler.add_task("평일 알림", "알림", "평일 9시")

        self.assertEqual(task.repeat_rule, "weekdays")

    def test_weekday_repeat_skips_weekends_and_reads_legacy_daily_rule(self):
        scheduler = ProactiveScheduler.__new__(ProactiveScheduler)
        tasks = [
            ScheduledTask(
                task_id="weekdays",
                goal="평일 알림",
                schedule_expr="평일 9시",
                next_run="2026-03-27T09:00:00",
                repeat=True,
                repeat_seconds=86400,
                repeat_rule="weekdays",
            ),
            ScheduledTask(
                task_id="legacy-weekdays",
                goal="평일 알림",
                schedule_expr="평일 9시",
                next_run="2026-03-27T09:00:00",
                repeat=True,
                repeat_seconds=86400,
                repeat_rule="daily",
            ),
        ]

        for task in tasks:
            with self.subTest(task_id=task.task_id):
                self.assertEqual(
                    scheduler._compute_next_run(
                        task,
                        datetime(2026, 3, 27, 9),
                        datetime(2026, 3, 27, 9),
                    ),
                    datetime(2026, 3, 30, 9),
                )

    def test_normalize_task_adds_alarm_metadata_defaults(self):
        scheduler = ProactiveScheduler.__new__(ProactiveScheduler)

        task = scheduler._normalize_task(
            {
                "task_id": "a",
                "goal": "알람",
                "schedule_expr": "11시",
                "next_run": "2026-03-25T11:00:00",
            }
        )

        self.assertEqual(task.repeat_rule, "")
        self.assertEqual(task.except_dates, [])
        self.assertEqual(task.alarm_sound, "")

    def test_compute_next_run_advances_past_missed_intervals(self):
        scheduler = ProactiveScheduler.__new__(ProactiveScheduler)
        task = ScheduledTask(
            task_id="a",
            goal="알람",
            schedule_expr="매일 오전 9시",
            next_run="2026-03-25T09:00:00",
            repeat=True,
            repeat_rule="daily",
        )

        next_run = scheduler._compute_next_run(
            task,
            datetime(2026, 3, 25, 9, 0, 0),
            datetime(2026, 3, 28, 10, 0, 0),
        )

        self.assertEqual(next_run, datetime(2026, 3, 29, 9, 0, 0))

    def test_check_missed_tasks_on_startup_uses_next_run_and_preclaims_task(self):
        scheduler = ProactiveScheduler.__new__(ProactiveScheduler)
        scheduler._tasks = {
            "task1": ScheduledTask(
                task_id="task1",
                goal="보고서 생성",
                schedule_expr="매일 오전 9시",
                next_run="2026-03-25T09:00:00",
                repeat=True,
                repeat_rule="daily",
            )
        }
        scheduler._lock = threading.Lock()
        scheduler._run_log_lock = threading.Lock()
        scheduler._stop_event = threading.Event()
        scheduler._orchestrator_func = None
        scheduler.tts = None
        scheduler._save = lambda: None
        scheduler._append_task_run = lambda record: None

        claimed = scheduler._claim_due_tasks(datetime(2026, 3, 25, 9, 5, 0))

        self.assertEqual(len(claimed), 1)
        stored = scheduler._tasks["task1"]
        self.assertEqual(stored.last_run, "2026-03-25T09:05:00")
        self.assertEqual(stored.next_run, "2026-03-26T09:00:00")

        claimed_again = scheduler._claim_due_tasks(datetime(2026, 3, 25, 9, 6, 0))
        self.assertEqual(claimed_again, [])

    def test_append_task_run_writes_structured_log(self):
        scheduler = ProactiveScheduler.__new__(ProactiveScheduler)
        scheduler._run_log_lock = threading.Lock()
        with tempfile.TemporaryDirectory() as tmp:
            from agent import proactive_scheduler as proactive_scheduler_module
            original_path = proactive_scheduler_module._SCHEDULE_RUN_LOG_FILE
            try:
                proactive_scheduler_module._SCHEDULE_RUN_LOG_FILE = os.path.join(tmp, "scheduled_task_runs.jsonl")
                scheduler._append_task_run(
                    proactive_scheduler_module.ScheduledTaskRun(
                        task_id="task1",
                        goal="테스트",
                        task_type="agent",
                        started_at="2026-03-25T09:00:00",
                        finished_at="2026-03-25T09:00:03",
                        success=True,
                        summary="완료",
                        next_run_before="2026-03-25T09:00:00",
                        next_run_after="2026-03-26T09:00:00",
                    )
                )
                records = scheduler.get_task_runs(limit=5)
                self.assertEqual(len(records), 1)
                self.assertEqual(records[0]["task_id"], "task1")
                self.assertEqual(records[0]["summary"], "완료")
            finally:
                proactive_scheduler_module._SCHEDULE_RUN_LOG_FILE = original_path

    def test_finalize_task_run_records_learning_artifacts(self):
        scheduler = ProactiveScheduler.__new__(ProactiveScheduler)
        scheduler._lock = threading.Lock()
        scheduler._run_log_lock = threading.Lock()
        scheduler._tasks = {
            "task1": ScheduledTask(
                task_id="task1",
                goal="보고서 생성",
                schedule_expr="매일 오전 9시",
                next_run="2026-03-25T09:00:00",
                repeat=True,
                repeat_rule="daily",
            )
        }
        scheduler._save = lambda: None
        scheduler._append_task_run = lambda record: None

        fake_strategy_memory = SimpleNamespace(record=Mock())
        fake_episode_memory = SimpleNamespace(record=Mock())

        with patch("agent.strategy_memory.get_strategy_memory", return_value=fake_strategy_memory) as strategy_memory:
            with patch("agent.episode_memory.get_episode_memory", return_value=fake_episode_memory) as episode_memory:
                scheduler._finalize_task_run(
                    scheduler._tasks["task1"],
                    "2026-03-25T09:00:00",
                    True,
                    "",
                    "완료",
                    "2026-03-25T09:00:00",
                    "2026-03-26T09:00:00",
                )

        strategy_goal = strategy_memory.return_value.record.call_args.kwargs["goal"]
        episode_goal = episode_memory.return_value.record.call_args.args[0].goal
        self.assertIn("[예약:agent]", strategy_goal)
        self.assertEqual(strategy_goal, episode_goal)


if __name__ == "__main__":
    unittest.main()
