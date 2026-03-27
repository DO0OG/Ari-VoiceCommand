"""
다중 LLM 제공자 통합 — Groq, OpenAI, Anthropic, Mistral, Gemini, OpenRouter
모든 OpenAI-호환 제공자는 openai SDK + base_url 방식으로 통일.
Anthropic만 자체 SDK 사용.
"""
import json
import logging
import os
import re
from datetime import datetime
from typing import Optional, List, Dict, Tuple, Any

_PROVIDER_CONFIG = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
        "label": "Groq",
    },
    "openai": {
        "base_url": None,  # openai SDK 기본값 사용
        "default_model": "gpt-4o-mini",
        "label": "OpenAI",
    },
    "anthropic": {
        "base_url": None,  # anthropic SDK 사용
        "default_model": "claude-haiku-4-5-20251001",
        "label": "Anthropic",
    },
    "mistral": {
        "base_url": "https://api.mistral.ai/v1",
        "default_model": "mistral-small-latest",
        "label": "Mistral AI",
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "default_model": "gemini-2.0-flash",
        "label": "Google Gemini",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "meta-llama/llama-3.3-70b-instruct:free",
        "label": "OpenRouter",
    },
    "nvidia_nim": {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "default_model": "meta/llama-3.3-70b-instruct",
        "label": "NVIDIA NIM",
    },
}


