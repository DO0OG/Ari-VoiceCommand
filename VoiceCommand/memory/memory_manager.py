"""
기억 관리자 (단기 및 장기 기억 통합)
"""
import logging
import re
from datetime import datetime
from memory.user_context import get_context_manager
from memory.conversation_history import add_conversation

# FACT로 저장하면 안 되는 일시적/task-specific 키워드
_EPHEMERAL_FACT_KEYS = {
    '오늘', '현재', '지금', '요청', '작업', '귀가', '출근', '퇴근',
    '기분', '시간', '위치', '장소', '날씨', '상태', '결과', '내용',
    '실행', '완료', '목표', '명령', '수행', '처리',
}
_TOPIC_BLOCKLIST = {
    "있어", "그냥", "정도", "이번엔", "저거", "이거", "그거", "응답", "대화",
}


class MemoryManager:
    """단기(대화 기록) 및 장기(사용자 패턴/사실) 기억 통합 관리"""

    def __init__(self):
        self.context_manager = get_context_manager()
        logging.info("MemoryManager 초기화 완료")

    def process_interaction(self, user_msg, ai_response):
        """대화 상호작용 기록 및 정보 추출"""
        try:
            add_conversation(user_msg, ai_response)
        except Exception as e:
            logging.error(f"대화 저장 실패: {e}")
        try:
            self._extract_info_from_response(ai_response)
        except Exception as e:
            logging.error(f"응답 정보 추출 실패: {e}")
        try:
            topics = self._extract_topics(user_msg, ai_response)
            if topics:
                self.context_manager.record_topics(topics)
        except Exception as e:
            logging.error(f"대화 주제 추출 실패: {e}")

    def _is_persistent_fact(self, key: str) -> bool:
        """지속성 있는 사실인지 확인. 일시적 상태나 task 요청 관련 키는 False."""
        return not any(kw in key for kw in _EPHEMERAL_FACT_KEYS)

    def _extract_info_from_response(self, response):
        """AI 응답에서 [FACT: ...], [BIO: ...], [PREF: ...] 태그 추출 및 저장"""
        try:
            # 사실 추출: [FACT: key=value] — 지속성 있는 사실만 저장
            facts = re.findall(r'\[FACT:\s*([^=]+)=([^\]]+)\]', response)
            for key, value in facts:
                k = key.strip()
                if self._is_persistent_fact(k):
                    logging.info(f"사실 기억함: {k} = {value.strip()}")
                    self.context_manager.record_fact(k, value.strip(), source="assistant_tag", confidence=0.75)
                else:
                    logging.info(f"[MemoryManager] 일시적 FACT 무시 (비저장): {k}={value.strip()}")

            # 기본 정보 추출: [BIO: field=value]
            bios = re.findall(r'\[BIO:\s*([^=]+)=([^\]]+)\]', response)
            for field, value in bios:
                logging.info(f"바이오 업데이트: {field.strip()} = {value.strip()}")
                self.context_manager.update_bio(field.strip(), value.strip())

            # 선호도 추출: [PREF: category=value]
            prefs = re.findall(r'\[PREF:\s*([^=]+)=([^\]]+)\]', response)
            for cat, val in prefs:
                logging.info(f"선호도 저장: {cat.strip()} = {val.strip()}")
                self.context_manager.record_preference(cat.strip(), val.strip())
        except Exception as e:
            logging.error(f"응답 태그 파싱 실패: {e}")

    def get_full_context_prompt(self):
        """LLM에 전달할 전체 컨텍스트 요약 생성"""
        try:
            summary = self.context_manager.get_context_summary()
        except Exception as e:
            logging.error(f"컨텍스트 요약 실패: {e}")
            summary = ""
        now = datetime.now()
        time_info = f"현재 시간: {now.strftime('%Y-%m-%d %H:%M:%S')}"
        return f"{time_info}\n\n{summary}"

    def clean_response(self, response):
        """특수 태그(FACT, BIO 등)를 제거하여 사용자에게 보낼 메시지 정제.
        일본어·중국어 한자 등 비한국어 문자도 제거합니다."""
        cleaned = re.sub(r'\[(FACT|BIO|PREF|CMD):[^\]]+\]', '', response)
        # 일본어 히라가나·카타카나, CJK 한자(한국 한자와 구분) 제거
        cleaned = re.sub(r'[\u3040-\u30FF\u4E00-\u9FFF\uF900-\uFAFF]', '', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        return cleaned

    def _extract_topics(self, user_msg: str, ai_response: str):
        topics = self.context_manager.extract_topics(user_msg, ai_response)
        return [topic for topic in topics if topic not in _TOPIC_BLOCKLIST]

# 싱글톤
_memory_manager = None

def get_memory_manager():
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager
