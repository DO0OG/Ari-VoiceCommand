"""반복 성공 패턴을 재사용 가능한 스킬로 보관."""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from typing import List, Optional


@dataclass
class Skill:
    skill_id: str
    name: str
    trigger_patterns: List[str]
    steps: List[dict]
    success_count: int = 0
    fail_count: int = 0
    avg_duration_ms: int = 0
    confidence: float = 0.5
    enabled: bool = True


class SkillLibrary:
    def __init__(self):
        self.file_path = os.path.join(os.path.dirname(__file__), "skill_library.json")
        self.skills: List[Skill] = []
        self._load()

    def _load(self):
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.skills = [Skill(**item) for item in data]
        except FileNotFoundError:
            self.skills = []
        except Exception as e:
            logging.warning(f"[SkillLibrary] 로드 실패: {e}")
            self.skills = []

    def _save(self):
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump([asdict(skill) for skill in self.skills], f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.warning(f"[SkillLibrary] 저장 실패: {e}")

    def list_skills(self) -> List[Skill]:
        return [skill for skill in self.skills if skill.enabled]

    def get_applicable_skill(self, goal: str) -> Optional[Skill]:
        normalized = self._normalize_goal(goal)
        best_skill = None
        best_score = 0
        for skill in self.skills:
            if not skill.enabled:
                continue
            score = 0
            for pattern in skill.trigger_patterns:
                if pattern and pattern in normalized:
                    score += len(pattern)
            if score > best_score and skill.confidence >= 0.45:
                best_skill = skill
                best_score = score
        return best_skill

    def try_extract_skill(self, goal: str, steps: list, success: bool, duration_ms: int = 0) -> Optional[Skill]:
        if not success or not steps or len(steps) > 5:
            return None
        normalized = self._normalize_goal(goal)
        skill = self.get_applicable_skill(goal)
        if skill:
            skill.success_count += 1
            skill.avg_duration_ms = self._blend_duration(skill.avg_duration_ms, duration_ms, skill.success_count)
            skill.confidence = min(1.0, round(skill.confidence + 0.05, 2))
            self._save()
            return skill

        trigger_patterns = self._extract_patterns(normalized)
        if len(trigger_patterns) < 2:
            return None
        skill = Skill(
            skill_id=f"skill_{len(self.skills)+1}",
            name=trigger_patterns[0][:24],
            trigger_patterns=trigger_patterns[:4],
            steps=[self._step_to_dict(step) for step in steps],
            success_count=3,
            avg_duration_ms=int(duration_ms),
            confidence=0.65,
        )
        self.skills.append(skill)
        self._save()
        return skill

    def record_feedback(self, skill_id: str, positive: bool):
        for skill in self.skills:
            if skill.skill_id != skill_id:
                continue
            if positive:
                skill.success_count += 1
                skill.confidence = min(1.0, round(skill.confidence + 0.06, 2))
            else:
                skill.fail_count += 1
                skill.confidence = max(0.0, round(skill.confidence - 0.12, 2))
                if skill.fail_count >= 2 and skill.fail_count > skill.success_count:
                    skill.enabled = False
            self._save()
            return

    def deprecate_if_failing(self, skill_id: str):
        self.record_feedback(skill_id, positive=False)

    def deprecate_skill(self, skill_id: str) -> bool:
        for skill in self.skills:
            if skill.skill_id == skill_id:
                skill.enabled = False
                self._save()
                return True
        return False

    def _normalize_goal(self, goal: str) -> str:
        return re.sub(r"\s+", " ", (goal or "").strip().lower())

    def _extract_patterns(self, normalized_goal: str) -> List[str]:
        tokens = re.findall(r"[가-힣a-zA-Z0-9]{2,}", normalized_goal)
        stop = {"해줘", "해주세요", "좀", "바로", "이거", "저거", "관련", "작업"}
        patterns = []
        for token in tokens:
            if token in stop or token in patterns:
                continue
            patterns.append(token)
        return patterns

    def _step_to_dict(self, step) -> dict:
        return {
            "step_id": getattr(step, "step_id", 0),
            "step_type": getattr(step, "step_type", "python"),
            "content": getattr(step, "content", ""),
            "description_kr": getattr(step, "description_kr", ""),
            "expected_output": getattr(step, "expected_output", ""),
            "condition": getattr(step, "condition", ""),
            "on_failure": getattr(step, "on_failure", "abort"),
        }

    def _blend_duration(self, current: int, new_value: int, count: int) -> int:
        if count <= 1:
            return int(new_value)
        return int(((current * (count - 1)) + new_value) / count)


_skill_library: SkillLibrary | None = None


def get_skill_library() -> SkillLibrary:
    global _skill_library
    if _skill_library is None:
        _skill_library = SkillLibrary()
    return _skill_library
