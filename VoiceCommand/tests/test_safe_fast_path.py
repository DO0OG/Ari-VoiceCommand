import builtins
import gettext
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from commands.ai_command import AICommand
from tests.test_decision_engine import _simple_skill_context, _write_model


class SafeFastPathTests(unittest.TestCase):
    def setUp(self):
        from agent.decision.engine import LocalDecisionEngine

        self.assistant = Mock()
        self.assistant.chat_with_tools.return_value = ("기존 응답", [])
        self.command = AICommand(self.assistant, Mock(), {"enabled": True})
        self.command._get_skill_context = Mock(return_value=_simple_skill_context())
        self.command._should_escalate_to_agent_task = Mock(return_value=False)
        self.command._record_user_pattern = Mock()
        self.command._recover_tool_calls_from_response = Mock(return_value=[])
        self.local = LocalDecisionEngine("unused")
        self.command._decision_engine = self.local
        self.handlers = {name: Mock(return_value="처리 결과") for name in self.command._dispatch}
        self.command._dispatch.update(self.handlers)
        values = {
            "local_decision_mode": "fast",
            "local_decision_engine_enabled": True,
            "local_decision_backend": "linear",
            "local_decision_threshold": 0.92,
            "local_decision_direct_execution": True,
        }
        self.enterContext(patch("core.config_manager.ConfigManager.get", side_effect=lambda key, default=None: values.get(key, default)))
        self.history = self.enterContext(patch("memory.conversation_history.add_conversation"))
        self.events = self.enterContext(patch("core.VoiceCommand.emit_plugin_event"))

    def predict(self, name, confidence=1.0, margin=1.0):
        from agent.decision.engine import DecisionResult

        self.local.choice = Mock(return_value=DecisionResult(
            name, {name: confidence}, confidence, margin, "linear", 0.1,
        ))

    def assert_fallback(self, text):
        self.command.run_interaction(text)
        self.assistant.chat_with_tools.assert_called_once_with(text, include_context=True)
        self.assistant.feed_tool_result.assert_not_called()
        for handler in self.handlers.values():
            handler.assert_not_called()

    def test_success_dispatches_once_without_followup_recovery_or_raw_history(self):
        self.predict("get_current_time")
        self.command.run_interaction("what time is it")
        self.handlers["get_current_time"].assert_called_once_with({})
        self.assistant.chat_with_tools.assert_not_called()
        self.assistant.feed_tool_result.assert_not_called()
        self.command._recover_tool_calls_from_response.assert_not_called()
        self.command._record_user_pattern.assert_not_called()
        self.history.assert_not_called()
        self.events.assert_not_called()
        self.assertFalse(self.command._exec_lock.locked())

    def test_low_confidence_uses_existing_path_once(self):
        self.predict("get_current_time", confidence=0.91)
        self.assert_fallback("what time is it")

    def test_low_margin_uses_existing_path_once(self):
        self.predict("get_current_time", margin=0.29)
        self.assert_fallback("what time is it")

    def test_result_callback_and_output_bindings_are_preserved(self):
        self.predict("get_current_time")
        original_tts = self.command.tts_wrapper
        original_exec_tts = self.command.executor.tts_wrapper
        original_orch_tts = self.command.orchestrator.tts
        result_callback = Mock()
        self.command.run_interaction("what time is it", tool_result_callback=result_callback)
        result_callback.assert_called_once_with("get_current_time", "처리 결과")
        self.assertIs(self.command.tts_wrapper, original_tts)
        self.assertIs(self.command.executor.tts_wrapper, original_exec_tts)
        self.assertIs(self.command.orchestrator.tts, original_orch_tts)

    def test_conflicting_window_request_uses_existing_path(self):
        self.predict("focus_window")
        self.assert_fallback("Close the Chrome window")

    def test_compound_request_never_executes_partial_action(self):
        self.predict("play_youtube")
        self.assert_fallback("크롬을 켜고 유튜브에서 재즈를 찾아 재생해줘")

    def test_forbidden_action_at_full_confidence_uses_existing_path(self):
        self.predict("delete_file")
        self.assert_fallback("delete this file")

    def test_missing_weights_preserve_existing_path(self):
        with tempfile.TemporaryDirectory() as directory:
            self.local.model_dir = Path(directory) / "missing"
            self.assert_fallback("what time is it")

    def test_corrupt_weights_preserve_existing_path(self):
        with tempfile.TemporaryDirectory() as directory:
            _write_model(directory)
            weights = Path(directory) / "weights.npz"
            weights.write_bytes(weights.read_bytes() + b"corrupt")
            self.local.model_dir = directory
            self.assert_fallback("what time is it")
            self.assertTrue(self.local._load_attempted)
            self.assertIsNone(self.local._scorer)

    def test_real_weights_reach_single_dispatch(self):
        import numpy as np
        from agent.decision.engine import candidate_names

        with tempfile.TemporaryDirectory() as directory:
            labels = candidate_names()
            bias = np.zeros(len(labels), dtype=np.float32)
            bias[labels.index("get_current_time")] = 30
            _write_model(directory, bias=bias)
            self.local.model_dir = directory
            self.command.run_interaction("what time is it")
        self.handlers["get_current_time"].assert_called_once_with({})
        self.assistant.chat_with_tools.assert_not_called()
        self.assistant.feed_tool_result.assert_not_called()

    def test_lock_blocks_reentrant_input_and_releases_after_execution(self):
        self.predict("get_current_time")
        lock_observations = []

        def handler(args):
            lock_observations.append(self.command._exec_lock.locked())
            self.command.run_interaction("what time is it")
            return "현재 시각"

        self.handlers["get_current_time"].side_effect = handler
        with self.assertLogs(level="WARNING") as captured:
            self.command.run_interaction("what time is it")
        self.assertNotIn("what time is it", "\n".join(captured.output))
        self.assertEqual(lock_observations, [True])
        self.handlers["get_current_time"].assert_called_once()
        self.assistant.chat_with_tools.assert_not_called()
        self.assertFalse(self.command._exec_lock.locked())

    def test_handler_failure_does_not_retry_through_conversation(self):
        self.predict("take_screenshot")
        self.handlers["take_screenshot"].side_effect = RuntimeError("실행 실패")
        self.command.run_interaction("take a screenshot")
        self.handlers["take_screenshot"].assert_called_once()
        self.assistant.chat_with_tools.assert_not_called()
        self.assistant.feed_tool_result.assert_not_called()
        self.assertFalse(self.command._exec_lock.locked())

    def test_empty_handler_failure_reports_fixed_message_once(self):
        from i18n.translator import _

        self.predict("take_screenshot")
        self.handlers["take_screenshot"].return_value = None
        output = self.command.run_interaction("take a screenshot")
        self.assertEqual(output, _("요청한 작업을 완료하지 못했어요."))
        self.handlers["take_screenshot"].assert_called_once()
        self.assistant.chat_with_tools.assert_not_called()
        self.assertEqual(self.local.metrics()["execution_failed"], 1)

    def test_rejection_before_dispatch_keeps_conversation_path(self):
        from agent.decision.engine import FastPathResult

        self.command.try_fast_path = Mock(return_value=FastPathResult(
            "delete_file", {}, 1.0, 1.0, "linear", True,
        ))
        self.assert_fallback("delete this file")

    def test_direct_run_updates_local_counters(self):
        self.predict("get_current_time")
        self.command.run_interaction("what time is it")
        counts = self.local.metrics()
        self.assertEqual(counts["fast_selected"], 1)
        self.assertEqual(counts["fast_executed"], 1)
        self.assertEqual(counts["llm_calls_saved"], 1)

    def test_tool_execution_log_omits_user_supplied_arguments(self):
        query = "private phrase 4821"
        with self.assertLogs(level="INFO") as captured:
            self.command._execute_tool_calls([{
                "name": "web_search",
                "arguments": {"query": query},
            }])

        self.assertNotIn(query, "\n".join(captured.output))
        self.handlers["web_search"].assert_called_once_with({"query": query})

    def test_voice_command_event_preserves_original_text_and_shape(self):
        spoken = "private phrase 4821"
        self.command.run_interaction(spoken)

        self.events.assert_called_once()
        event_name, payload = self.events.call_args.args
        self.assertEqual(event_name, "on_voice_command")
        self.assertEqual(payload["text"], spoken)
        self.assertEqual(payload["response"], "기존 응답")

    def test_malformed_mcp_argument_log_omits_user_text(self):
        spoken_arguments = "private phrase 4821"
        with patch("agent.mcp_client.get_mcp_pool") as get_pool:
            with self.assertLogs(level="WARNING") as captured:
                result = self.command._handle_mcp_call({
                    "endpoint": "local",
                    "tool": "echo",
                    "arguments": spoken_arguments,
                })

        self.assertEqual(result, get_pool.return_value.call.return_value)
        get_pool.return_value.call.assert_called_once_with("local", "echo", {"input": spoken_arguments})
        self.assertNotIn(spoken_arguments, "\n".join(captured.output))

    def test_successful_payload_with_error_word_is_not_a_failure(self):
        from i18n.translator import _

        self.predict("take_screenshot")
        self.handlers["take_screenshot"].return_value = "C:/error-report/capture.png"
        output = self.command.run_interaction("take a screenshot")
        self.assertEqual(output, _("스크린샷을 저장했습니다: {path}").format(path="C:/error-report/capture.png"))
        self.handlers["take_screenshot"].assert_called_once()
        self.assistant.chat_with_tools.assert_not_called()

    def test_screenshot_uses_existing_handler_without_raw_audit_goal(self):
        self.predict("take_screenshot")
        self.command._dispatch["take_screenshot"] = self.command._handle_take_screenshot
        with patch.object(self.command.executor._automation, "screenshot", return_value="capture.png") as capture:
            with patch.object(self.command.executor, "_log_audit") as audit:
                self.command.run_interaction("take a screenshot")
        capture.assert_called_once_with(None)
        audit.assert_called_once()
        self.assertNotIn("take a screenshot", str(audit.call_args))
        self.assistant.chat_with_tools.assert_not_called()
        self.history.assert_not_called()

    def test_all_candidates_abstain_on_unsafe_or_compound_sentences(self):
        from agent.decision.candidates import DIRECT_ALLOWLIST

        sentences = (
            "Close the Chrome window",
            "Open a fresh Chrome window",
            "Chromeのウィンドウを閉じて",
            "크롬을 켜고 유튜브에서 재즈를 찾아 재생해줘",
            "what time is it and take a screenshot",
            "take a screenshot then mute the volume",
            "take a screenshot open Chrome",
            "after taking a screenshot increase the volume by 10%",
            "시간 알려줘 그리고 화면 캡처해줘",
            "화면 캡처하고 나서 음소거해줘",
            "화면 캡처해줘 음소거해줘",
            "スクリーンショットを撮ってそれから音量を下げて",
            "スクリーンショットを撮って音量を下げて",
            "音量を10%上げてからスクリーンショットを撮って",
            "don't take a screenshot",
            "do not mute the volume",
            "화면 캡처하지 마",
            "音量を上げないで",
            "소리 너무 큰 이유가 뭐야?",
            "why is the volume so loud?",
            "音量が大きいのはなぜ?",
            "increase volume by 101%",
            "increase volume by -10%",
            "increase volume by 10.5%",
            "set volume to 50",
            "turn the volume up and down by 10%",
            "take a screenshot of the second monitor",
            "take a screenshot and save it to private.png",
            "why take a screenshot?",
            "I took a screenshot yesterday",
            "explain what time means",
            "do you know how to list running apps?",
            "if I ask you later take a screenshot",
            "remind me to take a screenshot",
            "repeat the words take a screenshot",
            "what time is it in London",
            "take a screenshot take a screenshot",
            "take two screenshots",
            "increase volume to 50%",
            "increase volume by 10% decrease volume by 5%",
            "볼륨을 50%로 올려줘",
            "화면 캡처하는 방법 알려줘",
            "내일 화면 캡처해줘",
            "スクリーンショットの撮り方を教えて",
            "音量を50%に上げて",
        )
        for name in DIRECT_ALLOWLIST:
            self.predict(name)
            for sentence in sentences:
                with self.subTest(name=name, sentence=sentence):
                    self.assertIsNone(self.local.try_fast_path(sentence))

    def test_every_permanently_forbidden_candidate_abstains_at_full_confidence(self):
        from agent.decision.candidates import PERMANENTLY_FORBIDDEN

        for name in PERMANENTLY_FORBIDDEN:
            with self.subTest(name=name):
                self.predict(name)
                self.assertIsNone(self.local.try_fast_path("what time is it"))

    def test_wrong_allowed_candidate_cannot_override_sentence_meaning(self):
        from agent.decision.candidates import DIRECT_ALLOWLIST

        sentences = {
            "get_current_time": "what time is it",
            "get_running_apps": "list running apps",
            "take_screenshot": "take a screenshot",
            "adjust_volume": "mute the volume",
        }
        for expected, sentence in sentences.items():
            for proposed in DIRECT_ALLOWLIST - {expected}:
                with self.subTest(expected=expected, proposed=proposed):
                    self.predict(proposed)
                    self.assertIsNone(self.local.try_fast_path(sentence))

    def test_positive_requests_in_three_languages_dispatch_once(self):
        cases = (
            ("get_current_time", "지금 몇 시야?", {}),
            ("get_current_time", "what time is it", {}),
            ("get_current_time", "今何時?", {}),
            ("get_running_apps", "실행 중인 앱 목록 보여줘", {}),
            ("get_running_apps", "list running apps", {}),
            ("get_running_apps", "実行中のアプリを教えて", {}),
            ("take_screenshot", "화면 캡처해줘", {}),
            ("take_screenshot", "take a screenshot", {}),
            ("take_screenshot", "スクリーンショットを撮って", {}),
            ("adjust_volume", "볼륨을 10% 올려줘", {"direction": "up", "amount": 10}),
            ("adjust_volume", "increase volume by 10%", {"direction": "up", "amount": 10}),
            ("adjust_volume", "音量を10%上げて", {"direction": "up", "amount": 10}),
            ("adjust_volume", "볼륨을 20% 내려줘", {"direction": "down", "amount": 20}),
            ("adjust_volume", "lower volume by 20%", {"direction": "down", "amount": 20}),
            ("adjust_volume", "音量を20%下げて", {"direction": "down", "amount": 20}),
        )
        for name, sentence, args in cases:
            with self.subTest(name=name, sentence=sentence):
                self.assistant.reset_mock()
                for handler in self.handlers.values():
                    handler.reset_mock()
                self.predict(name)
                self.command.run_interaction(sentence)
                self.handlers[name].assert_called_once_with(args)
                self.assistant.chat_with_tools.assert_not_called()
                self.assistant.feed_tool_result.assert_not_called()

    def test_responses_use_compiled_translations_without_conversation(self):
        from i18n import translator
        from scripts.compile_po import compile_po

        cases = (
            ("get_current_time", "what time is it", "현재 시간은 {time}입니다.", {"time": "12:00"}),
            ("get_running_apps", "list running apps", "실행 중인 앱 목록입니다.\n{apps}", {"apps": "sample.exe"}),
            ("take_screenshot", "take a screenshot", "스크린샷을 저장했습니다: {path}", {"path": "capture.png"}),
            ("adjust_volume", "increase volume by 10%", "볼륨을 조절했습니다.", {}),
        )
        locales = Path(__file__).resolve().parents[1] / "i18n" / "locales"
        with tempfile.TemporaryDirectory() as directory:
            for language in ("ko", "en", "ja"):
                mo = Path(directory) / f"{language}.mo"
                compile_po(str(locales / language / "LC_MESSAGES" / "ari.po"), str(mo))
                with mo.open("rb") as stream:
                    translation = gettext.GNUTranslations(stream)
                with patch.object(translator, "_translation", translation), patch.object(translator, "_current_lang", language):
                    for name, sentence, template, values in cases:
                        with self.subTest(language=language, name=name):
                            translated = translation.gettext(template)
                            if language != "ko":
                                self.assertNotEqual(translated, template)
                            self.predict(name)
                            self.handlers[name].reset_mock()
                            self.handlers[name].return_value = {
                                "get_current_time": translation.gettext("현재 시간은 {time}입니다.").format(time="12:00"),
                                "get_running_apps": "sample.exe",
                                "take_screenshot": "capture.png",
                                "adjust_volume": translation.gettext("볼륨을 조절했습니다."),
                            }[name]
                            output = self.command.run_interaction(sentence)
                            self.assertEqual(output, translated.format(**values).replace("\n", " "))
                            self.handlers[name].assert_called_once()
                    for name, sentence, failure in (
                        ("adjust_volume", "increase volume by 10%", translation.gettext("볼륨 조절 실패")),
                        ("get_running_apps", "list running apps", translation.gettext("실행 앱 목록 조회 실패: {error}").format(error="sample")),
                    ):
                        with self.subTest(language=language, failure=name):
                            self.predict(name)
                            self.handlers[name].return_value = failure
                            self.assertEqual(self.command.run_interaction(sentence), failure)
        self.assistant.chat_with_tools.assert_not_called()
        self.assistant.feed_tool_result.assert_not_called()


