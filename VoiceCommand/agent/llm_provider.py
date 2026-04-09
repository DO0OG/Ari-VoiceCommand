"""
다중 LLM 제공자 통합 — Groq, OpenAI, Anthropic, Mistral, Gemini, OpenRouter
모든 OpenAI-호환 제공자는 openai SDK + base_url 방식으로 통일.
Anthropic만 자체 SDK 사용.
"""
import json
import logging
import re
import threading
from typing import List, Any

from agent.assistant_text_utils import (
    analyze_tool_request,
    clean_tool_artifact_text,
    contains_specific_goal_markers,
    is_generic_agent_explanation,
    resolve_agent_task_goal,
)
from agent.response_cache import ResponseCache, build_response_cache_key
from agent.tool_schemas import CORE_TOOL_SCHEMAS, build_available_tools

_PROVIDER_CONFIG = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "label": "Groq",
    },
    "openai": {
        "base_url": None,  # openai SDK 기본값 사용
        "label": "OpenAI",
    },
    "anthropic": {
        "base_url": None,  # anthropic SDK 사용
        "label": "Anthropic",
    },
    "mistral": {
        "base_url": "https://api.mistral.ai/v1",
        "label": "Mistral AI",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "label": "Google Gemini",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "label": "OpenRouter",
    },
    "nvidia_nim": {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "label": "NVIDIA NIM",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "label": "Ollama (로컬)",
        "requires_api_key": False,
    },
}
_EN_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

def _get_tool_instruction() -> str:
    try:
        from i18n.translator import get_language
        lang = get_language()
    except Exception as exc:
        logging.debug("[LLMProvider] 도구 지침 언어 조회 실패, ko 기본값 사용: %s", exc)
        lang = "ko"
    if lang == "en":
        return (
            "[Tool Usage Guidelines]\n"
            "- Always respond in English.\n"
            "- Use appropriate tools for PC control requests.\n"
            "- Do not damage URLs, code, or English names in responses."
        )
    if lang == "ja":
        return (
            "[ツール使用ガイドライン]\n"
            "- 常に日本語で回答してください。\n"
            "- PC操作の要求には適切なツールを使用してください。\n"
            "- URL・コード・英語の名称は変更しないでください。"
        )
    return (
        "[도구 사용 지침]\n"
        "- 사용자의 PC 동작 요청은 적절한 도구를 우선 호출하세요.\n"
        "- 위험하거나 파괴적인 작업은 명확한 의도를 확인하세요.\n"
        "- 답변은 한국어로 하되, URL/코드/영문 명칭은 손상시키지 마세요."
    )

_CORE_TOOL_NAMES = {
    tool["function"]["name"]
    for tool in CORE_TOOL_SCHEMAS
}
_TOOL_NAMES_BY_INTENT = {
    "conversation": {
        "get_weather",
        "get_current_time",
        "web_search",
        "web_fetch",
        "list_scheduled_tasks",
    },
    "memory": {
        "get_weather",
        "get_current_time",
        "web_search",
        "web_fetch",
        "list_scheduled_tasks",
    },
    "web": {
        "web_search",
        "web_fetch",
    },
    "schedule": {
        "set_timer",
        "cancel_timer",
        "schedule_task",
        "list_scheduled_tasks",
        "cancel_scheduled_task",
    },
}

