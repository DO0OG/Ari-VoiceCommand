"""레거시 GroqAssistant 호환 래퍼.

실제 구현은 agent.llm_provider.LLMProvider를 사용한다.
"""
from __future__ import annotations

import logging


class GroqAssistant:
    def __init__(self, api_key="", system_prompt="", personality="", scenario=""):
        self.api_key = api_key
        self.system_prompt = system_prompt
        self.personality = personality
        self.scenario = scenario

    @property
    def _provider(self):
        from agent.llm_provider import get_llm_provider
        return get_llm_provider()

    @property
    def client(self):
        return getattr(self._provider, "client", None)

    @property
    def conversation_history(self):
        return getattr(self._provider, "conversation_history", [])

    def add_to_history(self, role, content):
        self._provider.add_to_history(role, content)

    def get_available_tools(self):
        return self._provider.get_available_tools()

    def get_available_functions(self):
        return self._provider.get_available_functions()

    def execute_function(self, function_name, arguments):
        logging.info(f"[GroqAssistant] 레거시 execute_function 호출: {function_name}")
        return ""

    def chat_with_tools(self, user_message, include_context=True):
        return self._provider.chat_with_tools(user_message, include_context=include_context)

    def chat(self, user_message, include_context=True):
        return self._provider.chat(user_message, include_context=include_context)

    def feed_tool_result(self, original_msg, tool_calls, results):
        return self._provider.feed_tool_result(original_msg, tool_calls, results)

    def clear_history(self):
        self._provider.conversation_history = []
        logging.info("대화 기록 초기화됨")

    def process_query(self, query):
        response = self.chat(query, include_context=True)
        return response, [], "neutral"

    def learn_new_response(self, query, response):
        logging.info(f"학습 요청 (Groq wrapper) - Query: {query}, Response: {response}")

    def update_q_table(self, state, action, reward, next_state):
        logging.debug(f"Q-table 업데이트 (Groq wrapper): {action}, reward={reward}")


_groq_assistant = None


def get_groq_assistant():
    from agent.llm_provider import get_llm_provider
    return get_llm_provider()


def set_groq_api_key(api_key):
    from agent.llm_provider import reset_llm_provider
    from core.config_manager import ConfigManager
    ConfigManager.set_value("groq_api_key", api_key)
    reset_llm_provider()
