import unittest
import threading
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock, patch

import httpx

from agent import embedder as embedder_module
from agent.embedder import Embedder


class EmbedderTests(unittest.TestCase):
    def test_openai_client_uses_configured_timeout_and_retry_limit(self):
        embedder = Embedder.__new__(Embedder)
        embedder._ready_event = threading.Event()
        client_factory = Mock()

        def get_setting(key, default=None):
            if key == "embedding_remote_enabled":
                return True
            if key == "llm_timeout_chat_seconds":
                return 42
            return default

        with patch.object(embedder, "_get_api_key", return_value="test-key"), patch(
            "agent.embedder.importlib.import_module",
            return_value=SimpleNamespace(OpenAI=client_factory),
        ), patch.object(embedder_module.ConfigManager, "get", side_effect=get_setting):
            self.assertTrue(embedder._try_openai())

        options = client_factory.call_args.kwargs
        self.assertIsInstance(options["timeout"], httpx.Timeout)
        self.assertEqual(options["timeout"].read, 42.0)
        self.assertEqual(options["timeout"].connect, 5.0)
        self.assertEqual(options["max_retries"], 1)

    def test_openai_is_opted_out_by_default(self):
        client_factory = Mock()
        openai_module = ModuleType("openai")
        openai_module.OpenAI = client_factory
        settings = {"openai_api_key": "test-key"}
        with patch.object(
            embedder_module.ConfigManager,
            "get",
            side_effect=lambda key, default=None: settings.get(key, default),
        ), patch.object(
            embedder_module.ConfigManager, "load_settings", return_value=settings
        ), patch(
            "agent.embedder.threading.Thread"
        ), patch.dict("sys.modules", {"openai": openai_module}):
            embedder = Embedder()

            self.assertIsNone(embedder.embed("local model is not ready"))
            self.assertIsInstance(embedder.status, str)
            self.assertIsInstance(embedder.progress, float)

        client_factory.assert_not_called()

    def test_openai_is_used_only_after_explicit_opt_in(self):
        client_factory = Mock()
        openai_module = ModuleType("openai")
        openai_module.OpenAI = client_factory
        settings = {
            "embedding_remote_enabled": True,
            "openai_api_key": "test-key",
        }
        with patch.object(
            embedder_module.ConfigManager,
            "get",
            side_effect=lambda key, default=None: settings.get(key, default),
        ), patch.object(
            embedder_module.ConfigManager, "load_settings", return_value=settings
        ), patch(
            "agent.embedder.threading.Thread"
        ), patch.dict("sys.modules", {"openai": openai_module}):
            Embedder()

        client_factory.assert_called_once()

    def test_remote_embedder_stops_sending_after_opt_out(self):
        client = Mock()
        embedder = Embedder.__new__(Embedder)
        embedder.backend = "openai"
        embedder.status = "remote"
        embedder._client = client

        with patch.object(embedder_module.ConfigManager, "get", return_value=False):
            self.assertFalse(embedder.wait_until_ready())
            self.assertIsNone(embedder.embed("stored strategy text"))

        client.embeddings.create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