class LLMProvider:
    """단일 인터페이스로 여러 LLM 제공자를 지원하는 클래스."""

    def __init__(self, provider="groq", api_key="", model="",
                 planner_model="", execution_model="",
                 planner_provider="", execution_provider="",
                 planner_api_key="", execution_api_key="",
                 system_prompt="", personality="", scenario="", history_instruction="",
                 router_enabled=False):
        self.provider = provider
        self.api_key = api_key
        self.model = model.strip()
        self.planner_model = planner_model.strip() or self.model
        self.execution_model = execution_model.strip() or self.model
        # 역할별 제공자 (비어있으면 기본 제공자 사용)
        self.planner_provider = planner_provider.strip() or provider
        self.execution_provider = execution_provider.strip() or provider
        self.system_prompt = system_prompt
        self.personality = personality
        self.scenario = scenario
        self.router_enabled = bool(router_enabled)
        self.conversation_history = []
        self._history_lock = threading.RLock()
        self.max_history = 10
        self.client = None
        self.planner_client = None   # None = 기본 client 사용
        self.execution_client = None  # None = 기본 client 사용
        self._plugin_tools: list = []
        self._response_cache = ResponseCache()
        from core.rp_generator import RPGenerator
        self.rp_generator = RPGenerator()
        self.rp_generator.set_config(
            personality=personality,
            scenario=scenario,
            system_prompt=system_prompt,
            history_instruction=history_instruction,
        )

        if api_key or provider == "ollama":
            self._init_client()
        # 별도 제공자가 지정된 경우 추가 클라이언트 초기화
        if planner_provider and planner_provider != provider and planner_api_key:
            self.planner_client = self._make_client(self.planner_provider, planner_api_key)
            if self.planner_client:
                logging.info("플래너 클라이언트 초기화 완료 (%s / %s)", self.planner_provider, self.planner_model)
        if execution_provider and execution_provider != provider and execution_api_key:
            self.execution_client = self._make_client(self.execution_provider, execution_api_key)
            if self.execution_client:
                logging.info("실행 클라이언트 초기화 완료 (%s / %s)", self.execution_provider, self.execution_model)

    # ── 초기화 ─────────────────────────────────────────────────────────────────

    def _make_client(self, provider: str, api_key: str):
        """제공자와 API 키로 클라이언트 객체를 생성한다."""
        cfg = _PROVIDER_CONFIG.get(provider, _PROVIDER_CONFIG["groq"])
        try:
            if provider == "anthropic":
                import anthropic
                return anthropic.Anthropic(api_key=api_key)
            else:
                from openai import OpenAI
                kwargs = {"api_key": api_key}
                if provider == "ollama":
                    kwargs["api_key"] = api_key or "ollama"
                    kwargs["base_url"] = self._get_ollama_url()
                elif cfg["base_url"]:
                    kwargs["base_url"] = cfg["base_url"]
                if provider == "openrouter":
                    kwargs["default_headers"] = {
                        "HTTP-Referer": "https://github.com/Ari-Assistant",
                        "X-Title": "Ari Voice Assistant",
                    }
                return OpenAI(**kwargs)
        except Exception as e:
            logging.error("LLM 클라이언트 초기화 실패 (%s): %s", provider, e)
            return None

    def _get_ollama_url(self) -> str:
        try:
            from core.config_manager import ConfigManager
            return ConfigManager.get("ollama_base_url", "http://localhost:11434/v1")
        except Exception as exc:
            logging.debug("[LLMProvider] ollama_base_url 조회 실패, 기본값 사용: %s", exc)
            return "http://localhost:11434/v1"

    def _init_client(self):
        self.client = self._make_client(self.provider, self.api_key)
        if self.client:
            logging.info("LLM 클라이언트 초기화 완료 (%s / %s)", self.provider, self.model)
            logging.info(
                "  - Planner: %s/%s, Execution: %s/%s",
                self.planner_provider,
                self.planner_model,
                self.execution_provider,
                self.execution_model,
            )

    # ── 도구 정의 ──────────────────────────────────────────────────────────────

    def get_available_tools(self):
        """OpenAI-호환 function calling 스키마"""
        return build_available_tools(self._plugin_tools)

    def get_available_functions(self):
        return [t["function"] for t in self.get_available_tools()]

    def register_plugin_tool(self, schema: dict) -> None:
        """플러그인 도구 스키마를 등록한다."""
        tool_name = str(schema.get("function", {}).get("name", "") or "")
        self._plugin_tools = [
            tool for tool in self._plugin_tools
            if tool.get("function", {}).get("name", "") != tool_name
        ]
        self._plugin_tools.append(schema)

    def unregister_plugin_tool(self, tool_name: str) -> None:
        self._plugin_tools = [
            tool for tool in self._plugin_tools
            if tool.get("function", {}).get("name", "") != tool_name
        ]

    # ── 대화 ───────────────────────────────────────────────────────────────────

    def add_to_history(self, role, content):
        with self._history_lock:
            self.conversation_history.append({"role": role, "content": content})
            if len(self.conversation_history) > self.max_history * 2:
                self.conversation_history = self.conversation_history[-self.max_history * 2:]

    def clear_history(self):
        with self._history_lock:
            self.conversation_history = []

    def _history_snapshot(self) -> list[dict]:
        with self._history_lock:
            return list(self.conversation_history)

    def _estimate_max_tokens(self, message: str) -> int:
        length = len(message or "")
        if length < 20:
            return 200
        if length < 60:
            return 400
        if length < 150:
            return 600
        return 800

    def _should_cache(self, message: str) -> bool:
        text = (message or "").lower()
        skip_keywords = (
            "날씨", "기온", "시간", "몇 시", "temperature", "weather", "forecast",
            "예약", "스케줄", "일정", "저장", "실행", "삭제", "이동", "복사",
            "tool", "명령", "지금", "현재", "today", "now",
        )
        static_signals = (
            "뭐야", "뭐에요", "설명", "알려줘", "란", "의미", "정의",
            "what is", "explain", "tell me about",
        )
        return any(signal in text for signal in static_signals) and not any(keyword in text for keyword in skip_keywords)

    def _offline_response(self, message: str) -> str:
        return "(걱정) 인터넷 연결이 없어서 AI 기능이 제한돼요. 기본 명령은 그대로 쓸 수 있어요."

    def _build_cache_key(
        self,
        user_message: str,
        include_context: bool,
        *,
        provider: str | None = None,
        model: str | None = None,
    ) -> str:
        return build_response_cache_key(
            user_message,
            provider=provider or self.provider,
            model=model or self.model,
            system_prompt=self.system_prompt,
            personality=self.personality,
            scenario=self.scenario,
            history_instruction=self.rp_generator.history_instruction,
            include_context=include_context,
        )

    def _has_any_client(self) -> bool:
        return any((self.client, self.planner_client, self.execution_client))

    def _missing_model_response(self, provider: str, role: str = "default") -> str:
        label = _PROVIDER_CONFIG.get(provider, {}).get("label", provider)
        role_label = {
            "planner": "플래너",
            "execution": "실행",
        }.get(role, "기본")
        return f"{label} {role_label} 모델이 설정되지 않았습니다. 설정에서 선택한 모델을 지정해주세요."

    def _get_role_target(self, role: str) -> tuple[Any, str, str]:
        if role == "planner":
            provider = self.planner_provider
            model = self.planner_model or self.model
            client = self.client if provider == self.provider else self.planner_client
        elif role == "execution":
            provider = self.execution_provider
            model = self.execution_model or self.model
            client = self.client if provider == self.provider else self.execution_client
        else:
            provider = self.provider
            model = self.model
            client = self.client

        if client:
            return client, provider, model

        logging.warning("[LLMRouter] %s 역할 클라이언트가 없어 기본 모델로 폴백합니다.", role)
        return self.client, self.provider, self.model

    def get_role_fallback_targets(self, preferred_role: str = "default") -> list[tuple[Any, str, str]]:
        role_order = {
            "planner": ("planner", "default", "execution"),
            "execution": ("execution", "default", "planner"),
            "default": ("default", "planner", "execution"),
        }.get(preferred_role, ("default", "planner", "execution"))
        targets: list[tuple[Any, str, str]] = []
        seen: set[tuple[str, str]] = set()
        for role in role_order:
            client, provider, model = self._get_role_target(role)
            key = (str(provider or ""), str(model or ""))
            if not client or not model or key in seen:
                continue
            seen.add(key)
            targets.append((client, provider, model))
        return targets

    def _resolve_route(self, user_message: str, model_override: str = "") -> tuple[Any, str, str]:
        provider = self.provider
        model = model_override or self.model
        client = self.client
        if model_override or not self.router_enabled:
            return client, provider, model
        try:
            from agent.llm_router import get_llm_router
            route = get_llm_router().route(user_message, {})
            return self._get_role_target(route.role)
        except Exception as e:
            logging.debug("[LLMRouter] 라우팅 생략: %s", e)
        return client, provider, model

    def chat(self, user_message, include_context=True, model_override="", system_override="", stream_callback=None, save_history=True):
        """단순 대화"""
        if not self._has_any_client():
            return "AI 기능이 비활성화되어 있습니다."

        try:
            client, provider, model = self._resolve_route(user_message, model_override)
            if not client:
                return self._offline_response(user_message)
            if not model:
                logging.warning("[LLMProvider] 모델 미설정: provider=%s", provider)
                return self._missing_model_response(provider)
            cache_key = self._build_cache_key(
                user_message,
                include_context,
                provider=provider,
                model=model,
            )
            cached = self._response_cache.get(cache_key) if self._should_cache(user_message) else None
            if cached:
                if stream_callback:
                    self._emit_stream_text(cached, stream_callback)
                return cached
            if save_history:
                self.add_to_history("user", user_message)
            messages = [{"role": "system", "content": system_override or self._build_system(include_context, user_message=user_message)}]
            messages.extend(self._history_snapshot())

            if provider == "anthropic":
                resp = client.messages.create(
                    model=model, max_tokens=400, system=messages[0]["content"],
                    messages=messages[1:]
                )
                raw_msg = resp.content[0].text
                if stream_callback and raw_msg:
                    self._emit_stream_text(raw_msg, stream_callback)
            else:
                raw_msg = self._stream_or_chat_completion(
                    client,
                    model=model,
                    messages=messages,
                    temperature=0.7,
                    max_tokens=self._estimate_max_tokens(user_message),
                    stream_callback=stream_callback,
                )
            
            from memory.memory_manager import get_memory_manager
            memory_manager = get_memory_manager()
            memory_manager.process_interaction(user_message, raw_msg)
            msg = self._clean_response(memory_manager.clean_response(raw_msg))
            if save_history:
                self.add_to_history("assistant", msg)
            if msg and self._should_cache(user_message):
                self._response_cache.set(cache_key, msg)
            return msg
        except Exception as e:
            logging.error("LLM chat 오류 (%s): %s", model, e)
            return self._offline_response(user_message)

    def chat_with_tools(self, user_message, include_context=True, model_override="", stream_callback=None):
        """도구 포함 대화"""
        if not self._has_any_client():
            return "AI 기능 비활성화 상태입니다.", []

        try:
            client, provider, model = self._resolve_route(user_message, model_override)
            if not client:
                return self._offline_response(user_message), []
            if not model:
                logging.warning("[LLMProvider] 도구 대화 모델 미설정: provider=%s", provider)
                return self._missing_model_response(provider), []
            self.add_to_history("user", user_message)
            skill_ctx = self._get_skill_context(user_message)
            messages = [{"role": "system", "content": self._build_system(include_context, user_message=user_message)}]
            messages.extend(self._history_snapshot())
            
            request_ctx = self._analyze_request(user_message)
            if skill_ctx.get("force_web_search"):
                request_ctx["force_tool"] = True
                request_ctx["preferred_tool"] = "web_search"
                required_tool_names = set(skill_ctx.get("required_tool_names", []))
                required_tool_names.add("web_search")
                skill_ctx = {**skill_ctx, "required_tool_names": sorted(required_tool_names)}
            if skill_ctx.get("search_query_template"):
                request_ctx["search_query_hint"] = self._build_search_query_hint(
                    skill_ctx.get("search_query_template", ""),
                    user_message,
                )
            if skill_ctx.get("force_web_search") and provider == "gemini":
                messages[0]["content"] += "\n\n" + self._get_force_web_search_instruction(
                    request_ctx.get("search_query_hint", "") or skill_ctx.get("search_query_template", ""),
                )
            if skill_ctx.get("preferred_tool") and not request_ctx.get("preferred_tool"):
                request_ctx["preferred_tool"] = skill_ctx["preferred_tool"]
            tools, tool_choice = self._select_tools_for_request(
                request_ctx,
                required_tool_names=set(skill_ctx.get("required_tool_names", [])),
            )

            if provider == "anthropic":
                # Anthropic tool use is more complex, using simple fallback for now
                return self._anthropic_chat(
                    user_message,
                    include_context,
                    use_tools=True,
                    model_override=model,
                    client_override=client,
                    stream_callback=stream_callback,
                )

            response = client.chat.completions.create(
                model=model, messages=messages, tools=tools, tool_choice=tool_choice,
                temperature=0.1 if request_ctx["force_tool"] else 0.3,
                max_tokens=self._estimate_max_tokens(user_message) + 200,
            )
            choice = response.choices[0]
            tool_calls = []
            if choice.message.tool_calls:
                from memory.memory_manager import get_memory_manager
                ctx_mgr = get_memory_manager().context_manager
                for tc in choice.message.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments)
                    except Exception as exc:
                        logging.debug("[LLMProvider] tool arguments 파싱 실패, 빈 값 사용: %s", exc)
                        args = {}
                    args = self._normalize_tool_arguments(tc.function.name, args, user_message)
                    if tc.function.name == "web_search" and not str(args.get("query", "") or "").strip():
                        query_hint = str(request_ctx.get("search_query_hint", "") or "").strip()
                        args["query"] = query_hint or user_message
                    tool_calls.append({"id": tc.id, "name": tc.function.name, "arguments": args})
                    ctx_mgr.record_command(tc.function.name, args)

            raw_msg = choice.message.content or ""
            if not tool_calls and raw_msg:
                tool_calls = self._fallback_tool_calls_from_text(raw_msg, user_message, request_ctx)
                if tool_calls:
                    raw_msg = re.sub(r'```.*?```', '', raw_msg, flags=re.DOTALL)
                    raw_msg = re.sub(r'\{.*\}', '', raw_msg, flags=re.DOTALL)
            
            from memory.memory_manager import get_memory_manager
            memory_manager = get_memory_manager()
            memory_manager.process_interaction(user_message, raw_msg)
            msg = self._clean_response(memory_manager.clean_response(raw_msg))
            if stream_callback and msg and not tool_calls:
                self._emit_stream_text(msg, stream_callback)
            if msg:
                self.add_to_history("assistant", msg)
            return msg, tool_calls
        except Exception as e:
            logging.error("LLM chat_with_tools 오류 (%s): %s", model, e)
            return self._offline_response(user_message), []

    def feed_tool_result(self, original_msg: str, tool_calls: list, results: list, model_override="", stream_callback=None) -> str:
        """도구 결과 피드백"""
        if not self._has_any_client():
            return ""
        try:
            client, provider, model = self._resolve_route(original_msg, model_override)
            if not client:
                return ""
            if not model:
                logging.warning("[LLMProvider] tool_result 모델 미설정: provider=%s", provider)
                return ""
            if provider == "anthropic":
                return self._anthropic_feed_tool_result(
                    original_msg,
                    tool_calls,
                    results,
                    model_override=model,
                    client_override=client,
                    stream_callback=stream_callback,
                )

            assistant_tool_calls = []
            for tc in tool_calls:
                assistant_tool_calls.append({
                    "id": tc.get("id", tc.get("name", "tool_0")),
                    "type": "function",
                    "function": {"name": tc.get("name", ""), "arguments": json.dumps(tc.get("arguments", {}), ensure_ascii=False)},
                })

            tool_result_messages = []
            for tc, result in zip(tool_calls, results):
                tool_result_messages.append({
                    "role": "tool", "tool_call_id": tc.get("id", tc.get("name", "tool_0")), "content": str(result)
                })

            messages = [{
                "role": "system",
                "content": "\n\n".join(
                    part for part in (
                        self._build_system(user_message=original_msg),
                        self._get_source_attribution_instruction(),
                    )
                    if part
                ),
            }]
            messages.extend(self._history_snapshot())
            messages.append({"role": "assistant", "content": None, "tool_calls": assistant_tool_calls})
            messages.extend(tool_result_messages)

            response = client.chat.completions.create(model=model, messages=messages, temperature=0.7, max_tokens=self._estimate_max_tokens(original_msg))
            msg = self._clean_response(response.choices[0].message.content or "")
            if stream_callback and msg:
                self._emit_stream_text(msg, stream_callback)
            if msg:
                self.add_to_history("assistant", msg)
            return msg
        except Exception as e:
            logging.error("feed_tool_result 오류 (%s): %s", model, e)
            return ""

    def _anthropic_chat(self, user_message, include_context, use_tools, model_override="", client_override=None, stream_callback=None):
        model = model_override or self.model
        client = client_override or self.client
        try:
            system = self._build_system(include_context, user_message=user_message)
            messages = self._history_snapshot()
            kwargs = {"model": model, "max_tokens": 1000, "system": system, "messages": messages}
            if use_tools:
                kwargs["tools"] = [{"name": t["function"]["name"], "description": t["function"]["description"], "input_schema": t["function"]["parameters"]} for t in self.get_available_tools()]
            
            resp = client.messages.create(**kwargs)
            tool_calls, text_parts = [], []
            for b in resp.content:
                if b.type == "tool_use":
                    tool_calls.append({"id": b.id, "name": b.name, "arguments": b.input})
                elif b.type == "text":
                    text_parts.append(b.text)
            
            raw_msg = " ".join(text_parts)
            msg = self._clean_response(raw_msg)
            if stream_callback and msg and not tool_calls:
                self._emit_stream_text(msg, stream_callback)
            if msg:
                self.add_to_history("assistant", msg)
            return msg, tool_calls
        except Exception as e:
            logging.error("Anthropic API 오류: %s", e)
            return f"오류 발생: {e}", []

    def _anthropic_feed_tool_result(self, original_msg, tool_calls, results, model_override="", client_override=None, stream_callback=None):
        model = model_override or self.model
        client = client_override or self.client
        try:
            results_content = [{"type": "tool_result", "tool_use_id": tc["id"], "content": str(r)} for tc, r in zip(tool_calls, results)]
            messages = self._history_snapshot()
            messages.append({"role": "user", "content": results_content})
            resp = client.messages.create(
                model=model,
                max_tokens=500,
                system=self._build_system(user_message=original_msg),
                messages=messages,
            )
            msg = self._clean_response(" ".join([b.text for b in resp.content if b.type == "text"]))
            if stream_callback and msg:
                self._emit_stream_text(msg, stream_callback)
            if msg:
                self.add_to_history("assistant", msg)
            return msg
        except Exception as e:
            logging.error("Anthropic feed 오류: %s", e)
            return ""

    def _stream_or_chat_completion(
        self,
        client,
        *,
        model: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        stream_callback=None,
    ) -> str:
        if not stream_callback:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content or ""
        try:
            stream = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            parts: List[str] = []
            for chunk in stream:
                try:
                    delta = chunk.choices[0].delta.content or ""
                except Exception as exc:
                    logging.debug("[LLMProvider] 스트리밍 delta 추출 실패: %s", exc)
                    delta = ""
                if not delta:
                    continue
                parts.append(delta)
                stream_callback(delta)
            text = "".join(parts)
            if text:
                return text
        except Exception as exc:
            logging.debug("[LLMProvider] 스트리밍 폴백: %s", exc)
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        text = resp.choices[0].message.content or ""
        self._emit_stream_text(text, stream_callback)
        return text

    def _emit_stream_text(self, text: str, stream_callback, chunk_size: int = 24) -> None:
        if not stream_callback or not text:
            return
        for start in range(0, len(text), chunk_size):
            chunk = text[start:start + chunk_size]
            if chunk:
                stream_callback(chunk)

    def _analyze_request(self, user_message: str) -> dict:
        ctx = analyze_tool_request(user_message)
        ctx.setdefault("intent", "conversation")
        return ctx

    def _select_tools_for_request(self, ctx: dict, required_tool_names: set[str] | None = None):
        required_tool_names = set(required_tool_names or set())
        tools = self.get_available_tools()
        if ctx.get("preferred_tool"):
            filtered = [t for t in tools if t["function"]["name"] == ctx["preferred_tool"]]
            if required_tool_names:
                filtered.extend(
                    tool
                    for tool in tools
                    if tool["function"]["name"] in required_tool_names
                    and tool["function"]["name"] != ctx["preferred_tool"]
                )
            if filtered:
                return filtered, {"type": "function", "function": {"name": ctx["preferred_tool"]}}

        allowed_names = _TOOL_NAMES_BY_INTENT.get(ctx.get("intent", "conversation"))
        if allowed_names:
            allowed_names = set(allowed_names) | required_tool_names
            filtered = []
            for tool in tools:
                name = tool["function"]["name"]
                if name not in _CORE_TOOL_NAMES or name in allowed_names:
                    filtered.append(tool)
            if filtered:
                tools = filtered
        elif required_tool_names:
            filtered = []
            for tool in tools:
                name = tool["function"]["name"]
                if name not in _CORE_TOOL_NAMES or name in required_tool_names:
                    filtered.append(tool)
            if filtered:
                tools = filtered
        return tools, "required" if ctx.get("force_tool") else "auto"

    def _normalize_tool_arguments(self, name, args, user_msg):
        n = dict(args or {})
        if name == "run_agent_task":
            detailed_request = (n.get("explanation") or user_msg or "").strip()
            current_goal = (n.get("goal") or "").strip()
            resolved_goal = resolve_agent_task_goal(current_goal, detailed_request)
            if resolved_goal:
                n["goal"] = resolved_goal
        return n

    def _is_generic_agent_explanation(self, text: str) -> bool:
        return is_generic_agent_explanation(text)

    def _contains_specific_goal_markers(self, text: str) -> bool:
        return contains_specific_goal_markers(text)

    def _fallback_tool_calls_from_text(self, raw, msg, ctx):
        if ctx.get("preferred_tool") == "web_search":
            query = str(ctx.get("search_query_hint", "") or "").strip() or msg
            return [{"id": "fb_1", "name": "web_search", "arguments": {"query": query, "max_results": 5}}]
        if "execute_python_code" in raw or ctx.get("force_tool"):
            return [{"id": "fb_1", "name": "run_agent_task", "arguments": {"goal": msg, "explanation": "진행할게요."}}]
        return []

    def _get_skill_context(self, user_message: str) -> dict:
        if not str(user_message or "").strip():
            return {
                "skills": [],
                "prompt": "",
                "required_tool_names": [],
                "preferred_tool": "",
                "force_web_search": False,
                "escalate_to_agent": False,
                "search_query_template": "",
            }
        try:
            from agent.skill_manager import get_skill_manager

            return get_skill_manager().build_match_context(user_message)
        except Exception as exc:
            logging.debug("[LLMProvider] 스킬 컨텍스트 주입 생략: %s", exc)
            return {
                "skills": [],
                "prompt": "",
                "required_tool_names": [],
                "preferred_tool": "",
                "force_web_search": False,
                "escalate_to_agent": False,
                "search_query_template": "",
            }

    def _get_source_attribution_instruction(self) -> str:
        from i18n.translator import _

        return _(
            "[실시간 데이터 응답 지침]\n"
            "- 검색 결과에 없는 정보는 절대 지어내지 마세요.\n"
            "- 정보가 없으면 '검색 결과에서 확인하지 못했습니다'라고 솔직하게 말하세요.\n"
            "- 데이터 출처(웹 검색, 공식 API 등)를 짧게 언급하세요."
        )

    def _get_force_web_search_instruction(self, query_hint: str) -> str:
        from i18n.translator import _

        guidance = _(
            "이 요청은 최신 실시간 데이터가 필요합니다. 반드시 web_search 도구를 먼저 호출하세요."
        )
        query_hint = str(query_hint or "").strip()
        if not query_hint:
            return guidance
        return guidance + "\n" + _("권장 검색어: {query}").format(query=query_hint)

    def _build_search_query_hint(self, template: str, user_message: str) -> str:
        template = str(template or "").strip()
        if not template:
            return ""
        import datetime

        today = datetime.date.today()
        date_hint = self._extract_date_hint(user_message, today) or today.isoformat()
        return template.replace("{date}", date_hint)

    def _extract_date_hint(self, user_message: str, today) -> str:
        text = str(user_message or "").strip()
        iso_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
        if iso_match:
            return iso_match.group(1)
        month_day_match = re.search(r"(\d{1,2})\s*[월月]\s*(\d{1,2})\s*[일日]", text)
        if month_day_match:
            month = int(month_day_match.group(1))
            day = int(month_day_match.group(2))
            try:
                return today.replace(month=month, day=day).isoformat()
            except ValueError:
                return ""
        en_match = re.search(
            r"\b(january|february|march|april|may|june|july|august|september|october|november|december|"
            r"jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\s+(\d{1,2})\b",
            text,
            re.IGNORECASE,
        )
        if en_match:
            month = _EN_MONTHS[en_match.group(1).lower()]
            day = int(en_match.group(2))
            try:
                return today.replace(month=month, day=day).isoformat()
            except ValueError:
                return ""
        return ""

    def _build_system(self, include_context=False, user_message=""):
        try:
            from i18n.translator import get_language
            lang = get_language()
        except Exception as exc:
            logging.debug("[LLMProvider] 언어 설정 조회 실패, ko 기본값 사용: %s", exc)
            lang = "ko"
        _BASE_PROMPT = {
            "ko": "당신은 한국어 AI 어시스턴트 아리입니다.",
            "en": "You are Ari, an AI assistant.",
            "ja": "あなたはAIアシスタントのAriです。",
        }
        _LANG_INSTRUCTION = {
            "ko": "항상 한국어로 응답하세요.",
            "en": "Always respond in English.",
            "ja": "常に日本語で応答してください。",
        }
        parts: List[str] = []
        base_prompt = self.system_prompt or _BASE_PROMPT.get(lang, _BASE_PROMPT["ko"])
        if include_context:
            try:
                from memory.user_profile_engine import get_user_profile_engine
                profile_prompt = get_user_profile_engine().get_prompt_injection()
                if profile_prompt:
                    parts.append(profile_prompt)
            except Exception as e:
                logging.debug("[LLM] 사용자 프로파일 주입 실패: %s", e)
            try:
                from memory.memory_manager import get_memory_manager
                memory_manager = get_memory_manager()
                facts_prompt = memory_manager.get_top_facts_prompt(n=5)
                if facts_prompt:
                    parts.append(facts_prompt)
            except Exception as e:
                logging.debug("[LLM] 사실 주입 실패: %s", e)
        parts.append(self.rp_generator.build_system_prompt(base_prompt))
        if include_context:
            try:
                from memory.memory_manager import get_memory_manager
                context_prompt = get_memory_manager().get_full_context_prompt()
                if context_prompt:
                    parts.append(f"[대화 컨텍스트]\n{context_prompt}")
            except Exception as e:
                logging.debug("[LLM] 메모리 컨텍스트 주입 실패: %s", e)
        parts.append(_get_tool_instruction())
        skill_ctx = self._get_skill_context(user_message)
        if skill_ctx.get("prompt"):
            parts.append(skill_ctx["prompt"])
        parts.append(_LANG_INSTRUCTION.get(lang, _LANG_INSTRUCTION["ko"]))
        return "\n\n".join(part for part in parts if part)

    def _clean_response(self, text):
        return clean_tool_artifact_text(text, remove_memory_tags=True)

    def _filter_korean(self, text):
        return self._clean_response(text)


