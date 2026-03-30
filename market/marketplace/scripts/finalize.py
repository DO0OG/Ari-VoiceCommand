from __future__ import annotations

import json
import os

import requests
from supabase import create_client


def load_json(path: str):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


def main() -> None:
    supabase = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    plugin_id = os.environ["PLUGIN_ID"]

    clamav_fail = load_json("clamav_fail.json")
    static_fail = load_json("static_fail.json")
    semgrep_result = load_json("semgrep_result_summary.json") or {
        "passed": False,
        "summary": "검사 결과 없음",
    }

    stages = {
        "virus_scan": {"passed": clamav_fail is None, "detail": clamav_fail},
        "static_analysis": {"passed": static_fail is None, "detail": static_fail},
        "semgrep_review": {
            "passed": bool(semgrep_result.get("passed")),
            "detail": semgrep_result,
        },
    }
    status = "approved" if all(stage["passed"] for stage in stages.values()) else "rejected"
    report = {
        "status": status,
        "stages": stages,
        "summary": semgrep_result.get("summary", ""),
    }

    update_payload = {
        "status": status,
        "review_report": report,
    }

    if status == "approved":
        plugin = (
            supabase.table("plugins")
            .select("zip_url, name, version")
            .eq("id", plugin_id)
            .single()
            .execute()
            .data
        )
        signed = supabase.storage.from_("plugin-uploads").create_signed_url(plugin["zip_url"], 60)
        content = requests.get(signed["signedURL"], timeout=30).content
        destination = f"{plugin['name']}-{plugin['version']}.zip"
        supabase.storage.from_("plugin-releases").upload(
            destination,
            content,
            {"content-type": "application/zip", "upsert": "true"},
        )
        update_payload["release_url"] = supabase.storage.from_("plugin-releases").get_public_url(destination)

    supabase.table("plugins").update(update_payload).eq("id", plugin_id).execute()

    try:
        requests.post(
            f"{os.environ['SUPABASE_URL']}/functions/v1/notify-developer",
            headers={
                "Authorization": f"Bearer {os.environ['SUPABASE_KEY']}",
                "Content-Type": "application/json",
            },
            json={"plugin_id": plugin_id, "status": status, "report": report},
            timeout=15,
        )
    except Exception as exc:
        print(f"notify-developer 호출 생략: {exc}")

    print(f"final status: {status}")


if __name__ == "__main__":
    main()
