"""
사용자 컨텍스트 학습 및 관리
"""
import json
import os
import logging
import re
from datetime import datetime, timedelta


_MAX_FACTS = 100
_MAX_COMMANDS = 50
_MAX_TIME_PATTERNS_PER_SLOT = 20
_MAX_COMMAND_FREQ = 100
_MAX_SEQUENCE_ROOTS = 100
_MAX_SEQUENCE_EDGES = 20
_MAX_BIO_LIST_ITEMS = 30
_MAX_TOPIC_COUNT = 40
_SUMMARY_FACT_LIMIT = 5
_SUMMARY_TOPIC_LIMIT = 3
_DEFAULT_FACT_TTL_DAYS = 180
_KOREAN_STOPWORDS = {
    "그리고", "하지만", "그러나", "오늘", "지금", "이번", "저번", "관련", "대한",
    "해주세요", "해줘", "정리", "요약", "저장", "실행", "작업", "요청", "결과",
    "사용자", "아리", "파일", "폴더", "문서", "정보", "내용",
}
_ENGLISH_STOPWORDS = {
    "the", "and", "for", "with", "this", "that", "from", "into", "your",
    "user", "task", "save", "open", "file", "folder", "report", "summary",
}


class UserContextManager:
    """사용자 행동 패턴 및 컨텍스트 관리"""

    def __init__(self, context_file="user_context.json"):
        try:
            from resource_manager import ResourceManager
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
        """기본 컨텍스트 구조"""
        return self._normalize_context({
            "user_bio": {
                "name": "사용자",
                "location": "",
                "interests": [],
                "memos": []
            },
            "facts": {},  # 사용자에 대한 단편적 사실들 (예: "커피를 좋아함": "2025-02-21")
            "command_frequency": {},  # 명령어 사용 빈도
            "command_sequences": {},  # 명령어 연속 사용 패턴 (예: "날씨" -> ["유튜브"])
            "time_patterns": {},  # 시간대별 활동
            "preferences": {},  # 선호도 (음악 장르, 온도 등)
            "last_commands": [],  # 최근 명령어 (최대 50개)
            "conversation_topics": {}  # 대화 주제 빈도
        })

    def _normalize_context(self, data):
        """구버전 구조를 현재 스키마로 보정하고 크기 제한을 적용"""
        context = self._default_context_structure()
        if isinstance(data, dict):
            context.update(data)

        bio = context.get("user_bio")
        if not isinstance(bio, dict):
            bio = {}
        context["user_bio"] = {
            "name": bio.get("name", "사용자"),
            "location": bio.get("location", ""),
            "interests": self._dedupe_recent(bio.get("interests", []), _MAX_BIO_LIST_ITEMS),
            "memos": self._dedupe_recent(bio.get("memos", []), _MAX_BIO_LIST_ITEMS),
        }

        facts = {}
        for key, raw in (context.get("facts") or {}).items():
            normalized = self._normalize_fact_entry(raw)
            if normalized is not None:
                facts[key] = normalized
        context["facts"] = self._limit_facts(facts)

        context["command_frequency"] = self._limit_frequency_map(context.get("command_frequency", {}))
        context["command_sequences"] = self._limit_sequences(context.get("command_sequences", {}))
        context["time_patterns"] = self._normalize_time_patterns(context.get("time_patterns", {}))
        context["preferences"] = self._normalize_preferences(context.get("preferences", {}))
        context["last_commands"] = self._normalize_last_commands(context.get("last_commands", []))
        context["conversation_topics"] = self._limit_frequency_map(
            context.get("conversation_topics", {}), max_items=_MAX_TOPIC_COUNT
        )
        return context

    def _default_context_structure(self):
        return {
            "user_bio": {
                "name": "사용자",
                "location": "",
                "interests": [],
                "memos": []
            },
            "facts": {},
            "command_frequency": {},
            "command_sequences": {},
            "time_patterns": {},
            "preferences": {},
            "last_commands": [],
            "conversation_topics": {},
        }

    def save_context(self):
        """컨텍스트 저장"""
        try:
            with open(self.context_file, 'w', encoding='utf-8') as f:
                json.dump(self.context, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.error(f"컨텍스트 저장 실패: {e}")

    def record_command(self, command_type, params=None):
        """명령어 사용 기록 및 패턴 학습"""
        # 연속성 기록 (패턴 학습)
        if self.context["last_commands"]:
            last_cmd = self.context["last_commands"][-1]["command"]
            if last_cmd != command_type:
                if last_cmd not in self.context["command_sequences"]:
                    self.context["command_sequences"][last_cmd] = {}
                if command_type not in self.context["command_sequences"][last_cmd]:
                    self.context["command_sequences"][last_cmd][command_type] = 0
                self.context["command_sequences"][last_cmd][command_type] += 1
                self.context["command_sequences"] = self._limit_sequences(self.context["command_sequences"])

        # 빈도 업데이트
        if command_type not in self.context["command_frequency"]:
            self.context["command_frequency"][command_type] = 0
        self.context["command_frequency"][command_type] += 1
        self.context["command_frequency"] = self._limit_frequency_map(self.context["command_frequency"])

        # 시간대별 패턴
        hour = datetime.now().hour
        time_slot = f"{hour:02d}:00"
        if time_slot not in self.context["time_patterns"]:
            self.context["time_patterns"][time_slot] = []
        self.context["time_patterns"][time_slot].append(command_type)
        if len(self.context["time_patterns"][time_slot]) > _MAX_TIME_PATTERNS_PER_SLOT:
            self.context["time_patterns"][time_slot] = \
                self.context["time_patterns"][time_slot][-_MAX_TIME_PATTERNS_PER_SLOT:]

        # 최근 명령어
        self.context["last_commands"].append({
            "command": command_type,
            "params": self._truncate_param_repr(params),
            "timestamp": datetime.now().isoformat()
        })

        if len(self.context["last_commands"]) > _MAX_COMMANDS:
            self.context["last_commands"] = self.context["last_commands"][-_MAX_COMMANDS:]

        self.save_context()

    def record_fact(self, key, value, source="assistant_tag", confidence=0.7, ttl_days=_DEFAULT_FACT_TTL_DAYS):
        """사용자에 대한 사실 기록"""
        expires_at = None
        if ttl_days:
            expires_at = (datetime.now() + timedelta(days=ttl_days)).isoformat()
        self.context["facts"][key] = {
            "value": value,
            "updated_at": datetime.now().isoformat(),
            "source": source,
            "confidence": max(0.0, min(float(confidence), 1.0)),
            "expires_at": expires_at,
        }
        self.context["facts"] = self._limit_facts(self.context["facts"])
        self.save_context()

    def update_bio(self, field, value):
        """기본 정보 업데이트 (이름, 관심사 등)"""
        if field in self.context["user_bio"]:
            if isinstance(self.context["user_bio"][field], list):
                if value not in self.context["user_bio"][field]:
                    self.context["user_bio"][field].append(value)
                self.context["user_bio"][field] = self._dedupe_recent(
                    self.context["user_bio"][field],
                    _MAX_BIO_LIST_ITEMS,
                )
            else:
                self.context["user_bio"][field] = value
            self.save_context()

    def record_preference(self, category, value):
        """선호도 기록 (예: 음악 장르, 선호 온도)"""
        if category not in self.context["preferences"]:
            self.context["preferences"][category] = {}

        if value not in self.context["preferences"][category]:
            self.context["preferences"][category][value] = 0
        self.context["preferences"][category][value] += 1

        if len(self.context["preferences"][category]) > 50:
            sorted_vals = sorted(
                self.context["preferences"][category].items(),
                key=lambda x: x[1], reverse=True
            )
            self.context["preferences"][category] = dict(sorted_vals[:50])

        self.save_context()

    def record_topics(self, topics):
        """대화 주제 빈도 기록"""
        changed = False
        for topic in topics or []:
            normalized = self._normalize_topic(topic)
            if not normalized:
                continue
            self.context["conversation_topics"][normalized] = (
                self.context["conversation_topics"].get(normalized, 0) + 1
            )
            changed = True

        if changed:
            self.context["conversation_topics"] = self._limit_frequency_map(
                self.context["conversation_topics"],
                max_items=_MAX_TOPIC_COUNT,
            )
            self.save_context()

    def extract_topics(self, *texts):
        """간단한 규칙 기반 주제 후보 추출"""
        scores = {}
        for text in texts:
            if not text:
                continue
            for token in re.findall(r"[가-힣A-Za-z][가-힣A-Za-z0-9_-]{1,20}", text):
                normalized = self._normalize_topic(token)
                if not normalized:
                    continue
                scores[normalized] = scores.get(normalized, 0) + 1
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        return [topic for topic, _ in ranked[:_SUMMARY_TOPIC_LIMIT]]

    def get_predicted_next_commands(self):
        """현재 패턴을 바탕으로 다음 예상 명령 제안"""
        if not self.context["last_commands"]:
            return []
        
        last_cmd = self.context["last_commands"][-1]["command"]
        if last_cmd in self.context["command_sequences"]:
            candidates = sorted(
                self.context["command_sequences"][last_cmd].items(),
                key=lambda x: x[1],
                reverse=True
            )
            return [cmd for cmd, count in candidates[:2]]
        return []

    def get_context_summary(self):
        """컨텍스트 요약 (프롬프트용)"""
        self._prune_expired_facts()
        summary = []

        # 기본 정보
        bio = self.context.get("user_bio", {})
        if bio.get("name") and bio["name"] != "사용자":
            summary.append(f"사용자 이름: {bio['name']}")
        if bio.get("location"):
            summary.append(f"사용자 위치: {bio['location']}")
        for field, label in (("interests", "관심사"), ("memos", "메모")):
            values = bio.get(field) or []
            if values:
                summary.append(f"{label}: {', '.join(values[:3])}")
        
        # 사실들
        facts = self.context.get("facts", {})
        if facts:
            ranked_facts = sorted(
                facts.items(),
                key=lambda item: (
                    item[1].get("confidence", 0.0),
                    item[1].get("updated_at", ""),
                ),
                reverse=True,
            )
            fact_list = [f"{k}: {v['value']}" for k, v in ranked_facts[:_SUMMARY_FACT_LIMIT]]
            summary.append(f"사용자에 대한 사실: {', '.join(fact_list)}")

        # 자주 사용하는 명령어
        if self.context["command_frequency"]:
            top_commands = sorted(
                self.context["command_frequency"].items(),
                key=lambda x: x[1],
                reverse=True
            )[:3]
            commands_str = ", ".join([cmd for cmd, _ in top_commands])
            summary.append(f"자주 사용하는 명령: {commands_str}")

        # 예상 다음 명령
        predictions = self.get_predicted_next_commands()
        if predictions:
            summary.append(f"패턴 기반 추천: {', '.join(predictions)}")

        # 현재 시간대 활동
        hour = datetime.now().hour
        time_slot = f"{hour:02d}:00"
        if time_slot in self.context["time_patterns"]:
            recent = self.context["time_patterns"][time_slot][-3:]
            if recent:
                summary.append(f"이 시간대 활동: {', '.join(set(recent))}")

        # 선호도
        if self.context["preferences"]:
            prefs = []
            for category, values in self.context["preferences"].items():
                if values:
                    top_pref = max(values.items(), key=lambda x: x[1])
                    prefs.append(f"{category}: {top_pref[0]}")
            if prefs:
                summary.append(f"선호: {', '.join(prefs)}")

        topics = self.context.get("conversation_topics", {})
        if topics:
            top_topics = sorted(topics.items(), key=lambda item: item[1], reverse=True)[:_SUMMARY_TOPIC_LIMIT]
            summary.append(f"최근 대화 주제: {', '.join(topic for topic, _ in top_topics)}")

        return "\n".join(summary) if summary else ""

    def _normalize_fact_entry(self, raw):
        if isinstance(raw, dict):
            value = raw.get("value")
            if value in (None, ""):
                return None
            expires_at = raw.get("expires_at")
            if expires_at and self._is_expired(expires_at):
                return None
            return {
                "value": str(value),
                "updated_at": raw.get("updated_at") or datetime.now().isoformat(),
                "source": raw.get("source", "legacy"),
                "confidence": max(0.0, min(float(raw.get("confidence", 0.6)), 1.0)),
                "expires_at": expires_at,
            }
        if raw in (None, ""):
            return None
        return {
            "value": str(raw),
            "updated_at": datetime.now().isoformat(),
            "source": "legacy",
            "confidence": 0.6,
            "expires_at": None,
        }

    def _limit_facts(self, facts):
        ranked = sorted(
            facts.items(),
            key=lambda item: (
                item[1].get("updated_at", ""),
                item[1].get("confidence", 0.0),
            ),
            reverse=True,
        )
        return dict(ranked[:_MAX_FACTS])

    def _limit_frequency_map(self, mapping, max_items=_MAX_COMMAND_FREQ):
        if not isinstance(mapping, dict):
            return {}
        ranked = sorted(mapping.items(), key=lambda item: item[1], reverse=True)
        return {str(key): int(value) for key, value in ranked[:max_items]}

    def _limit_sequences(self, sequences):
        if not isinstance(sequences, dict):
            return {}
        limited = {}
        root_items = sorted(
            sequences.items(),
            key=lambda item: sum((item[1] or {}).values()) if isinstance(item[1], dict) else 0,
            reverse=True,
        )[:_MAX_SEQUENCE_ROOTS]
        for root, edges in root_items:
            if not isinstance(edges, dict):
                continue
            ranked_edges = sorted(edges.items(), key=lambda item: item[1], reverse=True)[:_MAX_SEQUENCE_EDGES]
            limited[str(root)] = {str(key): int(value) for key, value in ranked_edges}
        return limited

    def _normalize_time_patterns(self, patterns):
        normalized = {}
        if not isinstance(patterns, dict):
            return normalized
        for slot, values in patterns.items():
            if not isinstance(values, list):
                continue
            normalized[str(slot)] = [str(v) for v in values[-_MAX_TIME_PATTERNS_PER_SLOT:]]
        return normalized

    def _normalize_preferences(self, preferences):
        normalized = {}
        if not isinstance(preferences, dict):
            return normalized
        for category, values in preferences.items():
            if not isinstance(values, dict):
                continue
            normalized[str(category)] = self._limit_frequency_map(values, max_items=50)
        return normalized

    def _normalize_last_commands(self, commands):
        normalized = []
        if not isinstance(commands, list):
            return normalized
        for item in commands[-_MAX_COMMANDS:]:
            if not isinstance(item, dict):
                continue
            normalized.append({
                "command": str(item.get("command", "")),
                "params": self._truncate_param_repr(item.get("params")),
                "timestamp": item.get("timestamp") or datetime.now().isoformat(),
            })
        return normalized

    def _dedupe_recent(self, values, max_items):
        seen = set()
        deduped = []
        for value in reversed(list(values or [])):
            text = str(value).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            deduped.append(text)
            if len(deduped) >= max_items:
                break
        deduped.reverse()
        return deduped

    def _truncate_param_repr(self, params):
        if params is None:
            return None
        text = str(params)
        return text[:200]

    def _normalize_topic(self, topic):
        token = str(topic).strip().lower()
        if len(token) < 2:
            return ""
        if token in _KOREAN_STOPWORDS or token in _ENGLISH_STOPWORDS:
            return ""
        if token.isdigit():
            return ""
        return token

    def _prune_expired_facts(self):
        facts = self.context.get("facts", {})
        expired_keys = [key for key, value in facts.items() if self._is_expired(value.get("expires_at"))]
        for key in expired_keys:
            del facts[key]
        if expired_keys:
            self.save_context()

    def _is_expired(self, expires_at):
        if not expires_at:
            return False
        try:
            return datetime.fromisoformat(expires_at) < datetime.now()
        except ValueError:
            return False


# 싱글톤 인스턴스
_context_manager = None

def get_context_manager():
    """UserContextManager 싱글톤"""
    global _context_manager
    if _context_manager is None:
        _context_manager = UserContextManager()
    return _context_manager
