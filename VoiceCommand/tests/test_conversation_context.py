import unittest

from memory.conversation_history import ConversationHistory


class ConversationContextTests(unittest.TestCase):
    def test_get_messages_for_context_compacts_long_tool_like_output(self):
        history = ConversationHistory.__new__(ConversationHistory)
        history.active = [{"user": "질문", "ai": "x" * 2500}]
        history.summaries = ["오래된 요약"]
        import threading
        history._lock = threading.RLock()

        messages = history.get_messages_for_context(max_tokens=8000)

        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[-1]["content"], "[도구 결과 요약: 2500자]")


if __name__ == "__main__":
    unittest.main()
