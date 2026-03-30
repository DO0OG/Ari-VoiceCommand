from __future__ import annotations

import json
import os
import sys


def main() -> None:
    infected_files: list[str] = []
    if os.path.exists("clamav_result.txt"):
        with open("clamav_result.txt", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if "FOUND" in line:
                    infected_files.append(line.strip())

    if infected_files:
        result = {
            "passed": False,
            "stage": "virus_scan",
            "reason": "virus_detected",
            "infected_files": infected_files,
        }
        with open("clamav_fail.json", "w", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
        print(f"virus detected in {len(infected_files)} file(s)")
        sys.exit(1)

    print("clamav passed")


if __name__ == "__main__":
    main()
