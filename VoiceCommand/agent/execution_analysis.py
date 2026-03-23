"""
실행 결과/단계 분석 유틸리티.
실패 분류, 읽기 전용 단계 판정, 실행 산출물 추출 규칙을 한 곳에 모읍니다.
"""
from __future__ import annotations

import os
import re
from typing import Dict, Iterable, List


_MUTATING_TOKENS = (
    "save_document", "open(", "write_", "os.makedirs", "mkdir", "remove",
    "delete", "unlink", "copy", "move", "rename", "launch_app", "open_url",
    "open_path", "click_screen", "type_text", "press_keys", "hotkey",
    "browser_login", "shutdown", "set-content", "new-item", "move-item",
    "copy-item", "remove-item", "rename-item", "start-process",
)

_STORAGE_DESC_TOKENS = ("저장", "생성", "폴더", "파일", "문서", "보고서", "목록", "요약")
_OPEN_DESC_TOKENS = ("열기", "실행")


def classify_failure_message(message: str) -> str:
    normalized = (message or "").lower()
    if not normalized:
        return ""
    if "timeout" in normalized or "시간 초과" in normalized:
        return "timeout"
    if "permission" in normalized or "권한" in normalized or "access is denied" in normalized:
        return "permission_denied"
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


def is_read_only_step_content(content: str, description: str = "") -> bool:
    lowered_content = (content or "").lower()
    lowered_desc = (description or "").lower()
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
