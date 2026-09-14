from __future__ import annotations

import glob
import json
import os
import re
from pathlib import Path


DANGER_RE = re.compile(r"\b(exec|eval|compile|__import__)\s*\(")
RESULT_PATH = Path("static_result.json")
FAIL_PATH = Path("static_fail.json")


def load_json(path: str):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def read_exit_code(name: str) -> int | None:
    value = os.environ.get(name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def write_result(result: dict) -> None:
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    RESULT_PATH.write_text(serialized, encoding="utf-8")
    if result["passed"]:
        FAIL_PATH.unlink(missing_ok=True)
    else:
        FAIL_PATH.write_text(serialized, encoding="utf-8")


def main() -> None:
    bandit_data = load_json("bandit_result.json")
    pylint_data = load_json("pylint_result.json")
    bandit_exit_code = read_exit_code("BANDIT_EXIT_CODE")
    pylint_exit_code = read_exit_code("PYLINT_EXIT_CODE")

    execution_errors: list[str] = []
    if bandit_exit_code is None:
        execution_errors.append("bandit exit code missing or invalid")
    elif bandit_exit_code < 0 or bandit_exit_code > 1:
        execution_errors.append(
            f"bandit execution failed with exit code {bandit_exit_code}"
        )
    if not isinstance(bandit_data, dict) or not isinstance(
        bandit_data.get("results"), list
    ):
        execution_errors.append("bandit result missing or invalid")
    elif not all(isinstance(item, dict) for item in bandit_data["results"]):
        execution_errors.append("bandit result entries are invalid")
    elif bandit_exit_code == 1 and not bandit_data["results"]:
        execution_errors.append(
            "bandit reported findings without result details"
        )
    elif bandit_exit_code == 0 and bandit_data["results"]:
        execution_errors.append("bandit returned success with result details")

    if pylint_exit_code is None:
        execution_errors.append("pylint exit code missing or invalid")
    elif pylint_exit_code < 0 or pylint_exit_code & ~31:
        execution_errors.append(
            f"pylint execution failed with exit code {pylint_exit_code}"
        )
    if not isinstance(pylint_data, list):
        execution_errors.append("pylint result missing or invalid")
    elif not all(isinstance(item, dict) for item in pylint_data):
        execution_errors.append("pylint result entries are invalid")
    elif (
        pylint_exit_code is not None
        and pylint_exit_code != 0
        and not pylint_data
    ):
        execution_errors.append(
            "pylint reported a nonzero result without details"
        )
    elif pylint_exit_code == 0 and pylint_data:
        execution_errors.append("pylint returned success with result details")

    if execution_errors:
        result = {
            "passed": False,
            "execution_succeeded": False,
            "threat_detected": False,
            "stage": "static_analysis",
            "reason": "static_analysis_execution_failed",
            "execution_errors": execution_errors,
            "bandit_exit_code": bandit_exit_code,
            "pylint_exit_code": pylint_exit_code,
        }
        write_result(result)
        print(
            "static analysis execution failed: " + "; ".join(execution_errors)
        )
        raise SystemExit(1)

    high_issues = [
        result
        for result in bandit_data["results"]
        if result.get("issue_severity") in ("HIGH", "CRITICAL")
    ]
    fatal_issues = [
        result for result in pylint_data if result.get("type") == "fatal"
    ]
    errors = [
        result for result in pylint_data if result.get("type") == "error"
    ]

    dangerous_patterns = []
    plugin_paths = glob.glob("./plugin/**/*.py", recursive=True)
    if not plugin_paths:
        result = {
            "passed": False,
            "execution_succeeded": False,
            "threat_detected": False,
            "stage": "static_analysis",
            "reason": "plugin_files_missing",
        }
        write_result(result)
        print("static analysis execution failed: plugin files missing")
        raise SystemExit(1)

    for path in plugin_paths:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line_number, line in enumerate(handle, start=1):
                if DANGER_RE.search(line):
                    dangerous_patterns.append(
                        {
                            "file": path,
                            "line": line_number,
                            "content": line.strip(),
                        }
                    )

    failed = bool(high_issues or fatal_issues or errors or dangerous_patterns)
    result = {
        "passed": not failed,
        "execution_succeeded": True,
        "threat_detected": bool(
            high_issues or fatal_issues or errors or dangerous_patterns
        ),
        "stage": "static_analysis",
        "reason": "static_analysis_failed" if failed else "clean",
        "bandit_high": high_issues,
        "pylint_fatal": fatal_issues,
        "pylint_errors": errors[:20],
        "dangerous_patterns": dangerous_patterns,
        "bandit_exit_code": bandit_exit_code,
        "pylint_exit_code": pylint_exit_code,
    }
    write_result(result)
    if failed:
        print(
            f"static analysis failed: bandit={len(high_issues)} "
            f"pylint={len(errors)} danger={len(dangerous_patterns)}"
        )
        raise SystemExit(1)

    print("static analysis passed")


if __name__ == "__main__":
    main()
