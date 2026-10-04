"""
기억 관리자 (단기 및 장기 기억 통합)
"""
import heapq
import json
import logging
import math
import re
import threading
import unicodedata
from datetime import datetime
from typing import Callable, Optional
from commands.memory_command import is_memory_command
from core.config_manager import ConfigManager
from i18n.translator import _
from memory.fact_suggestions import get_fact_suggestion_store
from memory.sensitive_patterns import is_sensitive_memory_text
from memory.user_context import get_context_manager
from memory.conversation_history import add_conversation, get_conversation_history
from memory.memory_index import get_memory_index
from memory.user_profile_engine import get_user_profile_engine
from memory.sensitive_patterns import is_sensitive_memory_text

# 정규식 캐싱
_RE_FACT = re.compile(r'\[FACT:\s*([^=]+)=([^\]]+)\]')
_RE_BIO = re.compile(r'\[BIO:\s*([^=]+)=([^\]]+)\]')
_RE_PREF = re.compile(r'\[PREF:\s*([^=]+)=([^\]]+)\]')
_RE_TAGS = re.compile(r'\[(FACT|BIO|PREF|CMD):[^\]]+\]')
_RE_WHITESPACE = re.compile(r'\s+')
_MIN_EXTRACTION_LENGTH = 12
_RE_FACT_EXTRACTION_TRIGGER = re.compile(
    r"\b(?:i(?:['’]m| am)?|my|mine)\b|나는|내가|저는|제가|저의|나의|내 취미|제 취미|"
    r"私(?:は|が|の|も)|僕(?:は|が|の|も)|俺(?:は|が|の)|自分(?:は|が|の)|"
    r"\b(?:like|love|prefer|dislike|hate|want|plan|planning|going to|would like)\b|"
    r"좋아하|싫어하|선호|취향|원하|하고 싶|하고싶|계획|예정|앞으로|"
    r"好き|嫌い|好む|希望|予定|計画|したい|つもり",
    re.IGNORECASE,
)
_BIO_FIELDS = {"name", "location", "interests", "memos"}

# FACT로 저장하면 안 되는 일시적/task-specific 키워드
_EPHEMERAL_FACT_KEYS = {
    "ko": {
        "오늘", "현재", "지금", "요청", "작업", "귀가", "출근", "퇴근",
        "기분", "시간", "위치", "장소", "날씨", "상태", "결과", "내용",
        "실행", "완료", "목표", "명령", "수행", "처리",
    },
    "en": {
        "today", "current", "now", "request", "task", "commute", "mood",
        "time", "location", "place", "weather", "status", "result", "content",
        "run", "complete", "goal", "command", "execution", "process",
    },
    "ja": {
        "今日", "現在", "今", "依頼", "作業", "気分", "時間", "場所", "天気",
        "状態", "結果", "内容", "実行", "完了", "目標", "命令", "処理",
    },
}
_TOPIC_BLOCKLIST = {
    "있어", "그냥", "정도", "이번엔", "저거", "이거", "그거", "응답", "대화",
}


