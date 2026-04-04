"""
기억 관리자 (단기 및 장기 기억 통합)
"""
import logging
import re
import threading
from datetime import datetime
from memory.user_context import get_context_manager
from memory.conversation_history import add_conversation
from memory.memory_index import get_memory_index
from memory.user_profile_engine import get_user_profile_engine

# 정규식 캐싱
_RE_FACT = re.compile(r'\[FACT:\s*([^=]+)=([^\]]+)\]')
_RE_BIO = re.compile(r'\[BIO:\s*([^=]+)=([^\]]+)\]')
_RE_PREF = re.compile(r'\[PREF:\s*([^=]+)=([^\]]+)\]')
_RE_TAGS = re.compile(r'\[(FACT|BIO|PREF|CMD):[^\]]+\]')
_RE_WHITESPACE = re.compile(r'\s+')

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
        timestamp = datetime.now().isoformat()
        try:
            add_conversation(user_msg, ai_response)
        except Exception as e:
            logging.warning("대화 저장 실패: %s", e)
        try:
            get_memory_index().index_conversation(user_msg, ai_response, timestamp)
        except Exception as e:
            logging.warning("대화 인덱싱 실패: %s", e)
        try:
            self._extract_info_from_response(ai_response)
        except Exception as e:
            logging.warning("응답 정보 추출 실패: %s", e)
        try:
            topics = self._extract_topics(user_msg, ai_response)
            if topics:
                self.context_manager.record_topics(topics)
        except Exception as e:
            logging.warning("대화 주제 추출 실패: %s", e)
        try:
            last_command = ""
            last_commands = self.context_manager.context.get("last_commands", [])
            if last_commands:
                last_command = last_commands[-1].get("command", "")
            get_user_profile_engine().update(user_msg, command_type=last_command, success=True)
        except Exception as e:
            logging.warning("프로파일 업데이트 실패: %s", e)

    def _is_persistent_fact(self, key: str) -> bool:
        """지속성 있는 사실인지 확인. 일시적 상태나 task 요청 관련 키는 False."""
        return not any(kw in key for kw in _EPHEMERAL_FACT_KEYS)

    def _extract_info_from_response(self, response):
        """AI 응답에서 [FACT: ...], [BIO: ...], [PREF: ...] 태그 추출 및 저장"""
        try:
            # 사실 추출: [FACT: key=value] — 지속성 있는 사실만 저장
            for key, value in _RE_FACT.findall(response):
                k = key.strip()
                if self._is_persistent_fact(k):
                    logging.info("사실 기억함: %s = %s", k, value.strip())
                    self.context_manager.record_fact(k, value.strip(), source="assistant_tag", confidence=0.75)
                    get_memory_index().index_fact(k, value.strip(), 0.75)
                else:
                    logging.info("[MemoryManager] 일시적 FACT 무시 (비저장): %s=%s", k, value.strip())

            # 기본 정보 추출: [BIO: field=value]
            for field, value in _RE_BIO.findall(response):
                logging.info("바이오 업데이트: %s = %s", field.strip(), value.strip())
                self.context_manager.update_bio(field.strip(), value.strip())

            # 선호도 추출: [PREF: category=value]
            for cat, val in _RE_PREF.findall(response):
                logging.info("선호도 저장: %s = %s", cat.strip(), val.strip())
                self.context_manager.record_preference(cat.strip(), val.strip())
        except Exception as e:
            logging.warning("응답 태그 파싱 실패: %s", e)

    def get_full_context_prompt(self):
        """LLM에 전달할 전체 컨텍스트 요약 생성"""
        parts = []
        try:
            profile = get_user_profile_engine().get_prompt_injection()
            if profile:
                parts.append(profile)
        except Exception as e:
            logging.error(f"프로파일 요약 실패: {e}")
        facts_prompt = self.get_top_facts_prompt()
        if facts_prompt:
            parts.append(facts_prompt)
        try:
            summary = self.context_manager.get_context_summary()
            if summary:
                parts.append(summary)
        except Exception as e:
            logging.error(f"컨텍스트 요약 실패: {e}")
        now = datetime.now()
        time_info = f"현재 시간: {now.strftime('%Y-%m-%d %H:%M:%S')}"
        parts.insert(0, time_info)
        return "\n\n".join(part for part in parts if part)

    def get_top_facts_prompt(self, n: int = 5) -> str:
        top_facts = sorted(
            self.context_manager.context.get("facts", {}).items(),
            key=lambda item: item[1].get("confidence", 0),
            reverse=True,
        )[:n]
        if not top_facts:
            return ""
        lines = ["[기억하고 있는 사실]"]
        for key, fact in top_facts:
            value = fact.get("value", "")
            if value:
                lines.append(f"- {key}: {value}")
        return "\n".join(lines)

    def clean_response(self, response):
        """특수 태그만 제거하고 텍스트 자체는 보존."""
        cleaned = _RE_TAGS.sub('', response or "")
        cleaned = _RE_WHITESPACE.sub(' ', cleaned).strip()
        return cleaned

    def _extract_topics(self, user_msg: str, ai_response: str):
        topics = self.context_manager.extract_topics(user_msg, ai_response)
        return [topic for topic in topics if topic not in _TOPIC_BLOCKLIST]

# 싱글톤
_memory_manager = None
_memory_manager_lock = threading.Lock()


def get_memory_manager():
    global _memory_manager
    if _memory_manager is None:
        with _memory_manager_lock:
            if _memory_manager is None:
                _memory_manager = MemoryManager()
    return _memory_manager
