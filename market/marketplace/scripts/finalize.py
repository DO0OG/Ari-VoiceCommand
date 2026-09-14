from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any

import requests
from supabase import create_client


def load_json(path: str):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def scan_stage(path: str, stage: str) -> dict[str, Any]:
    result = load_json(path)
    if not isinstance(result, dict):
        return {
            "passed": False,
            "detail": {
                "stage": stage,
                "passed": False,
                "reason": "scan_result_missing_or_invalid",
            },
        }

    passed = (
        result.get("passed") is True
        and result.get("execution_succeeded") is True
        and result.get("threat_detected") is False
    )
    return {"passed": passed, "detail": result}


def expected_artifact() -> dict[str, str]:
    return {
        "developer_id": os.environ.get("DEVELOPER_ID", ""),
        "submission_id": os.environ.get("SUBMISSION_ID", ""),
        "version": os.environ.get("PLUGIN_VERSION", ""),
        "sha256": os.environ.get("PLUGIN_SHA256", "").lower(),
    }


def artifact_stage(
    plugin: object, snapshot: object, expected: dict[str, str]
) -> dict[str, Any]:
    errors: list[str] = []
    if not expected["developer_id"]:
        errors.append("developer id missing")
    if not expected["submission_id"]:
        errors.append("submission id missing")
    if not expected["version"]:
        errors.append("plugin version missing")
    if not re.fullmatch(r"[0-9a-f]{64}", expected["sha256"]):
        errors.append("plugin sha256 missing or invalid")
    if not isinstance(snapshot, dict):
        errors.append("downloaded plugin metadata missing or invalid")
    if not isinstance(plugin, dict):
        errors.append("current plugin record missing or invalid")

    detail: dict[str, Any] = {"expected": expected, "errors": errors}
    if errors:
        return {"passed": False, "detail": detail}

    assert isinstance(snapshot, dict)
    assert isinstance(plugin, dict)
    snapshot_path = snapshot.get("zip_url")
    current_path = plugin.get("zip_url")
    checks = {
        "submission_id": (
            snapshot.get("submission_id"),
            plugin.get("submission_id"),
            expected["submission_id"],
        ),
        "version": (
            snapshot.get("version"),
            plugin.get("version"),
            expected["version"],
        ),
        "sha256": (
            str(snapshot.get("sha256", "")).lower(),
            str(plugin.get("sha256", "")).lower(),
            expected["sha256"],
        ),
        "name": (
            snapshot.get("name"),
            plugin.get("name"),
            snapshot.get("name"),
        ),
        "developer_id": (
            snapshot.get("developer_id"),
            plugin.get("developer_id"),
            snapshot.get("developer_id"),
        ),
        "zip_url": (snapshot_path, current_path, snapshot_path),
    }
    for field, (snapshot_value, current_value, expected_value) in checks.items():
        if (
            not snapshot_value
            or snapshot_value != current_value
            or snapshot_value != expected_value
        ):
            errors.append(f"{field} does not match the submitted artifact")

    expected_prefix = f"{expected['developer_id']}/"
    if not isinstance(snapshot_path, str) or not snapshot_path.startswith(
        expected_prefix
    ):
        errors.append("upload path does not belong to the submitting user")

    detail.update(
        {
            "snapshot_submission_id": snapshot.get("submission_id"),
            "current_submission_id": plugin.get("submission_id"),
            "snapshot_version": snapshot.get("version"),
            "current_version": plugin.get("version"),
            "snapshot_sha256": snapshot.get("sha256"),
            "current_sha256": plugin.get("sha256"),
            "zip_url": snapshot_path,
            "errors": errors,
        }
    )
    return {"passed": not errors, "detail": detail}


def fetch_current_plugin(supabase, plugin_id: str):
    return (
        supabase.table("plugins")
        .select(
            "id, developer_id, name, version, zip_url, sha256, submission_id"
        )
        .eq("id", plugin_id)
        .single()
        .execute()
        .data
    )


