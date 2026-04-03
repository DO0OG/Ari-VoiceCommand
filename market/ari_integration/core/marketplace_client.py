"""Ari 앱에서 마켓플레이스를 조회하고 설치하는 클라이언트."""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import urllib.parse
import urllib.request
import zipfile
from typing import Dict, List


logger = logging.getLogger(__name__)

MARKETPLACE_API = os.environ.get(
    "ARI_MARKETPLACE_API",
    "https://your-project.supabase.co/functions/v1",
)


def _require_web_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"허용되지 않는 URL입니다: {url}")
    return url


def _plugin_target_filename(plugin_name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", (plugin_name or "plugin").strip())
    safe = safe.strip("._") or "plugin"
    return f"{safe}.zip"


def _compute_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _resolve_zip_plugin_metadata(archive: zipfile.ZipFile, plugin_name: str, entry: str) -> tuple[str, str]:
    resolved_name = plugin_name
    resolved_entry = entry

    try:
        with archive.open("plugin.json") as meta_file:
            meta = json.loads(meta_file.read().decode("utf-8"))
        resolved_name = str(meta.get("name", "") or resolved_name)
        resolved_entry = str(meta.get("entry", "") or resolved_entry)
    except Exception as exc:
        logger.debug("failed to read plugin.json from zip: %s", exc)

    root_python_files = [
        name for name in archive.namelist()
        if name.endswith(".py") and "/" not in name and "\\" not in name
    ]
    if resolved_entry not in archive.namelist():
        if len(root_python_files) == 1:
            resolved_entry = root_python_files[0]
        elif _plugin_target_filename(resolved_name) in root_python_files:
            resolved_entry = _plugin_target_filename(resolved_name)

    return resolved_name, resolved_entry


def fetch_plugins(search: str = "", sort: str = "install_count") -> List[Dict]:
    query = urllib.parse.urlencode({"search": search, "sort": sort})
    request = urllib.request.Request(_require_web_url(f"{MARKETPLACE_API}/get-plugins?{query}"))
    # URL scheme/host validation is handled by _require_web_url().
    with urllib.request.urlopen(request) as response:  # nosec B310
        payload = json.loads(response.read().decode("utf-8"))
    return payload.get("items", [])


def fetch_plugin(plugin_id: str) -> Dict:
    request = urllib.request.Request(_require_web_url(f"{MARKETPLACE_API}/get-plugin?plugin_id={plugin_id}"))
    # URL scheme/host validation is handled by _require_web_url().
    with urllib.request.urlopen(request) as response:  # nosec B310
        return json.loads(response.read().decode("utf-8"))


def install_plugin(plugin_id: str, plugin_dir: str) -> bool:
    request = urllib.request.Request(
        _require_web_url(f"{MARKETPLACE_API}/install-plugin"),
        data=json.dumps({"plugin_id": plugin_id}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    # URL scheme/host validation is handled by _require_web_url().
    with urllib.request.urlopen(request) as response:  # nosec B310
        data = json.loads(response.read().decode("utf-8"))

    release_url = data.get("release_url")
    plugin_name = str(data.get("name", "") or "")
    entry = str(data.get("entry", "") or "")
    sha256 = str(data.get("sha256", "") or "")
    if not plugin_name or not entry or not sha256:
        plugin_meta = fetch_plugin(plugin_id) or {}
        plugin_name = plugin_name or str(plugin_meta.get("name", "") or "")
        entry = entry or str(plugin_meta.get("entry", "") or "")
        sha256 = sha256 or str(plugin_meta.get("sha256", "") or "")
    if not release_url or not plugin_name or not entry or not sha256:
        logger.error("install response incomplete for plugin %s", plugin_id)
        return False

    release_request = urllib.request.Request(_require_web_url(release_url))
    # URL scheme/host validation is handled by _require_web_url().
    with urllib.request.urlopen(release_request) as response:  # nosec B310
        content = response.read()
    if _compute_sha256(content) != sha256:
        logger.error("sha256 verification failed for plugin %s", plugin_id)
        return False

    os.makedirs(plugin_dir, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        plugin_name, entry = _resolve_zip_plugin_metadata(archive, plugin_name, entry)
        if entry not in archive.namelist():
            logger.error("entry file missing in zip: %s", entry)
            return False
        target_path = os.path.join(plugin_dir, _plugin_target_filename(plugin_name))
        with open(target_path, "wb") as output:
            output.write(content)

    legacy_path = os.path.join(plugin_dir, f"{os.path.splitext(_plugin_target_filename(plugin_name))[0]}.py")
    if os.path.exists(legacy_path):
        try:
            os.remove(legacy_path)
        except OSError as exc:
            logger.warning("failed to remove legacy plugin file: %s", exc)

    logger.info("plugin installed: %s -> %s", plugin_id, plugin_dir)
    return True