# ── 싱글톤 팩토리 ──────────────────────────────────────────────────────────────

_instance: LLMProvider | None = None
_instance_lock = threading.Lock()

_KEY_MAP = {
    "groq": "groq_api_key", "openai": "openai_api_key", "anthropic": "anthropic_api_key",
    "mistral": "mistral_api_key", "gemini": "gemini_api_key",
    "openrouter": "openrouter_api_key", "nvidia_nim": "nvidia_nim_api_key",
    "ollama": "",
}

def get_llm_provider() -> LLMProvider:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                try:
                    from core.config_manager import ConfigManager
                    s = ConfigManager.load_settings()
                except Exception as exc:
                    logging.debug("[LLMProvider] 설정 로드 실패, 기본 LLM 설정 사용: %s", exc)
                    s = {}
                provider = s.get("llm_provider", "groq")
                api_key = "ollama" if provider == "ollama" else s.get(_KEY_MAP.get(provider, ""), "")
                planner_provider = s.get("llm_planner_provider", "") or provider
                execution_provider = s.get("llm_execution_provider", "") or provider
                planner_api_key = (
                    "ollama" if planner_provider == "ollama"
                    else s.get(_KEY_MAP.get(planner_provider, ""), "")
                ) if planner_provider != provider else ""
                execution_api_key = (
                    "ollama" if execution_provider == "ollama"
                    else s.get(_KEY_MAP.get(execution_provider, ""), "")
                ) if execution_provider != provider else ""
                _instance = LLMProvider(
                    provider=provider, api_key=api_key,
                    model=s.get("llm_model", ""),
                    planner_model=s.get("llm_planner_model", ""),
                    execution_model=s.get("llm_execution_model", ""),
                    planner_provider=planner_provider if planner_provider != provider else "",
                    execution_provider=execution_provider if execution_provider != provider else "",
                    planner_api_key=planner_api_key,
                    execution_api_key=execution_api_key,
                    system_prompt=s.get("system_prompt", ""),
                    personality=s.get("personality", ""),
                    scenario=s.get("scenario", ""),
                    history_instruction=s.get("history_instruction", ""),
                    router_enabled=s.get("llm_router_enabled", False),
                )
    return _instance

def reset_llm_provider():
    global _instance
    _instance = None
