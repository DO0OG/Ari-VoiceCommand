import os
import unittest
import tempfile
import threading
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch


from agent.proactive_scheduler import ProactiveScheduler, ScheduledTask


class ProactiveSchedulerTests(unittest.TestCase):
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
