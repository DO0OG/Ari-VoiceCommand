import json
import os
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

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


if __name__ == "__main__":
    unittest.main()
