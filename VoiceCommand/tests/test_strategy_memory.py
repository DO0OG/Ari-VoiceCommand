import json
import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

import numpy as np

from agent.strategy_memory import StrategyMemory


class StrategyMemoryTests(unittest.TestCase):
    def setUp(self):
        self.embedder = Mock()
        self.embedder.model_id = "test/local-model"
        self.embedder.dim = 3
        self.embedder.status = "ready"
        self.embedder.progress = 1.0
        self.embedder.wait_until_ready.return_value = True
        self.embedder.embed.side_effect = lambda _text: np.array(
            [1.0, 0.0, 0.0], dtype=np.float32
        )

        embedder_patch = patch("agent.embedder.get_embedder", return_value=self.embedder)
        timer_patch = patch("agent.strategy_memory.threading.Timer")
        self.worker_factory = Mock()
        worker_patch = patch("agent.strategy_memory.threading.Thread", self.worker_factory)
        embedder_patch.start()
        timer_patch.start()
        worker_patch.start()
        self.addCleanup(embedder_patch.stop)
        self.addCleanup(timer_patch.stop)
        self.addCleanup(worker_patch.stop)

    def test_legacy_records_without_goal_tokens_are_normalized(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "strategy.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump([
                    {
                        "goal_summary": "회의록 요약 작성",
                        "tags": ["텍스트"],
                        "steps_desc": ["요약 생성"],
                        "success": True,
                        "error_summary": "",
                        "failure_kind": "",
                        "duration_ms": 10,
                        "timestamp": "2026-03-24T00:00:00",
                    }
                ], handle, ensure_ascii=False)

            memory = StrategyMemory(filepath=path)
            self.assertIn("회의록", memory._records[0].goal_tokens)
            context = memory.get_relevant_context("회의록 작성")
            self.assertIn("회의록 요약 작성", context)

    def test_ngram_similarity_surfaces_similar_goal_and_recent_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = StrategyMemory(filepath=os.path.join(tmp, "strategy.json"))
            memory.record("브라우저 셀렉터 전략 저장", [], False, error="selector timeout", lesson="도메인별 셀렉터 캐시를 우선 적용")
            memory.record("파일 병합 자동화", [], True)

            context = memory.get_relevant_context("브라우져 셀렉터 전략")
            failures = memory.recent_failures("브라우져 셀렉터 전략")

            self.assertIn("브라우저 셀렉터 전략 저장", context)
            self.assertTrue(any("셀렉터 캐시" in item for item in failures))

    def test_successful_workflow_hints_are_included_in_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = StrategyMemory(filepath=os.path.join(tmp, "strategy.json"))

            class _Step:
                def __init__(self, description_kr, content):
                    self.description_kr = description_kr
                    self.content = content

            memory.record(
                "메모장에 메모 저장",
                [
                    _Step("메모장 실행", "result = run_desktop_workflow(goal_hint='메모장에 메모 저장', app_target='notepad')"),
                ],
                True,
            )

            context = memory.get_relevant_context("메모장에 메모 저장")

            self.assertIn("재사용 힌트", context)
            self.assertIn("goal_hint='메모장에 메모 저장'", context)

    def test_embedding_search_surfaces_similar_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = StrategyMemory(filepath=os.path.join(tmp, "strategy.json"))
            memory.record("브라우저 다운로드 자동화", [], True)
            memory.record("파일 이름 일괄 변경", [], True)

            results = memory.search_similar_records("브라우저 다운로드", limit=2)

            self.assertTrue(results)
            self.assertEqual(results[0].goal_summary, "브라우저 다운로드 자동화")

    def test_embedding_files_store_float16_vectors_and_metadata_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "strategy.json")
            memory = StrategyMemory(filepath=path)
            memory.record("first goal", [], True)
            self.assertTrue(memory._embedding_valid)
            memory.record("second goal", [], True)
            memory.flush()

            with open(path, "r", encoding="utf-8") as handle:
                serialized = handle.read()
            payload = json.loads(serialized)
            vectors = np.load(os.path.join(tmp, "strategy_embeddings.npy"))

            self.assertIsInstance(payload, dict)
            self.assertTrue({
                "embedding_model_id",
                "dim",
                "record_ids",
                "embedding_sha256",
                "records",
            }.issubset(payload))
            self.assertEqual(payload["embedding_model_id"], self.embedder.model_id)
            self.assertEqual(payload["dim"], self.embedder.dim)
            self.assertIs(payload["embedding_complete"], True)
            self.assertEqual(len(payload["record_ids"]), 2)
            self.assertEqual(len(payload["embedding_sha256"]), 64)
            self.assertEqual(len(payload["records"]), 2)
            self.assertTrue(all("embedding" not in record for record in payload["records"]))
            self.assertNotIn(": ", serialized)
            self.assertEqual(vectors.dtype, np.float16)
            self.assertEqual(vectors.shape, (2, self.embedder.dim))

    def test_legacy_list_format_is_read_and_saved_in_split_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "strategy.json")
            legacy_record = {
                "goal_summary": "legacy goal",
                "tags": [],
                "goal_tokens": ["legacy"],
                "steps_desc": [],
                "success": True,
                "error_summary": "",
                "failure_kind": "",
                "workflow_hints": [],
                "duration_ms": 0,
                "timestamp": "2026-03-24T00:00:00",
                "embedding": [1.0, 0.0, 0.0],
            }
            with open(path, "w", encoding="utf-8") as handle:
                json.dump([legacy_record], handle)

            memory = StrategyMemory(filepath=path)
            self.assertEqual(memory.count(), 1)
            self.assertIn("legacy goal", memory.get_relevant_context("legacy goal"))
            memory.flush()

            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)

            self.assertIsInstance(payload, dict)
            self.assertEqual(payload["records"][0]["goal_summary"], "legacy goal")
            self.assertNotIn("embedding", payload["records"][0])
            self.assertTrue(os.path.exists(os.path.join(tmp, "strategy_embeddings.npy")))
            vectors = np.load(os.path.join(tmp, "strategy_embeddings.npy"))
            np.testing.assert_array_equal(vectors[0], [1.0, 0.0, 0.0])

    def test_record_id_mismatch_disables_vectors_and_schedules_reembedding(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "strategy.json")
            memory = StrategyMemory(filepath=path)
            memory.record("candidate wording", [], True)
            memory.flush()
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            payload["record_ids"] = ["stale-id"]
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)

            self.worker_factory.reset_mock()
            loaded = StrategyMemory(filepath=path)

            self.assertFalse(loaded._embedding_valid)
            self.worker_factory.assert_called_once()
            with patch.object(loaded, "_extract_tags", return_value=[]), patch.object(
                loaded, "_extract_tokens", return_value={"candidate"}
            ), patch.object(
                loaded,
                "_extract_ngrams",
                side_effect=lambda text: {"query-gram"}
                if text == "paraphrase"
                else {"record-gram"},
            ):
                self.assertEqual(
                    loaded.search_similar_records("paraphrase"), [loaded._records[0]]
                )

    def test_semantic_candidate_surfaces_when_lexical_score_is_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "strategy.json")
            memory = StrategyMemory(filepath=path)
            memory.record("candidate wording", [], True)
            record = memory._records[0]
            record.goal_tokens = ["candidate"]
            memory.flush()
            memory = StrategyMemory(filepath=path)
            record = memory._records[0]

            def ngrams(text):
                return {"query-gram"} if text == "paraphrased request" else {"record-gram"}

            with patch.object(memory, "_extract_tags", return_value=[]), patch.object(
                memory, "_extract_tokens", return_value={"paraphrase"}
            ), patch.object(memory, "_extract_ngrams", side_effect=ngrams):
                self.assertEqual(memory._token_similarity({"paraphrase"}, {"candidate"}), 0.0)
                self.assertEqual(memory._ngram_similarity({"query-gram"}, {"record-gram"}), 0.0)

                results = memory.search_similar_records("paraphrased request", limit=2)

            self.assertIn(record, results)

    def test_lesson_lookup_stats_and_repeated_failures_are_available(self):
        # get_stats()는 record() 시점과 조회 시점 각각에서 datetime.now()를 다시
        # 호출한다. 실제 시계를 쓰면 두 시점 사이의 실행 지연(특히 느린 CI
        # 러너)이 날짜 경계와 겹칠 때 드물게 window 필터가 어긋날 수 있으므로,
        # 시각을 고정해 테스트를 실제 시계 타이밍과 무관하게 만든다.
        fixed_now = datetime(2026, 1, 1, 12, 0, 0)

        class _FrozenDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed_now

        with tempfile.TemporaryDirectory() as tmp, \
                patch("agent.strategy_memory.datetime", _FrozenDateTime):
            memory = StrategyMemory(filepath=os.path.join(tmp, "strategy.json"))
            now = fixed_now.isoformat()
            memory.record("브라우저 다운로드 자동화", [], False, error="timeout", failure_kind="timeout", lesson="대기 후 재확인", duration_ms=120)
            memory.record("브라우저 다운로드 자동화", [], False, error="timeout", failure_kind="timeout", lesson="도메인별 셀렉터 점검", duration_ms=150)
            memory.record("브라우저 다운로드 자동화", [], True, duration_ms=90)
            for record in memory._records:
                record.timestamp = now
            memory._save()

            lessons = memory.get_lessons_by_cause("timeout", limit=2)
            stats = memory.get_stats(days=7)
            repeated = memory.get_repeated_failures(min_count=2)

            self.assertEqual(len(lessons), 2)
            self.assertIn("대기 후 재확인", lessons)
            self.assertEqual(stats["total"], 3)
            self.assertEqual(stats["fail"], 2)
            self.assertTrue(any(kind == "timeout" and count == 2 for kind, count in repeated))

    def test_learning_page_data_lists_skill_usage_and_deletes_only_lesson(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = StrategyMemory(filepath=os.path.join(tmp, "strategy.json"))
            memory.record(
                "스킬 작업",
                [],
                True,
                lesson="이전 성공 교훈",
                skill_id="skill_a",
            )
            memory.record(
                "스킬 작업",
                [],
                False,
                lesson="최근 실패 교훈",
                skill_id="skill_a",
            )
            first, latest = memory._records

            usage = memory.get_skill_usage()["skill_a"]
            lessons = memory.get_recent_lessons()

            self.assertEqual(usage["total"], 2)
            self.assertEqual(usage["success_rate"], 0.5)
            self.assertEqual(usage["last_used"], latest.timestamp)
            self.assertEqual(
                [item.record_id for item in lessons],
                [latest.record_id, first.record_id],
            )
            self.assertTrue(memory.delete_lesson(latest.record_id))
            self.assertFalse(memory.delete_lesson(latest.record_id))
            self.assertEqual(memory.count(), 2)
            self.assertEqual(memory.get_recent_lessons(), [first])

            memory.flush()
            with open(memory.filepath, "r", encoding="utf-8") as handle:
                saved_records = json.load(handle)["records"]
            self.assertEqual(saved_records[1]["lesson"], "")
            self.assertEqual(saved_records[1]["skill_id"], "skill_a")

    def test_flush_persists_pending_debounced_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "strategy.json")
            memory = StrategyMemory(filepath=path)
            memory.record("보고서 저장", [], True)

            memory.flush()

            self.assertTrue(os.path.exists(path))
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self.assertEqual(len(payload["records"]), 1)


if __name__ == "__main__":
    unittest.main()
