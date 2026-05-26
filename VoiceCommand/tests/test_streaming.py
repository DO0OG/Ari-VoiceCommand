import unittest
from types import SimpleNamespace

from agent.llm_provider import LLMProvider


class _FakeCompletions:
    def create(self, **kwargs):
        if kwargs.get("stream"):
            return [
                SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="안"))]),
                SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="녕"))]),
            ]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="안녕"))])


class StreamingTests(unittest.TestCase):
    def test_stream_chat_emits_tokens_and_done(self):
        provider = LLMProvider(provider="openai", model="test")
        provider.client = SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions()))
        tokens = []
        done = []

        text = provider.stream_chat(
            [{"role": "user", "content": "hi"}],
            tokens.append,
            lambda full_text, tool_calls: done.append((full_text, tool_calls)),
            max_tokens=10,
        )

        self.assertEqual(tokens, ["안", "녕"])
        self.assertEqual(text, "안녕")
        self.assertEqual(done[0][0], "안녕")


if __name__ == "__main__":
    unittest.main()
