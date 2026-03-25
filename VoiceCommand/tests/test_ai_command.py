import os
import sys
import unittest
from datetime import datetime
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from commands.ai_command import AICommand


class _FakeAssistant:
    def chat_with_tools(self, text, include_context=True):
        return "무엇을 도와드릴까요?", []


class _FakeScheduler:
    def __init__(self):
        self.calls = []

    def schedule(self, goal, next_run_dt, desc, repeat=False, repeat_sec=0, task_type="agent"):
        self.calls.append({
            "goal": goal,
            "desc": desc,
            "repeat": repeat,
            "repeat_sec": repeat_sec,
            "task_type": task_type,
        })
        return "task1234"


class AICommandTests(unittest.TestCase):
    def test_complex_request_is_escalated_to_agent_task(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})
        self.assertTrue(
            command._should_escalate_to_agent_task(
                "바탕화면에 오늘 뉴스 요약 보고서 저장해줘",
                "무엇을 도와드릴까요?",
            )
        )

    def test_simple_chat_is_not_escalated(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})
        self.assertFalse(command._should_escalate_to_agent_task("안녕?", "안녕하세요!"))

    def test_delayed_shutdown_is_scheduled_not_executed_immediately(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})
        command.scheduler = _FakeScheduler()
        command._current_goal = "5분 뒤에 컴퓨터 꺼줘"

        result = command._handle_shutdown_computer({})

        self.assertIn("작업 예약 완료", result)
        self.assertEqual(command.scheduler.calls[0]["goal"], "컴퓨터 종료")
        self.assertEqual(command.scheduler.calls[0]["desc"], "5분 뒤")

    def test_shutdown_recovery_prefers_schedule_tool_when_goal_is_delayed(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})

        recovered = command._recover_tool_calls_from_response(
            "5분 뒤에 컴퓨터 꺼줘",
            "shutdown_computer 호출",
        )

        self.assertEqual(recovered[0]["name"], "schedule_task")
        self.assertEqual(recovered[0]["arguments"]["when"], "5분 뒤")

    def test_shutdown_recovery_treats_relative_e_phrase_as_delayed_schedule(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})

        recovered = command._recover_tool_calls_from_response(
            "30분에 컴퓨터 꺼줘",
            "shutdown_computer 호출",
        )

        self.assertEqual(recovered[0]["name"], "schedule_task")
        self.assertEqual(recovered[0]["arguments"]["when"], "30분에")

    def test_set_timer_response_for_shutdown_is_recovered_as_schedule_task(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})

        recovered = command._recover_tool_calls_from_response(
            "30분에 컴퓨터 꺼줘",
            '(평온) 알겠습니다. <function=set_timer>{"minutes": 30, "seconds": 0}</function>',
        )

        self.assertEqual(recovered[0]["name"], "schedule_task")
        self.assertEqual(recovered[0]["arguments"]["when"], "30분에")

    def test_extract_schedule_phrase_keeps_absolute_minute_expression(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})

        self.assertEqual(command._extract_schedule_phrase("30분에 컴퓨터 꺼줘"), "30분에")

    def test_extract_schedule_phrase_keeps_hour_and_minute_expression(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})

        self.assertEqual(command._extract_schedule_phrase("11시 30분에 컴퓨터 꺼줘"), "11시 30분에")

    def test_extract_schedule_phrase_keeps_hour_expression(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})

        self.assertEqual(command._extract_schedule_phrase("11시에 컴퓨터 꺼줘"), "11시에")

    def test_parse_schedule_interprets_relative_minute_hu_expression(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})

        class _FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                del tz
                return cls(2026, 3, 25, 3, 31, 51)

        with patch("commands.ai_command.datetime", _FixedDateTime):
            next_run, repeat, repeat_seconds = command._parse_schedule("5분 후")

        self.assertEqual(next_run, datetime(2026, 3, 25, 3, 36, 51))
        self.assertFalse(repeat)
        self.assertEqual(repeat_seconds, 0)

    def test_parse_schedule_interprets_minute_e_as_next_matching_clock_minute(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})

        class _FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                del tz
                return cls(2026, 3, 25, 3, 31, 51)

        with patch("commands.ai_command.datetime", _FixedDateTime):
            next_run, repeat, repeat_seconds = command._parse_schedule("30분에")

        self.assertEqual(next_run, datetime(2026, 3, 25, 4, 30, 0))
        self.assertFalse(repeat)
        self.assertEqual(repeat_seconds, 0)

    def test_parse_schedule_interprets_hour_e_as_next_matching_clock_hour(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})

        class _FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                del tz
                return cls(2026, 3, 25, 3, 31, 51)

        with patch("commands.ai_command.datetime", _FixedDateTime):
            next_run, repeat, repeat_seconds = command._parse_schedule("11시에")

        self.assertEqual(next_run, datetime(2026, 3, 25, 11, 0, 0))
        self.assertFalse(repeat)
        self.assertEqual(repeat_seconds, 0)

    def test_parse_schedule_interprets_hour_minute_e_as_next_matching_clock_time(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})

        class _FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                del tz
                return cls(2026, 3, 25, 12, 10, 0)

        with patch("commands.ai_command.datetime", _FixedDateTime):
            next_run, repeat, repeat_seconds = command._parse_schedule("11시 30분에")

        self.assertEqual(next_run, datetime(2026, 3, 26, 11, 30, 0))
        self.assertFalse(repeat)
        self.assertEqual(repeat_seconds, 0)


if __name__ == "__main__":
    unittest.main()
