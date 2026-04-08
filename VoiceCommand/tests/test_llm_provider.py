import threading
import unittest


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

    def test_cache_key_changes_when_prompt_configuration_changes(self):
        provider_a = LLMProvider(provider="groq", model="model-a", system_prompt="prompt-a")
        provider_b = LLMProvider(provider="groq", model="model-a", system_prompt="prompt-b")

        self.assertNotEqual(
            provider_a._build_cache_key("파이썬 딕셔너리가 뭐야?", include_context=False),
            provider_b._build_cache_key("파이썬 딕셔너리가 뭐야?", include_context=False),
        )

    def test_get_available_tools_includes_core_schemas(self):
        provider = LLMProvider()

        tool_names = {tool["function"]["name"] for tool in provider.get_available_tools()}

        self.assertIn("run_agent_task", tool_names)
        self.assertIn("web_search", tool_names)
        self.assertIn("schedule_task", tool_names)

    def test_analyze_request_marks_automation_and_memory_intents(self):
        provider = LLMProvider()

        automation = provider._analyze_request("바탕화면에 폴더 만들어줘")
        memory = provider._analyze_request("저번에 내가 뭐라고 했는지 기억나?")

        self.assertEqual(automation["intent"], "automation")
        self.assertTrue(automation["force_tool"])
        self.assertEqual(memory["intent"], "memory")
        self.assertFalse(memory["force_tool"])

    def test_select_tools_for_request_excludes_execution_tools_for_memory_intent(self):
        provider = LLMProvider()

        tools, tool_choice = provider._select_tools_for_request(
            {"intent": "memory", "force_tool": False}
        )
        tool_names = {tool["function"]["name"] for tool in tools}

        self.assertEqual(tool_choice, "auto")
        self.assertNotIn("run_agent_task", tool_names)
        self.assertNotIn("execute_python_code", tool_names)
        self.assertNotIn("execute_shell_command", tool_names)
        self.assertIn("web_search", tool_names)

    def test_select_tools_for_request_prefers_schedule_tools(self):
        provider = LLMProvider()

        tools, tool_choice = provider._select_tools_for_request(
            {"intent": "schedule", "force_tool": True}
        )
        tool_names = {tool["function"]["name"] for tool in tools}

        self.assertEqual(tool_choice, "required")
        self.assertIn("schedule_task", tool_names)
        self.assertIn("set_timer", tool_names)
        self.assertNotIn("run_agent_task", tool_names)

    def test_register_plugin_tool_updates_available_tools_without_mutating_core_tools(self):
        provider = LLMProvider()
        base_tool_names = {tool["function"]["name"] for tool in provider.get_available_tools()}

        provider.register_plugin_tool(
            {
                "type": "function",
                "function": {
                    "name": "plugin_echo",
                    "description": "plugin helper",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        )

        updated_tool_names = {tool["function"]["name"] for tool in provider.get_available_tools()}
        self.assertEqual(base_tool_names | {"plugin_echo"}, updated_tool_names)

        provider.unregister_plugin_tool("plugin_echo")
        reverted_tool_names = {tool["function"]["name"] for tool in provider.get_available_tools()}
        self.assertEqual(base_tool_names, reverted_tool_names)

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
