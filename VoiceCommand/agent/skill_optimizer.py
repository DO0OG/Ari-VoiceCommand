"""스킬 자기수정 엔진.

Direction 1 — Step 레벨 재작성:
    스킬 실패 시 LLM이 JSON 스텝 시퀀스를 수정·단순화.

Direction 2 — Python 코드 컴파일:
    충분히 검증된 스킬을 단일 Python 함수로 컴파일, 저장,
    이후 실행 시 LLM 계획 없이 직접 호출. 실패 시 LLM이 코드 수정.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import logging
import os
import re
import tempfile
import threading
from typing import List, Optional

logger = logging.getLogger(__name__)

# 컴파일된 스킬 저장 디렉터리
_COMPILED_DIR: str = ""
_COMPILED_DIR_LOCK = threading.Lock()

# 정규식 캐싱
_RE_JSON_BLOCK = re.compile(r"```json\s*([\s\S]+?)\s*```")
_RE_PY_BLOCK = re.compile(r"```python\s*([\s\S]+?)\s*```")

# skill_id 허용 패턴 (경로 탈출 방지)
_SKILL_ID_RE = re.compile(r'^[A-Za-z0-9_\-]+$')


def _validate_skill_id(skill_id: str) -> None:
    """skill_id에 경로 구분자나 특수문자가 없는지 검증."""
    if not _SKILL_ID_RE.match(skill_id):
        raise ValueError(f"유효하지 않은 skill_id: {skill_id!r}")


def _invoke_run_skill(run_skill, goal: str) -> str:
    if not callable(run_skill):
        raise TypeError("run_skill 함수 없음")
    return str(run_skill(goal))


def _get_compiled_dir() -> str:
    global _COMPILED_DIR
    if not _COMPILED_DIR:
        with _COMPILED_DIR_LOCK:
            if not _COMPILED_DIR:  # double-checked
                try:
                    from core.resource_manager import ResourceManager
                    _COMPILED_DIR = ResourceManager.get_writable_path("compiled_skills")
                except (ImportError, AttributeError):
                    project_root = os.path.dirname(os.path.dirname(__file__))
                    _COMPILED_DIR = os.path.join(project_root, ".ari_runtime", "compiled_skills")
                os.makedirs(_COMPILED_DIR, exist_ok=True)
    return _COMPILED_DIR


class SkillOptimizer:
    """LLM을 사용해 스킬을 자기수정하고 Python으로 컴파일합니다."""

    # ── Direction 1: Step 레벨 재작성 ─────────────────────────────────────

    def optimize_steps(self, skill, error: str) -> Optional[List[dict]]:
        """실패한 스킬의 스텝 시퀀스를 LLM으로 수정. 수정된 스텝 반환."""
        prompt = (
            "당신은 AI 에이전트의 스킬 옵티마이저입니다.\n"
            f"스킬 '{skill.name}'이 다음 에러로 실패했습니다:\n{error[:400]}\n\n"
            f"현재 스텝:\n{json.dumps(skill.steps, ensure_ascii=False, indent=2)}\n\n"
            "실패 원인을 수정한 스텝 배열을 JSON 코드블록으로만 반환하세요.\n"
            "각 스텝: step_type(python/shell/browser), content, description_kr, "
            "expected_output, condition, on_failure(abort/continue) 필드.\n"
            "```json\n[...]\n```"
        )
        response = self._call_llm(prompt)
        steps = self._parse_json_steps(response)
        if steps:
            logger.info(
                "[SkillOptimizer] '%s' 스텝 수정 완료 (%s개)",
                skill.name,
                len(steps),
            )
        return steps

    def condense_steps(self, skill) -> Optional[List[dict]]:
        """N회 성공한 스킬의 스텝을 LLM으로 단순화."""
        if len(skill.steps) <= 1:
            return None
        prompt = (
            "당신은 AI 에이전트의 스킬 옵티마이저입니다.\n"
            f"스킬 '{skill.name}'이 {skill.success_count}회 성공했습니다.\n"
            "중복·불필요한 스텝을 제거하고 효율적으로 단순화하세요.\n\n"
            f"현재 스텝:\n{json.dumps(skill.steps, ensure_ascii=False, indent=2)}\n\n"
            "단순화된 스텝 배열을 JSON 코드블록으로만 반환하세요.\n"
            "```json\n[...]\n```"
        )
        response = self._call_llm(prompt)
        steps = self._parse_json_steps(response)
        if steps and len(steps) < len(skill.steps):
            logger.info(
                "[SkillOptimizer] '%s' 스텝 압축: %s → %s개",
                skill.name,
                len(skill.steps),
                len(steps),
            )
            return steps
        return None

    # ── Direction 2: Python 코드 컴파일 ───────────────────────────────────

    def compile_to_python(self, skill) -> Optional[str]:
        """스킬을 단일 Python 함수로 컴파일. 성공 시 코드 문자열 반환."""
        prompt = (
            "당신은 AI 에이전트 스킬을 Python 함수로 컴파일합니다.\n"
            f"스킬: {skill.name}\n"
            f"트리거 패턴: {', '.join(skill.trigger_patterns)}\n"
            f"스텝:\n{json.dumps(skill.steps, ensure_ascii=False, indent=2)}\n\n"
            "규칙:\n"
            "1. 함수명: run_skill(goal: str) -> str\n"
            "2. 표준 라이브러리(os, subprocess, pathlib, shutil, json, re, datetime)만 사용\n"
            "3. subprocess 사용 시 timeout=30, check=False 필수\n"
            "4. 반환값: 실행 결과 요약 한국어 문자열\n"
            "5. 예외는 raise로 전파 (try/except 최소화)\n"
            "```python\n...\n```"
        )
        code = self._extract_code_block(self._call_llm(prompt))
        if self._validate_python(code):
            logger.info("[SkillOptimizer] '%s' Python 컴파일 성공", skill.name)
            return code
        return None

    def repair_python(self, skill, code: str, error: str) -> Optional[str]:
        """실패한 컴파일 스킬 코드를 LLM으로 수정."""
        prompt = (
            f"Python 스킬 함수가 실패했습니다.\n"
            f"에러: {error[:300]}\n\n"
            f"현재 코드:\n```python\n{code}\n```\n\n"
            "에러를 수정한 코드를 반환하세요. "
            "함수명 run_skill(goal: str) -> str 유지.\n"
            "```python\n...\n```"
        )
        new_code = self._extract_code_block(self._call_llm(prompt))
        if self._validate_python(new_code):
            logger.info("[SkillOptimizer] '%s' 코드 수정 완료", skill.name)
            return new_code
        return None

    def save_compiled(self, skill_id: str, code: str) -> str:
        """컴파일된 코드를 파일로 저장하고 경로 반환."""
        _validate_skill_id(skill_id)
        path = os.path.join(_get_compiled_dir(), f"{skill_id}.py")
        with open(path, "w", encoding="utf-8") as f:
            f.write(code)
        return path

    def load_compiled(self, skill_id: str) -> Optional[str]:
        """저장된 컴파일 코드 로드."""
        _validate_skill_id(skill_id)
        path = os.path.join(_get_compiled_dir(), f"{skill_id}.py")
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def delete_compiled(self, skill_id: str):
        """컴파일된 스킬 파일 삭제."""
        _validate_skill_id(skill_id)
        path = os.path.join(_get_compiled_dir(), f"{skill_id}.py")
        if os.path.exists(path):
            os.remove(path)

    def run_compiled(self, skill_id: str, goal: str) -> tuple[bool, str]:
        """
        저장된 Python 스킬 실행.
        반환: (success, result_or_error)
        """
        _validate_skill_id(skill_id)
        code = self.load_compiled(skill_id)
        if not code:
            return False, "컴파일된 스킬 없음"
        try:
            from agent.safety_checker import DangerLevel, get_safety_checker
            report = get_safety_checker().check_python(code)
            if report.level == DangerLevel.DANGEROUS:
                return False, f"실행 직전 안전 검사 실패: {report.summary_kr}"
            with tempfile.TemporaryDirectory(prefix="ari_skill_") as temp_dir:
                module_path = os.path.join(temp_dir, f"skill_{skill_id}.py")
                with open(module_path, "w", encoding="utf-8") as f:
                    f.write(code)
                spec = importlib.util.spec_from_file_location(f"skill_{skill_id}", module_path)
                if spec is None or spec.loader is None:
                    return False, "컴파일된 스킬 로더 생성 실패"
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            run_fn = getattr(module, "run_skill", None)
            result = _invoke_run_skill(run_fn, str(goal))
            return True, str(result)
        except Exception as exc:
            logger.exception("[SkillOptimizer] run_compiled 실패 (skill_id=%s)", skill_id)
            return False, str(exc)

    # ── 내부 헬퍼 ─────────────────────────────────────────────────────────

    def _call_llm(self, prompt: str) -> str:
        from agent.llm_provider import get_llm_provider
        return get_llm_provider().chat(
            prompt,
            include_context=False,
            system_override=(
                "당신은 AI 에이전트 스킬 최적화 전문가입니다. "
                "요청된 형식으로만 응답하세요."
            ),
        )

    def _parse_json_steps(self, response: str) -> Optional[List[dict]]:
        try:
            m = _RE_JSON_BLOCK.search(response)
            raw = m.group(1) if m else response.strip()
            steps = json.loads(raw)
            if not isinstance(steps, list) or not steps:
                return None
            for step in steps:
                if not {"step_type", "content"}.issubset(step.keys()):
                    return None
            return steps
        except Exception as exc:
            logger.debug("[SkillOptimizer] 스텝 파싱 실패: %s", exc)
            return None

    def _extract_code_block(self, response: str) -> str:
        m = _RE_PY_BLOCK.search(response)
        return m.group(1).strip() if m else response.strip()

    def _validate_python(self, code: str) -> bool:
        """safety_checker + AST 컴파일 검증."""
        if not code or "def run_skill" not in code:
            return False
        try:
            from agent.safety_checker import DangerLevel, get_safety_checker
            report = get_safety_checker().check_python(code)
            if report.level == DangerLevel.DANGEROUS:
                logger.warning("[SkillOptimizer] 안전 검사 실패: %s", report.summary_kr)
                return False
        except Exception as exc:
            logger.debug("[SkillOptimizer] 안전 검사기 사용 불가: %s", exc)
        try:
            tree = ast.parse(code)
            if not self._is_safe_module(tree):
                logger.warning("[SkillOptimizer] 허용되지 않은 최상위 실행문이 포함되어 있습니다.")
                return False
            return True
        except SyntaxError as exc:
            logger.debug("[SkillOptimizer] 문법 오류: %s", exc)
            return False

    def _is_safe_module(self, tree: ast.Module) -> bool:
        allowed_top_level = (
            ast.FunctionDef,
            ast.AsyncFunctionDef,
            ast.Import,
            ast.ImportFrom,
            ast.Assign,
            ast.AnnAssign,
            ast.Expr,
        )
        for node in tree.body:
            if not isinstance(node, allowed_top_level):
                return False
            if isinstance(node, ast.Expr) and not isinstance(getattr(node, "value", None), ast.Constant):
                return False
        return True


_optimizer: SkillOptimizer | None = None
_optimizer_lock = threading.Lock()


def get_skill_optimizer() -> SkillOptimizer:
    global _optimizer
    if _optimizer is None:
        with _optimizer_lock:
            if _optimizer is None:
                _optimizer = SkillOptimizer()
    return _optimizer
