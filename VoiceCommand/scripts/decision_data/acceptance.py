"""Run review corpora through the real command path and count unsafe outcomes.

Each sentence goes through ``AICommand.run_interaction`` with the bundled model, fast
mode and direct execution switched on. Tool handlers and the conversation model are
replaced by counters, so nothing on the machine changes and no network call is made.
The EXE self-test covers the packaged build; this harness covers the decision path.

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
# The existing volume handler steps by 10 when no amount is given.
_DEFAULT_VOLUME_STEP = 10


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
    """Only volume carries arguments the handler acts on; other tools take none."""
    if tool != "adjust_volume":
        return True
    if expected.get("direction") != actual.get("direction"):
        return False
    if "amount_percent" in expected:
        return expected["amount_percent"] == actual.get("amount", _DEFAULT_VOLUME_STEP)
    return True


def classify(row: dict, handler_calls: list[tuple[str, dict]], chat_calls: int) -> str:
    """Return ``direct``, ``fallback`` or the failure kind for one sentence."""
    if len(handler_calls) > 1 or (handler_calls and chat_calls):
        return "duplicate_action"
    if not handler_calls and not chat_calls:
        return "fallback_failure"
    if not handler_calls:
        return "fallback"
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


def run(corpora: list[Path]) -> dict:
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
        for path in corpora:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                calls.clear()
                assistant.chat_with_tools.reset_mock()
                command.run_interaction(row["text"])
                outcome = classify(row, list(calls), assistant.chat_with_tools.call_count)
                group = f"{row.get('corpus', path.stem)}:{row.get('language', '')}"
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
    result = run(list(args.corpus or DEFAULT_CORPORA))
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    print(json.dumps({"totals": result["totals"], "passed": result["passed"]}, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
