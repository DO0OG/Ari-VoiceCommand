"""
사용자 컨텍스트 학습 및 관리 — Phase 3.1 고도화
사실 충돌 해소, 신뢰도 학습, 지능형 메모리 정리를 지원합니다.
"""
import json
import os
import logging
import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)
_context_manager: Optional["UserContextManager"] = None


_MAX_FACTS = 150
_MAX_COMMANDS = 50
_MAX_TIME_PATTERNS_PER_SLOT = 20
_MAX_COMMAND_FREQ = 100
_MAX_SEQUENCE_ROOTS = 100
_MAX_SEQUENCE_EDGES = 20
_MAX_BIO_LIST_ITEMS = 30
_MAX_TOPIC_COUNT = 50
_SUMMARY_FACT_LIMIT = 10
_SUMMARY_TOPIC_LIMIT = 5
_DEFAULT_FACT_TTL_DAYS = 180
_MAX_FACT_HISTORY = 8

_KOREAN_STOPWORDS = {
    "그리고", "하지만", "그러나", "오늘", "지금", "이번", "저번", "관련", "대한",
    "해주세요", "해줘", "정리", "요약", "저장", "실행", "작업", "요청", "결과",
    "사용자", "아리", "파일", "폴더", "문서", "정보", "내용",
}


