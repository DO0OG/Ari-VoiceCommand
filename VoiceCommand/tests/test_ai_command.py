import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


from commands.ai_command import AICommand
from agent.agent_orchestrator import AgentRunResult


class _FakeAssistant:
    def chat_with_tools(self, text, include_context=True):
        return "무엇을 도와드릴까요?", []

    def feed_tool_result(self, original_text, tool_calls, results):
        del original_text, tool_calls, results
        return ""


class _AgentTaskAssistant:
    def chat_with_tools(self, text, include_context=True):
        del include_context
        return "(진지) 바로 처리할게요.", [{
            "id": "tool_1",
            "name": "run_agent_task",
            "arguments": {
                "goal": text,
                "explanation": text,
            },
        }]

    def feed_tool_result(self, original_text, tool_calls, results):
        del original_text, tool_calls, results
        return "tool_calls: [{\"name\":\"run_agent_task\"}] 이 문장은 읽히면 안 됩니다."


class _StreamingAssistant:
    def chat_with_tools(self, text, include_context=True, stream_callback=None):
        del text, include_context
        if stream_callback:
            stream_callback("안녕")
            stream_callback("하세요")
        return "안녕하세요", []

    def feed_tool_result(self, original_text, tool_calls, results, stream_callback=None):
        del original_text, tool_calls, results, stream_callback
        return ""


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

    def test_security_check_request_is_escalated_to_agent_task(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})
        self.assertTrue(
            command._should_escalate_to_agent_task(
                "자체 보안 점검 진행해줘",
                "무엇을 도와드릴까요?",
            )
        )

    def test_simple_chat_is_not_escalated(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})
        self.assertFalse(command._should_escalate_to_agent_task("안녕?", "안녕하세요!"))

    def test_get_current_time_returns_direct_response(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})

        class _FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                del tz
                return cls(2026, 3, 25, 16, 48, 0)

        with patch("commands.ai_command.datetime", _FixedDateTime):
            result = command._handle_get_current_time({})

        self.assertEqual(result, "현재 시간은 오후 4시 48분입니다.")

    def test_preface_response_filters_ellipsis_placeholder(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})

        self.assertFalse(command._should_emit_preface_response("(평온)..."))
        self.assertFalse(command._should_emit_preface_response("get_current_time"))
        self.assertTrue(command._should_emit_preface_response("알겠습니다. 바로 확인해볼게요."))

    def test_agent_task_prefers_detailed_explanation_over_short_label(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})

        goal = command._resolve_agent_task_goal({
            "goal": "Ari autonomy test",
            "explanation": "바탕화면에 Ari autonomy test 폴더를 만들고 열린 창 제목들을 markdown으로 정리해서 저장해줘.",
        })

        self.assertIn("바탕화면에 Ari autonomy test 폴더", goal)

    def test_agent_task_prefers_detailed_explanation_over_generic_goal_summary(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})

        goal = command._resolve_agent_task_goal({
            "goal": "바탕화면에 폴더 만들기, 창 제목 수집 및 분류, markdown 보고서 생성",
            "explanation": "바탕화면에 'Ari autonomy final audit' 폴더를 만들고 창 제목을 분류한 markdown 보고서를 summary.md로 저장해줘.",
        })

        self.assertIn("Ari autonomy final audit", goal)

    def test_agent_task_keeps_goal_when_explanation_is_generic_placeholder(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})

        goal = command._resolve_agent_task_goal({
            "goal": "바탕화면에 Ari workspace audit 폴더를 만들고 summary.md 저장",
            "explanation": "복합 작업을 실행할게요.",
        })

        self.assertIn("Ari workspace audit", goal)

    def test_sanitize_user_facing_text_removes_tool_call_artifacts(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})

        cleaned = command._sanitize_user_facing_text(
            '(진지) 알겠습니다. tool_calls: [{"name":"run_agent_task","arguments":{"goal":"Ari autonomy test"}}] 이제 진행할게요.'
        )

        self.assertEqual(cleaned, "(진지) 알겠습니다. 이제 진행할게요.")

    def test_run_agent_task_skips_long_followup_response(self):
        command = AICommand(_AgentTaskAssistant(), lambda msg: None, {"enabled": False})
        command._dispatch["run_agent_task"] = lambda args: "작업 완료. Ari autonomy test 폴더에 summary.md를 저장했습니다."

        combined = command.run_interaction('바탕화면에 "Ari autonomy test" 폴더를 만들고 보고서를 저장해줘')

        self.assertIn("작업 완료.", combined)
        self.assertNotIn("읽히면 안 됩니다", combined)

    def test_run_interaction_passes_stream_callback_when_supported(self):
        command = AICommand(_StreamingAssistant(), lambda msg: None, {"enabled": False})
        streamed = []

        combined = command.run_interaction("안녕", stream_callback=streamed.append)

        self.assertEqual("".join(streamed), "안녕하세요")
        self.assertIn("안녕하세요", combined)

    def test_handle_agent_task_saves_developer_report_in_user_report_dir(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})
        run_result = AgentRunResult(
            goal="VoiceCommand 저장소 개선",
            achieved=True,
            summary="코드 변경과 검증을 완료했습니다.",
            total_iterations=1,
            step_results=[
                SimpleNamespace(
                    step=SimpleNamespace(step_type="python", description_kr="코드 수정", content="print('patched')"),
                    exec_result=SimpleNamespace(success=True, output="patched file", error="", state_delta_summary=""),
                    attempt=1,
                    was_fixed=False,
                ),
                SimpleNamespace(
                    step=SimpleNamespace(step_type="shell", description_kr="검증 실행", content="py -3.11 VoiceCommand\\validate_repo.py --compile-only"),
                    exec_result=SimpleNamespace(success=True, output="[validate] compile-only checks passed", error="", state_delta_summary=""),
                    attempt=1,
                    was_fixed=False,
                ),
            ],
        )
        command.orchestrator.run = lambda goal: run_result

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(command, "_resolve_user_report_dir", return_value=Path(temp_dir)):
                message = command._handle_agent_task({"goal": run_result.goal, "explanation": run_result.goal})

            created = os.listdir(temp_dir)
            self.assertEqual(len(created), 1)
            report_path = os.path.join(temp_dir, created[0])
            self.assertTrue(os.path.exists(report_path))
            with open(report_path, "r", encoding="utf-8") as handle:
                report = handle.read()

        self.assertIn("실행 보고서는", message)
        self.assertIn("코드 수정", report)
        self.assertIn("검증 실행", report)

    def test_run_agent_task_stores_tool_result_in_conversation_history(self):
        command = AICommand(_AgentTaskAssistant(), lambda msg: None, {"enabled": False})
        command._dispatch["run_agent_task"] = lambda args: "작업 실패 (2회 시도). 계획 수립에 실패했습니다. 실행 보고서는 바탕화면 Ari Reports 폴더의 agent_run_test.md에 저장했습니다."

        with patch("memory.conversation_history.add_conversation") as add_conversation:
            combined = command.run_interaction("VoiceCommand 저장소 전체 파악 후 코드 변경 및 검증")

        self.assertIn("실행 보고서", combined)
        add_conversation.assert_called_once()
        self.assertIn("실행 보고서", add_conversation.call_args[0][1])

    def test_script_skill_escalation_routes_to_run_agent_task_and_records_metadata(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})
        command._dispatch["run_agent_task"] = lambda args: "작업 완료. 스크립트 스킬을 실행했습니다."

        skill_ctx = {
            "skills": [SimpleNamespace(name="joseon-sillok-search")],
            "prompt": "",
            "required_tool_names": [],
            "preferred_tool": "",
            "force_web_search": False,
            "escalate_to_agent": True,
            "search_query_template": "",
        }

        with patch.object(command, "_get_skill_context", return_value=skill_ctx):
            with patch("memory.conversation_history.add_conversation") as add_conversation:
                combined = command.run_interaction("실록에서 세종 기록 찾아줘")

        self.assertIn("작업 완료.", combined)
        add_conversation.assert_called_once()
        self.assertEqual(add_conversation.call_args.kwargs["skill_used"], "joseon-sillok-search")
        self.assertEqual(add_conversation.call_args.kwargs["data_source"], "agent")

    def test_extract_saved_path_ignores_scanned_markdown_path_without_save_signal(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})
        run_result = AgentRunResult(
            goal="VoiceCommand 저장소 개선",
            achieved=True,
            summary="완료",
            total_iterations=1,
            step_results=[
                SimpleNamespace(
                    step=SimpleNamespace(step_type="python", description_kr="파일 스캔", content="print('scan')"),
                    exec_result=SimpleNamespace(
                        success=True,
                        output='{"docs": {"md": ["D:\\\\Git\\\\Ari-VoiceCommand\\\\docs\\\\ARI_ENHANCEMENT_PLAN.md"]}}',
                        error="",
                        state_delta_summary="",
                    ),
                    attempt=1,
                    was_fixed=False,
                ),
            ],
        )

        self.assertEqual(command._extract_saved_path_from_agent_run(run_result), "")

    def test_delayed_shutdown_is_scheduled_not_executed_immediately(self):
        # P2-5 이후: 지연 종료는 SystemCommand 경로(execute_command)로 라우팅됨
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})
        command._current_goal = "5분 뒤에 컴퓨터 꺼줘"

        executed_cmds = []
        with patch("core.VoiceCommand.execute_command", side_effect=lambda cmd: executed_cmds.append(cmd)):
            result = command._handle_shutdown_computer({})

        # 즉시 종료 대신 지연 명령이 전달돼야 함
        self.assertIsNone(result)
        self.assertTrue(executed_cmds, "execute_command가 호출되지 않음")
        self.assertTrue(
            any("5분" in cmd for cmd in executed_cmds),
            f"5분이 포함된 명령 없음: {executed_cmds}",
        )

    def test_handle_mcp_call_routes_through_mcp_pool(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})
        fake_pool = Mock()
        fake_pool.call.return_value = "검색 결과"

        with patch("agent.mcp_client.get_mcp_pool", return_value=fake_pool):
            result = command._handle_mcp_call(
                {
                    "endpoint": "https://example.com/mcp",
                    "tool": "search_coupang_products",
                    "arguments": {"keyword": "monitor"},
                }
            )

        self.assertEqual(result, "검색 결과")
        fake_pool.call.assert_called_once_with(
            "https://example.com/mcp",
            "search_coupang_products",
            {"keyword": "monitor"},
        )

    def test_shutdown_recovery_prefers_schedule_tool_when_goal_is_delayed(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})

        recovered = command._recover_tool_calls_from_response(
            "5분 뒤에 컴퓨터 꺼줘",
            "shutdown_computer 호출",
        )

        self.assertEqual(recovered[0]["name"], "schedule_task")
        self.assertEqual(recovered[0]["arguments"]["when"], "5분 뒤")

    def test_shutdown_recovery_skips_confirmation_question_response(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})

        recovered = command._recover_tool_calls_from_response(
            "컴퓨터 꺼줘",
            "(진지) 지금 컴퓨터를 종료하면 진행 중인 작업이 모두 중단됩니다. "
            "혹시 저장 안 한 코드나 작업이 있으신가요? 정말 꺼드릴까요?",
        )

        self.assertEqual(recovered, [])

    def test_shutdown_recovery_skips_delayed_confirmation_question_response(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})

        recovered = command._recover_tool_calls_from_response(
            "5분 뒤에 컴퓨터 꺼줘",
            "5분 뒤에 컴퓨터를 종료하면 진행 중인 작업이 중단됩니다. 정말 종료할까요?",
        )

        self.assertEqual(recovered, [])

    def test_shutdown_recovery_allows_execution_statement_response(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})

        recovered = command._recover_tool_calls_from_response(
            "컴퓨터 꺼줘",
            "컴퓨터를 종료합니다. 잠시만 기다려 주세요.",
        )

        self.assertEqual(recovered[0]["name"], "shutdown_computer")
        self.assertTrue(recovered[0]["arguments"]["confirmed"])

    def test_shutdown_recovery_treats_relative_e_phrase_as_delayed_schedule(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})

        recovered = command._recover_tool_calls_from_response(
            "30분에 컴퓨터 꺼줘",
            "shutdown_computer 호출",
        )

        self.assertEqual(recovered[0]["name"], "schedule_task")
        self.assertEqual(recovered[0]["arguments"]["when"], "30분에")

    def test_recover_tool_calls_from_response_parses_web_search_call(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})

        recovered = command._recover_tool_calls_from_response(
            "오늘 LCK 경기 결과 알려줘",
            'tools.web_search(query="LCK 2026-04-10 경기 결과")',
        )

        self.assertEqual(recovered[0]["name"], "web_search")
        self.assertEqual(recovered[0]["arguments"]["query"], "LCK 2026-04-10 경기 결과")

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

    def test_extract_schedule_phrase_supports_half_hour_expression(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})

        self.assertEqual(command._extract_schedule_phrase("반 시간 뒤에 알려줘"), "반 시간 뒤")

    def test_parse_schedule_supports_korean_hour_expression(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})

        class _FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                del tz
                return cls(2026, 3, 25, 3, 31, 51)

        with patch("commands.ai_command.datetime", _FixedDateTime):
            next_run, repeat, repeat_seconds = command._parse_schedule("두 시간 뒤")

        self.assertEqual(next_run, datetime(2026, 3, 25, 5, 31, 51))
        self.assertFalse(repeat)
        self.assertEqual(repeat_seconds, 0)


if __name__ == "__main__":
    unittest.main()
