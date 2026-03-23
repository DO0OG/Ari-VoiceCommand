"""
RP 텍스트 생성기
"""
import logging


class RPGenerator:
    def __init__(self):
        self.personality = ""
        self.scenario = ""
        self.system_prompt = ""
        self.history_instruction = ""

    def set_config(self, personality="", scenario="", system_prompt="", history_instruction=""):
        """RP 설정"""
        self.personality = personality
        self.scenario = scenario
        self.system_prompt = system_prompt
        self.history_instruction = history_instruction
        logging.info("RP 설정 업데이트됨")

    def generate(self, user_input):
        """사용자 입력에 대한 RP 응답 생성"""
        # RP 기능은 추후 LLM API 연동 시 구현
        # 현재는 입력을 그대로 반환
        return user_input
