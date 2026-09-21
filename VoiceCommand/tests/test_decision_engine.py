import builtins
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from commands.ai_command import AICommand


def _engine_module():
    from agent.decision import engine

    return engine


def _simple_skill_context():
    return {
        "skills": [],
        "prompt": "",
        "required_tool_names": [],
        "preferred_tool": "",
        "force_web_search": False,
        "escalate_to_agent": False,
        "search_query_template": "",
    }


def _write_model(directory, *, labels=None, weights=None, bias=None, **overrides):
    import numpy as np

    engine = _engine_module()
    labels = list(labels or engine.candidate_names())
    buckets = int(overrides.pop("buckets", 32))
    if weights is None:
        weights = np.zeros((len(labels), buckets), dtype=np.float32)
    if bias is None:
        bias = np.zeros(len(labels), dtype=np.float32)

    weights_path = Path(directory) / "weights.npz"
    np.savez(weights_path, weights=weights, bias=bias)
    payload = weights_path.read_bytes()
    config = {
        "version": 1,
        "labels": labels,
        "buckets": buckets,
        "temperature": 1.5,
        "dataset_version": "test-dataset",
        "calibration_version": "test-temperature",
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    config.update(overrides)
    (Path(directory) / "config.json").write_text(
        json.dumps(config), encoding="utf-8"
    )
    return config, payload


class DecisionEngineTests(unittest.TestCase):
    def _simple_router(self):
        return SimpleNamespace(
            route=Mock(return_value=SimpleNamespace(task_type="simple_chat"))
        )

    def _config_patch(self, *, enabled=True, backend="linear", threshold=0.92, direct=True):
        values = {
            "local_decision_engine_enabled": enabled,
            "local_decision_backend": backend,
            "local_decision_threshold": threshold,
            "local_decision_direct_execution": direct,
        }

        def get(key, default=None):
            return values.get(key, default)

        return patch("core.config_manager.ConfigManager.get", side_effect=get)

    def test_candidate_names_come_from_registered_intents(self):
        engine = _engine_module()
        registered = {
            schema["function"]["name"] for schema in engine.CORE_TOOL_SCHEMAS
        }
        mapped = set().union(*engine._TOOL_NAMES_BY_INTENT.values())
        expected = tuple(sorted(registered & mapped)) + (engine.UNKNOWN,)

        self.assertEqual(engine.candidate_names(), expected)
        self.assertIn("delete_file", expected)
        self.assertIn("send_email", expected)
        self.assertIn("execute_shell_command", expected)
        self.assertIn("execute_python_code", expected)
        self.assertNotIn("shutdown_computer", expected)

    def test_hash_features_are_stable_for_nfkc_casefolded_unicode(self):
        import numpy as np

        engine = _engine_module()
        first = engine.hash_features("  ＡＲＩ\tHELLO  ", buckets=64)
        second = engine.hash_features("ari hello", buckets=64)
        repeated = engine.hash_features("  ＡＲＩ\tHELLO  ", buckets=64)

        np.testing.assert_array_equal(first[0], second[0])
        np.testing.assert_allclose(first[1], second[1])
        np.testing.assert_array_equal(first[0], repeated[0])
        np.testing.assert_array_equal(first[1], repeated[1])
        self.assertAlmostEqual(float(np.linalg.norm(first[1])), 1.0, places=6)

    def test_linear_scorer_returns_calibrated_probabilities_that_sum_to_one(self):
        import numpy as np

        engine = _engine_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            labels = engine.candidate_names()
            buckets = 32
            weights = np.zeros((len(labels), buckets), dtype=np.float32)
            bias = np.linspace(-1.0, 1.0, len(labels), dtype=np.float32)
            _write_model(
                temp_dir,
                labels=labels,
                weights=weights,
                bias=bias,
                buckets=buckets,
                temperature=2.0,
            )

            result = engine.LinearScorer(temp_dir).predict("ＡＲＩ hello")

        self.assertEqual(tuple(result.probabilities), labels)
        self.assertAlmostEqual(sum(result.probabilities.values()), 1.0, places=7)
        self.assertAlmostEqual(result.confidence, max(result.probabilities.values()))
        self.assertGreaterEqual(result.margin, 0.0)
        self.assertEqual(result.source, "linear")

    def test_complex_router_result_abstains_before_model_load(self):
        engine = _engine_module()
        router = SimpleNamespace(
            route=Mock(return_value=SimpleNamespace(task_type="complex_plan"))
        )
        local = engine.LocalDecisionEngine("unused")

        with patch.object(engine, "get_llm_router", return_value=router):
            with patch.object(engine, "LinearScorer") as scorer:
                self.assertIsNone(local.choice("organize these files"))

        router.route.assert_called_once_with("organize these files")
        scorer.assert_not_called()
        self.assertFalse(local._load_attempted)

    def test_missing_model_falls_back_and_does_not_retry_load(self):
        engine = _engine_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            local = engine.LocalDecisionEngine(Path(temp_dir) / "missing")
            with patch.object(engine, "get_llm_router", return_value=self._simple_router()):
                with patch.object(engine, "LinearScorer", wraps=engine.LinearScorer) as scorer:
                    self.assertIsNone(local.choice("hello"))
                    self.assertIsNone(local.choice("hello again"))

            scorer.assert_called_once()
            self.assertTrue(local._load_attempted)
            self.assertIsNone(local._scorer)

    def test_corrupt_checksum_falls_back_and_cached_failure_survives_repair(self):
        engine = _engine_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            model_dir = Path(temp_dir)
            _write_model(model_dir)
            weights_path = model_dir / "weights.npz"
            weights_path.write_bytes(weights_path.read_bytes() + b"corrupt")
            local = engine.LocalDecisionEngine(model_dir)

            with patch.object(engine, "get_llm_router", return_value=self._simple_router()):
                with patch.object(engine, "LinearScorer", wraps=engine.LinearScorer) as scorer:
                    self.assertIsNone(local.choice("hello"))
                    _write_model(model_dir)
                    self.assertIsNone(local.choice("hello"))

            scorer.assert_called_once()

    def test_invalid_config_and_weight_shapes_fall_back(self):
        import numpy as np

        engine = _engine_module()
        cases = ("bad-labels", "bad-weights")
        with tempfile.TemporaryDirectory() as temp_dir:
            for case in cases:
                with self.subTest(case=case):
                    model_dir = Path(temp_dir) / case
                    model_dir.mkdir()
                    if case == "bad-labels":
                        _write_model(model_dir, labels=["not-a-registered-tool"])
                    else:
                        labels = engine.candidate_names()
                        _write_model(
                            model_dir,
                            labels=labels,
                            weights=np.zeros((1, 32), dtype=np.float32),
                        )
                    local = engine.LocalDecisionEngine(model_dir)
                    with patch.object(
                        engine, "get_llm_router", return_value=self._simple_router()
                    ):
                        self.assertIsNone(local.choice("hello"))
                        self.assertTrue(local._load_attempted)
                        self.assertIsNone(local._scorer)

    def test_inference_exception_falls_back_without_leaking(self):
        engine = _engine_module()
        scorer = Mock()
        scorer.predict.side_effect = RuntimeError("inference failed")
        local = engine.LocalDecisionEngine("unused")
        local._load_attempted = True
        local._scorer = scorer

        with patch.object(engine, "get_llm_router", return_value=self._simple_router()):
            self.assertIsNone(local.choice("hello"))
            self.assertIsNone(local.choice("hello again"))

        self.assertEqual(scorer.predict.call_count, 2)
        self.assertIs(local._scorer, scorer)

    def test_unknown_low_confidence_and_low_margin_abstain(self):
        engine = _engine_module()
        cases = (
            engine.DecisionResult(
                engine.UNKNOWN, {engine.UNKNOWN: 0.99}, 0.99, 0.90, "linear", 1.0
            ),
            engine.DecisionResult(
                "get_current_time", {"get_current_time": 0.91}, 0.91, 0.80, "linear", 1.0
            ),
            engine.DecisionResult(
                "get_current_time", {"get_current_time": 0.98}, 0.98, 0.20, "linear", 1.0
            ),
        )

        for decision in cases:
            with self.subTest(choice=decision.choice, confidence=decision.confidence):
                local = engine.LocalDecisionEngine("unused")
                local.choice = Mock(return_value=decision)
                with self._config_patch():
                    self.assertIsNone(local.try_fast_path("what time is it"))
                self.assertIsNone(local.last_decision)
                local.choice.assert_called_once_with("what time is it")

    def test_high_confidence_decision_is_diagnostic_only_even_when_direct_flag_true(self):
        engine = _engine_module()
        decision = engine.DecisionResult(
            "get_current_time", {"get_current_time": 0.99}, 0.99, 0.80, "linear", 1.0
        )
        local = engine.LocalDecisionEngine("unused")
        local.choice = Mock(return_value=decision)

        with self._config_patch(direct=True):
            self.assertIsNone(local.try_fast_path("what time is it"))

        self.assertIs(local.last_decision, decision)
        local.choice.assert_called_once_with("what time is it")

    def test_ai_command_flags_off_preserve_chat_without_decision_or_numpy_import(self):
        events = []

        class Assistant:
            def chat_with_tools(self, text, include_context=True):
                events.append(("chat", text, include_context))
                return "ordinary chat response", []

        command = AICommand(Assistant(), events.append, {"enabled": False})
        command._get_skill_context = Mock(return_value=_simple_skill_context())
        imported = []
        original_import = builtins.__import__

        def observe_import(name, *args, **kwargs):
            if name == "numpy" or name == "agent.decision.engine":
                imported.append(name)
            return original_import(name, *args, **kwargs)

        with self._config_patch(enabled=False):
            with patch("memory.conversation_history.add_conversation"):
                with patch("core.VoiceCommand.emit_plugin_event"):
                    with patch("builtins.__import__", side_effect=observe_import):
                        result = command.run_interaction("hello")

        self.assertEqual(result, "ordinary chat response")
        self.assertEqual(events[0], ("chat", "hello", True))
        self.assertEqual(imported, [])

    def test_ai_command_high_risk_prediction_uses_chat_and_existing_safety_handler(self):
        engine = _engine_module()
        messages = []
        events = []

        class Assistant:
            def __init__(self, target):
                self.target = target

            def chat_with_tools(self, text, include_context=True):
                events.append(("chat", text, include_context))
                return "I will check that", [{
                    "id": "risky-1",
                    "name": "delete_file",
                    "arguments": {"path": self.target, "confirmed": True},
                }]

            def feed_tool_result(self, original_text, tool_calls, results):
                events.append(("feed", original_text, tool_calls, results))
                return "existing safety response"

        decision = engine.DecisionResult(
            "delete_file", {"delete_file": 0.99}, 0.99, 0.80, "linear", 1.0
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "should-survive.txt"
            target.write_text("preserve", encoding="utf-8")
            assistant = Assistant(str(target))
            command = AICommand(assistant, messages.append, {"enabled": False})
            command._get_skill_context = Mock(return_value=_simple_skill_context())

            with self._config_patch(enabled=True, direct=True):
                with patch(
                    "core.resource_manager.ResourceManager.get_bundle_path",
                    return_value="unused",
                ):
                    with patch.object(engine.LocalDecisionEngine, "choice", return_value=decision) as infer:
                        confirmation = Mock()
                        confirmation.request_confirmation.return_value = False
                        with patch(
                            "agent.confirmation_manager.get_confirmation_manager",
                            return_value=confirmation,
                        ):
                            with patch("memory.conversation_history.add_conversation"):
                                with patch("core.VoiceCommand.emit_plugin_event"):
                                    result = command.run_interaction("delete this file")

            infer.assert_called_once_with("delete this file")
            confirmation.request_confirmation.assert_called_once()
            self.assertEqual(
                confirmation.request_confirmation.call_args.args[1].category,
                "file_delete",
            )
            self.assertTrue(target.exists())

        self.assertEqual(events[0][0], "chat")
        self.assertEqual(events[1][0], "feed")
        self.assertIn("existing safety response", result)

    def test_high_risk_predictions_never_direct_dispatch_in_phase_three(self):
        engine = _engine_module()
        high_risk = (
            "delete_file",
            "send_email",
            "execute_shell_command",
            "execute_python_code",
            "shutdown_computer",
        )
        decisions = [
            engine.DecisionResult(name, {name: 0.99}, 0.99, 0.80, "linear", 1.0)
            for name in high_risk
        ]
        chat_calls = []
        messages = []

        class Assistant:
            def chat_with_tools(self, text, include_context=True):
                chat_calls.append((text, include_context))
                return "ordinary chat response", []

        command = AICommand(Assistant(), messages.append, {"enabled": False})
        command._get_skill_context = Mock(return_value=_simple_skill_context())
        handlers = {name: Mock() for name in high_risk}
        command._dispatch.update(handlers)

        with self._config_patch(enabled=True, direct=True):
            with patch(
                "core.resource_manager.ResourceManager.get_bundle_path",
                return_value="unused",
            ):
                with patch.object(
                    engine.LocalDecisionEngine,
                    "choice",
                    side_effect=decisions,
                ) as infer:
                    with patch("memory.conversation_history.add_conversation"):
                        with patch("core.VoiceCommand.emit_plugin_event"):
                            for _ in high_risk:
                                self.assertEqual(
                                    command.run_interaction("hello"),
                                    "ordinary chat response",
                                )

        self.assertEqual(chat_calls, [("hello", True)] * len(high_risk))
        self.assertEqual(infer.call_count, len(high_risk))
        for call in infer.call_args_list:
            self.assertEqual(call.args, ("hello",))
        for handler in handlers.values():
            handler.assert_not_called()

    def test_template_and_schema_keep_decision_flags_in_sync(self):
        from core.settings_schema import DEFAULT_SETTINGS

        template_path = Path(__file__).resolve().parents[1] / "ari_settings.template.json"
        template = json.loads(template_path.read_text(encoding="utf-8"))
        for key in (
            "local_decision_engine_enabled",
            "local_decision_backend",
            "local_decision_threshold",
            "local_decision_direct_execution",
        ):
            with self.subTest(key=key):
                self.assertIn(key, template)
                self.assertIn(key, DEFAULT_SETTINGS)
                self.assertEqual(template[key], DEFAULT_SETTINGS[key])


if __name__ == "__main__":
    unittest.main()
