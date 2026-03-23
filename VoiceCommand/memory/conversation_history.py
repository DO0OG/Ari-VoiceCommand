"""대화 기록 관리"""
import json
import logging
from datetime import datetime
from collections import deque


class ConversationHistory:
    """대화 기록 저장/로드"""

    def __init__(self, max_size=50):
        self.history = deque(maxlen=max_size)
        from resource_manager import ResourceManager
        self.file_path = ResourceManager.get_writable_path("conversation_history.json")
        self.load()

    def add(self, user_msg, ai_response):
        """대화 추가"""
        self.history.append({
            "timestamp": datetime.now().isoformat(),
            "user": user_msg,
            "ai": ai_response
        })
        self.save()

    def save(self):
        """파일 저장"""
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(list(self.history), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"대화 기록 저장 실패: {e}")

    def load(self):
        """파일 로드"""
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.history = deque(data, maxlen=self.history.maxlen)
            logging.info(f"대화 기록 로드: {len(self.history)}개")
        except FileNotFoundError:
            logging.info("새 대화 기록 시작")
        except Exception as e:
            logging.error(f"대화 기록 로드 실패: {e}")

    def get_recent(self, n=5):
        """최근 N개 대화 반환"""
        return list(self.history)[-n:]


# 전역 인스턴스
_history = ConversationHistory()


def add_conversation(user_msg, ai_response):
    """대화 추가 (전역 함수)"""
    _history.add(user_msg, ai_response)
