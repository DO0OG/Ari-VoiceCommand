import os
import threading
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


from commands.ai_command import AICommand
from commands.ai_fast_path import FastPathMixin
from agent.instant_ack import InstantAckTimer, should_acknowledge
from agent.agent_orchestrator import AgentRunResult
from i18n.translator import _, get_language, set_language


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


class _CancellableStreamingAssistant:
    def __init__(self):
        self.started = threading.Event()

    def chat_with_tools(self, text, include_context=True, stream_callback=None, cancel_event=None):
        del text, include_context
        if stream_callback:
            stream_callback("표시된 문장.")
        self.started.set()
        cancel_event.wait(timeout=5)
        return "표시된 문장. 아직 표시되지 않은 문장.", []


class _ToolCallAssistant:
    def __init__(self, tool_calls, response=""):
        self.tool_calls = tool_calls
        self.response = response
        self.followups = []
        self.recorded_results = []

    def chat_with_tools(self, text, include_context=True, stream_callback=None):
        del text, include_context
        if stream_callback and self.response:
            stream_callback(self.response)
        return self.response, self.tool_calls

    def feed_tool_result(self, original_text, tool_calls, results, stream_callback=None):
        del original_text, stream_callback
        self.followups.append((tool_calls, results))
        return "후속 설명 응답입니다."

    def record_tool_result(self, tool_calls, results, response):
        self.recorded_results.append((tool_calls, results, response))


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


class _ManualTimer:
    instances = []

    def __init__(self, interval, callback):
        self.interval = interval
        self.callback = callback
        self.started = False
        self.cancelled = False
        self.instances.append(self)

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def fire(self):
        if self.started and not self.cancelled:
            self.callback()


class _PhrasePicker(FastPathMixin):
    pass


