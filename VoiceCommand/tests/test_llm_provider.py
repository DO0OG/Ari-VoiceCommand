import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.llm_provider import LLMProvider


class LLMProviderTests(unittest.TestCase):
    def test_normalize_run_agent_task_prefers_detailed_explanation(self):
        provider = LLMProvider()

        args = provider._normalize_tool_arguments(
            "run_agent_task",
            {
                "goal": "Ari autonomy test",
                "explanation": "바탕화면에 Ari autonomy test 폴더를 만들고 열린 창 제목들을 요약해 markdown으로 저장해줘.",
            },
            "Ari autonomy test",
        )

        self.assertIn("바탕화면에 Ari autonomy test 폴더", args["goal"])

    def test_normalize_run_agent_task_prefers_detailed_explanation_over_generic_goal(self):
        provider = LLMProvider()

        args = provider._normalize_tool_arguments(
            "run_agent_task",
            {
                "goal": "바탕화면에 폴더 만들기, 창 제목 수집 및 분류, markdown 보고서 생성",
                "explanation": "바탕화면에 'Ari autonomy final audit' 폴더를 만들고 창 제목을 분류한 markdown 보고서를 summary.md로 저장해줘.",
            },
            "바탕화면에 Ari autonomy final audit 폴더 만들기",
        )

        self.assertIn("Ari autonomy final audit", args["goal"])

    def test_normalize_run_agent_task_ignores_generic_explanation(self):
        provider = LLMProvider()

        args = provider._normalize_tool_arguments(
            "run_agent_task",
            {
                "goal": "바탕화면에 Ari workspace audit 폴더를 만들고 summary.md 저장",
                "explanation": "복합 작업을 실행할게요.",
            },
            "바탕화면에 Ari workspace audit 폴더를 만들고 summary.md 저장",
        )

        self.assertIn("Ari workspace audit", args["goal"])

    def test_clean_response_removes_tool_call_artifacts(self):
        provider = LLMProvider()

        cleaned = provider._clean_response(
            '(평온) tool_calls: [{"name":"run_agent_task"}] <function=run_agent_task>{"goal":"Ari autonomy test"}</function> 진행할게요.'
        )

        self.assertEqual(cleaned, "(평온) 진행할게요.")


if __name__ == "__main__":
    unittest.main()
