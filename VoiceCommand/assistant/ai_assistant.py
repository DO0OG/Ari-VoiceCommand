"""
간단한 AI 어시스턴트 (TensorFlow 제거)
"""
import logging
from secrets import choice


class SimpleAIAssistant:
    """간단한 규칙 기반 AI 어시스턴트"""

    def __init__(self):
        self.responses = {
            "인사": ["안녕하세요!", "반갑습니다!", "네, 무엇을 도와드릴까요?"],
            "감사": ["천만에요!", "별말씀을요!", "도움이 되었다니 기쁩니다!"],
            "미안": ["괜찮습니다!", "걱정 마세요!", "이해합니다!"],
            "기본": ["죄송합니다. 이해하지 못했습니다.", "다시 한번 말씀해 주시겠어요?", "잘 모르겠습니다."]
        }
        logging.info("Simple AI Assistant 초기화 완료")

    def process_query(self, query):
        """쿼리 처리"""
        query = query.lower()

        # 간단한 패턴 매칭
        if any(word in query for word in ["안녕", "하이", "헬로"]):
            response = choice(self.responses["인사"])
        elif any(word in query for word in ["고마", "감사"]):
            response = choice(self.responses["감사"])
        elif any(word in query for word in ["미안", "죄송"]):
            response = choice(self.responses["미안"])
        else:
            response = choice(self.responses["기본"])

        # AdvancedAIAssistant와 호환성을 위해 튜플 반환
        return response, [], "neutral"

    def learn_new_response(self, query, response):
        """응답 학습 (간단 버전은 로그만)"""
        logging.info(f"학습 요청 - Query: {query}, Response: {response}")

    def update_q_table(self, state, action, reward, next_state):
        """Q-learning (간단 버전은 로그만)"""
        logging.debug(f"Q-table 업데이트: {action}, reward={reward}")


def get_ai_assistant():
    """AI 어시스턴트 싱글톤"""
    try:
        from assistant.groq_assistant import get_groq_assistant
        return get_groq_assistant()
    except Exception as e:
        logging.warning(f"Groq 초기화 실패, Simple AI 사용: {e}")
        return SimpleAIAssistant()
