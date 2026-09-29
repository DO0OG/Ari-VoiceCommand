import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from unittest.mock import Mock
from types import SimpleNamespace

import httpx


from agent.llm_provider import LLMProvider
from i18n.translator import _


class LLMProviderTests(unittest.TestCase):
    def _run_stream_chat(self, provider, callback, clean_response=None):
        request_context = {
            "intent": "conversation",
            "force_tool": False,
            "preferred_tool": None,
        }
        with patch.object(provider, "_build_system", return_value="system"), \
             patch.object(provider, "_get_skill_context", return_value={}), \
             patch.object(provider, "_analyze_request", return_value=request_context), \
             patch.object(provider, "_select_tools_for_request", return_value=([], "auto")), \
             patch.object(provider, "_load_int_setting", return_value=1), \
             patch.object(
                 provider,
                 "_normalize_tool_arguments",
                 side_effect=lambda name, args, user_text: args,
             ), \
             patch("memory.memory_manager.get_memory_manager") as memory:
            memory.return_value.clean_response.side_effect = clean_response or (
                lambda text: text
            )
            return provider.chat_with_tools("hello", stream_callback=callback)

    def _stream_provider(self, provider_name="openai"):
        provider = LLMProvider(provider=provider_name, model="test")
        provider.client = Mock()
        return provider

    def test_personality_section_labels_follow_ui_language(self):
        provider = LLMProvider(
            personality="calm",
            scenario="at home",
            history_instruction="listen carefully",
        )
        labels = {
            "en": {
                "[캐릭터 성격]": "[Character personality]",
                "[현재 상황]": "[Current situation]",
                "[대화 방식]": "[Conversation style]",
            },
            "ja": {
                "[캐릭터 성격]": "[キャラクターの性格]",
                "[현재 상황]": "[現在の状況]",
                "[대화 방식]": "[会話スタイル]",
            },
        }

        for language, expected in labels.items():
            translate = lambda message: expected.get(message, message)
            with (
                patch("i18n.translator.get_language", return_value=language),
                patch("i18n.translator._", side_effect=translate),
            ):
                prompt = provider.rp_generator.build_system_prompt("Ari")

            for label in expected.values():
                self.assertIn(label, prompt)

    def test_personality_examples_only_use_the_current_ui_language(self):
        provider = LLMProvider(
            personality_examples_en="English example",
            personality_examples_ja="Japanese example",
        )
        for language, included, excluded in (
            ("en", "English example", ("Japanese example",)),
            ("ja", "Japanese example", ("English example",)),
            ("ko", "", ("English example", "Japanese example")),
        ):
            with (
                patch("i18n.translator.get_language", return_value=language),
                patch("i18n.translator._", side_effect=lambda message: message),
            ):
                prompt = provider.rp_generator.build_system_prompt("Ari")

            if included:
                self.assertIn(included, prompt)
            for example in excluded:
                self.assertNotIn(example, prompt)

        with (
            patch("i18n.translator.get_language", return_value="en"),
            patch("i18n.translator._", side_effect=lambda message: message),
        ):
            prompt = LLMProvider().rp_generator.build_system_prompt("Ari")

        self.assertNotIn("[예시 대사]", prompt)

    def test_language_instruction_is_added_once_by_system_assembly(self):
        provider = LLMProvider()
        instructions = {
            "ko": "항상 한국어로 응답하세요.",
            "en": "Always respond in English.",
            "ja": "常に日本語で応答してください。",
        }
        for language, instruction in instructions.items():
            with (
                patch("i18n.translator.get_language", return_value=language),
                patch.object(provider, "_get_skill_context", return_value={}),
                patch.object(provider, "_build_situation_prompt", return_value=""),
            ):
                prompt = provider._build_system()

            self.assertEqual(prompt.count(instruction), 1)
            for other_instruction in instructions.values():
                if other_instruction != instruction:
                    self.assertNotIn(other_instruction, prompt)
            self.assertNotIn("반드시 한국어로만 대답하세요", prompt)

    def test_system_prompt_ends_with_situation_even_without_general_context(self):
        provider = LLMProvider(model="test")
        metrics = {
            "last_interaction_elapsed_minutes": 4,
            "today_interaction_count": 2,
            "continuous_use_minutes": 9,
            "local_time": "14:25",
            "recent_praise_count": 1,
        }
        context = SimpleNamespace(get_situation_metrics=lambda: metrics)
        translate = lambda message, **values: message.format(**values) if values else message
        with patch("i18n.translator._", side_effect=translate), \
             patch("memory.user_context.get_context_manager", return_value=context), \
             patch("core.window_inspector.get_foreground_fullscreen", return_value=None), \
             patch.object(provider, "_get_skill_context", return_value={}):
            prompt = provider._build_system(include_context=False, user_message="private request")

        situation = prompt.rsplit("\n\n", 1)[-1]
        self.assertIn("[상황]", situation)
        self.assertIn("4분", situation)
        self.assertIn("오늘2회", situation)
        self.assertIn("연속9분", situation)
        self.assertIn("14:25", situation)
        self.assertIn(
            "상황 블록을 참고해 말투를 조절하되, 내용을 그대로 언급하지 마세요.",
            prompt,
        )
        self.assertNotIn("전체 화면", situation)
        self.assertNotIn("private request", situation)
        self.assertTrue(prompt.endswith(situation))

    def test_situation_block_formats_elapsed_hours_and_stays_private(self):
        provider = LLMProvider()
        metrics = {
            "last_interaction_elapsed_minutes": 180,
            "today_interaction_count": 12,
            "continuous_use_minutes": 300,
            "local_time": "23:40",
            "recent_praise_count": 2,
        }
        context = SimpleNamespace(get_situation_metrics=lambda: metrics)
        translate = lambda message, **values: message.format(**values) if values else message
        with (
            patch("i18n.translator._", side_effect=translate),
            patch("memory.user_context.get_context_manager", return_value=context),
            patch("core.window_inspector.get_foreground_fullscreen", return_value=False),
        ):
            situation = provider._build_situation_prompt()

        self.assertIn("3시간", situation)
        self.assertIn("오늘12회", situation)
        self.assertIn("5시간", situation)
        self.assertIn("23:40", situation)
        self.assertIn("2회", situation)
        self.assertIn("전체 화면: 아니요", situation)
        self.assertNotIn("private", situation)
        self.assertLessEqual(len(situation), 120)

    def test_situation_prompt_includes_short_character_mood(self):
        provider = LLMProvider()
        metrics = {
            "last_interaction_elapsed_minutes": 4,
            "today_interaction_count": 2,
            "continuous_use_minutes": 9,
            "local_time": "14:25",
            "recent_praise_count": 1,
        }
        context = SimpleNamespace(get_situation_metrics=lambda: metrics)
        mood_state = SimpleNamespace(values=lambda: (0.6, 0.4))
        translate = lambda message, **values: message.format(**values) if values else message
        with (
            patch("agent.llm_provider._", side_effect=translate),
            patch("memory.user_context.get_context_manager", return_value=context),
            patch("core.window_inspector.get_foreground_fullscreen", return_value=None),
            patch("agent.llm_provider.get_mood_state", return_value=mood_state),
        ):
            situation = provider._build_situation_prompt()

        self.assertIn("기분 좋음", situation)
        self.assertLessEqual(len(situation), 120)

    def test_static_answer_cache_key_changes_with_situation_metadata(self):
        provider = LLMProvider(provider="openai", model="test")
        provider.client = Mock()
        with (
            patch.object(
                provider,
                "_resolve_route",
                return_value=(provider.client, "openai", "test"),
            ),
            patch.object(provider, "_should_cache", return_value=True),
            patch.object(
                provider,
                "_build_situation_prompt",
                side_effect=("[Situation] 1", "[Situation] 2", "[Situation] 2"),
            ),
            patch.object(
                provider,
                "_stream_or_chat_completion",
                side_effect=("first", "second"),
            ) as completion,
            patch.object(provider, "_get_skill_context", return_value={}),
        ):
            first = provider.chat("what is Ari?", include_context=False, save_history=False)
            second = provider.chat("what is Ari?", include_context=False, save_history=False)
            third = provider.chat("what is Ari?", include_context=False, save_history=False)

        self.assertEqual((first, second, third), ("first", "second", "second"))
        self.assertEqual(completion.call_count, 2)

    def test_cached_answer_records_completed_interaction(self):
        provider = LLMProvider(provider="openai", model="test")
        provider.client = Mock()
        provider._response_cache = Mock()
        provider._response_cache.get.return_value = "cached answer"
        context = Mock()
        memory_manager = Mock()
        with (
            patch.object(
                provider,
                "_resolve_route",
                return_value=(provider.client, "openai", "test"),
            ),
            patch.object(provider, "_should_cache", return_value=True),
            patch.object(provider, "_build_situation_prompt", return_value="[Situation]"),
            patch.object(provider, "_build_cache_key", return_value="cache-key"),
            patch("memory.user_context.get_context_manager", return_value=context),
            patch("memory.memory_manager.get_memory_manager", return_value=memory_manager),
            patch.object(provider, "_stream_or_chat_completion") as completion,
        ):
            result = provider.chat("repeat this", include_context=False)

        self.assertEqual(result, "cached answer")
        context.record_interaction.assert_called_once_with("repeat this")
        memory_manager.start_fact_suggestion_extraction.assert_called_once_with(
            "repeat this", provider.extract_memory_suggestions
        )
        completion.assert_not_called()

    def test_situation_prompt_stays_within_the_50_token_budget(self):
        provider = LLMProvider()
        metrics = {
            "last_interaction_elapsed_minutes": 1000000,
            "today_interaction_count": 1000000,
            "continuous_use_minutes": 1000000,
            "local_time": "14:25:59",
            "recent_praise_count": 1000000,
        }
        context = SimpleNamespace(get_situation_metrics=lambda: metrics)
        translate = lambda message, **values: message.format(**values) if values else message
        with (
            patch("i18n.translator._", side_effect=translate),
            patch("memory.user_context.get_context_manager", return_value=context),
            patch("core.window_inspector.get_foreground_fullscreen", return_value=False),
        ):
            prompt = provider._build_situation_prompt()

        self.assertLessEqual(len(prompt), 120)
        self.assertEqual(prompt.count("999+"), 4)
        self.assertIn("14:25", prompt)

    def test_translated_situation_blocks_stay_within_character_limit(self):
        provider = LLMProvider()
        metrics = {
            "last_interaction_elapsed_minutes": 1000000,
            "today_interaction_count": 1000000,
            "continuous_use_minutes": 1000000,
            "local_time": "23:59",
            "recent_praise_count": 1000000,
        }
        context = SimpleNamespace(get_situation_metrics=lambda: metrics)
        block_message = (
            "[상황] 전{elapsed} · 오늘{today}회 · 연속{continuous} · "
            "시각{time} · 칭찬24h {praise}회"
        )
        translations = {
            "ko": {},
            "en": {
                block_message: (
                    "[Situation] Last {elapsed} · Today {today} chats · "
                    "Use {continuous} · Time {time} · Praise24h {praise}"
                ),
                " · 전체 화면: {fullscreen}": " · Fullscreen: {fullscreen}",
                " · 기분 {mood}": " · Mood {mood}",
                "{minutes}분": "{minutes}m",
                "{hours}시간": "{hours}h",
                "없음": "None",
                "예": "Yes",
                "아니요": "No",
                "평온": "calm",
            },
            "ja": {
                block_message: (
                    "[状況] 前回 {elapsed} · 今日 {today}回 · "
                    "連続 {continuous} · 時刻 {time} · 称賛24h {praise}回"
                ),
                " · 전체 화면: {fullscreen}": " · 全画面: {fullscreen}",
                " · 기분 {mood}": " · 気分 {mood}",
                "{minutes}분": "{minutes}分",
                "{hours}시간": "{hours}時間",
                "없음": "なし",
                "예": "はい",
                "아니요": "いいえ",
                "평온": "穏やか",
            },
        }
        for language, catalogue in translations.items():
            def translate(message, **values):
                translated = catalogue.get(message, message)
                return translated.format(**values) if values else translated

            with self.subTest(language=language), patch(
                "agent.llm_provider._", side_effect=translate
            ), patch("memory.user_context.get_context_manager", return_value=context), patch(
                "core.window_inspector.get_foreground_fullscreen", return_value=True
            ):
                situation = provider._build_situation_prompt()

            self.assertLessEqual(len(situation), 120)
            if language == "ko":
                self.assertIn("기분 평온", situation)
            elif language == "en":
                self.assertTrue(situation.startswith("[Situation]"))
                self.assertIn("Mood calm", situation)
            elif language == "ja":
                self.assertTrue(situation.startswith("[状況]"))
                self.assertIn("気分 穏やか", situation)

    def test_rp_prompt_localizes_situation_guidance(self):
        provider = LLMProvider()
        instruction = (
            "Use the situation block to guide your tone, but do not repeat its "
            "contents verbatim."
        )
        with patch("i18n.translator.get_language", return_value="en"), patch(
            "i18n.translator._", return_value=instruction
        ):
            prompt = provider.rp_generator.build_system_prompt("You are Ari.")

        self.assertIn(instruction, prompt)

    def test_system_override_also_ends_with_situation(self):
        provider = LLMProvider(provider="openai", model="test")
        provider.client = Mock()
        with (
            patch.object(
                provider,
                "_resolve_route",
                return_value=(provider.client, "openai", "test"),
            ),
            patch.object(provider, "_should_cache", return_value=False),
            patch.object(provider, "_build_situation_prompt", return_value="[Situation]"),
            patch.object(
                provider,
                "_stream_or_chat_completion",
                return_value="ok",
            ) as completion,
        ):
            response = provider.chat(
                "do this",
                include_context=False,
                system_override="special system",
                save_history=False,
            )

        sent_system = completion.call_args.kwargs["messages"][0]["content"]
        self.assertEqual(response, "ok")
        self.assertEqual(sent_system, "special system\n\n[Situation]")

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
                calls = provider.chat_with_tools(goal)[1]
                request = provider.client.chat.completions.create.call_args.kwargs
                names = {item["function"]["name"] for item in request["tools"]}
                self.assertIn("launch_app", names)
                self.assertTrue(
                    memory.return_value.process_interaction.call_args.kwargs[
                        "contains_tool_result"
                    ]
                )
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
            calls = provider._anthropic_chat("read files", False, True)[1]
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

    def test_chat_with_tools_streams_content_before_stream_finishes(self):
        provider = self._stream_provider()
        streamed = []

        def response_stream():
            yield {"choices": [{"delta": {"content": "안녕"}}]}
            self.assertEqual(streamed, ["안녕"])
            yield {"choices": [{"delta": {"content": "하세요"}}]}

        provider.client.chat.completions.create.return_value = response_stream()

        result = self._run_stream_chat(provider, streamed.append)

        self.assertEqual(result, ("안녕하세요", []))
        self.assertEqual(streamed, ["안녕", "하세요"])
        self.assertTrue(provider.client.chat.completions.create.call_args.kwargs["stream"])

    def test_chat_with_tools_accumulates_tool_call_argument_fragments(self):
        provider = self._stream_provider()
        streamed = []
        provider.client.chat.completions.create.return_value = [
            {"choices": [{"delta": {"tool_calls": [{
                "index": 0,
                "id": "call-1",
                "function": {"name": "get_current_time", "arguments": "{"},
            }]}}]},
            {"choices": [{"delta": {"tool_calls": [{
                "index": 0,
                "function": {"arguments": "}"},
            }]}}]},
        ]

        result = self._run_stream_chat(provider, streamed.append)

        self.assertEqual(result, ("", [{
            "id": "call-1",
            "name": "get_current_time",
            "arguments": {},
        }]))
        self.assertEqual(streamed, [])

    def test_chat_with_tools_streams_preface_alongside_tool_call_deltas(self):
        provider = self._stream_provider()
        streamed = []
        provider.client.chat.completions.create.return_value = [
            {"choices": [{"delta": {
                "content": "바로 확인해볼게요.",
                "tool_calls": [{
                    "index": 0,
                    "id": "call-2",
                    "function": {
                        "name": "get_current_time",
                        "arguments": "{}",
                    },
                }],
            }}]},
        ]

        result = self._run_stream_chat(provider, streamed.append)

        self.assertEqual(result, ("바로 확인해볼게요.", [{
            "id": "call-2",
            "name": "get_current_time",
            "arguments": {},
        }]))
        self.assertEqual(streamed, ["바로 확인해볼게요."])

    def test_chat_with_tools_does_not_stream_textual_json(self):
        provider = self._stream_provider()
        streamed = []
        provider.client.chat.completions.create.return_value = [
            {"choices": [{"delta": {"content": '{"tool_calls":['}}]},
            {"choices": [{"delta": {"content": '{"name":"get_current_time","arguments":{}}]}'}}]},
        ]

        result = self._run_stream_chat(
            provider,
            streamed.append,
            clean_response=lambda text: "JSON should remain unchanged",
        )

        self.assertEqual(
            result[0],
            '{"tool_calls":[{"name":"get_current_time","arguments":{}}]}',
        )
        self.assertEqual(streamed, [])

    def test_custom_provider_falls_back_when_streaming_is_unsupported(self):
        class UnsupportedStreamError(RuntimeError):
            status_code = 400

        provider = self._stream_provider()
        provider.provider = "custom-test"
        provider.provider_configs["custom-test"] = {"requires_api_key": False}
        non_stream_response = {
            "choices": [{"message": {"content": "완료", "tool_calls": []}}],
        }
        provider.client.chat.completions.create.side_effect = [
            UnsupportedStreamError("stream is not supported"),
            non_stream_response,
            non_stream_response,
        ]
        streamed = []

        self.assertEqual(
            self._run_stream_chat(provider, streamed.append),
            ("완료", []),
        )
        self.assertIs(provider._tool_streaming_support["custom-test"], False)
        self.assertEqual(streamed, ["완료"])

        self._run_stream_chat(provider, lambda text: None)

        calls = provider.client.chat.completions.create.call_args_list
        self.assertTrue(calls[0].kwargs["stream"])
        self.assertNotIn("stream", calls[1].kwargs)
        self.assertNotIn("stream", calls[2].kwargs)

    def test_first_stream_token_timeout_tries_next_provider(self):
        provider = self._stream_provider()
        fallback_client = Mock()

        class TimeoutStream:
            def __iter__(self):
                return self

            def __next__(self):
                raise TimeoutError("read timed out")

        provider.client.chat.completions.create.return_value = TimeoutStream()
        fallback_client.chat.completions.create.return_value = [
            {"choices": [{"delta": {"content": "fallback"}}]},
        ]
        provider.get_role_fallback_targets = Mock(return_value=[
            (provider.client, "openai", "test"),
            (fallback_client, "fallback", "fallback-model"),
        ])
        streamed = []

        result = self._run_stream_chat(provider, streamed.append)

        self.assertEqual(result, ("fallback", []))
        self.assertEqual(streamed, ["fallback"])
        provider.client.chat.completions.create.assert_called_once()
        self.assertEqual(
            fallback_client.chat.completions.create.call_args.kwargs["model"],
            "fallback-model",
        )

    def test_custom_provider_stream_timeout_tries_next_provider(self):
        provider = self._stream_provider()
        provider.provider = "custom-timeout"
        provider.provider_configs["custom-timeout"] = {"requires_api_key": False}
        fallback_client = Mock()

        class TimeoutStream:
            def __iter__(self):
                return self

            def __next__(self):
                raise TimeoutError("read timed out")

        provider.client.chat.completions.create.return_value = TimeoutStream()
        fallback_client.chat.completions.create.return_value = [
            {"choices": [{"delta": {"content": "fallback"}}]},
        ]
        provider.get_role_fallback_targets = Mock(return_value=[
            (provider.client, "custom-timeout", "test"),
            (fallback_client, "fallback", "fallback-model"),
        ])
        streamed = []

        result = self._run_stream_chat(provider, streamed.append)

        self.assertEqual(result, ("fallback", []))
        self.assertEqual(streamed, ["fallback"])
        self.assertEqual(
            fallback_client.chat.completions.create.call_args.kwargs["model"],
            "fallback-model",
        )

    def test_anthropic_tool_result_rejects_missing_or_mismatched_calls(self):
        provider = LLMProvider(provider="anthropic", model="test")
        provider.client = Mock()
        calls = [{"id": "missing", "name": "read_file", "arguments": {}}]
        self.assertIn("실패", provider.feed_tool_result("read", calls, []))
        self.assertIn("실패", provider.feed_tool_result("read", calls, ["data"]))
        provider.client.messages.create.assert_not_called()

    def test_local_tool_response_records_anthropic_result_without_request(self):
        provider = LLMProvider(provider="anthropic", model="test")
        provider.client = Mock()
        calls = [{"id": "call-1", "name": "launch_app", "arguments": {"name": "메모장"}}]
        provider.add_to_history("user", "메모장을 열어줘")
        provider.add_to_history("assistant", [{
            "type": "tool_use",
            "id": "call-1",
            "name": "launch_app",
            "input": {"name": "메모장"},
        }])

        provider.record_tool_result(calls, ["메모장"], "앱을 실행했습니다.")

        history = provider._history_snapshot()
        self.assertEqual(history[-2], {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": "call-1",
                "content": "메모장",
            }],
        })
        self.assertEqual(history[-1], {"role": "assistant", "content": "앱을 실행했습니다."})
        provider.client.messages.create.assert_not_called()

    def test_anthropic_feed_failure_is_reported_and_retry_keeps_one_result_turn(self):
        provider = LLMProvider(provider="anthropic", model="test")
        provider.client = Mock()
        provider.client.messages.create.side_effect = RuntimeError("request failed")
        provider.add_to_history("assistant", [{"type": "tool_use", "id": "c", "name": "read_file", "input": {}}])
        calls = [{"id": "c", "name": "read_file", "arguments": {}}]
        with patch.object(provider, "_build_system", return_value="system"):
            for expected in ("request failed", "request failed"):
                self.assertIn(expected, provider.feed_tool_result("read", calls, ["data"]))
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
            [(target[1], target[2]) for target in targets],
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

    def test_isolated_chat_omits_situation_history_and_cache(self):
        provider = self._stream_provider()
        messages = []

        def capture_messages(_client, **kwargs):
            messages.extend(kwargs["messages"])
            return "digest"

        with (
            patch.object(
                provider,
                "_resolve_route",
                return_value=(provider.client, "openai", "test"),
            ),
            patch.object(provider, "_build_system", return_value="system"),
            patch.object(
                provider,
                "_build_situation_prompt",
                side_effect=AssertionError("situation should be excluded"),
            ),
            patch.object(
                provider,
                "_history_for_context",
                side_effect=AssertionError("history should be excluded"),
            ),
            patch.object(provider, "_stream_or_chat_completion", side_effect=capture_messages),
            patch.object(provider._response_cache, "set") as cache_set,
        ):
            result = provider.chat(
                "digest input",
                include_context=False,
                save_history=False,
                include_history=False,
            )

        self.assertEqual(result, "digest")
        self.assertEqual([message["role"] for message in messages], ["system", "user"])
        cache_set.assert_not_called()

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
        self.assertIn("memory_search", tool_names)
        self.assertIn("memory_remember", tool_names)
        self.assertIn("memory_forget", tool_names)

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
        self.assertIn("memory_search", tool_names)
        self.assertIn("memory_remember", tool_names)
        self.assertIn("memory_forget", tool_names)

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

    def test_plugin_tools_are_filtered_by_declared_intent(self):
        provider = LLMProvider()
        schemas = (
            ("plugin_unscoped", None),
            ("plugin_automation", ["automation"]),
            ("plugin_conversation", ["conversation"]),
            ("plugin_zeta", ["conversation"]),
            ("plugin_alpha", ["conversation"]),
        )
        for name, intents in schemas:
            schema = {
                "type": "function",
                "function": {
                    "name": name,
                    "description": name,
                    "parameters": {"type": "object", "properties": {}},
                },
            }
            if intents is None:
                provider.register_plugin_tool(schema)
            else:
                provider.register_plugin_tool(schema, intents=intents)

        conversation = provider._select_tools_for_request(
            {"intent": "conversation", "force_tool": False}
        )[0]
        conversation_names = [tool["function"]["name"] for tool in conversation]
        plugin_names = [name for name in conversation_names if name.startswith("plugin_")]

        self.assertNotIn("plugin_unscoped", conversation_names)
        self.assertNotIn("plugin_automation", conversation_names)
        self.assertIn("plugin_conversation", conversation_names)
        self.assertEqual(plugin_names, sorted(plugin_names))

        automation = provider._select_tools_for_request(
            {"intent": "automation", "force_tool": False}
        )[0]
        automation_names = {tool["function"]["name"] for tool in automation}

        self.assertIn("plugin_unscoped", automation_names)
        self.assertIn("plugin_automation", automation_names)
        self.assertNotIn("plugin_conversation", automation_names)

        other = provider._select_tools_for_request(
            {"intent": "other", "force_tool": False},
            required_tool_names={"get_current_time"},
        )[0]
        other_names = {tool["function"]["name"] for tool in other}

        self.assertEqual(other_names, {"get_current_time", "plugin_unscoped"})

    def test_anthropic_tool_request_uses_selected_tools_and_estimated_budget(self):
        provider = LLMProvider(provider="anthropic", model="test")
        provider.client = Mock()
        provider.client.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(type="text", text="done")]
        )
        provider.register_plugin_tool({
            "type": "function",
            "function": {
                "name": "plugin_unscoped",
                "description": "plugin helper",
                "parameters": {"type": "object", "properties": {}},
            },
        })
        provider.register_plugin_tool({
            "type": "function",
            "function": {
                "name": "plugin_conversation",
                "description": "plugin helper",
                "parameters": {"type": "object", "properties": {}},
            },
        }, intents=["conversation"])

        with patch.object(provider, "_build_system", return_value="system"), \
             patch.object(provider, "_get_skill_context", return_value={}), \
             patch.object(provider, "_analyze_request", return_value={
                 "intent": "conversation",
                 "force_tool": False,
                 "preferred_tool": None,
             }):
            provider.chat_with_tools("hello")

        request = provider.client.messages.create.call_args.kwargs
        tool_names = {tool["name"] for tool in request["tools"]}

        self.assertIn("plugin_conversation", tool_names)
        self.assertNotIn("plugin_unscoped", tool_names)
        self.assertEqual(
            request["max_tokens"],
            provider._estimate_max_tokens("hello") + 200,
        )

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

    def test_build_system_keeps_static_prefix_and_injects_profile_once(self):
        provider = LLMProvider()
        manager = Mock()
        manager.get_top_facts_prompt.return_value = "사실 블록"
        manager.get_full_context_prompt.return_value = "요약 블록"
        manager.get_current_time_prompt.return_value = "시간 블록"
        profile = Mock()
        profile.get_prompt_injection.return_value = "프로필 블록"
        knowledge_base = Mock()
        knowledge_base.prompt_for.return_value = "지식 베이스 블록"

        with patch.object(
            provider.rp_generator,
            "build_system_prompt",
            return_value="페르소나",
        ), patch("agent.llm_provider._get_tool_instruction", return_value="도구 지침"), \
             patch("i18n.translator.get_language", return_value="ko"), \
             patch("memory.user_profile_engine.get_user_profile_engine", return_value=profile), \
             patch("memory.memory_manager.get_memory_manager", return_value=manager), \
             patch("memory.knowledge_base.get_knowledge_base", return_value=knowledge_base), \
             patch.object(provider, "_get_skill_context", return_value={"prompt": "스킬 블록"}):
            first = provider._build_system(include_context=True, user_message="첫 요청")
            second = provider._build_system(include_context=True, user_message="둘째 요청")

        static_prefix = "\n\n".join((
            "페르소나",
            "도구 지침",
            "항상 한국어로 응답하세요.",
        ))
        expected_order = (
            "페르소나",
            "도구 지침",
            "항상 한국어로 응답하세요.",
            "프로필 블록",
            "사실 블록",
            "요약 블록",
            "지식 베이스 블록",
            "스킬 블록",
            "시간 블록",
        )
        for prompt in (first, second):
            positions = [prompt.index(item) for item in expected_order]
            self.assertEqual(positions, sorted(positions))
            self.assertTrue(prompt.startswith(static_prefix))
            self.assertEqual(prompt.count("프로필 블록"), 1)
            self.assertEqual(prompt.count("사실 블록"), 1)
        manager.get_full_context_prompt.assert_called_with(
            include_profile=False,
            include_facts=False,
            include_time=False,
        )

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


