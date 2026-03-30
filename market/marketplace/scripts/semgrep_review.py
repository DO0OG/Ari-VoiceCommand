from __future__ import annotations

import glob
import json
import os
import re
import shutil
import subprocess


RULESETS = ["p/python", "p/secrets", "p/owasp-top-ten"]


def load_json(path: str, default):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return default


def _run_semgrep() -> None:
    semgrep_bin = os.environ.get("SEMGREP_BIN") or shutil.which("semgrep") or "semgrep"
    command = [
        semgrep_bin,
        "--config",
        ",".join(RULESETS),
        "./plugin",
        "--json",
        "--quiet",
        "--output",
        "semgrep_result.json",
    ]
    result = subprocess.run(command, check=False, capture_output=True, text=True)  # nosec B603
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        raise SystemExit(message or f"semgrep failed with exit code {result.returncode}")


def main() -> None:
    _run_semgrep()

    data = load_json("semgrep_result.json", {"results": []})
    findings = data.get("results", [])
    critical_high = [
        finding
        for finding in findings
        if finding.get("extra", {}).get("severity") in ("ERROR", "WARNING")
    ]
    low_info = [
        finding
        for finding in findings
        if finding.get("extra", {}).get("severity") == "INFO"
    ]

    meta = load_json("plugin_meta.json", {})
    declared_perms = set(meta.get("permissions", []))
    ari_issues = []

    for path in glob.glob("./plugin/**/*.py", recursive=True):
        src = open(path, encoding="utf-8", errors="replace").read()
        if "internet" not in declared_perms and re.search(
            r"\b(requests|urllib|httpx|aiohttp|socket)\b", src
        ):
            ari_issues.append(
                {
                    "file": path,
                    "severity": "high",
                    "type": "permissions_mismatch",
                    "description": "permissions에 internet 미선언이나 네트워크 코드 존재",
                }
            )
        if re.search(
            r'open\s*\(\s*["\'][^"\']*(?:\.\.[\\/]|[A-Z]:\\(?!Users\\[^\\]+\\AppData\\Roaming\\Ari))',
            src,
        ):
            ari_issues.append(
                {
                    "file": path,
                    "severity": "high",
                    "type": "filesystem_escape",
                    "description": "AppData\\Ari 외부 파일 접근 의심",
                }
            )

    entry_file = os.path.join("./plugin", meta.get("entry", "main.py"))
    if os.path.exists(entry_file):
        entry_src = open(entry_file, encoding="utf-8", errors="replace").read()
        if "PLUGIN_INFO" not in entry_src:
            ari_issues.append(
                {
                    "file": entry_file,
                    "severity": "medium",
                    "type": "missing_plugin_info",
                    "description": "PLUGIN_INFO 딕셔너리가 없음",
                }
            )
        if "def register(" not in entry_src:
            ari_issues.append(
                {
                    "file": entry_file,
                    "severity": "high",
                    "type": "missing_register",
                    "description": "register(context) 함수가 없음",
                }
            )

    all_issues = critical_high + ari_issues
    fatal = [
        item
        for item in all_issues
        if item.get("extra", {}).get("severity") == "ERROR"
        or item.get("severity") in ("high", "critical")
    ]

    result = {
        "passed": len(fatal) == 0,
        "risk_level": (
            "critical"
            if any(item.get("severity") == "critical" for item in ari_issues)
            else "high"
            if fatal
            else "medium"
            if all_issues
            else "low"
        ),
        "summary": (
            "치명적/높음 보안 이슈 없음"
            if len(fatal) == 0
            else f"치명적/높음 이슈 {len(fatal)}건 발견"
        ),
        "counts": {
            "fatal": len(fatal),
            "high_warning": len(critical_high),
            "info": len(low_info),
            "custom": len(ari_issues),
        },
        "issues": all_issues,
    }
    with open("semgrep_result_summary.json", "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False))
    if fatal:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
