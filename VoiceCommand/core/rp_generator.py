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
        self.response_verbosity = "concise"

    def set_config(self, personality="", scenario="", system_prompt="", history_instruction="",
                    response_verbosity="concise"):
        """RP 설정"""
        self.personality = personality
        self.scenario = scenario
        self.system_prompt = system_prompt
        self.history_instruction = history_instruction
        self.response_verbosity = response_verbosity or "concise"
        logging.info("RP 설정 업데이트됨")

    def build_system_prompt(self, base_prompt: str) -> str:
        """캐릭터 설정을 시스템 프롬프트에 녹여서 반환."""
        try:
            from i18n.translator import get_language
            lang = get_language()
        except Exception:
            lang = "ko"
        _BASE_PROMPT = {
            "ko": "당신은 한국어 AI 어시스턴트 아리입니다.",
            "en": "You are Ari, an AI assistant.",
            "ja": "あなたはAIアシスタントのAriです。",
        }
        _EMOTION_INSTRUCTION = {
            "ko": (
                "[감정 표현]\n"
                "응답 맨 앞에 감정 태그를 자연스럽게 붙이세요. 사용할 수 있는 예: "
                "(기쁨) (슬픔) (화남) (놀람) (평온) (수줍) (기대) (진지) (걱정)"
            ),
            "en": (
                "[Emotion Tags]\n"
                "Start your response with an emotion tag naturally. "
                "Examples: (joy) (sad) (angry) (surprised) (calm) (shy) (excited) (serious) (worried)"
            ),
            "ja": (
                "[感情タグ]\n"
                "返答の先頭に感情タグを自然につけてください。"
                "例: (喜び) (悲しみ) (怒り) (驚き) (穏やか) (恥ずかしい) (期待) (真剣) (心配)"
            ),
        }
        _VERBOSITY_INSTRUCTION = {
            "ko": {
                "concise": "[응답 길이]\n한두 문장으로 핵심만 답하세요. 부연 설명, 배경 설명, 되묻기는 꼭 필요할 때만 덧붙이세요.",
                "normal": "[응답 길이]\n필요한 만큼만 설명하세요. 과도하게 길어지지 않도록 하세요.",
                "chatty": "[응답 길이]\n캐릭터의 말투를 살려 조금 더 풍부하게 이야기해도 됩니다.",
            },
            "en": {
                "concise": "[Response length]\nAnswer in one or two sentences with only the essentials. Add explanation only when truly necessary.",
                "normal": "[Response length]\nExplain only as much as needed. Avoid unnecessary length.",
                "chatty": "[Response length]\nFeel free to elaborate a bit more in character.",
            },
            "ja": {
                "concise": "[返答の長さ]\n一、二文で要点だけ答えてください。補足説明は本当に必要な時だけ。",
                "normal": "[返答の長さ]\n必要な分だけ説明してください。長くなりすぎないように。",
                "chatty": "[返答の長さ]\nキャラクターらしく、もう少し豊かに話してもかまいません。",
            },
        }
        parts = [base_prompt.strip() if base_prompt else _BASE_PROMPT.get(lang, _BASE_PROMPT["ko"])]
        if self.personality:
            parts.append(f"[캐릭터 성격]\n{self.personality.strip()}")
        if self.scenario:
            parts.append(f"[현재 상황]\n{self.scenario.strip()}")
        if self.history_instruction:
            parts.append(f"[대화 방식]\n{self.history_instruction.strip()}")
        verbosity_map = _VERBOSITY_INSTRUCTION.get(lang, _VERBOSITY_INSTRUCTION["ko"])
        parts.append(verbosity_map.get(self.response_verbosity, verbosity_map["concise"]))
        parts.append(_EMOTION_INSTRUCTION.get(lang, _EMOTION_INSTRUCTION["ko"]))
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

        # 어미에 "요"를 덧붙이는 보정은 "입니다요"처럼 어색한 문장을 만들어 두지 않는다.
        # 말투는 성격 설정이 들어간 시스템 프롬프트로 정한다.
        if self.personality:
            personality = self.personality.lower()
            if "차분" in personality:
                styled = styled.replace("!", ".")
        return styled
