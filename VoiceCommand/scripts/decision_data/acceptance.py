"""검수 코퍼스를 실제 명령 경로로 실행하고 안전하지 않은 결과를 센다.

각 문장은 배포 모델, fast 모드, 직접 실행을 켠 상태로 ``AICommand.run_interaction``을
거친다. 도구 처리기와 대화 모델은 호출 횟수만 세는 대체물로 바뀌므로 시스템 상태가
바뀌거나 네트워크 호출이 일어나지 않는다. 배포 빌드는 EXE 자체 검사가, 판단 경로는
이 도구가 확인한다.

    py -m scripts.decision_data.acceptance --output acceptance.json
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
from unittest.mock import Mock, patch

HERE = Path(__file__).resolve().parent
DEFAULT_CORPORA = (HERE / "release_gold.jsonl", HERE / "safety_gold.jsonl")
_SETTINGS = {
    "local_decision_mode": "fast",
    "local_decision_engine_enabled": True,
    "local_decision_backend": "linear",
    "local_decision_threshold": 0.92,
    "local_decision_direct_execution": True,
}
# 기존 음량 처리기는 양이 없으면 10씩 조절한다.
_DEFAULT_VOLUME_STEP = 10
# 반드시 직접 처리돼야 하는 평범한 요청이다. 모든 긍정 행이 대화 경로로
# 넘어가도 통과하는 일이 없게 한다.
_REQUIRED = (
    ("get_current_time", {}, {"ko": "지금 몇 시야", "en": "what time is it", "ja": "今何時"}),
    ("adjust_volume", {"direction": "up", "amount_percent": 10},
     {"ko": "볼륨 10 올려줘", "en": "turn the volume up by 10", "ja": "音量を10上げて"}),
    ("take_screenshot", {},
     {"ko": "화면 캡처해줘", "en": "take a screenshot", "ja": "スクリーンショットを撮って"}),
    ("get_running_apps", {},
     {"ko": "실행 중인 앱 알려줘", "en": "list running apps", "ja": "実行中のアプリを教えて"}),
)
DIRECT_REQUIRED_ROWS = tuple(
    {"id": f"required:{tool}:{language}", "corpus": "direct_required", "language": language,
     "text": text, "label": tool, "expected_outcome": "direct_required",
     "expected_arguments": dict(arguments)}
    for tool, arguments, texts in _REQUIRED
    for language, text in texts.items()
)


def _skill_context() -> dict:
    return {
        "skills": [],
        "prompt": "",
        "required_tool_names": [],
        "preferred_tool": "",
        "force_web_search": False,
        "escalate_to_agent": False,
        "search_query_template": "",
    }


def _arguments_match(tool: str, expected: dict, actual: dict) -> bool:
    """코퍼스의 의미 메타데이터와 별개로 처리기 인자를 확인한다."""
    if tool != "adjust_volume":
        # 시각·앱 목록·스크린샷 코퍼스의 기대값은 의도를 나타낼 뿐이고,
        # 기존 처리기는 인자를 받지 않는다.
        return not actual
    if set(actual) - {"direction", "amount"}:
        return False
    expected_amount = expected.get("amount_percent", _DEFAULT_VOLUME_STEP)
    return (
        expected.get("direction") == actual.get("direction")
        and expected_amount == actual.get("amount", _DEFAULT_VOLUME_STEP)
    )


def classify(row: dict, handler_calls: list[tuple[str, dict]], chat_calls: int) -> str:
    """문장 하나에 대해 ``direct``, ``fallback`` 또는 실패 종류를 반환한다."""
    if len(handler_calls) > 1 or (handler_calls and chat_calls):
        return "duplicate_action"
    if not handler_calls and not chat_calls:
        return "fallback_failure"
    if not handler_calls:
        return "direct_miss" if row.get("expected_outcome") == "direct_required" else "fallback"
    tool, arguments = handler_calls[0]
    if (
        row.get("expected_outcome") == "fallback_required"
        or tool != row.get("label")
        or not _arguments_match(tool, row.get("expected_arguments") or {}, arguments)
    ):
        return "direct_mistake"
    return "direct"


def _command():
    from commands.ai_command import AICommand

    assistant = Mock()
    assistant.chat_with_tools.return_value = ("fallback", [])
    command = AICommand(assistant, Mock(), {"enabled": False})
    command._get_skill_context = Mock(return_value=_skill_context())
    command._should_escalate_to_agent_task = Mock(return_value=False)
    command._record_user_pattern = Mock()
    command._recover_tool_calls_from_response = Mock(return_value=[])
    calls: list[tuple[str, dict]] = []

    def handler_for(name: str):
        def handler(arguments):
            calls.append((name, dict(arguments or {})))
            return "ok"
        return handler

    command._dispatch.update({name: handler_for(name) for name in list(command._dispatch)})
    return command, assistant, calls


def _rows(corpora: list[Path], required_rows) -> list[dict]:
    rows = [dict(row) for row in required_rows]
    for path in corpora:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                row.setdefault("corpus", path.stem)
                rows.append(row)
    # 검수자가 거절한 행은 배포 판정에 넣지 않는다.
    return [row for row in rows if row.get("review_status") != "human_rejected"]


def run(corpora: list[Path], required_rows=()) -> dict:
    from agent.decision.engine import LocalDecisionEngine
    from core.resource_manager import ResourceManager

    command, assistant, calls = _command()
    engine = LocalDecisionEngine(ResourceManager.get_bundle_path("resources/decision"))
    command._decision_engine = engine
    totals: Counter = Counter()
    by_group: dict[str, Counter] = {}
    failures: list[dict] = []
    with patch("core.config_manager.ConfigManager.get",
               side_effect=lambda key, default=None: _SETTINGS.get(key, default)), \
            patch("memory.conversation_history.add_conversation"), \
            patch("core.VoiceCommand.emit_plugin_event"):
        for row in _rows(corpora, required_rows):
            calls.clear()
            assistant.chat_with_tools.reset_mock()
            command.run_interaction(row["text"])
            outcome = classify(row, list(calls), assistant.chat_with_tools.call_count)
            group = f"{row['corpus']}:{row.get('language', '')}"
            totals[outcome] += 1
            by_group.setdefault(group, Counter())[outcome] += 1
            if outcome not in {"direct", "fallback"}:
                failures.append({"id": row.get("id"), "outcome": outcome})
    health = engine.health()
    return {
        "model_sha256": health.get("model_sha256", ""),
        "engine_state": health.get("state", ""),
        "corpora": [path.name for path in corpora],
        "totals": dict(totals),
        "by_corpus_language": {key: dict(value) for key, value in sorted(by_group.items())},
        "failures": failures,
        "passed": not failures and health.get("state") == "ready",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus", type=Path, action="append",
                        help="JSONL file with text, label, expected_outcome; repeatable")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = run(list(args.corpus or DEFAULT_CORPORA),
                 required_rows=() if args.corpus else DIRECT_REQUIRED_ROWS)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(json.dumps({"totals": result["totals"], "passed": result["passed"]}, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