class AICommandTests(unittest.TestCase):
    def setUp(self):
        _ManualTimer.instances.clear()

    def test_google_tools_do_not_call_services_when_disabled(self):
        command = AICommand(_FakeAssistant(), lambda _message: None, {"enabled": False})
        with (
            patch("core.config_manager.ConfigManager.get", return_value=False),
            patch("services.google_calendar.get_calendar_service") as calendar,
            patch("services.gmail_service.get_gmail_service") as gmail,
        ):
            results = (
                command._handle_get_calendar_events({}),
                command._handle_create_calendar_event({}),
                command._handle_send_email({}),
                command._handle_read_emails({}),
            )
        self.assertEqual(results, ("설정에서 Google 도구 사용을 켜야 합니다.",) * 4)
        calendar.assert_not_called()
        gmail.assert_not_called()

    def test_first_response_before_700ms_cancels_ack(self):
        shown = []
        ack = InstantAckTimer(lambda: shown.append("ack"), timer_factory=_ManualTimer)

        ack.start()
        self.assertEqual(_ManualTimer.instances[-1].interval, 0.7)
        ack.first_response()
        _ManualTimer.instances[-1].fire()

        self.assertEqual(shown, [])

    def test_timeout_emits_ack_only_once(self):
        shown = []
        ack = InstantAckTimer(lambda: shown.append("ack"), timer_factory=_ManualTimer)
        ack.start()
        timer = _ManualTimer.instances[-1]

        timer.fire()
        timer.fire()

        self.assertEqual(shown, ["ack"])

    def test_cancel_prevents_pending_ack(self):
        shown = []
        ack = InstantAckTimer(lambda: shown.append("ack"), timer_factory=_ManualTimer)
        ack.start()
        ack.cancel()
        _ManualTimer.instances[-1].fire()

        self.assertEqual(shown, [])

    def test_conversational_intent_is_excluded(self):
        self.assertFalse(should_acknowledge({"intent": "conversation"}))

    def test_instant_ack_disabled_setting_skips_timer(self):
        command = AICommand(_FakeAssistant(), lambda _message: None, {"enabled": False})
        cancel_event = threading.Event()

        with patch("core.config_manager.ConfigManager.get", return_value=False):
            ack = command._start_instant_ack("웹에서 검색해줘", {}, cancel_event)

        self.assertIsNone(ack)
        self.assertIsNone(command._active_instant_ack)

    def test_ack_bubble_shows_when_cached_audio_is_unavailable(self):
        command = AICommand(_FakeAssistant(), lambda _message: None, {"enabled": False})
        cancel_event = threading.Event()
        widget = Mock()
        command._active_response_cancel = cancel_event
        command.get_instant_ack_phrase = Mock(return_value="확인하겠습니다.")

        with (
            patch(
                "core.VoiceCommand._state",
                SimpleNamespace(character_widget=widget),
            ),
            patch("core.VoiceCommand.play_cached_tts", return_value=False),
        ):
            command._emit_instant_ack(cancel_event)

        widget.say.assert_called_once_with("확인하겠습니다.", duration=2500)

    def test_tool_intent_is_included(self):
        self.assertTrue(should_acknowledge({"intent": "web"}))
        self.assertTrue(should_acknowledge({"intent": "automation"}))
        self.assertTrue(
            should_acknowledge({"intent": "conversation", "force_tool": True})
        )

    def test_persona_fixed_response_overrides_pool_and_avoids_repeat(self):
        settings = {
            "fixed_responses": {
                "instant_ack": {"calm": ["확인할게요.", "곧 살펴볼게요."]},
            },
        }
        picker = _PhrasePicker()

        def get_setting(key, default=None):
            return settings.get(key, default)

        with (
            patch("core.config_manager.ConfigManager.get", side_effect=get_setting),
            patch("core.mood_state.get_mood_state", return_value=None),
            patch("commands.ai_fast_path._", side_effect=lambda message: message),
        ):
            first = picker.get_instant_ack_phrase()
            second = picker.get_instant_ack_phrase()

        phrases = settings["fixed_responses"]["instant_ack"]["calm"]
        self.assertIn(first, phrases)
        self.assertIn(second, phrases)
        self.assertNotEqual(first, second)

    def test_cancel_current_response_cancels_active_ack(self):
        command = AICommand(_FakeAssistant(), lambda _message: None, {"enabled": False})
        cancel_event = threading.Event()
        ack = Mock()
        command._active_response_cancel = cancel_event
        command._active_instant_ack = ack

        self.assertTrue(command.cancel_current_response())

        self.assertTrue(cancel_event.is_set())
        ack.cancel.assert_called_once_with()

    def test_memory_remember_requires_this_turn_explicit_request_and_uses_tool_source(self):
        command = AICommand(_FakeAssistant(), lambda _message: None, {"enabled": False})
        command._current_goal = "기억해: favorite drink=tea"
        context = Mock()
        memory_index = Mock()

        with patch("memory.user_context.get_context_manager", return_value=context), patch(
            "memory.memory_index.get_memory_index", return_value=memory_index
        ):
            result = command._handle_memory_remember(
                {"key": "unrelated", "value": "unrequested detail"}
            )

        context.record_fact.assert_called_once_with(
            "favorite drink", "tea", source="user_request", confidence=1.0,
            ttl_days=0, force=True,
        )
        memory_index.index_fact.assert_called_once_with("favorite drink", "tea", 1.0)
        self.assertEqual(result, "기억했어요: tea")

    def test_memory_remember_rejects_non_explicit_turn(self):
        command = AICommand(_FakeAssistant(), lambda _message: None, {"enabled": False})
        command._current_goal = "I enjoy tea"

        result = command._handle_memory_remember(
            {"key": "favorite drink", "value": "tea"}
        )

        self.assertEqual(result, "이번 요청에서 명시적으로 기억해 달라고 하지 않았어요.")

    def test_memory_forget_reuses_confirmation_before_deleting(self):
        command = AICommand(_FakeAssistant(), lambda _message: None, {"enabled": False})
        command._current_goal = "forget favorite drink"
        context = Mock()
        context.get_facts_snapshot.return_value = {
            "favorite drink": {"value": "tea"}
        }
        context.delete_fact.return_value = True

        with patch("memory.user_context.get_context_manager", return_value=context), patch(
            "agent.confirmation_manager.get_confirmation_manager"
        ) as get_manager:
            get_manager.return_value.request_confirmation.return_value = True
            result = command._handle_memory_forget({"key": "unrelated"})

        get_manager.return_value.request_confirmation.assert_called_once()
        context.delete_fact.assert_called_once_with(
            "favorite drink", expected_value="tea"
        )
        self.assertEqual(result, "기억을 잊었어요: favorite drink")

    def test_memory_search_passes_kind_and_since_filters(self):
        command = AICommand(_FakeAssistant(), lambda _message: None, {"enabled": False})
        index = Mock()
        index.search.return_value = [
            SimpleNamespace(timestamp="2026-09-29T10:00:00", content="favorite drink: tea"),
            SimpleNamespace(
                timestamp="2026-09-29T10:00:00",
                content="Health diagnosis: private details",
            ),
        ]

        with patch("memory.memory_index.get_memory_index", return_value=index):
            result = command._handle_memory_search({
                "query": "tea", "kind": "fact", "since": "2026-09-29"
            })

        index.search.assert_called_once_with(
            "tea", limit=5, kind="fact", since="2026-09-29"
        )
        self.assertIn("favorite drink: tea", result)
        self.assertNotIn("private details", result)

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

    def test_get_current_time_uses_active_language_translation(self):
        previous_language = get_language()
        set_language("en")
        self.addCleanup(set_language, previous_language)

        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})

        class _FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                del tz
                return cls(2026, 3, 25, 16, 48, 0)

        with patch("commands.ai_command.datetime", _FixedDateTime):
            result = command._handle_get_current_time({})

        expected_time = _("{ampm} {hour}시 {minute}분").format(
            ampm=_("오후"),
            hour=4,
            minute=48,
        )
        self.assertEqual(result, _("현재 시간은 {time}입니다.").format(time=expected_time))

    def test_preface_response_filters_ellipsis_placeholder(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})

        self.assertFalse(command._should_emit_preface_response("(평온)..."))
        self.assertFalse(command._should_emit_preface_response("get_current_time"))
        self.assertFalse(command._should_emit_preface_response('{"tool_calls": []}'))
        self.assertFalse(
            command._should_emit_preface_response(chr(96) * 3 + "json\n{}")
        )
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

    def test_sanitize_user_facing_text_removes_trailing_symbol_tokens(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})

        self.assertEqual(
            command._sanitize_user_facing_text(r"The time is 23:09. #]# [<>|{}] \\"),
            "The time is 23:09.",
        )

    def test_sanitize_user_facing_text_keeps_normal_trailing_punctuation(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})

        for text in (
            "Sure~",
            "Really!?",
            "Done...",
            "(\uC6C3\uC74C)",
        ):
            with self.subTest(text=text):
                self.assertEqual(command._sanitize_user_facing_text(text), text)

    def test_run_interaction_strips_trailing_symbol_tokens_before_history(self):
        class _Assistant:
            def chat_with_tools(self, text, include_context=True):
                del text, include_context
                return "The time is 23:09. #]#", []

        command = AICommand(_Assistant(), lambda msg: None, {"enabled": False})
        with (
            patch.object(command, "try_fast_path", return_value=None),
            patch.object(command, "_get_skill_context", return_value={}),
            patch.object(command, "_start_instant_ack", return_value=None),
            patch("memory.conversation_history.add_conversation") as add_conversation,
        ):
            response = command.run_interaction("What time is it?")

        self.assertEqual(response, "The time is 23:09.")
        self.assertEqual(add_conversation.call_args.args[1], "The time is 23:09.")

    def test_sanitize_user_facing_text_discards_json_and_code_fences(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})

        self.assertEqual(command._sanitize_user_facing_text('{"tool_calls": []}'), "")
        code_fence_response = chr(96) * 3 + "json\n{}\n" + chr(96) * 3
        self.assertEqual(command._sanitize_user_facing_text(code_fence_response), "")

    def test_run_agent_task_skips_long_followup_response(self):
        command = AICommand(_AgentTaskAssistant(), lambda msg: None, {"enabled": False})
        command._dispatch["run_agent_task"] = lambda args: "작업 완료. Ari autonomy test 폴더에 summary.md를 저장했습니다."

        combined = command.run_interaction('바탕화면에 "Ari autonomy test" 폴더를 만들고 보고서를 저장해줘')

        self.assertIn("작업 완료.", combined)
        self.assertNotIn("읽히면 안 됩니다", combined)

    def test_simple_tool_records_local_response_without_followup(self):
        assistant = _ToolCallAssistant([{
            "id": "tool_1",
            "name": "launch_app",
            "arguments": {"name": "메모장"},
        }])
        command = AICommand(assistant, lambda message: None, {"enabled": False})
        command.try_fast_path = lambda text: None
        command._get_skill_context = lambda text: {"skills": []}
        command._dispatch["launch_app"] = lambda args: args["name"]
        streamed = []

        tool_results = []
        with patch("core.config_manager.ConfigManager.get", return_value=True), \
             patch("memory.conversation_history.add_conversation") as add_conversation:
            response = command.run_interaction(
                "메모장을 열어줘",
                stream_callback=streamed.append,
                tool_result_callback=lambda name, result: tool_results.append((name, result)),
            )

        self.assertIn("앱을 실행했습니다.", response)
        self.assertEqual(assistant.followups, [])
        self.assertEqual(len(assistant.recorded_results), 1)
        self.assertIn("앱을 실행했습니다.", assistant.recorded_results[0][2])
        self.assertEqual(streamed, ["앱을 실행했습니다."])
        self.assertEqual(tool_results, [("launch_app", "메모장")])
        add_conversation.assert_called_once()
        self.assertIn("앱을 실행했습니다.", add_conversation.call_args.args[1])

    def test_tool_followup_handles_failures_and_empty_results(self):
        cases = (
            ("adjust_volume", {"direction": "up"}, _("볼륨 조절 실패"), "볼륨을 올려줘"),
            ("adjust_volume", {"direction": "up"}, "", "볼륨을 올려줘"),
            (
                "set_timer",
                {"minutes": 1},
                _("타이머는 최대 {max}개까지 설정할 수 있습니다.").format(max=10),
                "타이머를 설정해줘",
            ),
        )
        for tool_name, arguments, result, text in cases:
            with self.subTest(tool_name=tool_name, result=result):
                assistant = _ToolCallAssistant([{
                    "id": "tool_1",
                    "name": tool_name,
                    "arguments": arguments,
                }])
                command = AICommand(assistant, lambda message: None, {"enabled": False})
                command.try_fast_path = lambda text: None
                command._get_skill_context = lambda text: {"skills": []}
                command._dispatch[tool_name] = lambda args: result

                with patch("core.config_manager.ConfigManager.get", return_value=True):
                    response = command.run_interaction(text)

                self.assertEqual(len(assistant.followups), 1)
                self.assertEqual(assistant.recorded_results[0][1], [result])
                self.assertEqual(assistant.recorded_results[0][2], "")
                self.assertIn("후속 설명 응답입니다.", response)

    def test_none_tool_result_is_recorded_as_completed_without_value(self):
        assistant = _ToolCallAssistant([{
            "id": "tool_1",
            "name": "take_screenshot",
            "arguments": {},
        }])
        command = AICommand(assistant, lambda message: None, {"enabled": False})
        command.try_fast_path = lambda text: None
        command._get_skill_context = lambda text: {"skills": []}
        command._dispatch["take_screenshot"] = lambda args: None

        command.run_interaction("스크린샷을 저장해줘")

        self.assertEqual(
            assistant.recorded_results[0][1],
            [_("작업은 완료됐지만 확인 가능한 결과를 받지 못했습니다.")],
        )

    def test_tool_exception_result_instructs_followup_not_to_claim_success(self):
        command = AICommand(_FakeAssistant(), lambda message: None, {"enabled": False})
        command._dispatch["launch_app"] = Mock(side_effect=FileNotFoundError("네이버"))

        results = command._execute_tool_calls([{
            "name": "launch_app",
            "arguments": {"name": "네이버"},
        }])

        self.assertIn("도구 실행 실패", results[0])
        self.assertIn("성공한 실행 결과가 확인되지 않았습니다", results[0])
        self.assertIn("대체 동작을 했다고 말하지 마세요", results[0])
        self.assertTrue(command._fast_handler_failed(results[0]))

    def test_local_launch_app_response_describes_browser_fallback(self):
        command = AICommand(_FakeAssistant(), lambda message: None, {"enabled": False})

        response = command._build_local_tool_response(
            "launch_app",
            "https://www.naver.com",
            True,
        )

        self.assertEqual(
            response,
            _("기본 브라우저로 웹사이트를 열었습니다: {url}").format(
                url="https://www.naver.com"
            ),
        )

    def test_multiple_tool_calls_always_use_followup(self):
        assistant = _ToolCallAssistant([
            {"id": "tool_1", "name": "launch_app", "arguments": {"name": "앱"}},
            {"id": "tool_2", "name": "take_screenshot", "arguments": {}},
        ])
        command = AICommand(assistant, lambda message: None, {"enabled": False})
        command.try_fast_path = lambda text: None
        command._get_skill_context = lambda text: {"skills": []}
        command._dispatch["launch_app"] = lambda args: args["name"]
        command._dispatch["take_screenshot"] = lambda args: "shot.png"

        with patch("core.config_manager.ConfigManager.get", return_value=True):
            response = command.run_interaction("앱을 열고 화면도 저장해줘")

        self.assertEqual(len(assistant.followups), 1)
        self.assertEqual(assistant.recorded_results[0][1], ["앱", "shot.png"])
        self.assertIn("후속 설명 응답입니다.", response)

    def test_explanation_request_uses_followup_for_simple_tool(self):
        assistant = _ToolCallAssistant([{
            "id": "tool_1",
            "name": "launch_app",
            "arguments": {"name": "메모장"},
        }])
        command = AICommand(assistant, lambda message: None, {"enabled": False})
        command.try_fast_path = lambda text: None
        command._get_skill_context = lambda text: {"skills": []}
        command._dispatch["launch_app"] = lambda args: args["name"]

        with patch("core.config_manager.ConfigManager.get", return_value=True):
            response = command.run_interaction("메모장을 열고 실행 결과를 설명해줘")

        self.assertEqual(len(assistant.followups), 1)
        self.assertEqual(assistant.recorded_results[0][1], ["메모장"])
        self.assertIn("후속 설명 응답입니다.", response)

    def test_weather_result_uses_local_response_when_it_is_usable(self):
        assistant = _ToolCallAssistant([{
            "id": "tool_1",
            "name": "get_weather",
            "arguments": {},
        }])
        command = AICommand(assistant, lambda message: None, {"enabled": False})
        command.try_fast_path = lambda text: None
        command._get_skill_context = lambda text: {"skills": []}
        command._dispatch["get_weather"] = lambda args: "현재 날씨는 맑음입니다. 기온은 20도입니다."

        with patch("core.config_manager.ConfigManager.get", return_value=True):
            response = command.run_interaction("오늘 날씨 알려줘")

        self.assertEqual(assistant.followups, [])
        self.assertIn("현재 날씨는 맑음입니다.", response)

    def test_ambiguous_action_result_uses_followup(self):
        assistant = _ToolCallAssistant([{
            "id": "tool_1",
            "name": "focus_window",
            "arguments": {"title": "메모장"},
        }])
        command = AICommand(assistant, lambda message: None, {"enabled": False})
        command.try_fast_path = lambda text: None
        command._get_skill_context = lambda text: {"skills": []}
        command._dispatch["focus_window"] = lambda args: '{"focused": false, "title": "메모장"}'

        with patch("core.config_manager.ConfigManager.get", return_value=True):
            response = command.run_interaction("메모장 창으로 전환해줘")

        self.assertEqual(len(assistant.followups), 1)
        self.assertEqual(
            assistant.recorded_results[0][1],
            ['{"focused": false, "title": "메모장"}'],
        )
        self.assertIn("후속 설명 응답입니다.", response)

    def test_disabling_tool_followup_policy_keeps_llm_followup(self):
        assistant = _ToolCallAssistant([{
            "id": "tool_1",
            "name": "launch_app",
            "arguments": {"name": "메모장"},
        }])
        command = AICommand(assistant, lambda message: None, {"enabled": False})
        command.try_fast_path = lambda text: None
        command._get_skill_context = lambda text: {"skills": []}
        command._dispatch["launch_app"] = lambda args: args["name"]

        with patch("core.config_manager.ConfigManager.get", return_value=False):
            response = command.run_interaction("메모장을 열어줘")

        self.assertEqual(len(assistant.followups), 1)
        self.assertEqual(assistant.recorded_results[0][1], ["메모장"])
        self.assertIn("후속 설명 응답입니다.", response)

    def test_run_interaction_passes_stream_callback_when_supported(self):
        command = AICommand(_StreamingAssistant(), lambda msg: None, {"enabled": False})
        streamed = []

        combined = command.run_interaction("안녕", stream_callback=streamed.append)

        self.assertEqual("".join(streamed), "안녕하세요")
        self.assertIn("안녕하세요", combined)

    def test_cancelled_stream_records_only_displayed_text_and_marker(self):
        assistant = _CancellableStreamingAssistant()
        command = AICommand(assistant, lambda message: None, {"enabled": False})
        streamed = []
        result = []
        with (
            patch.object(command, "try_fast_path", return_value=None),
            patch.object(command, "_get_skill_context", return_value={}),
            patch("memory.conversation_history.add_conversation") as add_conversation,
        ):
            worker = threading.Thread(
                target=lambda: result.append(
                    command.run_interaction(
                        "간단한 인사",
                        stream_callback=streamed.append,
                    )
                )
            )
            worker.start()
            self.assertTrue(assistant.started.wait(timeout=2))
            self.assertTrue(command.cancel_current_response())
            worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(streamed, ["표시된 문장."])
        self.assertEqual(
            result,
            ["표시된 문장.\n\n(응답 중단)"],
        )
        add_conversation.assert_called_once()
        self.assertEqual(add_conversation.call_args.args[1], result[0])

    def test_busy_run_interaction_notifies_once_per_five_seconds(self):
        now = [100.0]
        command = AICommand(
            _FakeAssistant(),
            lambda msg: None,
            {"enabled": False},
            time_fn=lambda: now[0],
        )
        spoken = []
        command._exec_lock.acquire()
        try:
            command._run_interaction("안녕", spoken.append)
            now[0] = 104.9
            command._run_interaction("안녕", spoken.append)
            self.assertEqual(spoken, [_("아직 이전 요청을 처리하고 있어요.")])
            now[0] = 105.0
            command._run_interaction("안녕", spoken.append)
            self.assertEqual(
                spoken,
                [_("아직 이전 요청을 처리하고 있어요.")] * 2,
            )
        finally:
            command._exec_lock.release()

    def test_interrupt_is_handled_while_execution_lock_is_held(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})
        spoken = []
        with patch.object(command.orchestrator, "interrupt") as interrupt:
            command._exec_lock.acquire()
            try:
                command._run_interaction("stop", spoken.append)
            finally:
                command._exec_lock.release()

        interrupt.assert_called_once_with()
        self.assertEqual(spoken, [_("진행 중인 작업을 중단할게요.")])

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

    def test_shutdown_recovery_skips_english_confirmation_question_response(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})

        recovered = command._recover_tool_calls_from_response(
            "turn off the computer",
            "Shutting down the computer will stop ongoing work. "
            "Are you sure you want me to shut it down?",
        )

        self.assertEqual(recovered, [])

    def test_shutdown_recovery_skips_japanese_confirmation_question_response(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})

        recovered = command._recover_tool_calls_from_response(
            "コンピューターを終了して",
            "コンピューターをシャットダウンすると作業が中断されます。本当に終了しますか？",
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

    def test_shutdown_recovery_allows_english_execution_statement_response(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})

        recovered = command._recover_tool_calls_from_response(
            "turn off the computer",
            "Shutting down the computer. Please wait a moment.",
        )

        self.assertEqual(recovered[0]["name"], "shutdown_computer")
        self.assertTrue(recovered[0]["arguments"]["confirmed"])

    def test_shutdown_recovery_allows_japanese_execution_statement_response(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})

        recovered = command._recover_tool_calls_from_response(
            "コンピューターを終了して",
            "コンピューターを終了します。少々お待ちください。",
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

    def test_shutdown_recovery_ignores_shutdown_mentioned_only_by_model(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})

        recovered = command._recover_tool_calls_from_response(
            "시간 알려 주지 마",
            "Okay, the user said don't tell me the time. I should not call get_current_time "
            "or shutdown_computer here.",
        )

        self.assertEqual(recovered, [])

    def test_shutdown_recovery_ignores_negated_shutdown_request(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})

        for user_text, response in (
            ("컴퓨터 끄지 마", "알겠습니다. 컴퓨터를 종료하지 않을게요."),
            ("don't shut down the computer", "Okay, I won't shut down the computer."),
            ("パソコンをシャットダウンしないで", "シャットダウンしません。"),
        ):
            with self.subTest(user_text=user_text):
                self.assertEqual(command._recover_tool_calls_from_response(user_text, response), [])

    def test_recover_tool_calls_from_response_parses_web_search_call(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})

        recovered = command._recover_tool_calls_from_response(
            "오늘 LCK 경기 결과 알려줘",
            'tools.web_search(query="LCK 2026-04-10 경기 결과")',
        )

        self.assertEqual(recovered[0]["name"], "web_search")
        self.assertEqual(recovered[0]["arguments"]["query"], "LCK 2026-04-10 경기 결과")

    def test_recover_tool_calls_from_json_response(self):
        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})

        recovered = command._recover_tool_calls_from_response(
            "지금 몇 시야?",
            '{"tool_calls":[{"id":"call-1","function":'
            '{"name":"get_current_time","arguments":"{}"}}]}',
        )

        self.assertEqual(recovered, [{
            "id": "call-1",
            "name": "get_current_time",
            "arguments": {},
        }])

    def test_json_tool_call_response_executes_without_speaking_json(self):
        assistant = _FakeAssistant()
        assistant.chat_with_tools = lambda text, include_context=True: (
            '{"tool_calls":[{"name":"json_echo","arguments":{"value":"done"}}]}',
            [],
        )
        command = AICommand(assistant, lambda msg: None, {"enabled": False})
        command._dispatch["json_echo"] = lambda args: "JSON 복구 완료"

        result = command.run_interaction("테스트 실행")

        self.assertEqual(result, "JSON 복구 완료")
        self.assertNotIn("tool_calls", result)

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

    def test_parse_schedule_supports_translated_daily_pattern(self):
        previous_language = get_language()
        set_language("en")
        self.addCleanup(set_language, previous_language)

        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})

        class _FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                del tz
                return cls(2026, 3, 25, 3, 31, 51)

        schedule_text = f"{_('매일')} {_('오전')} 9{_('시')}"

        with patch("commands.ai_command.datetime", _FixedDateTime):
            next_run, repeat, repeat_seconds = command._parse_schedule(schedule_text)

        self.assertEqual(next_run, datetime(2026, 3, 25, 9, 0, 0))
        self.assertTrue(repeat)
        self.assertEqual(repeat_seconds, 86400)

    def test_handle_set_timer_localizes_missing_duration_prompt(self):
        previous_language = get_language()
        set_language("ja")
        self.addCleanup(set_language, previous_language)

        spoken = []
        command = AICommand(_FakeAssistant(), spoken.append, {"enabled": False})

        result = command._handle_set_timer({"minutes": 0, "seconds": 0})

        self.assertIsNone(result)
        self.assertEqual(spoken, [_("타이머 시간을 말씀해 주세요.")])

    def test_handle_get_screen_status_uses_character_current_screen(self):
        from PySide6.QtCore import QRect

        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})
        current_screen = SimpleNamespace(geometry=lambda: QRect(1920, 0, 2560, 1440))
        primary_screen = SimpleNamespace(geometry=lambda: QRect(0, 0, 1920, 1080))
        character_widget = SimpleNamespace(
            _current_screen=current_screen,
            get_screen_geometry=lambda: QRect(1920, 0, 2560, 1400),
        )
        fake_state = SimpleNamespace(character_widget=character_widget)

        with (
            patch("core.VoiceCommand._state", fake_state),
            patch("PySide6.QtWidgets.QApplication.primaryScreen", return_value=primary_screen),
        ):
            result = command._handle_get_screen_status({})

        self.assertIn("2560x1400", result)
        self.assertIn("2560x1440", result)

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

    def test_agent_dashboard_skipped_outside_gui_thread(self):
        """명령 실행 스레드에서 Qt 위젯을 만들면 앱이 멈추므로 생성하지 않는다."""
        from PySide6.QtCore import QThread

        command = AICommand(_FakeAssistant(), lambda msg: None, {"enabled": False})
        other_thread = QThread()
        fake_app = SimpleNamespace(thread=lambda: other_thread)

        with patch("core.config_manager.ConfigManager.get", return_value=True):
            with patch("PySide6.QtWidgets.QApplication.instance", return_value=fake_app):
                with patch("ui.agent_dashboard.AgentDashboard") as dashboard_cls:
                    result = command._maybe_show_agent_dashboard("목표")

        self.assertIsNone(result)
        dashboard_cls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
