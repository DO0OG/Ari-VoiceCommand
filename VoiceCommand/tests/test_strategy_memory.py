import json
import os
import tempfile
import unittest
from datetime import datetime


from agent.strategy_memory import StrategyMemory


class StrategyMemoryTests(unittest.TestCase):
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

    def test_lesson_lookup_stats_and_repeated_failures_are_available(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = StrategyMemory(filepath=os.path.join(tmp, "strategy.json"))
            now = datetime.now().isoformat()
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

    def test_flush_persists_pending_debounced_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "strategy.json")
            memory = StrategyMemory(filepath=path)
            memory.record("보고서 저장", [], True)

            memory.flush()

            self.assertTrue(os.path.exists(path))
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            self.assertEqual(len(payload), 1)


if __name__ == "__main__":
    unittest.main()
