"""
전략 기억 (Strategy Memory)
세션 간에 어떤 접근이 성공/실패했는지 기록하고,
다음 계획 수립 시 과거 경험을 참고합니다.
"""
import json
import logging
import os
import re
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Optional, Dict
from agent.execution_analysis import classify_failure_message

_MEMORY_FILE = os.path.join(os.path.dirname(__file__), "strategy_memory.json")
_MAX_RECORDS = 500

# 목표 유형 분류를 위한 키워드 맵
_TAG_KEYWORDS: Dict[str, List[str]] = {
    "파일":    ["파일", "저장", "읽기", "쓰기", "삭제", "복사", "이동", "폴더", "디렉토리"],
    "네트워크": ["API", "웹", "요청", "다운로드", "업로드", "HTTP", "검색", "크롤링", "사이트", "인터넷"],
    "시스템":  ["프로세스", "시스템", "CMD", "쉘", "레지스트리", "서비스", "종료", "재부팅"],
    "데이터":  ["데이터", "분석", "계산", "처리", "변환", "파싱", "JSON", "CSV", "엑셀"],
    "자동화":  ["자동", "반복", "루프", "스케줄", "예약", "배치", "타이머"],
    "UI":     ["창", "클릭", "마우스", "키보드", "화면", "스크린", "모니터"],
    "텍스트":  ["텍스트", "문자열", "출력", "인쇄", "쓰기", "요약", "번역", "정리"],
    "미디어":  ["유튜브", "음악", "영상", "소리", "볼륨", "오디오", "재생", "동영상"],
    "정보":    ["날씨", "뉴스", "시간", "환율", "주식", "알려줘", "뭐야", "누구"]
}
_TOKEN_STOPWORDS = {
    "해줘", "해주세요", "하고", "다음", "이후", "정리", "저장", "실행", "요청", "작업",
    "the", "and", "for", "with", "from", "this", "that", "save", "open",
}


@dataclass
class StrategyRecord:
    goal_summary: str
    tags: List[str]
    steps_desc: List[str]      # 단계 설명 목록 (코드 전체가 아닌 요약)
    success: bool
    error_summary: str
    failure_kind: str
    duration_ms: int
    timestamp: str