class _SilentRequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(content_length)
        self.server.request_received.set()
        self.server.release_requests.wait()

class _SilentHTTPServer(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True

    def __init__(self, server_address, request_handler):
        super().__init__(server_address, request_handler)
        self.request_received = threading.Event()
        self.release_requests = threading.Event()


class LLMClientTimeoutTests(unittest.TestCase):
    def setUp(self):
        self.provider = LLMProvider(
            provider="openai",
            provider_configs={
                "openai": {"requires_api_key": True},
                "anthropic": {"requires_api_key": True},
                "ollama": {"requires_api_key": False},
                "custom-local": {
                    "requires_api_key": False,
                    "base_url": "http://127.0.0.1:1234/v1",
                },
            },
        )

    def test_openai_client_receives_configured_timeouts_and_retry_limit(self):
        settings = {"llm_timeout_chat_seconds": "37"}
        with patch(
            "core.config_manager.ConfigManager.get",
            side_effect=lambda key, default=None: settings.get(key, default),
        ), patch("openai.OpenAI") as client_factory:
            self.provider._make_client("openai", "test-key")

        options = client_factory.call_args.kwargs
        self.assertIsInstance(options["timeout"], httpx.Timeout)
        self.assertEqual(options["timeout"].read, 37.0)
        self.assertEqual(options["timeout"].connect, 5.0)
        self.assertEqual(options["max_retries"], 1)

    def test_anthropic_client_uses_planner_timeout_and_retry_limit(self):
        settings = {"llm_timeout_planner_seconds": 87}
        with patch(
            "core.config_manager.ConfigManager.get",
            side_effect=lambda key, default=None: settings.get(key, default),
        ), patch("anthropic.Anthropic") as client_factory:
            self.provider._make_client("anthropic", "test-key", role="planner")

        options = client_factory.call_args.kwargs
        self.assertIsInstance(options["timeout"], httpx.Timeout)
        self.assertEqual(options["timeout"].read, 87.0)
        self.assertEqual(options["timeout"].connect, 5.0)
        self.assertEqual(options["max_retries"], 1)

    def test_same_provider_planner_uses_its_own_timeout_client(self):
        clients = [object(), object()]
        with patch(
            "core.config_manager.ConfigManager.get",
            side_effect=lambda key, default=None: default,
        ), patch("openai.OpenAI", side_effect=clients) as client_factory:
            provider = LLMProvider(
                provider="openai",
                api_key="test-key",
                model="test-model",
                provider_configs={"openai": {"requires_api_key": True}},
            )

        self.assertEqual(client_factory.call_count, 2)
        self.assertEqual(
            [call.kwargs["timeout"].read for call in client_factory.call_args_list],
            [30.0, 90.0],
        )
        self.assertIs(provider._get_role_target("planner")[0], provider.planner_client)

    def test_read_timeout_uses_role_and_local_provider_defaults(self):
        with patch(
            "core.config_manager.ConfigManager.get",
            side_effect=lambda key, default=None: default,
        ):
            self.assertEqual(self.provider._read_timeout_seconds("openai", "default"), 30.0)
            self.assertEqual(self.provider._read_timeout_seconds("openai", "planner"), 90.0)
            self.assertEqual(self.provider._read_timeout_seconds("openai", "execution"), 30.0)
            self.assertEqual(self.provider._read_timeout_seconds("ollama", "planner"), 120.0)
            self.assertEqual(self.provider._read_timeout_seconds("custom-local", "default"), 120.0)

    def test_invalid_timeout_settings_use_the_role_default(self):
        invalid_values = (None, "", "invalid", 0, -1, True, float("nan"), float("inf"))
        for value in invalid_values:
            with self.subTest(value=value):
                with patch(
                    "core.config_manager.ConfigManager.get",
                    side_effect=lambda key, default=None: value,
                ):
                    self.assertEqual(
                        self.provider._read_timeout_seconds("openai", "planner"),
                        90.0,
                    )

    def test_silent_local_server_returns_timeout_fallback_quickly(self):
        server = _SilentHTTPServer(("127.0.0.1", 0), _SilentRequestHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        provider = None
        settings = {
            "ollama_base_url": f"http://127.0.0.1:{server.server_port}/v1",
            "llm_timeout_local_seconds": 0.2,
        }
        try:
            with patch(
                "core.config_manager.ConfigManager.get",
                side_effect=lambda key, default=None: settings.get(key, default),
            ):
                provider = LLMProvider(provider="ollama", api_key="ollama", model="test")
                with patch.object(provider, "_build_system", return_value="system"), patch.object(
                    provider, "_should_cache", return_value=False
                ):
                    started_at = time.monotonic()
                    response = provider.chat("ping", include_context=False, save_history=False)
                    elapsed = time.monotonic() - started_at

            self.assertTrue(server.request_received.wait(timeout=3.0))
            self.assertLess(elapsed, 5.0)
            self.assertEqual(
                response,
                _("(걱정) 서버에 연결할 수 없어요. 네트워크 상태를 확인해주세요."),
            )
        finally:
            server.release_requests.set()
            try:
                server.shutdown()
            finally:
                server_thread.join()
                server.server_close()
                if provider and provider.client:
                    provider.client.close()


if __name__ == "__main__":
    unittest.main()
