import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx

from agent import embedder as embedder_module
from agent.embedder import Embedder


class EmbedderTests(unittest.TestCase):
    def test_openai_client_uses_configured_timeout_and_retry_limit(self):
        embedder = Embedder.__new__(Embedder)
        client_factory = Mock()
        with patch.object(embedder, "_get_api_key", return_value="test-key"), patch(
            "agent.embedder.importlib.import_module",
            return_value=SimpleNamespace(OpenAI=client_factory),
        ), patch.object(embedder_module.ConfigManager, "get", return_value=42):
            self.assertTrue(embedder._try_openai())

        options = client_factory.call_args.kwargs
        self.assertIsInstance(options["timeout"], httpx.Timeout)
        self.assertEqual(options["timeout"].read, 42.0)
        self.assertEqual(options["timeout"].connect, 5.0)
        self.assertEqual(options["max_retries"], 1)


if __name__ == "__main__":
    unittest.main()