class StrategyMemory:
    """과거 목표 달성 전략을 기억하고 유사한 목표에 재활용합니다."""

    def __init__(self, filepath: str = _MEMORY_FILE):
        self.filepath = filepath
        self._records: List[StrategyRecord] = []
        self._load()

    # ── 공개 API ──────────────────────────────────────────────────────────────

    def record(
        self,
        goal: str,
        steps: list,
        success: bool,
        error: str = "",
        duration_ms: int = 0,
        failure_kind: str = "",
    ):
        """목표 달성 시도 결과를 기록합니다."""
        rec = StrategyRecord(
            goal_summary=goal[:200],
            tags=self._extract_tags(goal),
            steps_desc=[getattr(s, "description_kr", str(s))[:80] for s in (steps or [])],
            success=success,
            error_summary=error[:200],
            failure_kind=failure_kind or self._classify_failure(error),
            duration_ms=duration_ms,
            timestamp=datetime.now().isoformat(),
        )
        self._records.append(rec)
        self._prune()
        self._save()
        logging.info(f"[StrategyMemory] 기록: {'성공' if success else '실패'} / {goal[:40]}")

    def get_relevant_context(self, goal: str) -> str:
        """
        현재 목표와 유사한 과거 전략을 LLM 프롬프트용 문자열로 반환합니다.
        최신 기록 우선, 공통 태그 기준 최대 3개.
        """
        goal_tags = set(self._extract_tags(goal))
        goal_tokens = self._extract_tokens(goal)
        scored = []
        for rec in self._records:
            overlap = len(goal_tags & set(rec.tags))
            token_score = self._token_similarity(goal_tokens, self._extract_tokens(rec.goal_summary))
            if overlap == 0 and token_score <= 0:
                continue
            recency = self._safe_timestamp(rec.timestamp)
            score = overlap * 10 + token_score * 8
            score += 3 if rec.success else 0
            score += min(rec.duration_ms, 60_000) / 60_000
            score += recency.timestamp() / 10_000_000_000
            scored.append((score, rec))

        relevant = [rec for _, rec in sorted(scored, key=lambda item: item[0], reverse=True)[:3]]

        if not relevant:
            return ""

        lines = ["## 과거 유사 전략 참고 (최신순):"]
        for rec in relevant:
            status = "✅ 성공" if rec.success else "❌ 실패"
            lines.append(f"- [{status}] {rec.goal_summary[:80]}")
            if rec.steps_desc:
                lines.append(f"  접근: {' → '.join(rec.steps_desc[:3])}")
            if not rec.success and rec.error_summary:
                lines.append(f"  실패 원인: {rec.error_summary[:80]}")
            if rec.failure_kind:
                lines.append(f"  실패 분류: {rec.failure_kind}")
            if rec.success:
                lines.append(f"  소요: {rec.duration_ms}ms")
        lines.append("※ 실패한 접근 방식은 반복하지 마세요.")
        return "\n".join(lines)

    def recent_failures(self, goal: str, n: int = 2) -> List[str]:
        """최근 실패한 접근 방식 목록 반환 (fix_step 힌트용)"""
        goal_tags = set(self._extract_tags(goal))
        goal_tokens = self._extract_tokens(goal)
        failures = []
        for rec in reversed(self._records):
            tag_overlap = goal_tags & set(rec.tags)
            token_score = self._token_similarity(goal_tokens, self._extract_tokens(rec.goal_summary))
            if not rec.success and (tag_overlap or token_score > 0):
                hint = rec.error_summary
                if rec.failure_kind:
                    hint = f"[{rec.failure_kind}] {hint}"
                failures.append(hint)
            if len(failures) >= n:
                break
        return failures

    # ── 내부 ──────────────────────────────────────────────────────────────────

    def _extract_tags(self, text: str) -> List[str]:
        tags = [tag for tag, words in _TAG_KEYWORDS.items() if any(w in text for w in words)]
        return tags or ["일반"]

    def _extract_tokens(self, text: str) -> set[str]:
        tokens = set()
        for token in re.findall(r"[가-힣A-Za-z][가-힣A-Za-z0-9_-]{1,20}", (text or "").lower()):
            if token in _TOKEN_STOPWORDS:
                continue
            tokens.add(token)
        return tokens

    def _token_similarity(self, left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        intersection = len(left & right)
        union = len(left | right)
        if union == 0:
            return 0.0
        return intersection / union

    def _prune(self):
        if len(self._records) > _MAX_RECORDS:
            self._records = self._records[-_MAX_RECORDS:]

    def _load(self):
        try:
            if os.path.exists(self.filepath):
                with open(self.filepath, encoding="utf-8") as f:
                    data = json.load(f)
                self._records = [self._normalize_record(r) for r in data if isinstance(r, dict)]
                logging.info(f"[StrategyMemory] {len(self._records)}개 전략 로드")
        except Exception as e:
            logging.warning(f"[StrategyMemory] 로드 실패: {e}")
            self._records = []

    def _save(self):
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(
                    [asdict(r) for r in self._records],
                    f, ensure_ascii=False, indent=2,
                )
        except Exception as e:
            logging.warning(f"[StrategyMemory] 저장 실패: {e}")

    def _normalize_record(self, raw: dict) -> StrategyRecord:
        return StrategyRecord(
            goal_summary=str(raw.get("goal_summary", ""))[:200],
            tags=list(raw.get("tags", [])) or ["일반"],
            steps_desc=list(raw.get("steps_desc", [])),
            success=bool(raw.get("success", False)),
            error_summary=str(raw.get("error_summary", ""))[:200],
            failure_kind=str(raw.get("failure_kind", "")),
            duration_ms=int(raw.get("duration_ms", 0) or 0),
            timestamp=raw.get("timestamp") or datetime.now().isoformat(),
        )

    def _classify_failure(self, error: str) -> str:
        return classify_failure_message(error)

    def _safe_timestamp(self, value: str) -> datetime:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return datetime.min


# ── 싱글톤 ─────────────────────────────────────────────────────────────────────

_instance: Optional[StrategyMemory] = None


def get_strategy_memory() -> StrategyMemory:
    global _instance
    if _instance is None:
        _instance = StrategyMemory()
    return _instance
