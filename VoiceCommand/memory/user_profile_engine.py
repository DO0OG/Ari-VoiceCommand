"""사용자 프로파일 추론 엔진."""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Dict, List


@dataclass
class UserProfile:
    expertise_areas: Dict[str, float] = field(default_factory=dict)
    response_style: str = "친근"
    active_hours: List[int] = field(default_factory=list)
    frequent_goals: List[str] = field(default_factory=list)
    last_profiled: str = ""


class UserProfileEngine:
    def __init__(self):
        from core.resource_manager import ResourceManager
        self.file_path = ResourceManager.get_writable_path("user_profile.json")
        self.profile = self._load()

    def _load(self) -> UserProfile:
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return UserProfile(
                expertise_areas=dict(data.get("expertise_areas", {})),
                response_style=str(data.get("response_style", "친근")),
                active_hours=list(data.get("active_hours", []))[-24:],
                frequent_goals=list(data.get("frequent_goals", []))[:10],
                last_profiled=str(data.get("last_profiled", "")),
            )
        except FileNotFoundError:
            return UserProfile()
        except Exception as e:
            logging.warning(f"[UserProfile] 로드 실패: {e}")
            return UserProfile()

    def _save(self):
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(asdict(self.profile), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.warning(f"[UserProfile] 저장 실패: {e}")

    def update(self, user_msg: str, command_type: str = "", success: bool = True):
        text = (user_msg or "").lower()
        hour = datetime.now().hour
        self.profile.active_hours.append(hour)
        self.profile.active_hours = self.profile.active_hours[-48:]

        if command_type:
            goals = [command_type] + [goal for goal in self.profile.frequent_goals if goal != command_type]
            self.profile.frequent_goals = goals[:10]

        expertise_keywords = {
            "코딩": ("코드", "파이썬", "python", "개발", "버그", "리팩토링", "테스트"),
            "자동화": ("자동화", "스케줄", "예약", "반복", "워크플로"),
            "요리": ("요리", "레시피", "음식"),
            "미디어": ("음악", "영화", "유튜브", "영상"),
        }
        for area, keywords in expertise_keywords.items():
            if any(keyword in text for keyword in keywords):
                current = self.profile.expertise_areas.get(area, 0.2)
                delta = 0.08 if success else -0.03
                self.profile.expertise_areas[area] = max(0.0, min(1.0, round(current + delta, 2)))

        if any(token in text for token in ("간단", "짧게", "요약")):
            self.profile.response_style = "간결"
        elif any(token in text for token in ("자세히", "상세", "설명")):
            self.profile.response_style = "상세"
        elif any(token in text for token in ("공손", "격식")):
            self.profile.response_style = "격식"
        else:
            self.profile.response_style = self.profile.response_style or "친근"

        self.profile.last_profiled = datetime.now().isoformat()
        self._save()

    def get_profile(self) -> UserProfile:
        return self.profile

    def get_prompt_injection(self) -> str:
        lines = ["[사용자 정보]"]
        if self.profile.response_style:
            lines.append(f"- 응답 선호: {self.profile.response_style}")
        if self.profile.expertise_areas:
            top = sorted(
                self.profile.expertise_areas.items(),
                key=lambda item: item[1],
                reverse=True,
            )[:3]
            lines.append(f"- 주요 관심: {', '.join(area for area, score in top if score >= 0.25)}")
        if self.profile.active_hours:
            recent_hour = self.profile.active_hours[-1]
            lines.append(f"- 최근 활동 시간대: {recent_hour:02d}시")
        if self.profile.frequent_goals:
            lines.append(f"- 자주 하는 작업: {', '.join(self.profile.frequent_goals[:3])}")
        return "\n".join(lines)


_engine: UserProfileEngine | None = None
_engine_lock = threading.Lock()


def get_user_profile_engine() -> UserProfileEngine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = UserProfileEngine()
    return _engine
