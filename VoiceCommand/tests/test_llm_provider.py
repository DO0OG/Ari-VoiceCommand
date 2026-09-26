import threading
import unittest
from unittest.mock import patch
from unittest.mock import Mock
from types import SimpleNamespace


from agent.llm_provider import LLMProvider


class LLMProviderTests(unittest.TestCase):
    def test_application_request_sends_available_controls_to_completion(self):
        provider = LLMProvider(model="test")
        provider.client = Mock()
        provider.client.chat.completions.create.return_value = SimpleNamespace(choices=[
            SimpleNamespace(message=SimpleNamespace(content="", tool_calls=[SimpleNamespace(
                id="open-1", function=SimpleNamespace(name="launch_app", arguments='{"app_name":"네이버 웨일"}'),
            )])),
        ])
        with patch.object(provider, "_build_system", return_value="system"), \
             patch.object(provider, "_get_skill_context", return_value={}), \
             patch("memory.memory_manager.get_memory_manager") as memory:
            memory.return_value.clean_response.side_effect = lambda value: value
            for goal in ("네이버 웨일 열어줘", "디스코드 켜줘"):
                _, calls = provider.chat_with_tools(goal)
                request = provider.client.chat.completions.create.call_args.kwargs
                names = {item["function"]["name"] for item in request["tools"]}
                self.assertIn("launch_app", names)
        request = provider.client.chat.completions.create.call_args.kwargs
        names = {item["function"]["name"] for item in request["tools"]}
        self.assertTrue({"launch_app", "close_app", "get_running_apps", "focus_window"} <= names)
        self.assertEqual(request["tool_choice"], "required")
        self.assertEqual(calls, [{"id": "open-1", "name": "launch_app", "arguments": {"app_name": "네이버 웨일"}}])

    def test_unsaved_chat_sends_current_message_without_memory_side_effects(self):
        for backend in ("openai", "anthropic"):
            with self.subTest(backend=backend):
                provider = LLMProvider(provider=backend, model="test")
                provider.client = Mock()
                provider.add_to_history("user", "previous")
                before = provider._history_snapshot()
                provider.client.messages.create.return_value = SimpleNamespace(
                    content=[SimpleNamespace(text="summary")]
                )
                with patch.object(provider, "_build_system", return_value="system"), \
                     patch.object(provider, "_should_cache", return_value=False), \
                     patch.object(provider, "_stream_or_chat_completion", return_value="summary") as completion, \
                     patch("memory.memory_manager.get_memory_manager") as memory:
                    result = provider.chat("summarize this transcript", include_context=False, save_history=False)
                request = provider.client.messages.create.call_args if backend == "anthropic" else completion.call_args
                self.assertEqual(request.kwargs["messages"][-1], {"role": "user", "content": "summarize this transcript"})
                self.assertEqual(result, "summary")
                self.assertEqual(provider._history_snapshot(), before)
                memory.assert_not_called()

    def test_anthropic_tool_turn_preserves_original_blocks_and_result_pair(self):
        provider = LLMProvider(provider="anthropic", model="test")
        provider.client = Mock()
        original = [
            SimpleNamespace(type="text", text="checking"),
            SimpleNamespace(type="tool_use", id="call-1", name="read_file", input={"path": "a"}),
            SimpleNamespace(type="tool_use", id="call-2", name="read_file", input={"path": "b"}),
        ]
        provider.client.messages.create.side_effect = [
            SimpleNamespace(content=original),
            SimpleNamespace(content=[SimpleNamespace(type="text", text="done")]),
        ]
        provider.add_to_history("user", "read files")
        with patch.object(provider, "_build_system", return_value="system"):
            _, calls = provider._anthropic_chat("read files", False, True)
            self.assertEqual(provider._history_snapshot()[-1]["content"], [vars(b) for b in original])
            self.assertEqual(provider.feed_tool_result("read files", calls, ["a data", "b data"]), "done")
        messages = provider.client.messages.create.call_args.kwargs["messages"]
        self.assertTrue(provider.client.messages.create.call_args.kwargs["tools"])
        self.assertEqual(messages[-2], {"role": "assistant", "content": [vars(b) for b in original]})
        self.assertEqual([b["tool_use_id"] for b in messages[-1]["content"]], ["call-1", "call-2"])
        self.assertEqual(provider._history_snapshot()[-2], messages[-1])
        # A token budget must not split the tool-use/result pair.
        provider.conversation_history.pop()
        self.assertEqual(len(provider._history_for_context(max_tokens=1)), 2)

    def test_anthropic_tool_result_rejects_missing_or_mismatched_calls(self):
        provider = LLMProvider(provider="anthropic", model="test")
        provider.client = Mock()
        calls = [{"id": "missing", "name": "read_file", "arguments": {}}]
        self.assertIn("실패", provider.feed_tool_result("read", calls, []))
        self.assertIn("실패", provider.feed_tool_result("read", calls, ["data"]))
        provider.client.messages.create.assert_not_called()

    def test_anthropic_feed_failure_is_reported_and_retry_keeps_one_result_turn(self):
        provider = LLMProvider(provider="anthropic", model="test")
        provider.client = Mock()
        provider.client.messages.create.side_effect = RuntimeError("request failed")
        provider.add_to_history("assistant", [{"type": "tool_use", "id": "c", "name": "read_file", "input": {}}])
        calls = [{"id": "c", "name": "read_file", "arguments": {}}]
        with patch.object(provider, "_build_system", return_value="system"):
            for _ in range(2):
                self.assertIn("request failed", provider.feed_tool_result("read", calls, ["data"]))
        self.assertEqual(len(provider._history_snapshot()), 2)

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

    def test_analyze_request_does_not_treat_time_words_or_explanations_as_steps(self):
        provider = LLMProvider()

        self.assertNotEqual(provider._analyze_request("다음 주 날씨 알려줘")["preferred_tool"], "run_agent_task")
        self.assertNotEqual(provider._analyze_request("회의는 다음 주 몇 시야?")["preferred_tool"], "run_agent_task")
        self.assertNotEqual(provider._analyze_request("일정은 다음 주에 뭐 있어?")["preferred_tool"], "run_agent_task")
        self.assertNotEqual(provider._analyze_request("왜 그런지 설명해서 알려줘")["preferred_tool"], "run_agent_task")
        self.assertEqual(provider._analyze_request("메모장 연 다음 내용 적어줘")["preferred_tool"], "run_agent_task")
        self.assertEqual(provider._analyze_request("사진 찍은 다음 저장해줘")["preferred_tool"], "run_agent_task")
        self.assertEqual(provider._analyze_request("화면 캡처해서 저장해줘")["preferred_tool"], "run_agent_task")

    def test_analyze_request_prefers_direct_tool_only_for_single_parsed_request(self):
        provider = LLMProvider()

        capture = provider._analyze_request("화면 캡처해 줘")
        apps = provider._analyze_request("실행 중인 앱 알려 줘")
        compound = provider._analyze_request("볼륨 올리고 캡처해줘")
        tools, tool_choice = provider._select_tools_for_request(provider._analyze_request("캡처해줘"))

        self.assertEqual(capture["preferred_tool"], "take_screenshot")
        self.assertTrue(capture["force_tool"])
        self.assertEqual(apps["preferred_tool"], "get_running_apps")
        self.assertIsNone(compound["preferred_tool"])
        self.assertEqual(tool_choice, "auto")
        self.assertIn("take_screenshot", {tool["function"]["name"] for tool in tools})

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

    def test_select_tools_for_request_keeps_required_mcp_tool(self):
        provider = LLMProvider()

        tools, tool_choice = provider._select_tools_for_request(
            {
                "intent": "conversation",
                "force_tool": False,
                "preferred_tool": "mcp_call",
            },
            required_tool_names={"mcp_call"},
        )
        tool_names = {tool["function"]["name"] for tool in tools}

        self.assertEqual(tool_choice, {"type": "function", "function": {"name": "mcp_call"}})
        self.assertEqual(tool_names, {"mcp_call"})

    def test_select_tools_for_request_prefers_web_search_when_forced(self):
        provider = LLMProvider()

        tools, tool_choice = provider._select_tools_for_request(
            {
                "intent": "conversation",
                "force_tool": True,
                "preferred_tool": "web_search",
            },
            required_tool_names={"web_search"},
        )
        tool_names = {tool["function"]["name"] for tool in tools}

        self.assertEqual(tool_choice, {"type": "function", "function": {"name": "web_search"}})
        self.assertEqual(tool_names, {"web_search"})

    def test_fallback_tool_calls_from_text_prefers_web_search_when_forced(self):
        provider = LLMProvider()

        tool_calls = provider._fallback_tool_calls_from_text(
            "web_search(\"LCK 경기 결과\")",
            "오늘 LCK 경기 결과 알려줘",
            {
                "force_tool": True,
                "preferred_tool": "web_search",
                "search_query_hint": "LCK 2026-04-10 경기 결과",
            },
        )

        self.assertEqual(tool_calls[0]["name"], "web_search")
        self.assertEqual(tool_calls[0]["arguments"]["query"], "LCK 2026-04-10 경기 결과")

    def test_build_search_query_hint_uses_explicit_month_day_from_user_message(self):
        provider = LLMProvider()
        import datetime
        real_date = datetime.date

        class _FixedDate:
            @staticmethod
            def today():
                return real_date(2026, 4, 10)

        with patch("datetime.date", _FixedDate):
            query = provider._build_search_query_hint("LCK {date} 경기 결과", "4월 9일 LCK 경기 결과 알려줘")

        self.assertEqual(query, "LCK 2026-04-09 경기 결과")

    def test_build_search_query_hint_supports_english_month_day(self):
        provider = LLMProvider()
        import datetime
        real_date = datetime.date

        class _FixedDate:
            @staticmethod
            def today():
                return real_date(2026, 4, 10)

        with patch("datetime.date", _FixedDate):
            query = provider._build_search_query_hint("LCK {date} match results", "Show me LCK match results for April 9")

        self.assertEqual(query, "LCK 2026-04-09 match results")

    def test_build_system_includes_skill_prompt_when_message_matches(self):
        provider = LLMProvider()

        with patch("agent.skill_manager.get_skill_manager") as get_manager:
            get_manager.return_value.build_match_context.return_value = {
                "skills": [],
                "prompt": "[사용 가능한 스킬]\n쿠팡 MCP 스킬",
                "required_tool_names": ["mcp_call"],
                "preferred_tool": "mcp_call",
                "force_web_search": False,
                "escalate_to_agent": False,
                "search_query_template": "",
            }
            system_prompt = provider._build_system(user_message="쿠팡에서 모니터 찾아줘")

        self.assertIn("[사용 가능한 스킬]", system_prompt)
        self.assertIn("쿠팡 MCP 스킬", system_prompt)

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