class MemoryManager:
    """단기(대화 기록) 및 장기(사용자 패턴/사실) 기억 통합 관리"""

    def __init__(self):
        self.context_manager = get_context_manager()
        logging.info("MemoryManager 초기화 완료")

    def process_interaction(
        self,
        user_msg: str,
        ai_response: str,
        contains_tool_result: bool = False,
        memory_extractor: Optional[Callable[[str], str]] = None,
        *,
        extract_response_info: bool = True,
        skill_used: str = "",
        data_source: str = "",
        lang: str = "",
    ) -> None:
        """대화 상호작용 기록 및 정보 추출"""
        timestamp = datetime.now().isoformat()
        index_conversation = True
        try:
            index_conversation = not get_conversation_history()._is_internal_entry(
                user_msg, ai_response
            )
        except Exception as e:
            logging.warning("대화 기록 조회 실패: %s", e)
        entry = None
        try:
            entry = add_conversation(
                user_msg,
                ai_response,
                skill_used=skill_used,
                data_source=data_source,
                lang=lang,
            )
        except Exception as e:
            logging.warning("대화 저장 실패: %s", e)
        try:
            if index_conversation and entry is not None:
                timestamp = str(entry.get("timestamp", timestamp) or timestamp)
                get_memory_index().index_conversation(user_msg, ai_response, timestamp)
        except Exception as e:
            logging.warning("대화 인덱싱 실패: %s", e)
        if extract_response_info:
            try:
                self._extract_info_from_response(
                    ai_response,
                    user_message=user_msg,
                    contains_tool_result=contains_tool_result,
                )
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
        try:
            self.context_manager.record_interaction(user_msg)
        except (AttributeError, OSError, TypeError, ValueError) as e:
            logging.warning("상황 정보 기록 실패: %s", e)
        self.start_fact_suggestion_extraction(user_msg, memory_extractor)

    def extract_response_tags(self, response: str, user_message: str = "") -> None:
        """응답의 기억 태그만 추출한다."""
        self._extract_info_from_response(response, user_message=user_message)

    def start_fact_suggestion_extraction(
        self,
        user_message: str,
        memory_extractor: Optional[Callable[[str], str]],
    ) -> None:
        message = str(user_message or "").strip()
        if not memory_extractor:
            return
        if is_memory_command(message):
            return
        if len(message) < _MIN_EXTRACTION_LENGTH:
            return
        if not _RE_FACT_EXTRACTION_TRIGGER.search(message):
            return
        if is_sensitive_memory_text(message):
            return
        try:
            if not ConfigManager.get("fact_extraction_suggestions_enabled", True):
                return
        except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
            logging.warning("기억 제안 설정을 읽지 못했습니다: %s", exc)
            return

        worker = threading.Thread(
            target=self._extract_fact_suggestions,
            args=(message, memory_extractor),
            name="fact-suggestion-extractor",
            daemon=True,
        )
        try:
            worker.start()
        except RuntimeError as exc:
            logging.warning("기억 제안 작업을 시작하지 못했습니다: %s", exc)

    def _extract_fact_suggestions(
        self,
        user_message: str,
        memory_extractor: Callable[[str], str],
    ) -> None:
        try:
            raw_result = memory_extractor(user_message)
        except Exception as exc:
            logging.warning("기억 제안 추출 호출 실패: %s", type(exc).__name__)
            return
        try:
            payload = json.loads(raw_result)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logging.warning("기억 제안 JSON을 읽지 못했습니다: %s", exc)
            return
        if not isinstance(payload, dict):
            return

        suggestions = []
        facts = payload.get("facts", [])
        if isinstance(facts, list):
            for item in facts:
                candidate = self._fact_suggestion(item, user_message)
                if candidate:
                    suggestions.append(candidate)
        preferences = payload.get("preferences", [])
        if isinstance(preferences, list):
            for item in preferences:
                candidate = self._preference_suggestion(item, user_message)
                if candidate:
                    suggestions.append(candidate)
        bio_items = payload.get("bio", [])
        if isinstance(bio_items, list):
            for item in bio_items:
                self._queue_bio_suggestion(item, user_message)
        if suggestions:
            try:
                get_fact_suggestion_store().add_suggestions(suggestions)
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                logging.warning("기억 제안을 저장하지 못했습니다: %s", exc)

    @staticmethod
    def _valid_evidence(item: object, user_message: str) -> str:
        if not isinstance(item, dict):
            return ""
        evidence = item.get("evidence")
        if not isinstance(evidence, str):
            return ""
        evidence = evidence.strip()
        if not evidence or len(evidence) > 60 or evidence not in user_message:
            return ""
        return evidence

    def _fact_suggestion(self, item: object, user_message: str) -> dict | None:
        evidence = self._valid_evidence(item, user_message)
        if not evidence:
            return None
        key = item.get("key") if isinstance(item, dict) else None
        value = item.get("value") if isinstance(item, dict) else None
        kind = item.get("kind") if isinstance(item, dict) else None
        if not isinstance(key, str) or not isinstance(value, str):
            return None
        key = key.strip()
        value = value.strip()
        if (
            not key
            or not value
            or not isinstance(kind, str)
            or kind not in {"stable", "state", "plan"}
        ):
            return None
        if is_sensitive_memory_text(f"{key} {value} {evidence}"):
            return None
        try:
            confidence = float(item.get("confidence"))
        except (TypeError, ValueError, OverflowError):
            return None
        if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
            return None
        return {
            "type": "fact",
            "key": key,
            "value": value,
            "kind": kind,
            "evidence": evidence,
            "confidence": confidence,
        }

    def _preference_suggestion(self, item: object, user_message: str) -> dict | None:
        evidence = self._valid_evidence(item, user_message)
        if not evidence:
            return None
        category = item.get("category") if isinstance(item, dict) else None
        value = item.get("value") if isinstance(item, dict) else None
        if not isinstance(category, str) or not isinstance(value, str):
            return None
        category = category.strip()
        value = value.strip()
        if not category or not value:
            return None
        if is_sensitive_memory_text(f"{category} {value} {evidence}"):
            return None
        return {
            "type": "preference",
            "key": category,
            "value": value,
            "kind": "",
            "evidence": evidence,
            "confidence": 0.8,
        }

    def _queue_bio_suggestion(self, item: object, user_message: str) -> None:
        evidence = self._valid_evidence(item, user_message)
        if not evidence or not isinstance(item, dict):
            return
        field = item.get("field")
        value = item.get("value")
        if not isinstance(field, str) or not isinstance(value, str):
            return
        field = field.strip()
        value = value.strip()
        if field not in _BIO_FIELDS or not value:
            return
        if is_sensitive_memory_text(f"{field} {value} {evidence}"):
            return
        self.context_manager.request_bio_update(field, value, user_message="")

    def approve_fact_suggestion(
        self,
        suggestion_id: str,
        context_manager=None,
    ) -> bool:
        """승인된 기억 제안을 기존 저장소와 검색 색인에 반영한다."""
        store = get_fact_suggestion_store()
        suggestion = store.get_suggestion(suggestion_id)
        if not suggestion:
            return False
        context = context_manager or self.context_manager
        if suggestion["type"] == "fact":
            existing = context.context.get("facts", {}).get(suggestion["key"])
            already_saved = (
                isinstance(existing, dict)
                and existing.get("value") == suggestion["value"]
                and existing.get("source") == "user_utterance"
            )
            if not already_saved:
                ttl_days = {"state": 1, "plan": 30, "stable": 180}[
                    suggestion["kind"]
                ]
                if not context.record_fact(
                    suggestion["key"],
                    suggestion["value"],
                    source="user_utterance",
                    confidence=suggestion["confidence"],
                    ttl_days=ttl_days,
                    force=True,
                ):
                    return False
        else:
            preferences = context.context.setdefault("preferences", {})
            values = preferences.setdefault(suggestion["key"], {})
            if not values.get(suggestion["value"]):
                if not context.record_preference(suggestion["key"], suggestion["value"]):
                    return False
        return store.resolve(suggestion_id, approved=True) is not None

    def _is_persistent_fact(self, key: str) -> bool:
        """지속성 있는 사실인지 확인. 일시적 상태나 task 요청 관련 키는 False."""
        normalized = unicodedata.normalize("NFKC", key).strip().casefold()
        normalized = _RE_WHITESPACE.sub(" ", normalized)
        return not any(normalized in keys for keys in _EPHEMERAL_FACT_KEYS.values())

    def _extract_info_from_response(
        self,
        response: str,
        user_message: str = "",
        contains_tool_result: bool = False,
    ) -> None:
        """AI 응답에서 [FACT: ...], [BIO: ...], [PREF: ...] 태그 추출 및 저장"""
        if contains_tool_result:
            logging.info("도구 결과가 포함된 응답의 기억 태그를 건너뜁니다.")
            return
        try:
            # 사실 추출: [FACT: key=value] — 지속성 있는 사실만 저장
            for key, value in _RE_FACT.findall(response):
                k = key.strip()
                if self._is_persistent_fact(k):
                    logging.info("사실 기억함: %s = %s", k, value.strip())
                    self.context_manager.record_fact(
                        k, value.strip(), source="assistant_tag", confidence=0.75
                    )
                else:
                    logging.info("[MemoryManager] 일시적 FACT 무시 (비저장): %s=%s", k, value.strip())

            # 기본 정보 추출: [BIO: field=value]
            for field, value in _RE_BIO.findall(response):
                self.context_manager.request_bio_update(
                    field.strip(), value.strip(), user_message=user_message
                )

            # 선호도 추출: [PREF: category=value]
            for cat, val in _RE_PREF.findall(response):
                logging.info("선호도 저장: %s = %s", cat.strip(), val.strip())
                self.context_manager.record_preference(cat.strip(), val.strip())
        except Exception as e:
            logging.warning("응답 태그 파싱 실패: %s", e)

    def get_full_context_prompt(
        self,
        include_profile: bool = True,
        include_facts: bool = True,
        include_time: bool = True,
    ) -> str:
        """LLM에 전달할 전체 컨텍스트 요약 생성"""
        parts = []
        if include_profile:
            try:
                profile = get_user_profile_engine().get_prompt_injection()
                if profile:
                    parts.append(profile)
            except Exception as e:
                logging.error("프로파일 요약 실패: %s", e)
        if include_facts:
            facts_prompt = self.get_top_facts_prompt()
            if facts_prompt:
                parts.append(facts_prompt)
        try:
            summary = self.context_manager.get_context_summary()
            if summary:
                parts.append(summary)
        except Exception as e:
            logging.error("컨텍스트 요약 실패: %s", e)
        if include_time:
            parts.insert(0, self.get_current_time_prompt())
        return "\n\n".join(part for part in parts if part)

    def get_current_time_prompt(self) -> str:
        """LLM에 전달할 현재 시각을 분 단위로 반환한다."""
        now = datetime.now()
        return f"현재 시간: {now.strftime('%Y-%m-%d %H:%M')}"

    def get_memory_prompt(self) -> str:
        """레거시 호출부 호환용 컨텍스트 프롬프트 반환."""
        return self.get_full_context_prompt()

    def get_top_facts_prompt(self, n: int = 5, query: str = "") -> str:
        facts = {
            key: fact
            for key, fact in self.context_manager.context.get("facts", {}).items()
            if isinstance(fact, dict)
            and not is_sensitive_memory_text(
                f"{key}: {fact.get('value', '')}"
            )
        }
        if not facts:
            return ""

        top_facts = []
        if query.strip():
            pinned_candidates = heapq.nlargest(
                len(facts),
                (
                    item for item in facts.items()
                    if item[1].get("pinned")
                    or item[1].get("source") in {"user", "user_request"}
                ),
                key=lambda item: item[1].get("confidence", 0),
            )
            pinned = []
            seen_values = set()
            for key, fact in pinned_candidates:
                value_key = " ".join(
                    str(fact.get("value", "") or "").casefold().split()
                )
                if value_key and value_key not in seen_values:
                    pinned.append((key, fact))
                    seen_values.add(value_key)
                    if len(pinned) == 3:
                        break
            pinned_keys = {key for key, _fact in pinned}
            indexed_facts = get_memory_index().search(
                query, limit=30, kind="fact"
            )
            candidates = []
            seen_keys = set()
            for result in indexed_facts:
                for key, fact in facts.items():
                    value = str(fact.get("value", "") or "")
                    value_key = " ".join(value.casefold().split())
                    prefix = f"{key}: {value} (confidence="
                    if (
                        key not in pinned_keys
                        and key not in seen_keys
                        and value_key not in seen_values
                        and value
                        and result.content.startswith(prefix)
                    ):
                        candidates.append((key, fact))
                        seen_keys.add(key)
                        seen_values.add(value_key)
                        break
            ranks = {key: rank for rank, (key, _fact) in enumerate(candidates)}
            semantic_ranks = {}
            try:
                from agent.embedder import get_embedder

                embedder = get_embedder()
                if embedder.status == "ready" and candidates:
                    query_vector = embedder.embed(query)
                    if query_vector is not None:
                        similarities = []
                        for key, fact in candidates:
                            text = f"{key}: {fact.get('value', '')}"
                            vector = embedder.embed(text)
                            if vector is not None:
                                score = embedder.cosine_similarity(query_vector, vector)
                                similarities.append((score, key))
                        semantic_ranks = {
                            key: rank
                            for rank, (_score, key) in enumerate(
                                sorted(similarities, reverse=True)
                            )
                        }
            except (AttributeError, ImportError, RuntimeError, TypeError, ValueError) as exc:
                logging.debug("사실 임베딩 검색 생략: %s", exc)
            candidates.sort(
                key=lambda item: (
                    (
                        1 / (60 + ranks[item[0]])
                        + 1 / (60 + semantic_ranks[item[0]])
                        if item[0] in semantic_ranks
                        else 1 / (60 + ranks[item[0]])
                    ),
                    -semantic_ranks.get(item[0], ranks[item[0]]),
                ),
                reverse=True,
            )
            top_facts = pinned + candidates[:min(3, max(0, n))]
        else:
            top_facts = heapq.nlargest(
                n,
                facts.items(),
                key=lambda item: item[1].get("confidence", 0),
            )
        lines = [_('[기억하고 있는 사실]')]
        for key, fact in top_facts:
            value = fact.get("value", "")
            if value:
                lines.append(f"- {value}" if key == value else f"- {key}: {value}")
        return "\n".join(lines)

    def clean_response(self, response: str) -> str:
        """특수 태그만 제거하고 텍스트 자체는 보존."""
        cleaned = _RE_TAGS.sub('', response or "")
        cleaned = _RE_WHITESPACE.sub(' ', cleaned).strip()
        return cleaned

    def _extract_topics(self, user_msg: str, ai_response: str) -> list[str]:
        topics = self.context_manager.extract_topics(user_msg, ai_response)
        return [topic for topic in topics if topic not in _TOPIC_BLOCKLIST]

# 싱글톤
_memory_manager: Optional[MemoryManager] = None
_memory_manager_lock = threading.Lock()


def get_memory_manager() -> MemoryManager:
    global _memory_manager
    if _memory_manager is None:
        with _memory_manager_lock:
            if _memory_manager is None:
                _memory_manager = MemoryManager()
    return _memory_manager