class DisabledEngineImportTests(unittest.TestCase):
    def test_off_mode_does_not_import_numpy_or_the_engine(self):
        real_import = builtins.__import__
        imported = []

        def recording_import(name, *args, **kwargs):
            imported.append(name)
            return real_import(name, *args, **kwargs)

        with patch("core.config_manager.ConfigManager.get",
                   side_effect=lambda key, default=None: "off" if key == "local_decision_mode" else default),                 patch("builtins.__import__", side_effect=recording_import):
            self.assertIsNone(AICommand.try_fast_path(object(), "volume up"))

        self.assertFalse([name for name in imported if name == "numpy" or name.startswith("agent.decision")])


class RunningAppsResponseTests(unittest.TestCase):
    def test_json_app_list_is_shortened_for_the_reply(self):
        import json

        from commands.ai_fast_path import FastPathMixin

        apps = [f"app{index}.exe" for index in range(54)]
        payload = json.dumps({"apps": apps, "count": len(apps)})
        reply = FastPathMixin()._fast_response("get_running_apps", payload)

        self.assertTrue(reply.startswith("실행 중인 앱이 54개 있어요: app0.exe, "))
        self.assertIn("app9.exe …", reply)
        self.assertNotIn("app10.exe", reply)
        # 대체된 처리기가 일반 텍스트를 반환하면 기존 목록 응답을 유지한다.
        self.assertEqual(FastPathMixin()._fast_response("get_running_apps", "sample.exe"),
                         "실행 중인 앱 목록입니다.\nsample.exe")


if __name__ == "__main__":
    unittest.main()
