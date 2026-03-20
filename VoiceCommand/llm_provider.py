"""
다중 LLM 제공자 통합 — Groq, OpenAI, Anthropic, Mistral, Gemini, OpenRouter
모든 OpenAI-호환 제공자는 openai SDK + base_url 방식으로 통일.
Anthropic만 자체 SDK 사용.
"""
import json
import logging
import re

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
        ]

    def get_available_functions(self):
        """하위 호환"""
        return [t["function"] for t in self.get_available_tools()]

    # ── 대화 ───────────────────────────────────────────────────────────────────

    def add_to_history(self, role, content):
        self.conversation_history.append({"role": role, "content": content})
        if len(self.conversation_history) > self.max_history * 2:
            self.conversation_history = self.conversation_history[-self.max_history * 2:]

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

        content += (
            "\n\n**중요 지침**:\n"
            "1. 반드시 한국어로만 대답하세요.\n"
            "2. 대답의 시작 부분에 상황에 맞는 감정 태그를 반드시 하나 포함하세요: (기쁨), (슬픔), (화남), (놀람), (평온), (수줍), (기대), (진지), (걱정)\n"
            "   예: (기대) 우와, 정말요? 너무 기대돼요!\n"
            "3. 음악 재생, 타이머 설정, 날씨 확인 등 동작 요청 시 해당 도구를 호출하세요.\n"
            "4. 간결하고 자연스럽게 캐릭터를 유지하며 대답하세요."
        )

        if include_context:
            try:
                from user_context import get_context_manager
                ctx = get_context_manager().get_context_summary()
                if ctx:
                    content += f"\n\n사용자 컨텍스트:\n{ctx}"
            except Exception:
                pass
        return content

    def chat_with_tools(self, user_message, include_context=False):
        """도구 포함 대화. Returns (text|None, tool_calls_list)"""
        if not self.client:
            return "AI 기능이 비활성화되어 있습니다. 설정에서 API 키를 입력하세요.", []

        if self.provider == "anthropic":
            return self._anthropic_chat(user_message, include_context, use_tools=True)

        try:
            self.add_to_history("user", user_message)
            messages = [{"role": "system", "content": self._build_system(include_context)}]
            messages.extend(self.conversation_history)

            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=self.get_available_tools(),
                tool_choice="auto",
                temperature=0.7,
                max_tokens=300,
            )
            choice = response.choices[0]

            tool_calls = []
            if choice.message.tool_calls:
                for tc in choice.message.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments)
                    except Exception:
                        args = {}
                    tool_calls.append({"name": tc.function.name, "arguments": args})
                logging.info(f"AI tool calls: {tool_calls}")

            msg = self._filter_korean(choice.message.content or "")
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
            msg = self._filter_korean(response.choices[0].message.content or "")
            if not msg:
                msg = "죄송해요, 답변을 생성할 수 없었어요."
            self.add_to_history("assistant", msg)
            return msg

        except Exception as e:
            logging.error(f"LLM chat 오류 ({self.provider}): {e}")
            return f"AI 응답 생성 중 오류가 발생했습니다: {e}"

    def _anthropic_chat(self, user_message, include_context=False, use_tools=False):
        """Anthropic Claude API (자체 SDK 형식)"""
        try:
            self.add_to_history("user", user_message)
            system_content = self._build_system(include_context)

            kwargs = {
                "model": self.model,
                "max_tokens": 300,
                "system": system_content,
                "messages": self.conversation_history,
            }

            if use_tools:
                kwargs["tools"] = [
                    {
                        "name": t["function"]["name"],
                        "description": t["function"]["description"],
                        "input_schema": t["function"]["parameters"],
                    }
                    for t in self.get_available_tools()
                ]

            response = self.client.messages.create(**kwargs)

            tool_calls = []
            text_parts = []
            for block in response.content:
                if block.type == "tool_use":
                    tool_calls.append({"name": block.name, "arguments": block.input})
                elif block.type == "text":
                    text_parts.append(block.text)

            if tool_calls:
                logging.info(f"Anthropic tool calls: {tool_calls}")
                return None, tool_calls

            msg = self._filter_korean(" ".join(text_parts)) or "죄송해요, 답변을 생성할 수 없었어요."
            self.add_to_history("assistant", msg)
            return msg, []

        except Exception as e:
            logging.error(f"Anthropic API 오류: {e}")
            return f"AI 응답 생성 중 오류가 발생했습니다: {e}", []

    # ── 텍스트 필터링 ──────────────────────────────────────────────────────────

    def _filter_korean(self, text):
        """한국어/숫자/구두점만 유지, 명령어 태그 보존"""
        commands = []

        def save_cmd(m):
            commands.append(m.group(0))
            return f"__CMD_{len(commands)-1}__"

        text = re.sub(r'\[CMD:[^\]]+\]', save_cmd, text)
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
