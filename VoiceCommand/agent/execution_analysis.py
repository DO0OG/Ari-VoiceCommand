"""
실행 결과/단계 분석 유틸리티.
실패 분류, 읽기 전용 단계 판정, 실행 산출물 추출 규칙을 한 곳에 모은다.
"""
from __future__ import annotations

import ast
import copy
import os
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List


_MUTATING_TOKENS = (
    # 파일 저장/쓰기 — open()의 read 모드는 포함하지 않음
    "save_document",
    ", 'w')", ", 'w')", ', "w")', ', "w")',
    ", 'a')", ', "a")',
    ", 'x')", ', "x")',
    ", 'wb')", ', "wb")',
    ", 'ab')", ', "ab")',
    ".write(", "write_text(", "write_bytes(", "write_",
    # 파일시스템 조작
    "os.makedirs", "mkdir", "os.remove", "os.unlink", "os.rename",
    "shutil.move", "shutil.copy", "shutil.rmtree",
    "delete", "unlink", "remove", "rename",
    # GUI/자동화
    "launch_app", "open_url", "open_path",
    "click_screen", "click_image", "type_text", "press_keys", "hotkey",
    "browser_login", "run_browser_actions", "run_desktop_workflow",
    # 시스템
    "shutdown",
    # PowerShell 변이 cmdlet
    "set-content", "new-item", "move-item",
    "copy-item", "remove-item", "rename-item", "start-process",
)

_STORAGE_DESC_TOKENS = ("저장", "생성", "폴더", "파일", "문서", "보고서", "목록", "요약")
_OPEN_DESC_TOKENS = ("열기", "실행")
_STATEFUL_UI_TOKENS = (
    "open_url", "open_path", "launch_app", "click_screen", "move_mouse",
    "click_image", "type_text", "press_keys", "hotkey", "browser_login",
    "focus_window", "run_browser_actions", "run_desktop_workflow",
)
_PATH_LITERAL_RE = re.compile(r"[A-Za-z]:\\[^\r\n\"']+")
_URL_RE = re.compile(r"https?://[^\s)\"']+")
_GOAL_HINT_RE = re.compile(r"goal_hint\s*=\s*['\"]([^'\"]+)['\"]")
_WORKFLOW_CALL_RE = re.compile(r"\b(run_browser_actions|run_desktop_workflow|focus_window|wait_for_window)\b")
_WINDOW_TARGET_RE = re.compile(r"(?:expected_window|window|title_substring)\s*=\s*['\"]([^'\"]+)['\"]")
# 문자열 목록은 open(path, mode='w')나 os.system(...)을 놓치므로 쓰기 모드 열기와 셸 호출은 따로 찾는다.
_WRITE_OR_SHELL_CALL_RE = re.compile(
    r"\bopen\s*\([^)]*['\"](?:[wax]|r\+|rb\+)[bt+]*['\"]"
    r"|\bos\s*\.\s*(?:system|popen|startfile|exec\w*|spawn\w*)\s*\("
)
_OPEN_MODE_RE = re.compile(r"[rwxabtU+]{1,4}")
# 첫 인자로 경로를 받고 모드는 둘째 인자로 받는 open (Image.open(path), gzip.open(path, 'wb') 등).
_PATH_FIRST_OPENERS = frozenset({"Image", "webbrowser", "io", "codecs", "os", "gzip", "bz2", "lzma", "tarfile", "wave"})


def _opens_for_write(content: str) -> bool:
    """open(str(p), mode='w')처럼 정규식이 놓치는 호출까지 AST로 본다. 모드를 코드만으로 알 수 없으면 쓰기로 본다."""
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError):
        return False  # 파이썬 코드가 아니면 정규식 검사에 맡긴다.
    for node in ast.walk(tree):
        func = getattr(node, "func", None)
        if isinstance(func, ast.Name) and func.id == "open":
            modes = node.args[1:2]
        elif isinstance(func, ast.Attribute) and func.attr == "open":
            owner = getattr(func.value, "id", None) or getattr(func.value, "attr", None)
            # Path(p).open(mode)는 첫 인자가 모드다. 경로를 먼저 받는 모듈과 경로 문자열 리터럴은 모드에서 뺀다.
            modes = [] if owner in _PATH_FIRST_OPENERS else [
                arg for arg in node.args[:1]
                if not isinstance(arg, ast.Constant) or _OPEN_MODE_RE.fullmatch(str(arg.value))
            ]
            modes += node.args[1:2]
        else:
            continue
        modes += [arg for arg in node.args if isinstance(arg, ast.Starred)]
        modes += [keyword.value for keyword in node.keywords if keyword.arg in ("mode", None)]
        for mode in modes:
            if not (isinstance(mode, ast.Constant) and isinstance(mode.value, str)) or set(mode.value) & set("wax+"):
                return True
    return False


@dataclass
class ErrorAnalysis:
    primary_cause: str
    severity: float
    recovery_probability: float
    recommended_strategy: str
    secondary_causes: List[str] = field(default_factory=list)


