import os
import sys
import threading
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.llm_provider import LLMProvider


class LLMProviderTests(unittest.TestCase):
    def test_provider_does_not_apply_code_default_model(self):
        provider = LLMProvider(provider="nvidia_nim")

        self.assertEqual(provider.model, "")
        self.assertEqual(provider.planner_model, "")
        self.assertEqual(provider.execution_model, "")

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

    def test_resolve_route_keeps_base_model_when_router_disabled(self):
        provider = LLMProvider(
            provider="nvidia_nim",
            api_key="test-key",
            model="selected-base-model",
            planner_model="selected-planner-model",
            execution_model="selected-execution-model",
            planner_provider="gemini",
            execution_provider="groq",
            router_enabled=False,
        )
        provider.client = object()
        provider.planner_client = object()
        provider.execution_client = object()

        client, selected_provider, selected_model = provider._resolve_route("코드 버그 수정해줘")

        self.assertIs(client, provider.client)
        self.assertEqual(selected_provider, "nvidia_nim")
        self.assertEqual(selected_model, "selected-base-model")

    def test_resolve_route_selects_execution_role_model_when_router_enabled(self):
        provider = LLMProvider(
            provider="nvidia_nim",
            api_key="test-key",
            model="selected-base-model",
            planner_model="selected-planner-model",
            execution_model="selected-execution-model",
            planner_provider="gemini",
            execution_provider="groq",
            router_enabled=True,
        )
        provider.client = object()
        provider.planner_client = object()
        provider.execution_client = object()

        client, selected_provider, selected_model = provider._resolve_route("코드 버그 수정해줘")

        self.assertIs(client, provider.execution_client)
        self.assertEqual(selected_provider, "groq")
        self.assertEqual(selected_model, "selected-execution-model")

    def test_resolve_route_selects_planner_role_model_when_router_enabled(self):
        provider = LLMProvider(
            provider="nvidia_nim",
            api_key="test-key",
            model="selected-base-model",
            planner_model="selected-planner-model",
            execution_model="selected-execution-model",
            planner_provider="gemini",
            execution_provider="groq",
            router_enabled=True,
        )
        provider.client = object()
        provider.planner_client = object()
        provider.execution_client = object()

        client, selected_provider, selected_model = provider._resolve_route("복잡한 작업을 자세히 분석해서 계획 세워줘")

        self.assertIs(client, provider.planner_client)
        self.assertEqual(selected_provider, "gemini")
        self.assertEqual(selected_model, "selected-planner-model")

    def test_resolve_route_falls_back_to_selected_base_model_when_role_model_is_empty(self):
        provider = LLMProvider(
            provider="nvidia_nim",
            api_key="test-key",
            model="selected-base-model",
            planner_model="",
            execution_model="",
            planner_provider="gemini",
            execution_provider="groq",
            router_enabled=True,
        )
        provider.client = object()
        provider.planner_client = object()
        provider.execution_client = object()

        client, selected_provider, selected_model = provider._resolve_route("코드 버그 수정해줘")

        self.assertIs(client, provider.execution_client)
        self.assertEqual(selected_provider, "groq")
        self.assertEqual(selected_model, "selected-base-model")

    def test_get_role_fallback_targets_prioritizes_selected_planner_then_base_then_execution(self):
        provider = LLMProvider(
            provider="nvidia_nim",
            api_key="test-key",
            model="selected-base-model",
            planner_model="selected-planner-model",
            execution_model="selected-execution-model",
            planner_provider="gemini",
            execution_provider="groq",
            router_enabled=True,
        )
        provider.client = object()
        provider.planner_client = object()
        provider.execution_client = object()

        targets = provider.get_role_fallback_targets("planner")

        self.assertEqual(
            [(selected_provider, selected_model) for _, selected_provider, selected_model in targets],
            [
                ("gemini", "selected-planner-model"),
                ("nvidia_nim", "selected-base-model"),
                ("groq", "selected-execution-model"),
            ],
        )

    def test_should_cache_only_static_questions(self):
        provider = LLMProvider()

        self.assertTrue(provider._should_cache("파이썬 딕셔너리가 뭐야?"))
        self.assertFalse(provider._should_cache("지금 몇 시야?"))
        self.assertFalse(provider._should_cache("오늘 날씨 알려줘"))

    def test_history_updates_are_thread_safe(self):
        provider = LLMProvider()

        def worker(index: int):
            provider.add_to_history("user", f"msg-{index}")

        threads = [threading.Thread(target=worker, args=(idx,)) for idx in range(30)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        snapshot = provider._history_snapshot()
        self.assertEqual(len(snapshot), 20)
        self.assertTrue(all(item["role"] == "user" for item in snapshot))

    def test_emit_stream_text_sends_incremental_chunks(self):
        provider = LLMProvider()
        chunks = []

        provider._emit_stream_text("abcdefghijklmnopqrstuvwxyz", chunks.append, chunk_size=10)

        self.assertEqual(chunks, ["abcdefghij", "klmnopqrst", "uvwxyz"])


if __name__ == "__main__":
    unittest.main()
