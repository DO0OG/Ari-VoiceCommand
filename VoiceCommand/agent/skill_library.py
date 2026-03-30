"""반복 성공 패턴을 재사용 가능한 스킬로 보관."""
from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import asdict, dataclass
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
    compiled: bool = False      # True: Python 함수로 컴파일됨 (Direction 2)

    # 자기수정 임계값
    _COMPILE_THRESHOLD = 5       # success_count >= 이 값이면 Python 컴파일 시도
    _CONDENSE_THRESHOLD = 8      # success_count >= 이 값이면 스텝 압축 시도
    _OPTIMIZE_ON_FAIL = 2        # fail_count >= 이 값이면 스텝 수정 시도


class SkillLibrary:
    def __init__(self):
        try:
            from core.resource_manager import ResourceManager
            self.file_path = ResourceManager.get_writable_path("skill_library.json")
        except Exception:
            self.file_path = os.path.join(os.path.dirname(__file__), "skill_library.json")
        self.skills: List[Skill] = []
        self._load()

    def _load(self):
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            loaded = []
            for item in data:
                # compiled 필드 없는 이전 데이터 호환
                item.setdefault("compiled", False)
                loaded.append(Skill(**{
                    k: v for k, v in item.items()
                    if k in Skill.__dataclass_fields__
                }))
            self.skills = loaded
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
            # Direction 1: 스텝 압축 (백그라운드)
            if skill.success_count == Skill._CONDENSE_THRESHOLD and not skill.compiled:
                threading.Thread(
                    target=self._async_condense, args=(skill,), daemon=True
                ).start()
            # Direction 2: Python 컴파일 (백그라운드)
            if skill.success_count == Skill._COMPILE_THRESHOLD and not skill.compiled:
                threading.Thread(
                    target=self._async_compile, args=(skill,), daemon=True
                ).start()
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

    def record_feedback(self, skill_id: str, positive: bool, error: str = ""):
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
                # Direction 1: 실패 시 스텝 수정 (백그라운드)
                elif skill.fail_count >= Skill._OPTIMIZE_ON_FAIL and error:
                    threading.Thread(
                        target=self._async_optimize, args=(skill, error), daemon=True
                    ).start()
                # Direction 2: 컴파일 스킬 실패 시 코드 수정 (백그라운드)
                if skill.compiled and error:
                    threading.Thread(
                        target=self._async_repair_compiled, args=(skill, error), daemon=True
                    ).start()
            self._save()
            return

    def mark_compiled(self, skill_id: str):
        """compiled=True로 표시."""
        for skill in self.skills:
            if skill.skill_id == skill_id:
                skill.compiled = True
                self._save()
                return

    def deprecate_if_failing(self, skill_id: str, error: str = ""):
        self.record_feedback(skill_id, positive=False, error=error)

    def deprecate_skill(self, skill_id: str) -> bool:
        for skill in self.skills:
            if skill.skill_id == skill_id:
                skill.enabled = False
                self._save()
                return True
        return False

    # ── 비동기 자기수정 ───────────────────────────────────────────────────

    def _async_optimize(self, skill: Skill, error: str):
        """Direction 1: 실패한 스텝 LLM 수정."""
        try:
            from agent.skill_optimizer import get_skill_optimizer
            new_steps = get_skill_optimizer().optimize_steps(skill, error)
            if new_steps:
                skill.steps = new_steps
                self._save()
                logging.info(f"[SkillLibrary] '{skill.name}' 스텝 자기수정 완료")
        except Exception as exc:
            logging.debug(f"[SkillLibrary] 스텝 수정 실패: {exc}")

    def _async_condense(self, skill: Skill):
        """Direction 1: 성공 반복 후 스텝 압축."""
        try:
            from agent.skill_optimizer import get_skill_optimizer
            new_steps = get_skill_optimizer().condense_steps(skill)
            if new_steps:
                skill.steps = new_steps
                self._save()
                logging.info(f"[SkillLibrary] '{skill.name}' 스텝 압축 완료")
        except Exception as exc:
            logging.debug(f"[SkillLibrary] 스텝 압축 실패: {exc}")

    def _async_compile(self, skill: Skill):
        """Direction 2: Python 함수로 컴파일."""
        try:
            from agent.skill_optimizer import get_skill_optimizer
            optimizer = get_skill_optimizer()
            code = optimizer.compile_to_python(skill)
            if code:
                optimizer.save_compiled(skill.skill_id, code)
                self.mark_compiled(skill.skill_id)
                logging.info(f"[SkillLibrary] '{skill.name}' Python 컴파일 완료")
        except Exception as exc:
            logging.debug(f"[SkillLibrary] Python 컴파일 실패: {exc}")

    def _async_repair_compiled(self, skill: Skill, error: str):
        """Direction 2: 컴파일 스킬 코드 LLM 수정."""
        try:
            from agent.skill_optimizer import get_skill_optimizer
            optimizer = get_skill_optimizer()
            code = optimizer.load_compiled(skill.skill_id)
            if not code:
                return
            new_code = optimizer.repair_python(skill, code, error)
            if new_code:
                optimizer.save_compiled(skill.skill_id, new_code)
                logging.info(f"[SkillLibrary] '{skill.name}' 컴파일 코드 수정 완료")
        except Exception as exc:
            logging.debug(f"[SkillLibrary] 컴파일 코드 수정 실패: {exc}")

    # ── 내부 헬퍼 ─────────────────────────────────────────────────────────

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
