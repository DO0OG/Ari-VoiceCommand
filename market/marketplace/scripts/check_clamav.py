from __future__ import annotations

import json
import os
import sys
from pathlib import Path


RESULT_PATH = Path("clamav_result.json")
FAIL_PATH = Path("clamav_fail.json")


def _scan_exit_code() -> int | None:
    value = os.environ.get("CLAMAV_EXIT_CODE")
    if value is None and len(sys.argv) > 1:
        value = sys.argv[1]
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _write_result(result: dict) -> None:
    serialized = json.dumps(result, ensure_ascii=False, indent=2)
    RESULT_PATH.write_text(serialized, encoding="utf-8")
    if result["passed"]:
        FAIL_PATH.unlink(missing_ok=True)
    else:
        FAIL_PATH.write_text(serialized, encoding="utf-8")


def main() -> None:
    infected_files: list[str] = []
    result_path = Path("clamav_result.txt")
    if result_path.is_file():
        with result_path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if "FOUND" in line:
                    infected_files.append(line.strip())

    exit_code = _scan_exit_code()
    if exit_code is None:
        result = {
            "passed": False,
            "execution_succeeded": False,
            "threat_detected": False,
            "stage": "virus_scan",
            "reason": "scan_exit_code_missing",
        }
    elif not result_path.is_file():
        result = {
            "passed": False,
            "execution_succeeded": False,
            "threat_detected": False,
            "stage": "virus_scan",
            "reason": "scan_result_missing",
            "scan_exit_code": exit_code,
        }
    elif exit_code not in (0, 1):
        result = {
            "passed": False,
            "execution_succeeded": False,
            "threat_detected": False,
            "stage": "virus_scan",
            "reason": "scan_execution_failed",
            "scan_exit_code": exit_code,
        }
    elif infected_files:
        result = {
            "passed": False,
            "execution_succeeded": True,
            "threat_detected": True,
            "stage": "virus_scan",
            "reason": "virus_detected",
            "infected_files": infected_files,
            "scan_exit_code": exit_code,
        }
    elif exit_code == 1:
        result = {
            "passed": False,
            "execution_succeeded": False,
            "threat_detected": False,
            "stage": "virus_scan",
            "reason": "scan_result_incomplete",
            "scan_exit_code": exit_code,
        }
    else:
        result = {
            "passed": True,
            "execution_succeeded": True,
            "threat_detected": False,
            "stage": "virus_scan",
            "reason": "clean",
            "scan_exit_code": exit_code,
        }

    _write_result(result)
    if result["passed"]:
        print("clamav passed")
        return
    if result.get("reason") == "virus_detected":
        print(f"virus detected in {len(infected_files)} file(s)")
    else:
        print(f"clamav validation failed: {result['reason']}")
    raise SystemExit(1)


if __name__ == "__main__":
    main()
