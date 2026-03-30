from __future__ import annotations

import glob
import json
import re
import sys


DANGER_RE = re.compile(r"\b(exec|eval|compile|__import__)\s*\(")


def load_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return default


def main() -> None:
    bandit_data = load_json("bandit_result.json", {"results": []})
    pylint_data = load_json("pylint_result.json", [])

    high_issues = [
        result
        for result in bandit_data.get("results", [])
        if result.get("issue_severity") in ("HIGH", "CRITICAL")
    ]
    errors = [result for result in pylint_data if result.get("type") == "error"]

    dangerous_patterns = []
    for path in glob.glob("./plugin/**/*.py", recursive=True):
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line_number, line in enumerate(handle, start=1):
                if DANGER_RE.search(line):
                    dangerous_patterns.append(
                        {"file": path, "line": line_number, "content": line.strip()}
                    )

    failed = bool(high_issues or len(errors) > 5 or dangerous_patterns)
    if failed:
        result = {
            "passed": False,
            "stage": "static_analysis",
            "reason": "static_analysis_failed",
            "bandit_high": high_issues,
            "pylint_errors": errors[:20],
            "dangerous_patterns": dangerous_patterns,
        }
        with open("static_fail.json", "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
        print(
            f"static analysis failed: bandit={len(high_issues)} "
            f"pylint={len(errors)} danger={len(dangerous_patterns)}"
        )
        sys.exit(1)

    print("static analysis passed")


if __name__ == "__main__":
    main()
