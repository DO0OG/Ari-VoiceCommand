"""자동화 액션 계획 조립/정렬/유사 목표 탐색 공통 유틸리티."""

import json
import re
from typing import Callable, List


_PLAN_TYPE_PRIORITY = {
    "adaptive": 3,
    "learned_only": 2,
    "fallback_only": 1,
}


def plan_sort_key(plan: dict) -> tuple:
    return (
        float(plan.get("score", 0.0)),
        _PLAN_TYPE_PRIORITY.get(str(plan.get("plan_type", "")), 0),
    )


def score_browser_plan(plan: dict, browser_state: dict, requested_url: str = "") -> float:
    score = 0.0
    plan_type = str(plan.get("plan_type", "") or "")
    if plan_type == "adaptive":
        score += 3.0
    elif plan_type == "learned_only":
        score += 2.0
    elif plan_type == "fallback_only":
        score += 1.0
    actions = list(plan.get("actions", []))
    score += min(len(actions), 6) * 0.1

    current_url = str((browser_state or {}).get("current_url", "") or "").lower()
    requested = str(requested_url or "").lower()
    if current_url and requested:
        current_domain = current_url.split("//", 1)[-1].split("/", 1)[0]
        requested_domain = requested.split("//", 1)[-1].split("/", 1)[0]
        if current_domain == requested_domain:
            score += 1.0
        if requested in current_url:
            score += 0.5

    if has_action_type(actions, "wait_url"):
        score += 0.2
    if has_action_type(actions, "download_wait"):
        score += 0.2
    return round(score, 3)


def describe_browser_plan_reason(plan: dict, browser_state: dict, requested_url: str = "") -> str:
    reasons: List[str] = []
    plan_type = str(plan.get("plan_type", "") or "")
    if plan_type == "adaptive":
        reasons.append("학습 전략과 fallback을 함께 사용")
    elif plan_type == "learned_only":
        reasons.append("과거 성공 전략 우선")
    elif plan_type == "fallback_only":
        reasons.append("기본 fallback 전략")

    current_url = str((browser_state or {}).get("current_url", "") or "")
    if current_url and requested_url:
        current_domain = current_url.lower().split("//", 1)[-1].split("/", 1)[0]
        requested_domain = requested_url.lower().split("//", 1)[-1].split("/", 1)[0]
        if current_domain == requested_domain:
            reasons.append("현재 브라우저 도메인 일치")
    return " | ".join(reasons[:3])


def score_desktop_plan(plan: dict) -> float:
    score = 0.0
    plan_type = str(plan.get("plan_type", "") or "")
    if plan_type == "adaptive":
        score += 3.0
    elif plan_type == "learned_only":
        score += 2.0
    elif plan_type == "fallback_only":
        score += 1.0
    actions = list(plan.get("actions", []))
    score += min(len(actions), 6) * 0.1
    expected_window = str(plan.get("expected_window", "") or "")
    if expected_window:
        score += 0.6
    if has_action_type(actions, "focus"):
        score += 0.2
    if has_action_type(actions, "wait_window"):
        score += 0.2
    return round(score, 3)


def describe_desktop_plan_reason(plan: dict) -> str:
    reasons: List[str] = []
    plan_type = str(plan.get("plan_type", "") or "")
    if plan_type == "adaptive":
        reasons.append("학습된 창 타깃과 fallback 결합")
    elif plan_type == "learned_only":
        reasons.append("과거 성공 데스크톱 워크플로우 우선")
    elif plan_type == "fallback_only":
        reasons.append("기본 fallback 워크플로우")
    if plan.get("expected_window"):
        reasons.append("대상 창 대기/포커스 가능")
    return " | ".join(reasons[:3])


def workflow_succeeded(summary: str) -> bool:
    normalized = (summary or "").strip().lower()
    if not normalized:
        return False
    if "실패:" in normalized or "오류:" in normalized or "error" in normalized:
        return False
    return "성공:" in normalized or "downloaded:" in normalized or "download complete:" in normalized


def should_remember_desktop_workflow(action_results: List[str]) -> bool:
    return (
        bool(action_results)
        and any(item.startswith("성공:") for item in action_results)
        and not any(item.startswith(("실패:", "오류:")) for item in action_results)
    )


def normalize_goal_hint(goal_hint: str) -> str:
    normalized = re.sub(r"\s+", " ", (goal_hint or "").strip().lower())
    return re.sub(r"[^a-z0-9가-힣 _-]", "", normalized)[:80]


def normalize_similarity_token(token: str) -> str:
    normalized = (token or "").strip().lower()
    for suffix in ("에서", "에게", "으로", "로", "까지", "부터", "하고", "후", "전", "에", "을", "를", "은", "는", "이", "가", "와", "과", "도", "만"):
        if normalized.endswith(suffix) and len(normalized) > len(suffix) + 1:
            return normalized[: -len(suffix)]
    return normalized


def tokenize_goal_hint(goal_hint: str) -> set[str]:
    tokens = set()
    for token in re.findall(r"[a-z0-9가-힣]+", (goal_hint or "").lower()):
        normalized = normalize_similarity_token(token)
        if len(normalized) >= 2:
            tokens.add(normalized)
    return tokens


