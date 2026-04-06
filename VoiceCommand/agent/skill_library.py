"""반복 성공 패턴을 재사용 가능한 스킬로 보관."""
from __future__ import annotations

import atexit
import json
import logging
import os
import re
import threading
from dataclasses import asdict, dataclass, field
from typing import List, Optional

_DEVELOPER_SCOPE_RE = re.compile(
    r"(voicecommand(?:/(?:agent|core|ui|plugins|tests)\b|\s*(?:저장소|repository|codebase|repo)\b)?|저장소|repository|codebase|\brepo\b|\bdocs\b)",
    re.IGNORECASE,
)
_DEVELOPER_ACTION_RE = re.compile(
    r"(validate_repo\.py|--compile-only|pytest|unittest|코드\s*(?:변경|수정)|검증|테스트(?:\s*실행)?|구현|개선(?:\s*과제)?|분석|전체\s*파악)",
    re.IGNORECASE,
)

_TAG_KEYWORDS = {
    "파일": ["파일", "폴더", "저장", "쓰기", "읽기", "복사", "이동", "다운로드"],
    "웹": ["웹", "브라우저", "사이트", "크롬", "엣지", "url", "링크", "로그인"],
    "자동화": ["자동", "반복", "스케줄", "예약", "알람", "배치"],
    "UI": ["창", "클릭", "마우스", "키보드", "화면", "포커스"],
    "정보": ["뉴스", "날씨", "시간", "요약", "정리", "검색"],
}


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
    user_positive_feedback: int = 0
    user_negative_feedback: int = 0
    context_tags: List[str] = field(default_factory=list)

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
        self._save_lock = threading.RLock()
        self._save_timer: threading.Timer | None = None
        self._save_delay_seconds = 0.1
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
        with self._save_lock:
            self._save_timer = None
            try:
                os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
                with open(self.file_path, "w", encoding="utf-8") as f:
                    json.dump([asdict(skill) for skill in self.skills], f, ensure_ascii=False, indent=2)
            except FileNotFoundError as e:
                logging.debug(f"[SkillLibrary] 저장 생략: {e}")
            except Exception as e:
                logging.warning(f"[SkillLibrary] 저장 실패: {e}")

    def list_skills(self) -> List[Skill]:
        return [skill for skill in self.skills if skill.enabled]

    def get_applicable_skill(self, goal: str) -> Optional[Skill]:
        if self._looks_like_developer_goal(goal):
            return None
        normalized = self._normalize_goal(goal)
        goal_tags = set(self._infer_context_tags(goal))
        best_skill = None
        best_score = 0
        for skill in self.skills:
            if not skill.enabled:
                continue
            score = 0
            for pattern in skill.trigger_patterns:
                if pattern and pattern in normalized:
                    score += len(pattern)
            tag_overlap = len(goal_tags & set(skill.context_tags or []))
            score += tag_overlap * 10
            if score > best_score and skill.confidence >= 0.4:
                best_skill = skill
                best_score = score
        return best_skill

    def try_extract_skill(self, goal: str, steps: list, success: bool, duration_ms: int = 0) -> Optional[Skill]:
        if self._looks_like_developer_goal(goal):
            return None
        if not success or not steps or len(steps) > 5:
            return None
        normalized = self._normalize_goal(goal)
        context_tags = self._infer_context_tags(goal, steps=steps)
        skill = self.get_applicable_skill(goal)
        if skill:
            skill.success_count += 1
            skill.avg_duration_ms = self._blend_duration(skill.avg_duration_ms, duration_ms, skill.success_count)
            skill.context_tags = self._merge_tags(skill.context_tags, context_tags)
            skill.confidence = self._recalculate_confidence(skill)
            self._schedule_save()
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
            context_tags=context_tags,
        )
        skill.confidence = self._recalculate_confidence(skill)
        self.skills.append(skill)
        self._schedule_save()
        return skill

    def record_feedback(self, skill_id: str, positive: bool, error: str = "", context_tags: Optional[List[str]] = None):
        for skill in self.skills:
            if skill.skill_id != skill_id:
                continue
            if positive:
                skill.success_count += 1
                skill.user_positive_feedback += 1
            else:
                skill.fail_count += 1
                skill.user_negative_feedback += 1
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
            if context_tags:
                skill.context_tags = self._merge_tags(skill.context_tags, context_tags)
            skill.confidence = self._recalculate_confidence(skill)
            self._schedule_save()
            return

    def mark_compiled(self, skill_id: str):
        """compiled=True로 표시."""
        for skill in self.skills:
            if skill.skill_id == skill_id:
                skill.compiled = True
                self._schedule_save()
                return

    def deprecate_if_failing(self, skill_id: str, error: str = ""):
        self.record_feedback(skill_id, positive=False, error=error)

    def deprecate_skill(self, skill_id: str) -> bool:
        for skill in self.skills:
            if skill.skill_id == skill_id:
                skill.enabled = False
                self._schedule_save()
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

    def _looks_like_developer_goal(self, goal: str) -> bool:
        normalized = self._normalize_goal(goal)
        return bool(normalized and _DEVELOPER_SCOPE_RE.search(normalized) and _DEVELOPER_ACTION_RE.search(normalized))

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

    def _infer_context_tags(self, goal: str, steps: list | None = None) -> List[str]:
        text_parts = [self._normalize_goal(goal)]
        for step in steps or []:
            text_parts.append(str(getattr(step, "description_kr", "") or "").lower())
            text_parts.append(str(getattr(step, "content", "") or "").lower())
        text = " ".join(text_parts)
        tags = [
            tag for tag, keywords in _TAG_KEYWORDS.items()
            if any(keyword.lower() in text for keyword in keywords)
        ]
        if re.search(r"https?://", text):
            tags.append("웹")
        return self._merge_tags([], tags or ["일반"])

    def _merge_tags(self, current: List[str], new_tags: List[str]) -> List[str]:
        merged = []
        for tag in list(current or []) + list(new_tags or []):
            value = str(tag or "").strip()
            if not value or value in merged:
                continue
            merged.append(value)
        return merged or ["일반"]

    def _recalculate_confidence(self, skill: Skill) -> float:
        confidence = 0.35
        confidence += min(skill.success_count * 0.06, 0.35)
        confidence -= min(skill.fail_count * 0.08, 0.3)
        confidence += min(skill.user_positive_feedback * 0.04, 0.12)
        confidence -= min(skill.user_negative_feedback * 0.06, 0.18)
        if skill.compiled:
            confidence += 0.05
        if skill.context_tags:
            confidence += min(len(skill.context_tags) * 0.01, 0.05)
        return round(max(0.0, min(1.0, confidence)), 2)

    def _schedule_save(self) -> None:
        with self._save_lock:
            if self._save_timer is not None:
                self._save_timer.cancel()
            self._save_timer = threading.Timer(self._save_delay_seconds, self._save)
            self._save_timer.daemon = True
            self._save_timer.start()

    def flush(self) -> None:
        with self._save_lock:
            timer = self._save_timer
            self._save_timer = None
        if timer is not None:
            timer.cancel()
        self._save()


_skill_library: SkillLibrary | None = None
_skill_library_lock = threading.Lock()


def get_skill_library() -> SkillLibrary:
    global _skill_library
    if _skill_library is None:
        with _skill_library_lock:
            if _skill_library is None:
                _skill_library = SkillLibrary()
    return _skill_library


def flush_skill_library() -> None:
    if _skill_library is None:
        return
    try:
        _skill_library.flush()
    except Exception as exc:
        logging.debug("[SkillLibrary] flush 생략: %s", exc)


atexit.register(flush_skill_library)