class UserContextManager:
    """사용자 행동 패턴 및 컨텍스트 관리"""

    def __init__(self, context_file="user_context.json"):
        try:
            from core.resource_manager import ResourceManager
            self.context_file = ResourceManager.get_writable_path(context_file)
        except Exception:
            self.context_file = context_file
        self.context = self.load_context()

    def load_context(self):
        """컨텍스트 로드"""
        if os.path.exists(self.context_file):
            try:
                with open(self.context_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                return self._normalize_context(loaded)
            except Exception as e:
                logging.exception(f"컨텍스트 로드 실패: {self.context_file} ({e})")

        return self._default_context()

    def _default_context(self):
        return self._normalize_context({
            "user_bio": {"name": "사용자", "location": "", "interests": [], "memos": []},
            "facts": {},
            "fact_history": {},
            "command_frequency": {},
            "command_sequences": {},
            "time_patterns": {},
            "preferences": {},
            "last_commands": [],
            "conversation_topics": {}
        })

    def _normalize_context(self, data):
        context = self._default_context_structure()
        if isinstance(data, dict):
            context.update(data)

        bio = context.get("user_bio", {})
        context["user_bio"] = {
            "name": bio.get("name", "사용자"),
            "location": bio.get("location", ""),
            "interests": self._dedupe_recent(bio.get("interests", []), _MAX_BIO_LIST_ITEMS),
            "memos": self._dedupe_recent(bio.get("memos", []), _MAX_BIO_LIST_ITEMS),
        }

        facts = {}
        for key, raw in (context.get("facts") or {}).items():
            normalized = self._normalize_fact_entry(raw)
            if normalized: facts[key] = normalized
        context["facts"] = self._limit_facts(facts)
        context["fact_history"] = self._normalize_fact_history(context.get("fact_history", {}))

        context["command_frequency"] = self._limit_frequency_map(context.get("command_frequency", {}))
        context["command_sequences"] = self._limit_sequences(context.get("command_sequences", {}))
        context["conversation_topics"] = self._limit_frequency_map(context.get("conversation_topics", {}), max_items=_MAX_TOPIC_COUNT)
        return context

    def _default_context_structure(self):
        return {
            "user_bio": {"name": "사용자", "location": "", "interests": [], "memos": []},
            "facts": {}, "fact_history": {}, "command_frequency": {}, "command_sequences": {},
            "time_patterns": {}, "preferences": {}, "last_commands": [], "conversation_topics": {},
        }

    def save_context(self):
        try:
            with open(self.context_file, 'w', encoding='utf-8') as f:
                json.dump(self.context, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"컨텍스트 저장 실패: {e}")

    # ── 지능형 사실 관리 (Phase 3.1) ──────────────────────────────────────────

    def record_fact(self, key: str, value: str, source: str = "assistant", confidence: float = 0.7, ttl_days: int = _DEFAULT_FACT_TTL_DAYS):
        """사용자에 대한 사실 기록 및 충돌 해소."""
        from memory.trust_engine import compute_reinforcement, compute_conflict_update, SOURCE_WEIGHTS, DEFAULT_SOURCE_WEIGHT

        facts = self.context["facts"]
        history_bucket = self.context.setdefault("fact_history", {}).setdefault(key, [])
        now = datetime.now()
        existing = facts.get(key)

        if existing:
            ex_value = existing.get("value", "")
            ex_confidence = float(existing.get("confidence", 0.7))
            ex_source = existing.get("source", "assistant")
            ex_reinforce = int(existing.get("reinforcement_count", 0))
            ex_conflict = int(existing.get("conflict_count", 0))

            if ex_value == value:
                result = compute_reinforcement(ex_confidence, source, ex_reinforce)
                existing["confidence"] = round(result.new_confidence, 2)
                existing["reinforcement_count"] = ex_reinforce + 1
                existing["access_count"] = int(existing.get("access_count", 0)) + 1
            else:
                result = compute_conflict_update(ex_confidence, confidence, ex_source, source, ex_conflict)
                if result.action == "conflict_replace":
                    existing["value"] = value
                    existing["source"] = source
                existing["confidence"] = round(result.new_confidence, 2)
                existing["conflict_count"] = ex_conflict + 1
                existing["last_conflict_at"] = now.isoformat()
                conflict_values = list(existing.get("conflict_values", []))
                conflict_values.append(ex_value)
                existing["conflict_values"] = conflict_values[-5:]

            existing["updated_at"] = now.isoformat()
            existing["expires_at"] = (now + timedelta(days=ttl_days)).isoformat() if ttl_days else None
            source_history = list(existing.get("source_history", []))
            source_history.append(source)
            existing["source_history"] = source_history[-5:]
        else:
            sw = SOURCE_WEIGHTS.get(source, DEFAULT_SOURCE_WEIGHT)
            initial_confidence = min(float(confidence) * sw + 0.1, 1.0)
            facts[key] = {
                "value": value,
                "updated_at": now.isoformat(),
                "source": source,
                "confidence": round(initial_confidence, 2),
                "expires_at": (now + timedelta(days=ttl_days)).isoformat() if ttl_days else None,
                "conflict_count": 0,
                "reinforcement_count": 0,
                "access_count": 0,
                "source_history": [source],
                "conflict_values": [],
                "last_conflict_at": "",
            }

        history_bucket.append({
            "value": value,
            "source": source,
            "confidence": round(float(facts[key]["confidence"]), 2),
            "recorded_at": now.isoformat(),
            "conflicted_with": existing.get("value", "") if existing and existing.get("value") != value else "",
        })
        self.context["fact_history"][key] = history_bucket[-_MAX_FACT_HISTORY:]
        self.save_context()

    def update_bio(self, field, value):
        """기본 정보 업데이트 (이름, 관심사 등)"""
        if field in self.context["user_bio"]:
            if isinstance(self.context["user_bio"][field], list):
                if value not in self.context["user_bio"][field]:
                    self.context["user_bio"][field].append(value)
                self.context["user_bio"][field] = self._dedupe_recent(
                    self.context["user_bio"][field], _MAX_BIO_LIST_ITEMS
                )
            else:
                self.context["user_bio"][field] = value
            self.save_context()

    def record_topics(self, topics):
        """대화 주제 빈도 기록"""
        for topic in topics or []:
            token = str(topic).strip().lower()
            if len(token) < 2 or token in _KOREAN_STOPWORDS: continue
            self.context["conversation_topics"][token] = self.context["conversation_topics"].get(token, 0) + 1
        
        self.context["conversation_topics"] = self._limit_frequency_map(
            self.context["conversation_topics"], max_items=_MAX_TOPIC_COUNT
        )
        self.save_context()

    def record_preference(self, category: str, value: str):
        """선호도 기록."""
        category = str(category or "").strip()
        value = str(value or "").strip()
        if not category or not value:
            return

        prefs = self.context.setdefault("preferences", {})
        bucket = prefs.setdefault(category, {})
        bucket[value] = bucket.get(value, 0) + 1
        prefs[category] = self._limit_frequency_map(bucket, max_items=50)
        self.save_context()

    def get_top_preferences(self, limit: int = 3) -> List[str]:
        """상위 선호도를 '카테고리:값' 형식으로 반환."""
        prefs = []
        for category, values in (self.context.get("preferences") or {}).items():
            if not values:
                continue
            top_name, top_score = max(values.items(), key=lambda item: item[1])
            prefs.append((top_score, f"{category}:{top_name}"))
        return [label for _, label in sorted(prefs, key=lambda item: item[0], reverse=True)[:limit]]

    def get_fact_conflicts(self, key: str = "", limit: int = 5) -> List[Dict[str, Any]]:
        history = self.context.get("fact_history", {}) or {}
        if key:
            return [entry for entry in reversed(history.get(key, [])) if entry.get("conflicted_with")][:limit]
        flattened: List[Dict[str, Any]] = []
        for fact_key, entries in history.items():
            for entry in entries:
                if entry.get("conflicted_with"):
                    flattened.append({"key": fact_key, **entry})
        flattened.sort(key=lambda item: item.get("recorded_at", ""), reverse=True)
        return flattened[:limit]

    def record_command(self, command_type, params=None):
        """명령어 패턴 기록"""
        # 최근 명령어와의 시퀀스 학습
        if self.context["last_commands"]:
            last = self.context["last_commands"][-1]["command"]
            if last != command_type:
                seq = self.context["command_sequences"].setdefault(last, {})
                seq[command_type] = seq.get(command_type, 0) + 1

        # 빈도 및 시간대 패턴
        self.context["command_frequency"][command_type] = self.context["command_frequency"].get(command_type, 0) + 1
        
        hour_slot = f"{datetime.now().hour:02d}:00"
        slot_list = self.context["time_patterns"].setdefault(hour_slot, [])
        slot_list.append(command_type)
        if len(slot_list) > _MAX_TIME_PATTERNS_PER_SLOT:
            self.context["time_patterns"][hour_slot] = slot_list[-_MAX_TIME_PATTERNS_PER_SLOT:]

        self.context["last_commands"].append({
            "command": command_type, "params": str(params)[:200] if params else None,
            "timestamp": datetime.now().isoformat()
        })
        if len(self.context["last_commands"]) > _MAX_COMMANDS:
            self.context["last_commands"] = self.context["last_commands"][-_MAX_COMMANDS:]
        
        self.save_context()

    def extract_topics(self, user_msg: str, ai_response: str = "") -> List[str]:
        """대화 텍스트에서 간단한 주제 후보를 추출."""
        text = f"{user_msg or ''} {ai_response or ''}".lower()
        tokens = re.findall(r"[가-힣a-zA-Z0-9]{2,}", text)
        seen = []
        for token in tokens:
            if token in _KOREAN_STOPWORDS:
                continue
            if token.isdigit():
                continue
            if token not in seen:
                seen.append(token)
            if len(seen) >= 8:
                break
        return seen

    def get_predicted_next_commands(self) -> List[str]:
        """이전 명령 흐름과 빈도를 바탕으로 다음 명령 후보를 반환."""
        predictions = []
        last_commands = self.context.get("last_commands", [])
        sequences = self.context.get("command_sequences", {})
        command_frequency = self.context.get("command_frequency", {})

        if last_commands:
            last = last_commands[-1].get("command")
            next_candidates = sequences.get(last, {})
            predictions.extend(
                cmd for cmd, _ in sorted(next_candidates.items(), key=lambda x: x[1], reverse=True)
            )

        for cmd, _ in sorted(command_frequency.items(), key=lambda x: x[1], reverse=True):
            if cmd not in predictions:
                predictions.append(cmd)

        return predictions[:5]

    def get_time_based_suggestions(self, hour: Optional[int] = None, limit: int = 3) -> List[str]:
        """현재 시간대에 자주 사용된 명령 후보를 반환."""
        target_hour = datetime.now().hour if hour is None else int(hour)
        slot = f"{target_hour:02d}:00"
        commands = self.context.get("time_patterns", {}).get(slot, [])
        counts: Dict[str, int] = {}
        for cmd in commands:
            counts[cmd] = counts.get(cmd, 0) + 1
        return [cmd for cmd, _ in sorted(counts.items(), key=lambda item: item[1], reverse=True)[:limit]]

    def get_topic_recommendations(self, limit: int = 5, include_strategy: bool = True) -> List[str]:
        topics = self.context.get("conversation_topics", {}) or {}
        recommendations = [
            f"{topic}:{score}"
            for topic, score in sorted(topics.items(), key=lambda item: item[1], reverse=True)[: max(limit * 2, limit)]
        ]
        if include_strategy:
            try:
                from agent.strategy_memory import get_strategy_memory
                memory = get_strategy_memory()
                enriched: List[str] = []
                for item in recommendations:
                    topic = item.split(":", 1)[0]
                    similar = memory.search_similar_records(topic, limit=1)
                    if similar:
                        enriched.append(f"{item}|전략:{similar[0].goal_summary[:40]}")
                    else:
                        enriched.append(item)
                recommendations = enriched
            except Exception as exc:
                logger.debug(f"[UserContext] 전략 기반 추천 보강 생략: {exc}")
        return recommendations[:limit]

    def optimize_memory(self):
        """주기적 메모리 최적화 및 감쇄(Decay) 적용."""
        logger.info("[UserContext] 메모리 최적화 수행 중...")
        now = datetime.now()
        
        # 1. 사실 신뢰도 감쇄 및 만료 정리
        facts = self.context.get("facts", {})
        from memory.trust_engine import compute_decay, should_remove
        for key in list(facts.keys()):
            f = facts[key]
            if f.get("expires_at") and datetime.fromisoformat(f["expires_at"]) < now:
                del facts[key]
                continue
            if f.get("updated_at"):
                days = (now - datetime.fromisoformat(f["updated_at"])).days
                result = compute_decay(float(f.get("confidence", 0.7)), days, int(f.get("access_count", 0)))
                if should_remove(result.new_confidence, int(f.get("conflict_count", 0)), days):
                    del facts[key]
                    continue
                f["confidence"] = round(result.new_confidence, 2)

        # 2. 주제(Topic) 점수 감쇄 (오래된 관심사 제거)
        topics = self.context.get("conversation_topics", {})
        for t in list(topics.keys()):
            topics[t] = int(topics[t] * 0.8) # 20% 감소
            if topics[t] < 1: del topics[t]

        self.save_context()

    # ── 유틸리티 ───────────────────────────────────────────────────────────────

    def get_context_summary(self) -> str:
        """프롬프트 주입용 요약 텍스트 생성."""
        lines = []
        bio = self.context.get("user_bio", {})
        if bio.get("name") != "사용자": lines.append(f"사용자 이름: {bio['name']}")
        if bio.get("interests"): lines.append(f"관심사: {', '.join(bio['interests'][:5])}")
        
        facts = self.context.get("facts", {})
        if facts:
            sorted_facts = sorted(facts.items(), key=lambda x: x[1].get("confidence", 0), reverse=True)
            fact_items = []
            for k, v in sorted_facts[:_SUMMARY_FACT_LIMIT]:
                conf = float(v.get("confidence", 0.7))
                label = "(불확실)" if conf < 0.4 else ""
                fact_items.append(f"{k}({v['value']}){label}[{conf:.2f}]")
            fact_str = ", ".join(fact_items)
            lines.append(f"학습된 사실: {fact_str}")
            
        topics = self.context.get("conversation_topics", {})
        if topics:
            top_t = sorted(topics.items(), key=lambda x: x[1], reverse=True)[:_SUMMARY_TOPIC_LIMIT]
            lines.append(f"최근 대화 주제: {', '.join(t[0] for t in top_t)}")
            
        return "\n".join(lines)

    def _normalize_fact_entry(self, raw):
        if isinstance(raw, dict):
            return {
                "value": str(raw.get("value", "")),
                "updated_at": raw.get("updated_at", datetime.now().isoformat()),
                "source": raw.get("source", "assistant"),
                "confidence": float(raw.get("confidence", 0.6)),
                "expires_at": raw.get("expires_at"),
                "conflict_count": int(raw.get("conflict_count", 0)),
                "reinforcement_count": int(raw.get("reinforcement_count", 1)),
                "access_count": int(raw.get("access_count", 0)),
                "source_history": list(raw.get("source_history", []))[-5:],
                "conflict_values": list(raw.get("conflict_values", []))[-5:],
                "last_conflict_at": str(raw.get("last_conflict_at", "")),
            }
        if raw is not None:
            return {
                "value": str(raw),
                "updated_at": datetime.now().isoformat(),
                "source": "legacy",
                "confidence": 0.6,
                "expires_at": None,
                "conflict_count": 0,
                "reinforcement_count": 1,
                "access_count": 0,
                "source_history": ["legacy"],
                "conflict_values": [],
                "last_conflict_at": "",
            }
        return None

    def _normalize_fact_history(self, raw_history):
        normalized: Dict[str, List[Dict[str, Any]]] = {}
        if not isinstance(raw_history, dict):
            return normalized
        for key, entries in raw_history.items():
            bucket: List[Dict[str, Any]] = []
            for entry in entries or []:
                if not isinstance(entry, dict):
                    continue
                bucket.append({
                    "value": str(entry.get("value", "")),
                    "source": str(entry.get("source", "assistant")),
                    "confidence": float(entry.get("confidence", 0.5)),
                    "recorded_at": str(entry.get("recorded_at", datetime.now().isoformat())),
                    "conflicted_with": str(entry.get("conflicted_with", "")),
                })
            if bucket:
                normalized[str(key)] = bucket[-_MAX_FACT_HISTORY:]
        return normalized

    def _limit_facts(self, facts):
        return dict(sorted(facts.items(), key=lambda x: x[1].get("updated_at", ""), reverse=True)[:_MAX_FACTS])

    def _limit_frequency_map(self, mapping, max_items=_MAX_COMMAND_FREQ):
        return dict(sorted(mapping.items(), key=lambda x: x[1], reverse=True)[:max_items])

    def _limit_sequences(self, sequences):
        return {k: dict(sorted(v.items(), key=lambda x: x[1], reverse=True)[:_MAX_SEQUENCE_EDGES]) 
                for k, v in sorted(sequences.items(), key=lambda x: sum(x[1].values()), reverse=True)[:_MAX_SEQUENCE_ROOTS]}

    def _dedupe_recent(self, values, max_items):
        res, seen = [], set()
        for v in reversed(values or []):
            if v not in seen:
                res.append(v); seen.add(v)
                if len(res) >= max_items: break
        return list(reversed(res))


def get_context_manager() -> UserContextManager:
    """앱 전역에서 공유하는 사용자 컨텍스트 매니저 반환."""
    global _context_manager
    if _context_manager is None:
        _context_manager = UserContextManager()
    return _context_manager