_FAILURE_PROFILES: dict[str, ErrorAnalysis] = {
    "timeout": ErrorAnalysis("timeout", 0.4, 0.6, "retry"),
    "permission_denied": ErrorAnalysis("permission_denied", 0.7, 0.3, "simplify"),
    "missing_module": ErrorAnalysis("missing_module", 0.3, 0.9, "retry"),
    "missing_resource": ErrorAnalysis("missing_resource", 0.5, 0.5, "llm_fix"),
    "syntax_error": ErrorAnalysis("syntax_error", 0.4, 0.8, "llm_fix"),
    "code_generation_error": ErrorAnalysis("code_generation_error", 0.5, 0.7, "simplify"),
    "network_error": ErrorAnalysis("network_error", 0.5, 0.5, "retry"),
    "user_cancelled": ErrorAnalysis("user_cancelled", 0.0, 0.0, "abort"),
    "execution_failed": ErrorAnalysis("execution_failed", 0.6, 0.4, "llm_fix"),
}


def classify_failure_message(message: str) -> str:
    normalized = (message or "").lower()
    if not normalized:
        return ""
    if "timeout" in normalized or "시간 초과" in normalized:
        return "timeout"
    if "permission" in normalized or "권한" in normalized or "access is denied" in normalized:
        return "permission_denied"
    if "no module named" in normalized or "modulenotfounderror" in normalized:
        return "missing_module"
    if "not found" in normalized or "찾을 수 없" in normalized or "no such file" in normalized:
        return "missing_resource"
    if "syntaxerror" in normalized or "문법" in normalized:
        return "syntax_error"
    if "nameerror" in normalized or "attributeerror" in normalized or "module" in normalized:
        return "code_generation_error"
    if "검색 오류" in normalized or "http" in normalized or "연결" in normalized:
        return "network_error"
    if "사용자 취소" in normalized:
        return "user_cancelled"
    return "execution_failed"


def analyze_failure(error_message: str) -> ErrorAnalysis:
    primary = classify_failure_message(error_message)
    return copy.copy(
        _FAILURE_PROFILES.get(
            primary,
            ErrorAnalysis(primary, 0.5, 0.5, "llm_fix"),
        )
    )


def is_read_only_step_content(content: str, description: str = "") -> bool:
    lowered_content = (content or "").lower()
    lowered_desc = (description or "").lower()
    if _WRITE_OR_SHELL_CALL_RE.search(lowered_content) or _opens_for_write(content or ""):
        return False
    return not any(token in lowered_content or token in lowered_desc for token in _MUTATING_TOKENS)


def extract_artifacts(texts: Iterable[str]) -> Dict[str, List[str]]:
    paths: List[str] = []
    urls: List[str] = []
    for text in texts:
        if not text:
            continue
        for path in re.findall(r'[A-Za-z]:\\[^\r\n]+', text):
            cleaned = path.strip().strip('"').strip("'")
            if cleaned:
                paths.append(cleaned)
        for url in re.findall(r'https?://[^\s)]+', text):
            cleaned = url.strip().strip('"').strip("'")
            if cleaned:
                urls.append(cleaned)
    return {
        "paths": list(dict.fromkeys(paths)),
        "urls": list(dict.fromkeys(urls)),
    }


def existing_paths(paths: Iterable[str]) -> List[str]:
    return [path for path in paths if os.path.exists(path)]


def describes_storage_action(description: str) -> bool:
    return any(token in (description or "") for token in _STORAGE_DESC_TOKENS)


def describes_open_action(description: str) -> bool:
    return any(token in (description or "") for token in _OPEN_DESC_TOKENS)


def mutates_runtime_state(content: str, description: str = "") -> bool:
    lowered_content = (content or "").lower()
    lowered_desc = (description or "").lower()
    return any(token in lowered_content or token in lowered_desc for token in _STATEFUL_UI_TOKENS)


def extract_step_targets(text: str) -> Dict[str, List[str]]:
    """단계 코드/명령에서 경로/URL 타깃을 추출한다."""
    text = text or ""
    paths = [p.strip().strip('"').strip("'") for p in _PATH_LITERAL_RE.findall(text)]
    urls = [u.strip().strip('"').strip("'") for u in _URL_RE.findall(text)]
    domains = []
    windows = []
    goal_hints = []
    for url in urls:
        normalized = url.lower()
        domain = normalized.split("//", 1)[-1].split("/", 1)[0]
        if domain:
            domains.append(domain)
    for window in _WINDOW_TARGET_RE.findall(text):
        cleaned = window.strip()
        if cleaned:
            windows.append(cleaned)
    for goal_hint in _GOAL_HINT_RE.findall(text):
        cleaned = goal_hint.strip()
        if cleaned:
            goal_hints.append(cleaned)
    return {
        "paths": list(dict.fromkeys(paths)),
        "urls": list(dict.fromkeys(urls)),
        "domains": list(dict.fromkeys(domains)),
        "windows": list(dict.fromkeys(windows)),
        "goal_hints": list(dict.fromkeys(goal_hints)),
    }


def extract_workflow_hints(texts: Iterable[str]) -> List[str]:
    """단계 코드/설명에서 재사용 가능한 워크플로우 힌트를 추출한다."""
    hints: List[str] = []
    for text in texts:
        if not text:
            continue
        for match in _GOAL_HINT_RE.findall(text):
            cleaned = match.strip()
            if cleaned:
                hints.append(cleaned)
        if _WORKFLOW_CALL_RE.search(text):
            compact = " ".join(text.strip().split())
            if compact:
                hints.append(compact[:120])
    return list(dict.fromkeys(hints))
