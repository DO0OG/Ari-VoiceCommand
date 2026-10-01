import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from agent.llm_provider import LLMProvider


class MemoryExtractorProviderTests(unittest.TestCase):
    def test_uses_configured_extractor_role_and_only_sends_user_utterance(self):
        create = Mock(
            return_value={"choices": [{"message": {"content": '{"facts":[]}'} }]}
        )
        client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )
        provider = LLMProvider.__new__(LLMProvider)
        provider._config_lock = threading.RLock()
        provider.memory_extractor_provider = "extractor"
        provider.memory_extractor_model = "small-model"
        provider.memory_extractor_client = client
        provider.execution_provider = "execution"
        provider.execution_model = "execution-model"
        provider.execution_client = None
        provider.provider = "main"
        provider.client = None
        provider.model = "main-model"
        provider._reasoning_extra_body = Mock(return_value={})

        result = provider.extract_memory_suggestions("I prefer concise answers.")

        self.assertEqual(result, '{"facts":[]}')
        kwargs = create.call_args.kwargs
        self.assertEqual(kwargs["model"], "small-model")
        self.assertEqual(kwargs["messages"][-1], {
            "role": "user",
            "content": "I prefer concise answers.",
        })
        self.assertEqual(len(kwargs["messages"]), 2)

    def test_unconfigured_extractor_role_uses_execution_model(self):
        client = object()
        with patch.object(LLMProvider, "_make_client", return_value=client):
            provider = LLMProvider(
                provider="main",
                api_key="main-key",
                model="main-model",
                execution_provider="execution",
                execution_model="execution-model",
                execution_api_key="execution-key",
                provider_configs={
                    "main": {"requires_api_key": True},
                    "execution": {"requires_api_key": True},
                },
            )

        target_client, target_provider, target_model = provider._get_role_target(
            "memory_extractor"
        )
        self.assertIs(target_client, client)
        self.assertEqual(target_provider, "execution")
        self.assertEqual(target_model, "execution-model")


if __name__ == "__main__":
    unittest.main()
