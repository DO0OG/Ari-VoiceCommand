"""
전략 기억 (Strategy Memory)
세션 간에 어떤 접근이 성공/실패했는지 기록하고,
다음 계획 수립 시 과거 경험을 참고합니다.
"""
import dataclasses
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict

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


@dataclass
class StrategyRecord:
    goal_summary: str
    tags: List[str]
    steps_desc: List[str]      # 단계 설명 목록 (코드 전체가 아닌 요약)
    success: bool
    error_summary: str
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
    ):
        """목표 달성 시도 결과를 기록합니다."""
        rec = StrategyRecord(
            goal_summary=goal[:200],
            tags=self._extract_tags(goal),
            steps_desc=[getattr(s, "description_kr", str(s))[:80] for s in (steps or [])],
            success=success,
            error_summary=error[:200],
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
        relevant: List[StrategyRecord] = []

        # 최신순 순회, 공통 태그가 있는 기록 수집
        for rec in reversed(self._records):
            if goal_tags & set(rec.tags):
                relevant.append(rec)
            if len(relevant) >= 3:
                break

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
            if rec.success:
                lines.append(f"  소요: {rec.duration_ms}ms")
        lines.append("※ 실패한 접근 방식은 반복하지 마세요.")
        return "\n".join(lines)

    def recent_failures(self, goal: str, n: int = 2) -> List[str]:
        """최근 실패한 접근 방식 목록 반환 (fix_step 힌트용)"""
        goal_tags = set(self._extract_tags(goal))
        failures = []
        for rec in reversed(self._records):
            if not rec.success and (goal_tags & set(rec.tags)):
                failures.append(rec.error_summary)
            if len(failures) >= n:
                break
        return failures

    # ── 내부 ──────────────────────────────────────────────────────────────────

    def _extract_tags(self, text: str) -> List[str]:
        tags = [tag for tag, words in _TAG_KEYWORDS.items() if any(w in text for w in words)]
        return tags or ["일반"]

    def _prune(self):
        if len(self._records) > _MAX_RECORDS:
            self._records = self._records[-_MAX_RECORDS:]

    def _load(self):
        try:
            if os.path.exists(self.filepath):
                with open(self.filepath, encoding="utf-8") as f:
                    data = json.load(f)
                self._records = [StrategyRecord(**r) for r in data]
                logging.info(f"[StrategyMemory] {len(self._records)}개 전략 로드")
        except Exception as e:
            logging.warning(f"[StrategyMemory] 로드 실패: {e}")
            self._records = []

    def _save(self):
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(
                    [dataclasses.asdict(r) for r in self._records],
                    f, ensure_ascii=False, indent=2,
                )
        except Exception as e:
            logging.warning(f"[StrategyMemory] 저장 실패: {e}")


# ── 싱글톤 ─────────────────────────────────────────────────────────────────────

_instance: Optional[StrategyMemory] = None


def get_strategy_memory() -> StrategyMemory:
    global _instance
    if _instance is None:
        _instance = StrategyMemory()
    return _instance
