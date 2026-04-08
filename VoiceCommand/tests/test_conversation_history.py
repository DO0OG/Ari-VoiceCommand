import json
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch


from memory.conversation_history import ConversationHistory


class ConversationHistoryTests(unittest.TestCase):
    def _make_history(self, tmpdir: str) -> ConversationHistory:
        history = ConversationHistory.__new__(ConversationHistory)
        history.file_path = os.path.join(tmpdir, "conversation_history.json")
        history.active = []
        history.summaries = []
        history._lock = threading.RLock()
        history._save_timer = None
        history._save_delay_seconds = 0.05
        return history

    def test_add_debounces_and_persists_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = self._make_history(tmp)
            history.add("안녕", "반가워요")
            history.add("날씨 알려줘", "맑아요")
            time.sleep(0.12)

            with open(history.file_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)

            self.assertEqual(len(payload["active"]), 2)
            self.assertEqual(payload["active"][0]["user"], "안녕")

    def test_summarize_chunk_uses_compact_summary_prefix(self):
        history = self._make_history(tempfile.gettempdir())

        with patch("agent.llm_provider.get_llm_provider", side_effect=RuntimeError("offline")):
            summary = history._summarize_chunk([
                {"user": "첫 질문", "ai": "첫 답변"},
                {"user": "둘째 질문", "ai": "둘째 답변"},
            ])

        self.assertIn("2건", summary)
        self.assertIn("첫 질문", summary)

    def test_summarize_chunk_prefers_llm_summary_when_available(self):
        history = self._make_history(tempfile.gettempdir())

        fake_provider = type(
            "FakeProvider",
            (),
            {
                "chat": lambda self, prompt, include_context=False, save_history=False: "사용자가 질문했고 아리가 핵심만 답했다.",
            },
        )()

        with patch("agent.llm_provider.get_llm_provider", return_value=fake_provider):
            summary = history._summarize_chunk([
                {"user": "긴 질문입니다", "ai": "긴 답변입니다"},
            ])

        self.assertEqual(summary, "사용자가 질문했고 아리가 핵심만 답했다.")

    def test_summarize_chunk_falls_back_when_llm_returns_empty(self):
        history = self._make_history(tempfile.gettempdir())

        fake_provider = type(
            "FakeProvider",
            (),
            {
                "chat": lambda self, prompt, include_context=False, save_history=False: "   ",
            },
        )()

        with patch("agent.llm_provider.get_llm_provider", return_value=fake_provider):
            summary = history._summarize_chunk([
                {"user": "첫 질문", "ai": "첫 답변"},
            ])

        self.assertIn("[대화요약 1건]", summary)

    def test_flush_persists_without_waiting_for_debounce_timer(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = self._make_history(tmp)
            history.add("안녕", "반가워요")

            history.flush()

            with open(history.file_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self.assertEqual(len(payload["active"]), 1)

    def test_add_skips_internal_prompt_entries(self):
        history = self._make_history(tempfile.gettempdir())

        history.add(
            "당신은 AI 에이전트 스킬을 Python 함수로 컴파일합니다.\n스킬 예시",
            "내부 응답",
        )
        history.add("사용자 질문", "일반 응답")

        self.assertEqual(len(history.active), 1)
        self.assertEqual(history.active[0]["user"], "사용자 질문")

    def test_load_filters_persisted_internal_prompt_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "conversation_history.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "active": [
                            {
                                "timestamp": "2026-04-07T00:00:00",
                                "user": "당신은 AI 에이전트 스킬을 Python 함수로 컴파일합니다.\n내부 테스트",
                                "ai": "내부 응답",
                            },
                            {
                                "timestamp": "2026-04-07T00:00:01",
                                "user": "실사용 질문",
                                "ai": "실사용 응답",
                            },
                        ],
                        "summaries": [],
                    },
                    handle,
                    ensure_ascii=False,
                )

            history = self._make_history(tmp)
            history.load()

            self.assertEqual(len(history.active), 1)
            self.assertEqual(history.active[0]["user"], "실사용 질문")


if __name__ == "__main__":
    unittest.main()
