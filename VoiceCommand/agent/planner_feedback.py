"""플래너 성능 피드백 루프."""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from typing import List

_TAG_KEYWORDS = {
    "파일": ["파일", "저장", "쓰기", "읽기", "폴더", "경로", "다운로드", "복사", "이동"],
    "웹": ["웹", "브라우저", "사이트", "크롬", "엣지", "url", "링크", "로그인"],
    "시스템": ["시스템", "쉘", "cmd", "프로세스", "서비스", "레지스트리"],
    "자동화": ["자동", "스케줄", "예약", "반복", "알람", "배치"],
    "ui": ["창", "클릭", "마우스", "키보드", "화면", "포커스"],
    "정보": ["뉴스", "날씨", "시간", "요약", "정리", "검색"],
}


class PlannerFeedbackLoop:
    def __init__(self):
        try:
            from core.resource_manager import ResourceManager
            self.file_path = ResourceManager.get_writable_path("planner_stats.json")
        except Exception:
            self.file_path = os.path.join(os.path.dirname(__file__), "planner_stats.json")
        self.stats = self._load()

    def _load(self):
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        except Exception as e:
            logging.warning(f"[PlannerFeedback] 로드 실패: {e}")
            return {}

    def _save(self):
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(self.stats, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.warning(f"[PlannerFeedback] 저장 실패: {e}")

    def record(self, steps: List, success: bool, duration_ms: int, tags: List[str] | None = None):
        normalized_tags = self._normalize_tags(tags or self.infer_tags(steps=steps))
        for step in steps or []:
            step_type = getattr(step, "step_type", "unknown")
            keys = [step_type]
            keys.extend(f"{step_type}:{tag}" for tag in normalized_tags)
            for key in keys:
                bucket = self.stats.setdefault(key, {"success": 0, "fail": 0, "durations": []})
                if success:
                    bucket["success"] += 1
                else:
                    bucket["fail"] += 1
                bucket["durations"] = (bucket["durations"] + [int(duration_ms)])[-20:]
        self._save()

    def get_hints(self, goal: str, tags: List[str]) -> str:
        normalized_tags = self._normalize_tags(tags or self.infer_tags(goal=goal))
        lines = []
        for key, bucket in self.stats.items():
            if ":" in key:
                _, key_tag = key.split(":", 1)
                if normalized_tags and key_tag not in normalized_tags:
                    continue
            total = bucket.get("success", 0) + bucket.get("fail", 0)
            if total <= 0:
                continue
            success_rate = bucket.get("success", 0) / total
            if success_rate >= 0.7:
                lines.append(f"{key} 단계 성공률 {success_rate * 100:.0f}%")
            elif bucket.get("fail", 0) >= 2:
                lines.append(f"{key} 단계 실패 빈도 높음, 대안 접근 권장")
        if not lines:
            return ""
        return "[플래너 힌트]\n" + "\n".join(f"- {line}" for line in lines[:4])

    def infer_tags(self, goal: str = "", steps: List | None = None) -> List[str]:
        text_parts = [str(goal or "")]
        for step in steps or []:
            text_parts.append(str(getattr(step, "description_kr", "") or ""))
            text_parts.append(str(getattr(step, "content", "") or ""))
        text = " ".join(text_parts).lower()
        tags = [
            tag for tag, keywords in _TAG_KEYWORDS.items()
            if any(keyword.lower() in text for keyword in keywords)
        ]
        if re.search(r"https?://", text):
            tags.append("웹")
        return self._normalize_tags(tags or ["일반"])

    def _normalize_tags(self, tags: List[str]) -> List[str]:
        normalized = []
        for tag in tags or []:
            value = str(tag or "").strip()
            if not value or value in normalized:
                continue
            normalized.append(value)
        return normalized or ["일반"]


_feedback_loop: PlannerFeedbackLoop | None = None
_feedback_loop_lock = threading.Lock()


def get_planner_feedback_loop() -> PlannerFeedbackLoop:
    global _feedback_loop
    if _feedback_loop is None:
        with _feedback_loop_lock:
            if _feedback_loop is None:
                _feedback_loop = PlannerFeedbackLoop()
    return _feedback_loop
