import os
import sys
import unittest
from datetime import datetime


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

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


if __name__ == "__main__":
    unittest.main()
