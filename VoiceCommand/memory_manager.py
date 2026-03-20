"""
기억 관리자 (단기 및 장기 기억 통합)
"""
import logging
import json
import re
from datetime import datetime
from user_context import get_context_manager
from conversation_history import add_conversation

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

    def _extract_info_from_response(self, response):
        """AI 응답에서 [FACT: ...], [BIO: ...], [PREF: ...] 태그 추출 및 저장"""
        try:
            # 사실 추출: [FACT: key=value]
            facts = re.findall(r'\[FACT:\s*([^=]+)=([^\]]+)\]', response)
            for key, value in facts:
                logging.info(f"사실 기억함: {key.strip()} = {value.strip()}")
                self.context_manager.record_fact(key.strip(), value.strip())

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
        """특수 태그(FACT, BIO 등)를 제거하여 사용자에게 보낼 메시지 정제"""
        cleaned = re.sub(r'\[(FACT|BIO|PREF|CMD):[^\]]+\]', '', response)
        return cleaned.strip()

# 싱글톤
_memory_manager = None

def get_memory_manager():
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager
