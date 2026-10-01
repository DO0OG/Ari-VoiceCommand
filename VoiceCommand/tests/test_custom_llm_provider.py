import sys
import types
import unittest
from unittest.mock import Mock, patch

from agent.llm_provider import (
    LLMProvider,
    get_llm_provider,
    reload_llm_provider,
    reset_llm_provider,
)
from agent.provider_config import _PROVIDER_CONFIG, get_provider_configs


CUSTOM_A = "custom_11111111111111111111111111111111"
CUSTOM_B = "custom_22222222222222222222222222222222"
CUSTOM_C = "custom_33333333333333333333333333333333"


def _config(label, base_url, model):
    return {
        "label": label,
        "base_url": base_url,
        "default_model": model,
        "requires_api_key": False,
    }


def _custom_module(customs, normalize=None):
    module = types.ModuleType("core.custom_llm_providers")
    module.get_custom_providers = lambda settings: customs
    module.custom_api_key_name = lambda provider: f"{provider}_api_key"
    module.normalize_custom_provider_settings = normalize or (lambda settings: None)
    return module


def _openai_module(constructor):
    module = types.ModuleType("openai")
    module.OpenAI = constructor
    return module


class CustomLLMProviderTests(unittest.TestCase):
    def setUp(self):
        reset_llm_provider()

    def tearDown(self):
        reset_llm_provider()

    def _assert_openai_call(self, call, api_key, base_url, read_timeout):
        self.assertEqual(call.kwargs["api_key"], api_key)
        self.assertEqual(call.kwargs["base_url"], base_url)
        self.assertEqual(call.kwargs["max_retries"], 1)
        timeout = call.kwargs["timeout"]
        self.assertEqual(timeout.read, read_timeout)
        self.assertEqual(timeout.connect, 5.0)

    def test_reload_preserves_singleton_history_and_plugin_tools(self):
        settings = {"llm_provider": "groq", "groq_api_key": ""}
        custom = {CUSTOM_A: _config("Local", "https://llm.example/v1", "local-model")}
        openai = Mock(return_value=Mock())
        with patch.dict(sys.modules, {"core.custom_llm_providers": _custom_module(custom)}), \
             patch.dict(sys.modules, {"openai": _openai_module(openai)}), \
             patch("core.config_manager.ConfigManager.load_settings", side_effect=lambda: dict(settings)), \
             patch("agent.llm_provider.ConfigManager.get", side_effect=lambda key, default: default), \
             patch.object(LLMProvider, "_load_int_setting", side_effect=lambda key, default: default), \
             patch("agent.llm_provider.ResponseCache.from_config", return_value=Mock()):
            provider = get_llm_provider()
            provider.add_to_history("user", "remember this")
            history_lock = provider._history_lock
            stream_lock = provider._active_stream_lock
            active_stream = Mock()
            cancel_event = Mock()
            provider._active_stream = active_stream
            provider._active_stream_cancel_event = cancel_event
            tool = {"type": "function", "function": {"name": "plugin_tool"}}
            provider.register_plugin_tool(tool, intents=["hello"])
            settings.update({"llm_provider": CUSTOM_A, f"{CUSTOM_A}_api_key": "custom-key"})

            reload_llm_provider()

        self.assertIs(get_llm_provider(), provider)
        self.assertEqual(provider.provider, CUSTOM_A)
        self.assertEqual(provider.model, "local-model")
        self.assertEqual(provider.provider_configs[CUSTOM_A]["base_url"], "https://llm.example/v1")
        self.assertEqual(provider.conversation_history, [{"role": "user", "content": "remember this"}])
        self.assertIs(provider._history_lock, history_lock)
        self.assertIs(provider._active_stream_lock, stream_lock)
        self.assertIs(provider._active_stream, active_stream)
        self.assertIs(provider._active_stream_cancel_event, cancel_event)
        self.assertEqual(provider._plugin_tools, [tool])
        self.assertEqual(provider._plugin_tool_intents, {"plugin_tool": {"hello"}})

    def test_reload_build_failure_leaves_existing_singleton_unchanged(self):
        provider = Mock()
        provider.provider = "groq"
        with patch("agent.llm_provider._instance", provider), \
             patch("agent.llm_provider._build_llm_provider", side_effect=RuntimeError("build failed")):
            with self.assertRaisesRegex(RuntimeError, "build failed"):
                reload_llm_provider()

            self.assertIs(get_llm_provider(), provider)
        self.assertEqual(provider.provider, "groq")

    def test_tool_block_history_is_withheld_from_other_providers_after_reload(self):
        settings = {"llm_provider": "anthropic", "anthropic_api_key": ""}
        custom = {CUSTOM_A: _config("Local", "https://llm.example/v1", "local-model")}
        with patch.dict(sys.modules, {"core.custom_llm_providers": _custom_module(custom)}), \
             patch.dict(sys.modules, {"openai": _openai_module(Mock(return_value=Mock()))}), \
             patch("core.config_manager.ConfigManager.load_settings", side_effect=lambda: dict(settings)), \
             patch("agent.llm_provider.ConfigManager.get", side_effect=lambda key, default: default), \
             patch.object(LLMProvider, "_load_int_setting", side_effect=lambda key, default: default), \
             patch("agent.llm_provider.ResponseCache.from_config", return_value=Mock()):
            provider = get_llm_provider()
            provider.add_to_history("user", "hi")
            provider.add_to_history("assistant", [{"type": "tool_use", "id": "t1", "name": "x", "input": {}}])
            provider.add_to_history("user", [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}])
            provider.add_to_history("assistant", "done")
            config_lock = provider._config_lock
            settings.update({"llm_provider": CUSTOM_A})

            reload_llm_provider()

        self.assertEqual(provider.provider, CUSTOM_A)
        self.assertIs(provider._config_lock, config_lock)
        self.assertEqual(len(provider._history_for_context()), 4)
        self.assertEqual(provider._history_for_context(tool_blocks=False), [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "done"},
        ])

    def test_provider_configs_merge_builtins_with_validated_custom_entries(self):
        custom = {CUSTOM_A: _config("Local", "http://localhost:1234/v1", "local-model")}
        with patch.dict(sys.modules, {"core.custom_llm_providers": _custom_module(custom)}):
            configs = get_provider_configs({"custom_llm_providers": []})

        self.assertEqual(configs["groq"], _PROVIDER_CONFIG["groq"])
        self.assertEqual(configs[CUSTOM_A]["base_url"], "http://localhost:1234/v1")
        self.assertFalse(configs[CUSTOM_A]["requires_api_key"])

    def test_client_uses_custom_base_url_and_api_key(self):
        openai = Mock(return_value=Mock())
        config = _config("Test", "https://llm.example/v1", "test-model")
        with patch.dict(sys.modules, {"openai": _openai_module(openai)}), \
             patch.object(LLMProvider, "_load_int_setting", side_effect=lambda key, default: default), \
             patch(
                 "agent.llm_provider.ConfigManager.get",
                 side_effect=lambda key, default: default,
             ), \
             patch("agent.llm_provider.ResponseCache.from_config", return_value=Mock()):
            LLMProvider(
                provider=CUSTOM_A,
                api_key="fake-custom-key",
                model="test-model",
                provider_configs={CUSTOM_A: config},
            )

        self.assertEqual(openai.call_count, 2)
        self._assert_openai_call(
            openai.call_args_list[0], "fake-custom-key", "https://llm.example/v1", 30
        )
        self._assert_openai_call(
            openai.call_args_list[1], "fake-custom-key", "https://llm.example/v1", 90
        )

    def test_no_key_custom_provider_still_creates_client(self):
        openai = Mock(return_value=Mock())
        config = _config("Local", "http://localhost:1234/v1", "local-model")
        with patch.dict(sys.modules, {"openai": _openai_module(openai)}), \
             patch.object(LLMProvider, "_load_int_setting", side_effect=lambda key, default: default), \
             patch(
                 "agent.llm_provider.ConfigManager.get",
                 side_effect=lambda key, default: default,
             ), \
             patch("agent.llm_provider.ResponseCache.from_config", return_value=Mock()):
            provider = LLMProvider(
                provider=CUSTOM_A,
                model="local-model",
                provider_configs={CUSTOM_A: config},
            )

        self.assertIsNotNone(provider.client)
        openai.assert_called_once()
        self._assert_openai_call(
            openai.call_args, "custom-provider", "http://localhost:1234/v1", 120
        )

    def test_main_planner_execution_and_fallback_resolve_custom_models_and_keys(self):
        customs = {
            CUSTOM_A: _config("Main", "https://main.example/v1", "main-default"),
            CUSTOM_B: _config("Planner", "https://planner.example/v1", "planner-default"),
            CUSTOM_C: _config("Execution", "https://execution.example/v1", "execution-default"),
        }
        settings = {
            "llm_provider": CUSTOM_A,
            "llm_model": "",
            "llm_planner_provider": CUSTOM_B,
            "llm_planner_model": "",
            "llm_execution_provider": CUSTOM_C,
            "llm_execution_model": "",
            f"{CUSTOM_A}_api_key": "main-key",
            f"{CUSTOM_B}_api_key": "planner-key",
            f"{CUSTOM_C}_api_key": "execution-key",
        }
        clients = [Mock(), Mock(), Mock()]
        openai = Mock(side_effect=clients)
        with patch.dict(sys.modules, {"core.custom_llm_providers": _custom_module(customs)}), \
             patch.dict(sys.modules, {"openai": _openai_module(openai)}), \
             patch("core.config_manager.ConfigManager.load_settings", return_value=settings), \
             patch(
                 "agent.llm_provider.ConfigManager.get",
                 side_effect=lambda key, default: default,
             ), \
             patch.object(LLMProvider, "_load_int_setting", side_effect=lambda key, default: default), \
             patch("agent.llm_provider.ResponseCache.from_config", return_value=Mock()):
            provider = get_llm_provider()

        self.assertEqual(provider.model, "main-default")
        self.assertEqual(provider.planner_model, "planner-default")
        self.assertEqual(provider.execution_model, "execution-default")
        self.assertIs(provider.client, clients[0])
        self.assertIs(provider.planner_client, clients[1])
        self.assertIs(provider.execution_client, clients[2])
        self.assertEqual(
            [(name, model) for _, name, model in provider.get_role_fallback_targets("planner")],
            [(CUSTOM_B, "planner-default"), (CUSTOM_A, "main-default"), (CUSTOM_C, "execution-default")],
        )
        self.assertEqual(openai.call_count, 3)
        self._assert_openai_call(
            openai.call_args_list[0], "main-key", "https://main.example/v1", 30
        )
        self._assert_openai_call(
            openai.call_args_list[1], "planner-key", "https://planner.example/v1", 90
        )
        self._assert_openai_call(
            openai.call_args_list[2], "execution-key", "https://execution.example/v1", 30
        )

    def test_blank_same_provider_role_models_inherit_main_custom_override(self):
        custom = {CUSTOM_A: _config("Main", "https://main.example/v1", "provider-default")}
        settings = {
            "llm_provider": CUSTOM_A,
            "llm_model": "user-selected-model",
            "llm_planner_provider": "",
            "llm_planner_model": "",
            "llm_execution_provider": "",
            "llm_execution_model": "",
            f"{CUSTOM_A}_api_key": "custom-key",
        }
        with patch.dict(sys.modules, {"core.custom_llm_providers": _custom_module(custom)}), \
             patch.dict(sys.modules, {"openai": _openai_module(Mock(return_value=Mock()))}), \
             patch("core.config_manager.ConfigManager.load_settings", return_value=settings), \
             patch.object(LLMProvider, "_load_int_setting", side_effect=lambda key, default: default), \
             patch("agent.llm_provider.ResponseCache.from_config", return_value=Mock()):
            provider = get_llm_provider()

        self.assertEqual(provider.model, "user-selected-model")
        self.assertEqual(provider.planner_model, "user-selected-model")
        self.assertEqual(provider.execution_model, "user-selected-model")

    def test_deleted_custom_provider_falls_back_without_reusing_key_or_model(self):
        stale_key = "stale-custom-key"
        settings = {
            "llm_provider": CUSTOM_A,
            "llm_model": "stale-custom-model",
            f"{CUSTOM_A}_api_key": stale_key,
            "groq_api_key": "groq-key",
        }
        openai = Mock(return_value=Mock())
        with patch.dict(sys.modules, {"core.custom_llm_providers": _custom_module({})}), \
             patch.dict(sys.modules, {"openai": _openai_module(openai)}), \
             patch("core.config_manager.ConfigManager.load_settings", return_value=settings), \
             patch(
                 "agent.llm_provider.ConfigManager.get",
                 side_effect=lambda key, default: default,
             ), \
             patch.object(LLMProvider, "_load_int_setting", side_effect=lambda key, default: default), \
             patch("agent.llm_provider.ResponseCache.from_config", return_value=Mock()):
            provider = get_llm_provider()

        self.assertEqual(provider.provider, "groq")
        self.assertEqual(provider.model, "")
        self.assertEqual(openai.call_count, 2)
        self._assert_openai_call(
            openai.call_args_list[0], "groq-key", _PROVIDER_CONFIG["groq"]["base_url"], 30
        )
        self._assert_openai_call(
            openai.call_args_list[1], "groq-key", _PROVIDER_CONFIG["groq"]["base_url"], 90
        )
        self.assertEqual(settings["llm_provider"], CUSTOM_A)
        self.assertEqual(settings["llm_model"], "stale-custom-model")

    def test_custom_fallback_exception_is_sanitized_before_it_escapes(self):
        custom = _config("Private", "https://custom.example/v1", "custom-model")
        with patch.dict(sys.modules, {"openai": _openai_module(Mock(return_value=Mock()))}), \
             patch.object(LLMProvider, "_load_int_setting", side_effect=lambda key, default: default), \
             patch("agent.llm_provider.ResponseCache.from_config", return_value=Mock()):
            provider = LLMProvider(
                provider="groq",
                api_key="groq-key",
                model="groq-model",
                execution_provider=CUSTOM_A,
                execution_api_key="custom-key",
                execution_model="custom-model",
                provider_configs={CUSTOM_A: custom},
            )
        primary = Mock()
        custom_client = Mock()

        class SDKError(Exception):
            def __init__(self, message, status_code):
                super().__init__(message)
                self.status_code = status_code

        primary.chat.completions.create.side_effect = SDKError("builtin error", 500)
        custom_client.chat.completions.create.side_effect = SDKError(
            "server echoed custom-key", 401
        )
        provider.client = primary
        provider.execution_client = custom_client

        with self.assertRaises(RuntimeError) as raised:
            provider._create_completion_with_fallback(primary, "groq", "groq-model")

        self.assertEqual(raised.exception.status_code, 401)
        self.assertNotIn("custom-key", str(raised.exception))
        self.assertEqual(str(raised.exception), "Custom provider request failed")


if __name__ == "__main__":
    unittest.main()
