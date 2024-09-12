"""
Groq API 기반 AI 어시스턴트
"""
import os
import json
import logging
from datetime import datetime
from groq import Groq


class GroqAssistant:
    def __init__(self, api_key="", system_prompt="", personality="", scenario=""):
        self.api_key = api_key
        self.client = None
        self.conversation_history = []
        self.max_history = 10  # 최근 10개 대화만 유지

        # 캐릭터 설정 저장
        self.system_prompt = system_prompt
        self.personality = personality
        self.scenario = scenario

        if api_key:
            try:
                self.client = Groq(api_key=api_key)
                logging.info("Groq 클라이언트 초기화 완료")
                if system_prompt:
                    logging.info("캐릭터 시스템 프롬프트 로드됨")
            except Exception as e:
                logging.error(f"Groq 초기화 실패: {e}")

    def add_to_history(self, role, content):
        """대화 기록 추가"""
        self.conversation_history.append({
            "role": role,
            "content": content
        })
        # 최대 개수 제한
        if len(self.conversation_history) > self.max_history * 2:
            self.conversation_history = self.conversation_history[-self.max_history * 2:]

    def get_available_tools(self):
        """Groq tool calling 형식의 도구 정의 (모든 사용 가능한 명령)"""
        return [
            {
                "type": "function",
                "function": {
                    "name": "play_youtube",
                    "description": "유튜브에서 음악이나 영상을 검색하여 재생합니다. 사용자가 음악 재생, 노래 틀기, 유튜브 검색을 요청할 때 사용하세요.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "검색할 음악이나 영상 제목 (예: '아이유 밤편지', '로파이 음악')"
                            }
                        },
                        "required": ["query"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "set_timer",
                    "description": "타이머를 설정합니다. 사용자가 몇 분/몇 초 후 알림을 요청할 때 사용하세요.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "minutes": {
                                "type": "integer",
                                "description": "타이머 시간 (분), 없으면 0"
                            },
                            "seconds": {
                                "type": "integer",
                                "description": "추가 초 단위, 없으면 0"
                            }
                        },
                        "required": ["minutes"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "cancel_timer",
                    "description": "현재 진행 중인 타이머를 취소합니다.",
                    "parameters": {
                        "type": "object",
                        "properties": {}
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "description": "현재 날씨 정보를 조회합니다. 사용자가 날씨, 기온, 온도를 물어볼 때 사용하세요.",
                    "parameters": {
                        "type": "object",
                        "properties": {}
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "adjust_volume",
                    "description": "시스템 볼륨을 조절합니다. 사용자가 소리를 크게/작게 해달라고 요청할 때 사용하세요.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "direction": {
                                "type": "string",
                                "enum": ["up", "down", "mute"],
                                "description": "up=볼륨 올리기, down=볼륨 내리기, mute=음소거"
                            }
                        },
                        "required": ["direction"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "get_current_time",
                    "description": "현재 시간을 알려줍니다. 사용자가 몇 시인지 물어볼 때 사용하세요.",
                    "parameters": {
                        "type": "object",
                        "properties": {}
                    }
                }
            }
        ]

    def get_available_functions(self):
        """사용 가능한 function 정의 (하위 호환)"""
        return [t["function"] for t in self.get_available_tools()]

    def execute_function(self, function_name, arguments):
        """Function 실행 (하위 호환용 — 직접 실행)"""
        try:
            if function_name == "get_weather":
                from weather_service import WeatherService
                weather_service = WeatherService(api_key="")
                return weather_service.get_weather()

            elif function_name == "set_timer":
                from timer_manager import TimerManager
                timer_manager = TimerManager(tts_callback=None)
                minutes = arguments.get("minutes", 5)
                timer_manager.set_timer(minutes)
                return f"{minutes}분 타이머가 설정되었습니다."

            elif function_name == "get_current_time":
                now = datetime.now()
                if now.hour < 12:
                    am_pm = "오전"
                    hour = now.hour
                else:
                    am_pm = "오후"
                    hour = now.hour - 12 if now.hour > 12 else 12
                return f"현재 시간은 {am_pm} {hour}시 {now.minute}분입니다."

        except Exception as e:
            logging.error(f"Function 실행 오류 ({function_name}): {e}")
            return f"실행 중 오류가 발생했습니다: {str(e)}"

    def chat_with_tools(self, user_message, include_context=False):
        """도구(function calling)를 활용한 AI 대화.

        Returns:
            tuple: (text_response: str | None, tool_calls: list)
              - 일반 대화: (text, [])
              - 명령 실행 필요: (None, [{"name": ..., "arguments": {...}}, ...])
        """
        if not self.client:
            return "AI 기능이 비활성화되어 있습니다. 설정에서 Groq API 키를 입력하세요.", []

        try:
            self.add_to_history("user", user_message)

            if self.system_prompt:
                system_content = self.system_prompt
                system_content += "\n\n**중요**: 반드시 한국어로만 대답하세요. 사용자가 특정 동작(음악 재생, 타이머, 날씨, 볼륨, 시간 등)을 요청하면 해당 도구를 호출하세요."
                if include_context:
                    try:
                        from user_context import get_context_manager
                        context_summary = get_context_manager().get_context_summary()
                        if context_summary:
                            system_content += f"\n\n사용자 컨텍스트:\n{context_summary}"
                    except Exception:
                        pass
            else:
                system_content = (
                    "당신은 친절하고 도움이 되는 한국어 AI 어시스턴트입니다. "
                    "**반드시 한국어로만 대답하세요.** "
                    "사용자가 음악 재생, 타이머 설정, 날씨 확인, 볼륨 조절, 시간 확인 등의 동작을 요청하면 "
                    "반드시 해당 도구를 호출하세요. 간결하고 자연스럽게 대답하세요."
                )

            messages = [{"role": "system", "content": system_content}]
            messages.extend(self.conversation_history)

            response = self.client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                tools=self.get_available_tools(),
                tool_choice="auto",
                temperature=0.7,
                max_tokens=300,
                top_p=0.9,
                stream=False
            )

            choice = response.choices[0]

            # 도구 호출이 있는 경우
            if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
                tool_calls = []
                for tc in choice.message.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments)
                    except Exception:
                        args = {}
                    tool_calls.append({
                        "name": tc.function.name,
                        "arguments": args
                    })
                logging.info(f"AI tool calls: {tool_calls}")
                # 대화 기록에는 어시스턴트 도구 호출 메시지 추가하지 않음 (단순화)
                return None, tool_calls

            # 일반 텍스트 응답
            assistant_message = choice.message.content or ""
            filtered_message = self._filter_korean_text_preserve_commands(assistant_message)
            if not filtered_message:
                filtered_message = "죄송해요, 답변을 생성할 수 없었어요."
            self.add_to_history("assistant", filtered_message)
            return filtered_message, []

        except Exception as e:
            logging.error(f"Groq chat_with_tools 오류: {e}")
            return f"AI 응답 생성 중 오류가 발생했습니다: {str(e)}", []

    def _filter_korean_text(self, text):
        """한국어와 기본 구두점만 유지 (영어 제거)"""
        import re
        # 한글, 숫자, 기본 구두점, 공백만 허용 (영문 제거!)
        filtered = re.sub(r'[^가-힣0-9\s.,!?~\-()%]', '', text)
        # 연속된 공백 제거
        filtered = re.sub(r'\s+', ' ', filtered)
        return filtered.strip()

    def chat(self, user_message, include_context=False):
        """AI와 대화"""
        if not self.client:
            logging.warning("Groq API 키가 설정되지 않았습니다.")
            return "AI 기능이 비활성화되어 있습니다. 설정에서 Groq API 키를 입력하세요."

        try:
            # 사용자 메시지 추가
            self.add_to_history("user", user_message)

            # 시스템 프롬프트 결정: 사용자 설정 우선, 없으면 기본값
            if self.system_prompt:
                system_content = self.system_prompt
                # 한국어 필터링 지시 추가
                system_content += "\n\n**중요**: 반드시 한국어로만 대답하세요. 중국어, 일본어 등 다른 언어의 문자를 절대 사용하지 마세요."

                # 사용자 컨텍스트 추가 (스마트 모드 시)
                if include_context:
                    try:
                        from user_context import get_context_manager
                        context_summary = get_context_manager().get_context_summary()
                        if context_summary:
                            system_content += f"\n\n사용자 컨텍스트:\n{context_summary}"
                    except:
                        pass
            else:
                system_content = (
                    "당신은 친절하고 도움이 되는 한국어 AI 어시스턴트입니다. "
                    "**반드시 한국어로만 대답하세요.** 중국어, 일본어 등 다른 언어를 절대 사용하지 마세요. "
                    "간결하고 자연스럽게 대답하세요."
                )

            messages = [
                {
                    "role": "system",
                    "content": system_content
                }
            ]
            messages.extend(self.conversation_history)

            # API 호출
            response = self.client.chat.completions.create(
                model="llama-3.3-70b-versatile",  # 최신 모델
                messages=messages,
                temperature=0.7,  # 캐릭터 RP를 위해 0.7로 유지
                max_tokens=200,  # 500 → 200으로 감소 (TTS용 짧은 응답)
                top_p=0.9,
                stream=False
            )

            assistant_message = response.choices[0].message.content

            # 한국어 필터링 적용 (명령어 태그는 보존)
            filtered_message = self._filter_korean_text_preserve_commands(assistant_message)

            if not filtered_message:
                filtered_message = "죄송해요, 답변을 생성할 수 없었어요."

            self.add_to_history("assistant", filtered_message)

            return filtered_message

        except Exception as e:
            logging.error(f"Groq API 오류: {e}")
            return f"AI 응답 생성 중 오류가 발생했습니다: {str(e)}"

    def _filter_korean_text_preserve_commands(self, text):
        """한국어 필터링 (명령어 태그 보존)"""
        import re

        # 명령어 태그 임시 저장
        commands = []
        def save_command(match):
            commands.append(match.group(0))
            return f"__CMD_{len(commands)-1}__"

        # 명령어 태그를 임시 플레이스홀더로 교체
        text = re.sub(r'\[CMD:[^\]]+\]', save_command, text)

        # 한국어 필터링
        text = self._filter_korean_text(text)

        # 명령어 태그 복원
        for i, cmd in enumerate(commands):
            text = text.replace(f"__CMD_{i}__", cmd)

        return text

    def clear_history(self):
        """대화 기록 초기화"""
        self.conversation_history = []
        logging.info("대화 기록 초기화됨")

    def process_query(self, query):
        """음성 명령 처리 (기존 인터페이스 호환)"""
        response = self.chat(query)
        return response, [], "neutral"

    def learn_new_response(self, query, response):
        """응답 학습 (Groq는 API 기반이므로 로그만)"""
        logging.info(f"학습 요청 (Groq) - Query: {query}, Response: {response}")

    def update_q_table(self, state, action, reward, next_state):
        """Q-learning (Groq는 API 기반이므로 로그만)"""
        logging.debug(f"Q-table 업데이트 (Groq): {action}, reward={reward}")


# 전역 인스턴스
_groq_assistant = None


def get_groq_assistant():
    """Groq Assistant 싱글톤"""
    global _groq_assistant
    if _groq_assistant is None:
        # 설정 파일에서 API 키 및 캐릭터 설정 로드
        try:
            from config_manager import ConfigManager
            settings = ConfigManager.load_settings()
            api_key = settings.get("groq_api_key", "")
            system_prompt = settings.get("system_prompt", "")
            personality = settings.get("personality", "")
            scenario = settings.get("scenario", "")
        except Exception as e:
            logging.warning(f"설정 로드 실패: {e}")
            api_key = ""
            system_prompt = ""
            personality = ""
            scenario = ""

        _groq_assistant = GroqAssistant(
            api_key=api_key,
            system_prompt=system_prompt,
            personality=personality,
            scenario=scenario
        )

    return _groq_assistant


def set_groq_api_key(api_key):
    """Groq API 키 설정"""
    global _groq_assistant
    _groq_assistant = GroqAssistant(api_key=api_key)
