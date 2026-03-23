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
}


class LLMProvider:
    """단일 인터페이스로 여러 LLM 제공자를 지원하는 클래스.

    GroqAssistant와 동일한 public 메서드를 제공하므로 drop-in 교체 가능.
    """

    def __init__(self, provider="groq", api_key="", model="",
                 system_prompt="", personality="", scenario=""):
        cfg = _PROVIDER_CONFIG.get(provider, _PROVIDER_CONFIG["groq"])
        self.provider = provider
        self.api_key = api_key
        self.model = model.strip() or cfg["default_model"]
        self.system_prompt = system_prompt
        self.personality = personality
        self.scenario = scenario
        self.conversation_history = []
        self.max_history = 10
        self.client = None

        if api_key:
            self._init_client()

    # ── 초기화 ─────────────────────────────────────────────────────────────────

    def _init_client(self):
        cfg = _PROVIDER_CONFIG.get(self.provider, _PROVIDER_CONFIG["groq"])
        try:
            if self.provider == "anthropic":
                import anthropic
                self.client = anthropic.Anthropic(api_key=self.api_key)
            else:
                from openai import OpenAI
                kwargs = {"api_key": self.api_key}
                if cfg["base_url"]:
                    kwargs["base_url"] = cfg["base_url"]
                if self.provider == "openrouter":
                    kwargs["default_headers"] = {
                        "HTTP-Referer": "https://github.com/Ari-Assistant",
                        "X-Title": "Ari Voice Assistant",
                    }
                self.client = OpenAI(**kwargs)
            logging.info(f"LLM 클라이언트 초기화 완료 ({self.provider} / {self.model})")
        except Exception as e:
            logging.error(f"LLM 클라이언트 초기화 실패 ({self.provider}): {e}")

    # ── 도구 정의 ──────────────────────────────────────────────────────────────

    def get_available_tools(self):
        """OpenAI-호환 function calling 스키마"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "get_screen_status",
                    "description": "현재 사용자의 화면 상태(작업표시줄 위치, 전체화면 모드 여부 등)를 확인합니다. 사용자가 '내 화면 어때?' 혹은 '지금 뭐하고 있어?' 라고 물어볼 때 사용하세요.",
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
                            "query": {"type": "string", "description": "검색할 음악이나 영상 제목"}
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "set_timer",
                    "description": "타이머를 설정합니다.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "minutes": {"type": "integer", "description": "타이머 시간 (분)"},
                            "seconds": {"type": "integer", "description": "추가 초 단위, 없으면 0"},
                        },
                        "required": ["minutes"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "cancel_timer",
                    "description": "현재 진행 중인 타이머를 취소합니다.",
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
                                "description": "up=볼륨 올리기, down=볼륨 내리기, mute=음소거",
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
                    "description": "기존 도구로 해결할 수 없는 요청을 파이썬 코드로 자율적으로 처리합니다.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "code": {"type": "string", "description": "실행할 파이썬 코드"},
                            "explanation": {"type": "string", "description": "사용자에게 말할 한국어 설명"},
                        },
                        "required": ["code"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "execute_shell_command",
                    "description": "기존 도구로 해결할 수 없는 요청을 CMD 명령어로 자율적으로 처리합니다.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "command": {"type": "string", "description": "실행할 CMD 명령어"},
                            "explanation": {"type": "string", "description": "사용자에게 말할 한국어 설명"},
                        },
                        "required": ["command"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "run_agent_task",
                    "description": (
                        "2단계 이상이 필요한 복합 목표를 자율 에이전트가 계획-실행-검증 루프로 처리합니다. "
                        "예: '폴더 만들고 거기에 저장해줘', '뉴스 검색해서 파일로 정리해줘', "
                        "'시스템 정보 수집해서 보고해줘' 등. "
                        "이런 복합 작업에는 execute_python_code/execute_shell_command를 "
                        "여러 번 나열하지 말고 이 도구 하나만 사용하세요."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "goal": {"type": "string", "description": "달성해야 할 목표 (한국어)"},
                            "explanation": {"type": "string", "description": "사용자에게 말할 한국어 설명"},
                        },
                        "required": ["goal"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "인터넷에서 정보를 검색합니다. 최신 뉴스, 실시간 정보, 모르는 지식이 필요할 때 사용하세요.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "검색할 내용. 반드시 사용자가 말한 언어(한국어)로 작성하세요. 영어나 일본어로 번역하지 마세요."},
                            "max_results": {"type": "integer", "description": "결과 수 (기본 5)"},
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "web_fetch",
                    "description": "특정 URL의 웹 페이지 내용을 가져옵니다.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string", "description": "가져올 웹 페이지 URL"},
                        },
                        "required": ["url"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "schedule_task",
                    "description": "지정된 시간에 작업을 자동 실행하도록 예약합니다. '30분 후', '매일 오전 9시', '내일 오후 3시' 등 한국어 시간 표현을 when에 그대로 전달하세요.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "goal": {"type": "string", "description": "예약할 작업 내용"},
                            "when": {"type": "string", "description": "실행 시간 (한국어, 예: '30분 후', '매일 오전 9시')"},
                            "explanation": {"type": "string", "description": "사용자에게 말할 한국어 설명"},
                        },
                        "required": ["goal", "when"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "cancel_scheduled_task",
                    "description": "예약된 작업을 취소합니다.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "task_id": {"type": "string", "description": "취소할 작업의 ID"},
                        },
                        "required": ["task_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_scheduled_tasks",
                    "description": "현재 예약된 작업 목록을 조회합니다.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ]

    def get_available_functions(self):
        """하위 호환"""
        return [t["function"] for t in self.get_available_tools()]

    # ── 대화 ───────────────────────────────────────────────────────────────────

    def add_to_history(self, role, content):
        self.conversation_history.append({"role": role, "content": content})
        if len(self.conversation_history) > self.max_history * 2:
            self.conversation_history = self.conversation_history[-self.max_history * 2:]

    def _analyze_request(self, user_message: str) -> dict:
        """실행형 요청인지, 복합 작업인지, 특정 도구 강제가 필요한지 가볍게 판별."""
        text = re.sub(r"\s+", " ", (user_message or "").strip())
        normalized = text.lower()

        action_markers = (
            "해줘", "해 줘", "해봐", "해 봐", "실행", "열어", "켜", "꺼", "재생",
            "만들", "생성", "저장", "정리", "검색", "찾아", "불러", "예약", "설정",
            "수집", "요약", "보고", "작성", "다운로드", "이동", "복사",
        )
        multi_step_markers = (
            "그리고", "해서", "한 뒤", "다음", "후에", "정리해서", "찾아서", "검색해서",
            "만들고", "저장하고", "수집해서", "요약해서",
        )

        asks_screen = any(token in text for token in ("화면", "작업표시줄", "전체화면")) and any(
            token in text for token in ("어때", "보여", "상태", "뭐하고", "어떻게", "지금")
        )
        asks_schedule_list = "예약" in text and any(token in text for token in ("목록", "리스트", "보여", "확인"))
        asks_schedule_cancel = any(token in text for token in ("예약 취소", "스케줄 취소"))
        asks_schedule_create = ("예약" in text or "알려" in text) and any(
            token in text for token in ("후", "매일", "내일", "오전", "오후", "시", "분")
        )
        asks_latest_info = any(token in text for token in ("최신", "실시간", "오늘 뉴스", "뉴스", "검색", "찾아"))
        has_url = bool(re.search(r'https?://\S+', text))
        asks_open_target = any(token in text for token in ("열어", "열어줘", "열어 줘", "켜", "켜줘", "오픈", "실행")) and any(
            token in text for token in (
                "사이트", "브라우저", "크롬", "엣지", "메모장", "탐색기",
                "네이버", "구글", "유튜브", "gmail", "지메일", "카카오", "github",
            )
        )
        asks_file_system_action = any(token in text for token in ("파일", "폴더", "문서", "바탕화면", "복사", "이동", "정리", "요약", "시스템 정보", "사양", "리포트", "보고서", "사이트", "브라우저", "크롬", "엣지", "메모장", "로그인"))
        has_action = any(token in text for token in action_markers)
        multi_step = sum(text.count(token) for token in multi_step_markers) > 0

        creates_artifact = any(token in text for token in ("파일", "폴더", "문서", "저장", "바탕화면"))
        if creates_artifact and asks_latest_info:
            multi_step = True
        if asks_file_system_action and has_action:
            multi_step = True
        if has_url and has_action:
            multi_step = True
        if asks_open_target and has_action:
            multi_step = True

        force_tool = asks_screen or asks_schedule_list or asks_schedule_cancel or asks_schedule_create or multi_step or asks_open_target
        preferred_tool = None
        if asks_screen:
            preferred_tool = "get_screen_status"
        elif asks_schedule_list:
            preferred_tool = "list_scheduled_tasks"
        elif asks_schedule_cancel:
            preferred_tool = "cancel_scheduled_task"
        elif asks_schedule_create:
            preferred_tool = "schedule_task"
        elif asks_open_target or multi_step:
            preferred_tool = "run_agent_task"

        return {
            "text": text,
            "normalized": normalized,
            "has_action": has_action,
            "multi_step": multi_step,
            "asks_screen": asks_screen,
            "asks_latest_info": asks_latest_info,
            "has_url": has_url,
            "asks_open_target": asks_open_target,
            "asks_file_system_action": asks_file_system_action,
            "creates_artifact": creates_artifact,
            "force_tool": force_tool,
            "preferred_tool": preferred_tool,
        }

    def _select_tools_for_request(self, request_ctx: dict):
        tools = self.get_available_tools()
        preferred_tool = request_ctx.get("preferred_tool")
        if preferred_tool:
            filtered = [t for t in tools if t["function"]["name"] == preferred_tool]
            if filtered:
                return filtered, {"type": "function", "function": {"name": preferred_tool}}
        if request_ctx.get("force_tool"):
            return tools, "required"
        return tools, "auto"

    def _extract_tool_name_from_text(self, text: str) -> str:
        for tool in self.get_available_tools():
            name = tool["function"]["name"]
            if name in text:
                return name
        return ""

    def _fallback_tool_calls_from_text(self, raw_msg: str, user_message: str, request_ctx: dict) -> list:
        """텍스트 응답 속 가짜 도구 호출이나 실행형 요청을 실제 tool call로 승격."""
        tool_calls = []
        if not raw_msg:
            raw_msg = ""

        tool_name = self._extract_tool_name_from_text(raw_msg)
        if request_ctx.get("asks_open_target") and tool_name in {"web_fetch", "web_search", ""}:
            tool_calls.append({
                "id": "fallback_1",
                "name": "run_agent_task",
                "arguments": {"goal": user_message, "explanation": "열기 작업을 실행할게요."},
            })
        elif tool_name == "run_agent_task":
            tool_calls.append({
                "id": "fallback_1",
                "name": "run_agent_task",
                "arguments": {"goal": user_message, "explanation": "복합 작업을 실행할게요."},
            })
        elif tool_name == "get_screen_status":
            tool_calls.append({"id": "fallback_1", "name": "get_screen_status", "arguments": {}})
        elif tool_name == "list_scheduled_tasks":
            tool_calls.append({"id": "fallback_1", "name": "list_scheduled_tasks", "arguments": {}})
        elif tool_name == "cancel_scheduled_task":
            tool_calls.append({
                "id": "fallback_1",
                "name": "cancel_scheduled_task",
                "arguments": {"task_id": user_message},
            })
        elif tool_name == "schedule_task":
            tool_calls.append({
                "id": "fallback_1",
                "name": "schedule_task",
                "arguments": {"goal": user_message, "when": user_message},
            })
        else:
            matchers = [
                ("execute_shell_command", r'execute_shell_command\s*[:(]\s*(.+?)(?:\n|\[|$)'),
                ("execute_python_code", r'execute_python_code\s*[:(]\s*(.+?)(?:\n|\[|$)'),
                ("web_search", r'web_search\s*[:(]\s*(.+?)(?:\n|\[|$)'),
            ]
            for name, pattern in matchers:
                match = re.search(pattern, raw_msg, flags=re.IGNORECASE)
                if not match:
                    continue
                value = match.group(1).strip()
                if name == "execute_shell_command":
                    tool_calls.append({"id": "fallback_1", "name": name, "arguments": {"command": value, "explanation": "명령을 실행합니다."}})
                elif name == "execute_python_code":
                    tool_calls.append({"id": "fallback_1", "name": name, "arguments": {"code": value, "explanation": "코드를 실행합니다."}})
                else:
                    tool_calls.append({"id": "fallback_1", "name": name, "arguments": {"query": value}})
                break

        if tool_calls:
            return tool_calls

        if request_ctx.get("preferred_tool") == "run_agent_task":
            return [{
                "id": "fallback_1",
                "name": "run_agent_task",
                "arguments": {"goal": user_message, "explanation": "복합 작업을 실행할게요."},
            }]

        if request_ctx.get("force_tool") and request_ctx.get("has_action"):
            return [{
                "id": "fallback_1",
                "name": "run_agent_task",
                "arguments": {"goal": user_message, "explanation": "요청을 자율적으로 처리할게요."},
            }]

        return []

    def _normalize_tool_arguments(self, tool_name: str, args: dict, user_message: str) -> dict:
        """불완전한 tool arguments를 최소 실행 가능한 형태로 보정."""
        normalized = dict(args or {})

        if tool_name == "run_agent_task":
            normalized.setdefault("goal", user_message)
            normalized.setdefault("explanation", "복합 작업을 실행할게요.")
        elif tool_name == "execute_python_code":
            if not normalized.get("code"):
                normalized["code"] = user_message
            normalized.setdefault("explanation", "코드를 실행합니다.")
        elif tool_name == "execute_shell_command":
            if not normalized.get("command"):
                normalized["command"] = user_message
            normalized.setdefault("explanation", "명령을 실행합니다.")
        elif tool_name == "web_search":
            normalized.setdefault("query", user_message)
        elif tool_name == "schedule_task":
            normalized.setdefault("goal", user_message)
            normalized.setdefault("when", user_message)
        elif tool_name in ("get_screen_status", "list_scheduled_tasks", "cancel_timer", "get_weather", "get_current_time"):
            normalized = {}

        return normalized

    def _trace_tool_decision(self, stage: str, user_message: str, detail: str):
        try:
            from core.resource_manager import ResourceManager
            log_dir = ResourceManager.get_writable_path("logs")
            os.makedirs(log_dir, exist_ok=True)
            path = os.path.join(log_dir, f"tool_trace_{datetime.now().strftime('%Y%m%d')}.log")
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"[{datetime.now().strftime('%H:%M:%S')}] {stage} | user={user_message}\n{detail}\n\n")
        except Exception as e:
            logging.warning(f"[LLMProvider] tool trace 저장 실패: {e}")

    def _build_system(self, include_context=False):
        content = ""
        if self.system_prompt:
            content = self.system_prompt
        else:
            content = "당신은 친절하고 도움이 되는 한국어 AI 어시스턴트입니다."

        # 캐릭터 설정 추가
        if self.personality:
            content += f"\n\n페르소나: {self.personality}"
        if self.scenario:
            content += f"\n\n시나리오: {self.scenario}"

        # 실시간 '감각' 데이터 주입 (아리의 자율적 판단을 돕는 데이터)
        try:
            from VoiceCommand import character_widget
            if character_widget:
                geom = character_widget.get_screen_geometry()
                from PySide6.QtWidgets import QApplication
                full_geom = QApplication.primaryScreen().geometry()
                is_full = (geom.height() >= full_geom.height() - 10)
                
                content += "\n\n**현재 당신의 감각 (실시간 데이터)**:\n"
                content += f"- 위치: (X={character_widget.x()}, Y={character_widget.y()})\n"
                content += f"- 상태: {'[전체화면/작업표시줄숨김]' if is_full else '[일반화면/작업표시줄노출]'}\n"
                content += f"- 현재 동작: {character_widget.current_animation}\n"
                content += "- 위 데이터를 바탕으로 사용자가 묻지 않아도 현재 당신의 처지나 화면 상황을 자유롭게 판단하고 언급하세요."
        except Exception:
            pass

        content += (
            "\n[지침]\n"
            "1. 한국어 응답. 시작에 감정 태그 필수: (기쁨), (슬픔), (화남), (놀람), (평온), (수줍), (기대), (진지), (걱정) 중 하나.\n"
            "2. 복합 작업(폴더생성+검색+저장 등 2단계 이상)은 반드시 'run_agent_task' 도구만 사용. 텍스트로 절차를 나열하지 마세요.\n"
            "3. 가짜 명령(텍스트로 도구 이름 출력) 절대 금지. 반드시 실제 도구 호출(Tool Call) 기능을 사용하세요.\n"
            "\n[기억]\n"
            "- [BIO: 키=값], [PREF: 키=값], [FACT: 키=값] 활용. 일시적 상태는 저장 금지!"
        )

        if include_context:
            try:
                from memory_manager import get_memory_manager
                content += f"\n\n사용자 및 시스템 컨텍스트:\n{get_memory_manager().get_full_context_prompt()}"
            except Exception:
                pass
        return content

    def chat_with_tools(self, user_message, include_context=False):
        """도구 포함 대화. Returns (text|None, tool_calls_list)"""
        if not self.client:
            return "AI 기능이 비활성화되어 있습니다. 설정에서 API 키를 입력하세요.", []

        from memory_manager import get_memory_manager
        memory_manager = get_memory_manager()

        if self.provider == "anthropic":
            return self._anthropic_chat(user_message, include_context, use_tools=True)

        try:
            self.add_to_history("user", user_message)
            messages = [{"role": "system", "content": self._build_system(include_context)}]
            messages.extend(self.conversation_history)
            request_ctx = self._analyze_request(user_message)
            tools, tool_choice = self._select_tools_for_request(request_ctx)
            logging.info(
                "[LLMProvider] request 분석: force_tool=%s preferred=%s multi_step=%s action=%s",
                request_ctx["force_tool"], request_ctx["preferred_tool"],
                request_ctx["multi_step"], request_ctx["has_action"],
            )

            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                temperature=0.1 if request_ctx["force_tool"] else 0.3,
                max_tokens=1000,
            )
            choice = response.choices[0]

            tool_calls = []
            if choice.message.tool_calls:
                for tc in choice.message.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments)
                    except Exception:
                        args = {}
                    args = self._normalize_tool_arguments(tc.function.name, args, user_message)
                    tool_calls.append({"id": tc.id, "name": tc.function.name, "arguments": args})
                    # 명령어 패턴 기록
                    memory_manager.context_manager.record_command(tc.function.name, args)
                logging.info(f"AI tool calls: {tool_calls}")

            raw_msg = choice.message.content or ""
            
            self._trace_tool_decision(
                "chat_with_tools",
                user_message,
                f"request_ctx={request_ctx}\ntool_choice={tool_choice}\nraw_msg={raw_msg[:1200]}",
            )

            # 가짜 tool call 감지 또는 실행형 요청 폴백 승격
            if not tool_calls and raw_msg:
                tool_calls = self._fallback_tool_calls_from_text(raw_msg, user_message, request_ctx)
                if tool_calls:
                    logging.warning(f"[LLMProvider] 가짜 tool call 텍스트 감지 → 실제 실행: {[tc['name'] for tc in tool_calls]}")
                    # 가짜 도구가 감지된 경우, 텍스트 응답에서 코드/JSON 잔해를 제거하여 TTS를 깨끗하게 함
                    clean_msg = re.sub(r'```.*?```', '', raw_msg, flags=re.DOTALL)
                    clean_msg = re.sub(r'\{.*\}', '', clean_msg, flags=re.DOTALL)
                    msg = self._filter_korean(clean_msg)
                    if not msg.strip():
                        msg = "(진지) 요청하신 명령을 실행할게요."
                else:
                    # 정보 추출 및 저장
                    memory_manager.process_interaction(user_message, raw_msg)
                    msg = memory_manager.clean_response(raw_msg)
                    msg = self._filter_korean(msg)
            elif raw_msg:
                # 정상 tool_call이 있거나 도구가 없는 일반 응답
                memory_manager.process_interaction(user_message, raw_msg)
                msg = memory_manager.clean_response(raw_msg)
                msg = self._filter_korean(msg)
            else:
                msg = ""
                if request_ctx.get("force_tool") and request_ctx.get("has_action"):
                    tool_calls = [{
                        "id": "fallback_1",
                        "name": request_ctx.get("preferred_tool") or "run_agent_task",
                        "arguments": (
                            {"goal": user_message, "explanation": "요청을 자율적으로 처리할게요."}
                            if request_ctx.get("preferred_tool") in (None, "run_agent_task")
                            else {}
                        ),
                    }]
            if not msg and not tool_calls:
                msg = "(평온) 죄송해요, 답변을 생성할 수 없었어요."
            
            if msg:
                self.add_to_history("assistant", msg)
            
            return msg, tool_calls

        except Exception as e:
            logging.error(f"LLM chat_with_tools 오류 ({self.provider}): {e}")
            return f"AI 응답 생성 중 오류가 발생했습니다: {e}", []

    def chat(self, user_message, include_context=False):
        """단순 대화"""
        if not self.client:
            return "AI 기능이 비활성화되어 있습니다. 설정에서 API 키를 입력하세요."

        from memory_manager import get_memory_manager
        memory_manager = get_memory_manager()

        if self.provider == "anthropic":
            result, _ = self._anthropic_chat(user_message, include_context, use_tools=False)
            return result

        try:
            self.add_to_history("user", user_message)
            messages = [{"role": "system", "content": self._build_system(include_context)}]
            messages.extend(self.conversation_history)

            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.7,
                max_tokens=200,
            )
            raw_msg = response.choices[0].message.content or ""
            
            # 정보 추출 및 저장
            memory_manager.process_interaction(user_message, raw_msg)
            msg = memory_manager.clean_response(raw_msg)
            
            msg = self._filter_korean(msg)
            if not msg:
                msg = "죄송해요, 답변을 생성할 수 없었어요."
            self.add_to_history("assistant", msg)
            return msg

        except Exception as e:
            logging.error(f"LLM chat 오류 ({self.provider}): {e}")
            return f"AI 응답 생성 중 오류가 발생했습니다: {e}"

    def feed_tool_result(self, original_msg: str, tool_calls: list, results: list) -> str:
        """도구 실행 결과를 LLM에 피드백하여 최종 한국어 응답을 생성합니다.

        무한 루프 방지: 이 호출에서는 tools=None으로 고정합니다.
        """
        if not self.client:
            return ""

        if self.provider == "anthropic":
            return self._anthropic_feed_tool_result(original_msg, tool_calls, results)

        try:
            # OpenAI 규칙: assistant의 tool_call 메시지 → tool result 메시지 순서로 구성
            assistant_tool_calls = []
            for tc in tool_calls:
                tool_id = tc.get("id", tc.get("name", "tool_0"))
                assistant_tool_calls.append({
                    "id": tool_id,
                    "type": "function",
                    "function": {
                        "name": tc.get("name", ""),
                        "arguments": json.dumps(tc.get("arguments", {}), ensure_ascii=False),
                    },
                })

            tool_result_messages = []
            for tc, result in zip(tool_calls, results):
                tool_id = tc.get("id", tc.get("name", "tool_0"))
                content = str(result) if result is not None else "완료"
                tool_result_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_id,
                    "content": content,
                })

            messages = [{"role": "system", "content": self._build_system()}]
            messages.extend(self.conversation_history)
            # assistant의 tool_call 메시지 삽입 (마지막 history 이후)
            messages.append({"role": "assistant", "content": None, "tool_calls": assistant_tool_calls})
            messages.extend(tool_result_messages)

            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.7,
                max_tokens=150,
                # tools=None 으로 무한 루프 방지
            )
            raw = response.choices[0].message.content or ""
            msg = self._filter_korean(raw)
            if msg:
                self.add_to_history("assistant", msg)
            return msg

        except Exception as e:
            logging.error(f"feed_tool_result 오류 ({self.provider}): {e}")
            return ""

    def _anthropic_feed_tool_result(self, original_msg: str, tool_calls: list, results: list) -> str:
        """Anthropic용 tool result 피드백"""
        try:
            tool_result_content = []
            for tc, result in zip(tool_calls, results):
                tool_id = tc.get("id", tc.get("name", "tool_0"))
                tool_result_content.append({
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": str(result) if result is not None else "완료",
                })

            messages = list(self.conversation_history)
            messages.append({"role": "user", "content": tool_result_content})

            response = self.client.messages.create(
                model=self.model,
                max_tokens=150,
                system=self._build_system(),
                messages=messages,
            )
            text_parts = [b.text for b in response.content if b.type == "text"]
            raw = " ".join(text_parts)
            msg = self._filter_korean(raw)
            if msg:
                self.add_to_history("assistant", msg)
            return msg

        except Exception as e:
            logging.error(f"Anthropic feed_tool_result 오류: {e}")
            return ""

    def _anthropic_chat(self, user_message, include_context=False, use_tools=False):
        """Anthropic Claude API (자체 SDK 형식)"""
        try:
            from memory_manager import get_memory_manager
            memory_manager = get_memory_manager()
            
            self.add_to_history("user", user_message)
            system_content = self._build_system(include_context)
            request_ctx = self._analyze_request(user_message)

            kwargs = {
                "model": self.model,
                "max_tokens": 300,
                "system": system_content,
                "messages": self.conversation_history,
            }

            if use_tools:
                tools, _ = self._select_tools_for_request(request_ctx)
                kwargs["tools"] = [
                    {
                        "name": t["function"]["name"],
                        "description": t["function"]["description"],
                        "input_schema": t["function"]["parameters"],
                    }
                    for t in tools
                ]

            response = self.client.messages.create(**kwargs)

            tool_calls = []
            text_parts = []
            for block in response.content:
                if block.type == "tool_use":
                    args = self._normalize_tool_arguments(block.name, block.input, user_message)
                    tool_calls.append({"name": block.name, "arguments": args})
                    # 명령어 패턴 기록
                    memory_manager.context_manager.record_command(block.name, args)
                elif block.type == "text":
                    text_parts.append(block.text)

            raw_msg = " ".join(text_parts)
            
            # 정보 추출 및 저장
            if raw_msg:
                memory_manager.process_interaction(user_message, raw_msg)
                msg = memory_manager.clean_response(raw_msg)
            else:
                msg = ""

            if not tool_calls:
                tool_calls = self._fallback_tool_calls_from_text(raw_msg, user_message, request_ctx)

            if tool_calls:
                logging.info(f"Anthropic tool calls: {tool_calls}")
                return msg if msg else None, tool_calls

            msg = self._filter_korean(msg) or "죄송해요, 답변을 생성할 수 없었어요."
            self.add_to_history("assistant", msg)
            return msg, []

        except Exception as e:
            logging.error(f"Anthropic API 오류: {e}")
            return f"AI 응답 생성 중 오류가 발생했습니다: {e}", []

    # ── 텍스트 필터링 ──────────────────────────────────────────────────────────

    def _filter_korean(self, text):
        """한국어/숫자/구두점만 유지, 명령어 태그 보존.
        TTS 출력 전 파일경로·가짜명령 등 기술 문자열을 먼저 제거합니다."""
        commands = []

        def save_cmd(m):
            commands.append(m.group(0))
            return f"__CMD_{len(commands)-1}__"

        # [CMD:...] 태그 보존
        text = re.sub(r'\[CMD:[^\]]+\]', save_cmd, text)

        # 가짜 명령 블록 제거: [execute_shell_command: ...], [web_search: ...] 등
        text = re.sub(r'\[[a-zA-Z_]+:[^\]]*\]', '', text)

        # 파일 경로 제거: ~/Desktop/..., C:\Users\..., /usr/... 등
        text = re.sub(r'[A-Za-z]:\\[^\s,!?]+', '', text)  # Windows 절대경로
        text = re.sub(r'~?/[A-Za-z0-9_\-./]+', '', text)  # Unix/상대경로

        # 나머지 비한국어 문자 제거
        text = re.sub(r'[^가-힣0-9\s.,!?~\-()%]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()

        for i, cmd in enumerate(commands):
            text = text.replace(f"__CMD_{i}__", cmd)
        return text

    # ── 기존 GroqAssistant 인터페이스 호환 ────────────────────────────────────

    def clear_history(self):
        self.conversation_history = []
        logging.info("대화 기록 초기화됨")

    def process_query(self, query):
        return self.chat(query), [], "neutral"

    def learn_new_response(self, query, response):
        logging.info(f"학습 요청 ({self.provider}) - Query: {query}")

    def update_q_table(self, state, action, reward, next_state):
        pass

    def execute_function(self, function_name, arguments):
        """Function 실행 (groq_assistant 호환)"""
        from datetime import datetime
        try:
            if function_name == "get_weather":
                from weather_service import WeatherService
                return WeatherService(api_key="").get_weather()
            elif function_name == "set_timer":
                from timer_manager import TimerManager
                minutes = arguments.get("minutes", 5)
                TimerManager(tts_callback=None).set_timer(minutes)
                return f"{minutes}분 타이머가 설정되었습니다."
            elif function_name == "get_current_time":
                now = datetime.now()
                am_pm = "오전" if now.hour < 12 else "오후"
                hour = now.hour if now.hour <= 12 else now.hour - 12
                return f"현재 시간은 {am_pm} {hour}시 {now.minute}분입니다."
            elif function_name == "get_screen_status":
                from VoiceCommand import character_widget
                if not character_widget: return "위젯 미초기화"
                geom = character_widget.get_screen_geometry()
                return f"가용 화면: {geom.width()}x{geom.height()}"
        except Exception as e:
            logging.error(f"Function 실행 오류 ({function_name}): {e}")
            return f"실행 중 오류가 발생했습니다: {e}"


# ── 싱글톤 팩토리 ──────────────────────────────────────────────────────────────

_instance: LLMProvider | None = None


def get_llm_provider() -> LLMProvider:
    """LLMProvider 싱글톤 반환"""
    global _instance
    if _instance is None:
        try:
            from config_manager import ConfigManager
            s = ConfigManager.load_settings()
        except Exception:
            s = {}

        provider = s.get("llm_provider", "groq")
        _key_map = {
            "groq": "groq_api_key",
            "openai": "openai_api_key",
            "anthropic": "anthropic_api_key",
            "mistral": "mistral_api_key",
            "gemini": "gemini_api_key",
            "openrouter": "openrouter_api_key",
        }
        api_key = s.get(_key_map.get(provider, "groq_api_key"), "")

        _instance = LLMProvider(
            provider=provider,
            api_key=api_key,
            model=s.get("llm_model", ""),
            system_prompt=s.get("system_prompt", ""),
            personality=s.get("personality", ""),
            scenario=s.get("scenario", ""),
        )
    return _instance


def reset_llm_provider():
    """설정 변경 후 싱글톤 리셋 (다음 호출 시 새로 초기화)"""
    global _instance
    _instance = None
