import unittest
from types import SimpleNamespace
from unittest.mock import patch

from memory.memory_manager import MemoryManager


class MemoryManagerTests(unittest.TestCase):
    def test_get_top_facts_prompt_uses_highest_confidence_facts(self):
        fake_context = SimpleNamespace(
            context={
                "facts": {
                    "낮음": {"value": "1", "confidence": 0.2},
                    "높음": {"value": "2", "confidence": 0.9},
                    "중간": {"value": "3", "confidence": 0.5},
                }
            },
            extract_topics=lambda user_msg, ai_response: [],
        )

        with patch("memory.memory_manager.get_context_manager", return_value=fake_context):
            manager = MemoryManager()

        prompt = manager.get_top_facts_prompt(n=2)

        self.assertIn("- 높음: 2", prompt)
        self.assertIn("- 중간: 3", prompt)
        self.assertNotIn("- 낮음: 1", prompt)

    def test_get_memory_prompt_delegates_to_full_context_prompt(self):
        fake_context = SimpleNamespace(
            context={"facts": {}},
            extract_topics=lambda user_msg, ai_response: [],
            get_context_summary=lambda: "요약",
        )
        fake_profile_engine = SimpleNamespace(get_prompt_injection=lambda: "프로필")

        with patch("memory.memory_manager.get_context_manager", return_value=fake_context):
            with patch("memory.memory_manager.get_user_profile_engine", return_value=fake_profile_engine):
                manager = MemoryManager()
                prompt = manager.get_memory_prompt()

        self.assertIn("프로필", prompt)
        self.assertIn("요약", prompt)


if __name__ == "__main__":
    unittest.main()