class LLMProvider:
    """단일 인터페이스로 여러 LLM 제공자를 지원하는 클래스."""

    def __init__(self, provider="groq", api_key="", model="",
                 planner_model="", execution_model="",
                 planner_provider="", execution_provider="",
                 planner_api_key="", execution_api_key="",
                 system_prompt="", personality="", scenario=""):
        cfg = _PROVIDER_CONFIG.get(provider, _PROVIDER_CONFIG["groq"])
        self.provider = provider
        self.api_key = api_key
        self.model = model.strip() or cfg["default_model"]
        self.planner_model = planner_model.strip() or self.model
        self.execution_model = execution_model.strip() or self.model
        # 역할별 제공자 (비어있으면 기본 제공자 사용)
        self.planner_provider = planner_provider.strip() or provider
        self.execution_provider = execution_provider.strip() or provider
        self.system_prompt = system_prompt
        self.personality = personality
        self.scenario = scenario
        self.conversation_history = []
        self.max_history = 10
        self.client = None
        self.planner_client = None   # None = 기본 client 사용
        self.execution_client = None  # None = 기본 client 사용
        self._plugin_tools: list = []

        if api_key:
            self._init_client()
        # 별도 제공자가 지정된 경우 추가 클라이언트 초기화
        if planner_provider and planner_provider != provider and planner_api_key:
            self.planner_client = self._make_client(self.planner_provider, planner_api_key)
            if self.planner_client:
                logging.info(f"플래너 클라이언트 초기화 완료 ({self.planner_provider} / {self.planner_model})")
        if execution_provider and execution_provider != provider and execution_api_key:
            self.execution_client = self._make_client(self.execution_provider, execution_api_key)
            if self.execution_client:
                logging.info(f"실행 클라이언트 초기화 완료 ({self.execution_provider} / {self.execution_model})")

    # ── 초기화 ─────────────────────────────────────────────────────────────────

    def _make_client(self, provider: str, api_key: str):
        """제공자와 API 키로 클라이언트 객체를 생성합니다."""
        cfg = _PROVIDER_CONFIG.get(provider, _PROVIDER_CONFIG["groq"])
        try:
            if provider == "anthropic":
                import anthropic
                return anthropic.Anthropic(api_key=api_key)
            else:
                from openai import OpenAI
                kwargs = {"api_key": api_key}
                if cfg["base_url"]:
                    kwargs["base_url"] = cfg["base_url"]
                if provider == "openrouter":
                    kwargs["default_headers"] = {
                        "HTTP-Referer": "https://github.com/Ari-Assistant",
                        "X-Title": "Ari Voice Assistant",
                    }
                return OpenAI(**kwargs)
        except Exception as e:
            logging.error(f"LLM 클라이언트 초기화 실패 ({provider}): {e}")
            return None

    def _init_client(self):
        self.client = self._make_client(self.provider, self.api_key)
        if self.client:
            logging.info(f"LLM 클라이언트 초기화 완료 ({self.provider} / {self.model})")
            logging.info(f"  - Planner: {self.planner_provider}/{self.planner_model}, Execution: {self.execution_provider}/{self.execution_model}")

    # ── 도구 정의 ──────────────────────────────────────────────────────────────

    def get_available_tools(self):
        """OpenAI-호환 function calling 스키마"""
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_screen_status",
                    "description": "현재 사용자의 화면 상태(작업표시줄 위치, 전체화면 모드 여부 등)를 확인합니다.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "play_youtube",
                    "description": "유튜브에서 음악이나 영상을 검색하여 재생합니다.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "검색할 제목"}
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "set_timer",
                    "description": "알림용 카운트다운 타이머를 설정합니다. 타이머 종료 시 알림만 울리며 추가 동작은 없습니다. 컴퓨터 종료·파일 저장 등 지연 실행은 schedule_task를 사용하세요.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "minutes": {"type": "integer", "description": "분"},
                            "seconds": {"type": "integer", "description": "초"},
                        },
                        "required": ["minutes"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "cancel_timer",
                    "description": "진행 중인 타이머를 취소합니다.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "현재 날씨 정보를 조회합니다.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "adjust_volume",
                    "description": "시스템 볼륨을 조절합니다.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "direction": {
                                "type": "string",
                                "enum": ["up", "down", "mute"],
                                "description": "up/down/mute",
                            }
                        },
                        "required": ["direction"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_current_time",
                    "description": "현재 시간을 알려줍니다.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "execute_python_code",
                    "description": "파이썬 코드로 자율 처리합니다.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "code": {"type": "string", "description": "코드"},
                            "explanation": {"type": "string", "description": "설명"},
                        },
                        "required": ["code"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "execute_shell_command",
                    "description": "CMD 명령어로 자율 처리합니다.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string", "description": "명령"},
                            "explanation": {"type": "string", "description": "설명"},
                        },
                        "required": ["command"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "run_agent_task",
                    "description": "복합 목표를 자율 에이전트 루프로 처리합니다.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "goal": {"type": "string", "description": "목표"},
                            "explanation": {"type": "string", "description": "설명"},
                        },
                        "required": ["goal"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "인터넷 정보를 검색합니다.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "검색어"},
                            "max_results": {"type": "integer", "description": "결과 수"},
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "web_fetch",
                    "description": "웹 페이지 내용을 가져옵니다.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string", "description": "URL"},
                        },
                        "required": ["url"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "schedule_task",
                    "description": "특정 시간에 작업을 예약 실행합니다. 'N분/시간 뒤', 'N시에' 등 시간 표현과 함께 컴퓨터 종료·파일 저장 등 지연 실행 요청에 사용합니다.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "goal": {"type": "string", "description": "작업 내용"},
                            "when": {"type": "string", "description": "시간 표현"},
                            "explanation": {"type": "string", "description": "설명"},
                        },
                        "required": ["goal", "when"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "shutdown_computer",
                    "description": "컴퓨터를 즉시 종료합니다. 시간 표현(예: '15분 뒤', '오후 11시')이 포함된 경우에는 schedule_task를 사용하세요.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "confirmed": {
                                "type": "boolean",
                                "description": "종료 확인 여부 (항상 true)",
                            }
                        },
                        "required": ["confirmed"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_scheduled_tasks",
                    "description": "현재 예약된 작업 목록을 조회합니다. '예약된 작업 뭐 있어?', '스케줄 확인해줘' 등의 요청에 사용합니다.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "cancel_scheduled_task",
                    "description": "예약된 작업을 ID로 취소합니다.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "task_id": {
                                "type": "string",
                                "description": "취소할 작업 ID (list_scheduled_tasks로 확인)",
                            }
                        },
                        "required": ["task_id"],
                    },
                },
            },
        ]
        tools.extend(self._plugin_tools)
        return tools

    def get_available_functions(self):
        return [t["function"] for t in self.get_available_tools()]

    def register_plugin_tool(self, schema: dict) -> None:
        """플러그인 도구 스키마를 등록한다."""
        self._plugin_tools.append(schema)

    # ── 대화 ───────────────────────────────────────────────────────────────────

    def add_to_history(self, role, content):
        self.conversation_history.append({"role": role, "content": content})
        if len(self.conversation_history) > self.max_history * 2:
            self.conversation_history = self.conversation_history[-self.max_history * 2:]

    def chat(self, user_message, include_context=False, model_override="", system_override=""):
        """단순 대화"""
        if not self.client:
            return "AI 기능이 비활성화되어 있습니다."

        model = model_override or self.model
        try:
            self.add_to_history("user", user_message)
            messages = [{"role": "system", "content": system_override or self._build_system(include_context)}]
            messages.extend(self.conversation_history)

            if self.provider == "anthropic":
                resp = self.client.messages.create(
                    model=model, max_tokens=400, system=messages[0]["content"],
                    messages=messages[1:]
                )
                raw_msg = resp.content[0].text
            else:
                resp = self.client.chat.completions.create(
                    model=model, messages=messages, temperature=0.7, max_tokens=400
                )
                raw_msg = resp.choices[0].message.content or ""
            
            from memory.memory_manager import get_memory_manager
            memory_manager = get_memory_manager()
            memory_manager.process_interaction(user_message, raw_msg)
            msg = memory_manager.clean_response(raw_msg)
            msg = self._filter_korean(msg)
            self.add_to_history("assistant", msg)
            return msg
        except Exception as e:
            logging.error(f"LLM chat 오류 ({model}): {e}")
            return f"오류 발생: {e}"

    def chat_with_tools(self, user_message, include_context=False, model_override=""):
        """도구 포함 대화"""
        if not self.client:
            return "AI 기능 비활성화 상태입니다.", []

        model = model_override or self.model
        try:
            self.add_to_history("user", user_message)
            messages = [{"role": "system", "content": self._build_system(include_context)}]
            messages.extend(self.conversation_history)
            
            request_ctx = self._analyze_request(user_message)
            tools, tool_choice = self._select_tools_for_request(request_ctx)

            if self.provider == "anthropic":
                # Anthropic tool use is more complex, using simple fallback for now
                return self._anthropic_chat(user_message, include_context, use_tools=True, model_override=model)

            response = self.client.chat.completions.create(
                model=model, messages=messages, tools=tools, tool_choice=tool_choice,
                temperature=0.1 if request_ctx["force_tool"] else 0.3, max_tokens=1000
            )
            choice = response.choices[0]
            tool_calls = []
            if choice.message.tool_calls:
                from memory.memory_manager import get_memory_manager
                ctx_mgr = get_memory_manager().context_manager
                for tc in choice.message.tool_calls:
                    try: args = json.loads(tc.function.arguments)
                    except Exception: args = {}
                    args = self._normalize_tool_arguments(tc.function.name, args, user_message)
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
            msg = memory_manager.clean_response(raw_msg)
            msg = self._filter_korean(msg)
            if msg: self.add_to_history("assistant", msg)
            return msg, tool_calls
        except Exception as e:
            logging.error(f"LLM chat_with_tools 오류 ({model}): {e}")
            return f"오류 발생: {e}", []

    def feed_tool_result(self, original_msg: str, tool_calls: list, results: list, model_override="") -> str:
        """도구 결과 피드백"""
        if not self.client: return ""
        model = model_override or self.model
        try:
            if self.provider == "anthropic":
                return self._anthropic_feed_tool_result(original_msg, tool_calls, results, model_override=model)

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

            messages = [{"role": "system", "content": self._build_system()}]
            messages.extend(self.conversation_history)
            messages.append({"role": "assistant", "content": None, "tool_calls": assistant_tool_calls})
            messages.extend(tool_result_messages)

            response = self.client.chat.completions.create(model=model, messages=messages, temperature=0.7, max_tokens=300)
            msg = self._filter_korean(response.choices[0].message.content or "")
            if msg: self.add_to_history("assistant", msg)
            return msg
        except Exception as e:
            logging.error(f"feed_tool_result 오류 ({model}): {e}")
            return ""

    def _anthropic_chat(self, user_message, include_context, use_tools, model_override=""):
        model = model_override or self.model
        try:
            system = self._build_system(include_context)
            messages = list(self.conversation_history)
            kwargs = {"model": model, "max_tokens": 1000, "system": system, "messages": messages}
            if use_tools:
                kwargs["tools"] = [{"name": t["function"]["name"], "description": t["function"]["description"], "input_schema": t["function"]["parameters"]} for t in self.get_available_tools()]
            
            resp = self.client.messages.create(**kwargs)
            tool_calls, text_parts = [], []
            for b in resp.content:
                if b.type == "tool_use": tool_calls.append({"id": b.id, "name": b.name, "arguments": b.input})
                elif b.type == "text": text_parts.append(b.text)
            
            raw_msg = " ".join(text_parts)
            msg = self._filter_korean(raw_msg)
            if msg: self.add_to_history("assistant", msg)
            return msg, tool_calls
        except Exception as e:
            logging.error(f"Anthropic API 오류: {e}")
            return f"오류 발생: {e}", []

    def _anthropic_feed_tool_result(self, original_msg, tool_calls, results, model_override=""):
        model = model_override or self.model
        try:
            results_content = [{"type": "tool_result", "tool_use_id": tc["id"], "content": str(r)} for tc, r in zip(tool_calls, results)]
            messages = list(self.conversation_history)
            messages.append({"role": "user", "content": results_content})
            resp = self.client.messages.create(model=model, max_tokens=500, system=self._build_system(), messages=messages)
            msg = self._filter_korean(" ".join([b.text for b in resp.content if b.type == "text"]))
            if msg: self.add_to_history("assistant", msg)
            return msg
        except Exception as e:
            logging.error(f"Anthropic feed 오류: {e}")
            return ""

    def _analyze_request(self, user_message: str) -> dict:
        text = (user_message or "").strip()
        force_tool = any(token in text for token in (
            "화면 상태", "화면 확인",
            "예약해줘", "스케줄 잡아",
            "검색해줘", "찾아줘",
            "수집해줘", "보고서 만들",
            "저장해줘", "만들어줘",
        ))
        multi_step = any(token in text for token in ("그리고", "해서", "한 뒤", "다음"))
        preferred = "run_agent_task" if multi_step else None
        return {"force_tool": force_tool, "has_action": "해줘" in text or "실행" in text, "preferred_tool": preferred}

    def _select_tools_for_request(self, ctx: dict):
        tools = self.get_available_tools()
        if ctx.get("preferred_tool"):
            filtered = [t for t in tools if t["function"]["name"] == ctx["preferred_tool"]]
            if filtered: return filtered, {"type": "function", "function": {"name": ctx["preferred_tool"]}}
        return tools, "required" if ctx.get("force_tool") else "auto"

    def _normalize_tool_arguments(self, name, args, user_msg):
        n = dict(args or {})
        if name == "run_agent_task": n.setdefault("goal", user_msg)
        return n

    def _fallback_tool_calls_from_text(self, raw, msg, ctx):
        if "execute_python_code" in raw or ctx.get("force_tool"):
            return [{"id": "fb_1", "name": "run_agent_task", "arguments": {"goal": msg, "explanation": "진행할게요."}}]
        return []

    def _build_system(self, include_context=False):
        sys = self.system_prompt or "당신은 한국어 AI 어시스턴트 아리입니다."
        if self.personality: sys += f"\n성격: {self.personality}"
        if include_context:
            try:
                from memory.memory_manager import get_memory_manager
                sys += f"\n\n컨텍스트:\n{get_memory_manager().get_full_context_prompt()}"
            except Exception as e:
                logging.debug(f"[LLM] 메모리 컨텍스트 주입 실패: {e}")
        sys += "\n한국어 응답 필수. 감정 태그 (기쁨), (진지) 등 필수 사용."
        return sys

    def _filter_korean(self, text):
        if not text: return ""
        text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
        text = re.sub(r'\[[a-zA-Z_]+:[^\]]*\]', '', text)
        text = re.sub(r'[^가-힣0-9\s.,!?~\-()%]', '', text)
        return re.sub(r'\s+', ' ', text).strip()


# ── 싱글톤 팩토리 ──────────────────────────────────────────────────────────────

_instance: LLMProvider | None = None

_KEY_MAP = {
    "groq": "groq_api_key", "openai": "openai_api_key", "anthropic": "anthropic_api_key",
    "mistral": "mistral_api_key", "gemini": "gemini_api_key",
    "openrouter": "openrouter_api_key", "nvidia_nim": "nvidia_nim_api_key",
}

def get_llm_provider() -> LLMProvider:
    global _instance
    if _instance is None:
        try:
            from core.config_manager import ConfigManager
            s = ConfigManager.load_settings()
        except Exception: s = {}
        provider = s.get("llm_provider", "groq")
        api_key = s.get(_KEY_MAP.get(provider, ""), "")
        planner_provider = s.get("llm_planner_provider", "") or provider
        execution_provider = s.get("llm_execution_provider", "") or provider
        planner_api_key = s.get(_KEY_MAP.get(planner_provider, ""), "") if planner_provider != provider else ""
        execution_api_key = s.get(_KEY_MAP.get(execution_provider, ""), "") if execution_provider != provider else ""
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
            scenario=s.get("scenario", "")
        )
    return _instance

def reset_llm_provider():
    global _instance
    _instance = None
