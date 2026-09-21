"""Derive and snapshot the local router candidate set from Ari's schemas.

The intent mapping is deliberately not copied here.  ``agent.tool_selection``
remains the source of intent membership and ``CORE_TOOL_SCHEMAS`` remains the
source of valid built-in tool names.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any


UNKNOWN_LABEL = "unknown_or_complex"


def _ensure_voicecommand_on_path() -> None:
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def _load_sources() -> tuple[dict[str, set[str]], list[dict[str, Any]]]:
    _ensure_voicecommand_on_path()
    from agent.tool_schemas import CORE_TOOL_SCHEMAS
    from agent.tool_selection import _TOOL_NAMES_BY_INTENT

    mapping = {
        str(intent): {str(name) for name in names}
        for intent, names in _TOOL_NAMES_BY_INTENT.items()
    }
    schemas = copy.deepcopy(CORE_TOOL_SCHEMAS)
    return mapping, schemas


def build_snapshot() -> dict[str, Any]:
    """Return a JSON-serializable, current snapshot of routing candidates."""

    mapping, schemas = _load_sources()
    schema_names = sorted(
        {
            str(schema["function"]["name"])
            for schema in schemas
            if isinstance(schema, dict)
            and isinstance(schema.get("function"), dict)
            and schema["function"].get("name")
        }
    )
    mapped_names = sorted(set().union(*mapping.values()) if mapping else set())
    supported = sorted(set(schema_names).intersection(mapped_names))
    return {
        "version": 1,
        "unknown_label": UNKNOWN_LABEL,
        "source": {
            "intent_mapping": "agent.tool_selection._TOOL_NAMES_BY_INTENT",
            "schemas": "agent.tool_schemas.CORE_TOOL_SCHEMAS",
        },
        "tool_names_by_intent": {
            intent: sorted(names) for intent, names in sorted(mapping.items())
        },
        "core_tool_names": schema_names,
        "mapped_tool_names": mapped_names,
        "candidate_labels": supported + [UNKNOWN_LABEL],
        "unsupported_schema_tools": sorted(set(schema_names) - set(mapped_names)),
        "stale_mapping_tools": sorted(set(mapped_names) - set(schema_names)),
        "core_tool_schemas": schemas,
    }


def candidate_names() -> tuple[str, ...]:
    """Return sorted supported tool names plus the mandatory abstain label."""

    snapshot = build_snapshot()
    return tuple(snapshot["candidate_labels"])


def write_snapshot(path: str | Path) -> dict[str, Any]:
    """Write a schema snapshot and return the snapshot."""

    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    snapshot = build_snapshot()
    output.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("candidate_snapshot.json"),
        help="JSON snapshot destination",
    )
    args = parser.parse_args(argv)
    snapshot = write_snapshot(args.output)
    print(json.dumps({
        "output": str(args.output),
        "candidate_count": len(snapshot["candidate_labels"]),
        "schema_count": len(snapshot["core_tool_names"]),
        "unsupported_schema_tools": snapshot["unsupported_schema_tools"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

