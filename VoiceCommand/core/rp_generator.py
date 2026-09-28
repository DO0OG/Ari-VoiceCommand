"""
RP 텍스트 생성기
"""
import logging
import re

from core.emotions import get_emotion_instruction


class RPGenerator:
    def __init__(self):
        self.personality = ""
        self.personality_examples_en = ""
        self.personality_examples_ja = ""
        self.scenario = ""
        self.system_prompt = ""
        self.history_instruction = ""
        self.response_verbosity = "concise"

    def set_config(self, personality="", scenario="", system_prompt="", history_instruction="",
                   response_verbosity="concise", personality_examples_en="",
                   personality_examples_ja=""):
        """RP 설정"""
        self.personality = personality
        self.personality_examples_en = personality_examples_en
        self.personality_examples_ja = personality_examples_ja
        self.scenario = scenario
        self.system_prompt = system_prompt
        self.history_instruction = history_instruction
        self.response_verbosity = response_verbosity or "concise"
        logging.info("RP 설정 업데이트됨")

    def build_system_prompt(self, base_prompt: str) -> str:
        """캐릭터 설정을 시스템 프롬프트에 녹여서 반환."""
        from i18n.translator import _

        try:
            from i18n.translator import get_language
            lang = get_language()
        except Exception:
            lang = "ko"
        _BASE_PROMPT = {
            "ko": "당신은 AI 어시스턴트 아리입니다.",
            "en": "You are Ari, an AI assistant.",
            "ja": "あなたはAIアシスタントのAriです。",
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
        prompt = base_prompt.strip() if base_prompt else _BASE_PROMPT.get(lang, _BASE_PROMPT["ko"])
        # 기존 설정에 저장된 감정 지시도 공통 지시로 대체한다.
        prompt = re.sub(
            r"(?m)^.*모든 답변 첫머리에 감정 태그를 붙이세요:[^\r\n]*\r?\n?",
            "",
            prompt,
        )
        parts = [prompt]
        if self.personality:
            parts.append(f"{_('[캐릭터 성격]')}\n{self.personality.strip()}")
        examples = {
            "en": self.personality_examples_en,
            "ja": self.personality_examples_ja,
        }.get(lang, "")
        if isinstance(examples, str) and examples.strip():
            parts.append(f"{_('[예시 대사]')}\n{examples.strip()}")
        if self.scenario:
            parts.append(f"{_('[현재 상황]')}\n{self.scenario.strip()}")
        if self.history_instruction:
            parts.append(f"{_('[대화 방식]')}\n{self.history_instruction.strip()}")
        verbosity_map = _VERBOSITY_INSTRUCTION.get(lang, _VERBOSITY_INSTRUCTION["ko"])
        parts.append(verbosity_map.get(self.response_verbosity, verbosity_map["concise"]))
        parts.append(get_emotion_instruction(lang))
        parts.append(_(
            "상황 블록을 참고해 말투를 조절하되, 내용을 그대로 언급하지 마세요."
        ))
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
