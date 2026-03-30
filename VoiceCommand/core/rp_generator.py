"""
RP 텍스트 생성기
"""
import logging
import re


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

    def build_system_prompt(self, base_prompt: str) -> str:
        """캐릭터 설정을 시스템 프롬프트에 녹여서 반환."""
        parts = [base_prompt.strip() if base_prompt else "당신은 한국어 AI 어시스턴트 아리입니다."]
        if self.personality:
            parts.append(f"[캐릭터 성격]\n{self.personality.strip()}")
        if self.scenario:
            parts.append(f"[현재 상황]\n{self.scenario.strip()}")
        if self.history_instruction:
            parts.append(f"[대화 방식]\n{self.history_instruction.strip()}")
        parts.append(
            "[감정 표현]\n"
            "응답 맨 앞에 감정 태그를 자연스럽게 붙이세요. 사용할 수 있는 예: "
            "(기쁨) (슬픔) (화남) (놀람) (평온) (수줍) (기대) (진지) (걱정)"
        )
        return "\n\n".join(part for part in parts if part)

    def generate(self, text: str) -> str:
        """TTS 출력용 말투를 가볍게 보정."""
        if not text:
            return ""
        return self._apply_speech_style(text)

    def _apply_speech_style(self, text: str) -> str:
        styled = text.strip()
        if not styled:
            return ""

        if self.personality:
            personality = self.personality.lower()
            if "상냥" in personality or "친절" in personality:
                styled = re.sub(r"(?<!요)\.$", "요.", styled)
            if "귀여" in personality and not styled.endswith(("요", "요.", "에요", "예요")):
                styled = f"{styled}요"
            if "차분" in personality:
                styled = styled.replace("!", ".")
        return styled
