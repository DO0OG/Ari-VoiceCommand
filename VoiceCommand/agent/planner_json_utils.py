"""플래너 JSON 응답 복구/파싱 유틸리티."""

import json
import logging
import re


_RE_CODE_FENCE = re.compile(r"```(?:json)?\s*", re.IGNORECASE)


def strip_json_code_fence(text: str) -> str:
    return _RE_CODE_FENCE.sub("", (text or "").strip())


def extract_balanced(text: str, open_char: str, close_char: str) -> str:
    start = text.find(open_char)
    if start < 0:
        return ""
    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == open_char:
            depth += 1
        elif ch == close_char:
            depth -= 1
            if depth == 0:
                return text[start:idx + 1]
    return ""


def extract_partial_object(text: str, start: int) -> tuple[str, int]:
    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:idx + 1], idx + 1
    return "", start


def recover_partial_array(text: str) -> list:
    start = text.find("[")
    if start < 0:
        return []
    items = []
    cursor = start
    while cursor < len(text):
        obj_start = text.find("{", cursor)
        if obj_start < 0:
            break
        obj_text, obj_end = extract_partial_object(text, obj_start)
        if not obj_text:
            break
        try:
            items.append(json.loads(obj_text))
        except Exception:
            break
        cursor = obj_end
        comma_idx = text.find(",", cursor)
        if comma_idx < 0:
            break
        cursor = comma_idx + 1
    return items


def recover_partial_object(text: str) -> dict:
    obj_start = text.find("{")
    if obj_start < 0:
        return {}
    obj_text, _ = extract_partial_object(text, obj_start)
    if not obj_text:
        return {}
    try:
        return json.loads(obj_text)
    except Exception:
        return {}


def parse_json_array(text: str) -> list:
    cleaned = strip_json_code_fence(text)
    candidate = extract_balanced(cleaned, "[", "]")
    if candidate:
        try:
            return json.loads(candidate)
        except Exception:
            logging.warning("[Planner] JSON 배열 파싱 실패: %s", candidate[:200])
    recovered = recover_partial_array(cleaned)
    if recovered:
        logging.info("[Planner] 부분 JSON 배열 복구 적용")
        return recovered
    return []


def parse_json_object(text: str) -> dict:
    cleaned = strip_json_code_fence(text)
    candidate = extract_balanced(cleaned, "{", "}")
    if candidate:
        try:
            return json.loads(candidate)
        except Exception:
            logging.warning("[Planner] JSON 객체 파싱 실패: %s", candidate[:200])
    recovered = recover_partial_object(cleaned)
    if recovered:
        logging.info("[Planner] 부분 JSON 객체 복구 적용")
        return recovered
    return {}