def token_overlap_score(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    overlap = 0
    for token in left:
        if any(token == candidate or token in candidate or candidate in token for candidate in right):
            overlap += 1
    return overlap / max(len(left), len(right))


def find_similar_goal_key(key: str, mapping: dict) -> str:
    if not key or not mapping:
        return ""
    target_tokens = tokenize_goal_hint(key)
    best_key = ""
    best_score = 0.0
    for candidate in mapping:
        candidate_tokens = tokenize_goal_hint(candidate)
        if not target_tokens or not candidate_tokens:
            continue
        score = token_overlap_score(target_tokens, candidate_tokens)
        if score > best_score:
            best_score = score
            best_key = candidate
    return best_key if best_score >= 0.34 else ""


def merge_action_sequences(learned_actions: List[dict], fallback_actions: List[dict]) -> List[dict]:
    merged: List[dict] = []
    seen: set[str] = set()
    for action in [*(learned_actions or []), *(fallback_actions or [])]:
        if not isinstance(action, dict):
            continue
        fingerprint = fingerprint_action(action)
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        merged.append({str(key): value for key, value in action.items()})
    return merged


def fingerprint_action(action: dict) -> str:
    act_type = str(action.get("type", "")).strip().lower()
    target = (
        str(action.get("window", ""))
        or str(action.get("url", ""))
        or str(action.get("path", ""))
        or str(action.get("image_path", ""))
        or str(action.get("text", ""))[:40]
        or ",".join(map(str, action.get("keys", [])))
    )
    return f"{act_type}|{target.strip().lower()}"


def describe_action_plan(kind: str, goal_hint: str, actions: List[dict], reused: bool) -> str:
    action_types = [str(action.get("type", "")).strip() for action in actions if isinstance(action, dict)]
    action_text = ", ".join(action_types[:5])
    reused_text = "reused" if reused else "fallback"
    return f"{kind}:{reused_text}:{goal_hint} [{action_text}]"


def has_action_type(actions: List[dict], action_type: str) -> bool:
    target = (action_type or "").strip().lower()
    return any(
        str(action.get("type", "")).strip().lower() == target
        for action in actions
        if isinstance(action, dict)
    )


def augment_browser_plan_with_state(actions: List[dict], browser_state: dict, domain: str) -> List[dict]:
    augmented = list(actions or [])
    current_url = str((browser_state or {}).get("current_url", "") or "")
    current_title = str((browser_state or {}).get("title", "") or "")
    last_summary = str((browser_state or {}).get("last_action_summary", "") or "")

    if domain and not has_action_type(augmented, "wait_url"):
        augmented.insert(0, {"type": "wait_url", "contains": domain, "timeout": 10.0})
    if current_title and not has_action_type(augmented, "read_title"):
        augmented.append({"type": "read_title"})
    if current_url and not has_action_type(augmented, "read_url"):
        augmented.append({"type": "read_url"})
    if last_summary and "성공:" in last_summary and not has_action_type(augmented, "read_links"):
        augmented.append({"type": "read_links", "selector": "a", "limit": 5})
    return merge_action_sequences([], augmented)


def augment_desktop_plan_with_state(actions: List[dict], expected_window: str) -> List[dict]:
    augmented = list(actions or [])
    if expected_window and not has_action_type(augmented, "wait_window"):
        augmented.insert(0, {"type": "wait_window", "window": expected_window, "timeout": 10.0})
    if expected_window and not has_action_type(augmented, "focus"):
        augmented.insert(1 if augmented else 0, {"type": "focus", "window": expected_window})
    if not has_action_type(augmented, "wait"):
        augmented.append({"type": "wait", "seconds": 0.5})
    return merge_action_sequences([], augmented)


def action_plan_cache_key(actions: List[dict], *parts: str) -> str:
    normalized_parts = [str(part or "") for part in parts]
    return json.dumps(
        {
            "parts": normalized_parts,
            "actions": actions,
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def build_ranked_plans(
    plan_specs: List[tuple],
    *,
    goal_hint: str,
    summary_kind: str,
    base_fields: dict,
    augment_actions: Callable[[List[dict]], List[dict]],
    dedupe_key: Callable[[List[dict]], str],
    score_plan: Callable[[dict], float],
    describe_reason: Callable[[dict], str],
) -> List[dict]:
    plans: List[dict] = []
    seen_keys: set[str] = set()
    for plan_type, raw_actions, reused in plan_specs:
        if not raw_actions:
            continue
        actions = augment_actions(list(raw_actions))
        if not actions:
            continue
        cache_key = dedupe_key(actions)
        if cache_key in seen_keys:
            continue
        seen_keys.add(cache_key)
        plan = {
            "plan_type": plan_type,
            "goal_hint": goal_hint,
            **base_fields,
            "actions": actions,
            "summary": describe_action_plan(
                f"{summary_kind}:{plan_type}",
                goal_hint,
                actions,
                reused,
            ),
        }
        plan["score"] = score_plan(plan)
        plan["selection_reason"] = describe_reason(plan)
        plans.append(plan)
    return sorted(plans, key=plan_sort_key, reverse=True)
