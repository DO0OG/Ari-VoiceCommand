import json
import os
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch


from memory.conversation_history import ConversationHistory, memory_text_matches
from memory.memory_consolidator import MemoryConsolidator


class ConversationHistoryTests(unittest.TestCase):
    def _make_history(self, tmpdir: str) -> ConversationHistory:
        history = ConversationHistory.__new__(ConversationHistory)
        history.file_path = os.path.join(tmpdir, "conversation_history.json")
        history.active = []
        history.summaries = []
        history._lock = threading.RLock()
        history._save_timer = None
        history._save_delay_seconds = 0.05
        history._compression_in_progress = False
        history._compression_thread = None
        return history

    def test_add_debounces_and_persists_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = self._make_history(tmp)
            history.add("안녕", "반가워요")
            history.add("날씨 알려줘", "맑아요", skill_used="korea-weather", data_source="web_search", lang="ko")
            # 고정 시간 대신 지연 저장 스레드가 끝날 때까지 기다린다.
            timer = history._save_timer
            self.assertIsNotNone(timer)
            timer.join(timeout=5.0)

            with open(history.file_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)

            self.assertEqual(len(payload["active"]), 2)
            self.assertEqual(payload["active"][0]["user"], "안녕")
            self.assertEqual(payload["active"][1]["skill_used"], "korea-weather")
            self.assertEqual(payload["active"][1]["data_source"], "web_search")
            self.assertEqual(payload["active"][1]["lang"], "ko")

    def test_interrupted_response_keeps_only_played_text_and_marker(self):
        history = self._make_history(tempfile.gettempdir())
        history.active.append({"user": "질문", "ai": "첫 문장. 둘째 문장."})

        with patch.object(history, "_schedule_save") as schedule_save:
            updated = history.mark_last_response_interrupted(
                "첫 문장. 둘째 문장.",
                "첫 문장.\n\n(응답 중단)",
            )

        self.assertTrue(updated)
        self.assertEqual(history.active[-1]["ai"], "첫 문장.\n\n(응답 중단)")
        schedule_save.assert_called_once_with()

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

    def test_load_preserves_overflow_entries_and_retries_compression(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = self._make_history(tmp)
            entries = [
                {"timestamp": str(number), "user": f"user {number}", "ai": f"answer {number}"}
                for number in range(history.MAX_ACTIVE + 3)
            ]
            with open(history.file_path, "w", encoding="utf-8") as handle:
                json.dump({"active": entries, "summaries": []}, handle)

            with patch.object(history, "_compress_oldest") as compress_oldest:
                history.load()
                self.assertEqual(len(history.active), len(entries))
                compress_oldest.assert_called_once_with()
                history.save()

            with open(history.file_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self.assertEqual(len(payload["active"]), len(entries))

    def test_async_compression_keeps_active_entries_until_summary_finishes(self):
        history = self._make_history(tempfile.gettempdir())
        history.MAX_ACTIVE = 2
        history.COMPRESS_UNIT = 1
        started = threading.Event()
        release = threading.Event()

        def slow_summary(items):
            started.set()
            release.wait(timeout=1.0)
            return f"요약:{items[0]['user']}"

        history._summarize_chunk = slow_summary
        history.add("첫 질문", "첫 답변")
        history.add("둘 질문", "둘 답변")
        history.add("셋 질문", "셋 답변")

        self.assertTrue(started.wait(timeout=0.5))
        self.assertEqual(len(history.active), 3)
        self.assertEqual(history.summaries, [])

        release.set()
        history.flush()

        self.assertEqual(len(history.active), 2)
        self.assertEqual(history.active[0]["user"], "둘 질문")
        self.assertEqual(history.summaries, ["요약:첫 질문"])

    def test_corrupt_history_is_backed_up_and_starts_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "conversation_history.json")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("{broken")
            history = self._make_history(tmp)

            history.load()

            self.assertEqual(history.active, [])
            self.assertEqual(history.summaries, [])
            backups = [name for name in os.listdir(tmp) if ".corrupt-" in name]
            self.assertEqual(len(backups), 1)
            with open(os.path.join(tmp, backups[0]), encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "{broken")

    def test_compaction_and_compression_do_not_duplicate_or_drop_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = self._make_history(tmp)
            history.MAX_ACTIVE = 2
            history.COMPRESS_UNIT = 1
            timestamp = (datetime.now() - timedelta(days=30)).isoformat()
            history.active = [
                {"timestamp": timestamp, "user": "one", "ai": "reply"},
                {"timestamp": timestamp, "user": "two", "ai": "reply"},
                {"timestamp": timestamp, "user": "three", "ai": "reply"},
            ]
            worker_started = threading.Event()
            compaction_started = threading.Event()
            release_worker = threading.Event()
            release_compaction = threading.Event()

            def slow_summary(items):
                if threading.current_thread().name == "ConversationHistoryCompress":
                    worker_started.set()
                    release_worker.wait(timeout=5)
                    return f"worker:{items[0]['user']}"
                compaction_started.set()
                release_compaction.wait(timeout=5)
                names = ",".join(item["user"] for item in items)
                return f"compact:{names}"

            history._summarize_chunk = slow_summary
            with history._lock:
                history._compress_oldest()
            worker = history._compression_thread
            self.assertTrue(worker_started.wait(timeout=2))
            compacted = []
            with patch(
                "memory.conversation_history.get_conversation_history",
                return_value=history,
            ):
                compactor = threading.Thread(
                    target=lambda: compacted.append(
                        MemoryConsolidator().summarize_old_conversations(days_ago=14)
                    ),
                    name="MemoryConsolidator",
                )
                compactor.start()
                self.assertTrue(compaction_started.wait(timeout=2))

                release_compaction.set()
                compactor.join(timeout=5)
                release_worker.set()
                worker.join(timeout=5)
                history.flush()

            self.assertEqual(compacted, [3])
            self.assertEqual(history.active, [])
            self.assertEqual(history.summaries, ["compact:one,two,three"])

    def test_consolidation_prunes_indexed_conversations_after_180_days(self):
        with patch(
            "memory.conversation_history.get_conversation_history",
            return_value=Mock(),
        ), patch("memory.memory_index.get_memory_index") as get_index:
            MemoryConsolidator().summarize_old_conversations(days_ago=14)

        get_index.return_value.prune_conversations_older_than.assert_called_once_with(180)

    def test_delete_containing_removes_active_and_summary_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = self._make_history(tmp)
            history.active = [
                {"user": "coffee please", "ai": "Okay"},
                {"user": "tea please", "ai": "Coffee is popular"},
                {"user": "water", "ai": "Sure"},
            ]
            history.summaries = ["Coffee and tea", "Weather discussion"]

            deleted = history.delete_containing("COFFEE")

            self.assertEqual(deleted, 3)
            self.assertEqual(history.active, [{"user": "water", "ai": "Sure"}])
            self.assertEqual(history.summaries, ["Weather discussion"])
            with open(history.file_path, encoding="utf-8") as handle:
                saved = json.load(handle)
            self.assertEqual(saved["active"], history.active)
            self.assertEqual(saved["summaries"], history.summaries)

    def test_memory_text_matches_uses_word_boundaries_for_ascii_values(self):
        self.assertTrue(memory_text_matches("I like Tea.", "tea"))
        self.assertTrue(memory_text_matches("커피를 좋아해", "커피"))
        self.assertFalse(memory_text_matches("steak for my team", "tea"))
        self.assertFalse(memory_text_matches("code AB12_X", "AB12"))
        self.assertFalse(memory_text_matches("anything", " "))

    def test_delete_containing_restores_memory_when_file_write_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            history = self._make_history(tmp)
            history.active = [{"user": "I like tea.", "ai": "Noted"}]
            before = list(history.active)
            with patch(
                "memory.conversation_history.write_json_atomic",
                side_effect=OSError("disk full"),
            ):
                with self.assertRaises(OSError):
                    history.delete_containing("tea")
                self.assertEqual(history.active, before)


if __name__ == "__main__":
    unittest.main()