def download_checked(
    supabase, source_path: str, expected_sha256: str
) -> bytes:
    signed = supabase.storage.from_("plugin-uploads").create_signed_url(
        source_path, 60
    )
    signed_url = signed.get("signedURL") or signed.get("signed_url")
    if not signed_url:
        raise RuntimeError("source upload signed URL missing")
    response = requests.get(signed_url, timeout=30)
    response.raise_for_status()
    content = response.content
    actual_sha256 = hashlib.sha256(content).hexdigest()
    if actual_sha256 != expected_sha256:
        raise RuntimeError("source upload hash changed during validation")
    return content


def update_current_submission(
    supabase, plugin_id: str, submission: dict[str, str], payload: dict
) -> None:
    response = (
        supabase.table("plugins")
        .update(payload)
        .eq("id", plugin_id)
        .eq("developer_id", submission["record_developer_id"])
        .eq("submission_id", submission["submission_id"])
        .eq("version", submission["version"])
        .eq("sha256", submission["sha256"])
        .eq("name", submission["name"])
        .eq("zip_url", submission["zip_url"])
        .select("id")
        .execute()
    )
    if not response.data:
        raise RuntimeError("plugin submission changed during validation")


def main() -> None:
    supabase = create_client(
        os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"]
    )
    plugin_id = os.environ["PLUGIN_ID"]
    expected = expected_artifact()

    stages = {
        "virus_scan": scan_stage("clamav_result.json", "virus_scan"),
        "static_analysis": scan_stage("static_result.json", "static_analysis"),
    }
    semgrep_result = load_json("semgrep_result_summary.json")
    if not isinstance(semgrep_result, dict):
        semgrep_result = {"passed": False, "summary": "검사 결과 없음"}
    stages["semgrep_review"] = {
        "passed": semgrep_result.get("passed") is True,
        "detail": semgrep_result,
    }

    snapshot = load_json("plugin_meta.json")
    try:
        plugin = fetch_current_plugin(supabase, plugin_id)
    except Exception as exc:
        plugin = None
        fetch_error = str(exc)
    else:
        fetch_error = ""

    stages["artifact_consistency"] = artifact_stage(plugin, snapshot, expected)
    if fetch_error:
        stages["artifact_consistency"]["passed"] = False
        stages["artifact_consistency"]["detail"]["errors"].append(
            f"current plugin lookup failed: {fetch_error}"
        )

    content: bytes | None = None
    if all(stage["passed"] for stage in stages.values()):
        assert isinstance(snapshot, dict)
        try:
            content = download_checked(
                supabase, snapshot["zip_url"], expected["sha256"]
            )
        except Exception as exc:
            stages["artifact_consistency"] = {
                "passed": False,
                "detail": {
                    **stages["artifact_consistency"]["detail"],
                    "errors": [f"validated upload download failed: {exc}"],
                },
            }

    status = (
        "approved" if all(stage["passed"] for stage in stages.values()) else "rejected"
    )
    report = {
        "status": status,
        "stages": stages,
        "summary": semgrep_result.get("summary", ""),
    }
    update_payload = {"status": status, "review_report": report}

    if status == "approved":
        assert content is not None
        assert isinstance(plugin, dict)
        destination = (
            f"{plugin['name']}-{plugin['version']}-{expected['submission_id']}.zip"
        )
        upload_result = supabase.storage.from_("plugin-releases").upload(
            destination,
            content,
            {"content-type": "application/zip", "upsert": "false"},
        )
        if getattr(upload_result, "error", None):
            raise RuntimeError(upload_result.error.message)
        update_payload["release_url"] = supabase.storage.from_(
            "plugin-releases"
        ).get_public_url(destination)
        update_payload["sha256"] = expected["sha256"]

    submission: dict[str, str] = {
        **expected,
        "name": (
            str(snapshot.get("name", "")) if isinstance(snapshot, dict) else ""
        ),
        "zip_url": (
            str(snapshot.get("zip_url", "")) if isinstance(snapshot, dict) else ""
        ),
        "record_developer_id": (
            str(snapshot.get("developer_id", ""))
            if isinstance(snapshot, dict)
            else ""
        ),
    }
    update_current_submission(supabase, plugin_id, submission, update_payload)

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
