"""Ari 앱에서 마켓플레이스를 조회하고 설치하는 클라이언트."""
from __future__ import annotations

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
    return f"{safe}.py"


def fetch_plugins(search: str = "", sort: str = "install_count") -> List[Dict]:
    query = urllib.parse.urlencode({"search": search, "sort": sort})
    request = urllib.request.Request(_require_web_url(f"{MARKETPLACE_API}/get-plugins?{query}"))
    with urllib.request.urlopen(request) as response:  # nosec B310 - validated http/https request only
        payload = json.loads(response.read().decode("utf-8"))
    return payload.get("items", [])


def fetch_plugin(plugin_id: str) -> Dict:
    request = urllib.request.Request(_require_web_url(f"{MARKETPLACE_API}/get-plugin?plugin_id={plugin_id}"))
    with urllib.request.urlopen(request) as response:  # nosec B310 - validated http/https request only
        return json.loads(response.read().decode("utf-8"))


def install_plugin(plugin_id: str, plugin_dir: str) -> bool:
    request = urllib.request.Request(
        _require_web_url(f"{MARKETPLACE_API}/install-plugin"),
        data=json.dumps({"plugin_id": plugin_id}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:  # nosec B310 - validated http/https request only
        data = json.loads(response.read().decode("utf-8"))

    release_url = data.get("release_url")
    plugin_name = str(data.get("name", "") or "")
    entry = str(data.get("entry", "") or "")
    if not plugin_name or not entry:
        plugin_meta = fetch_plugin(plugin_id) or {}
        plugin_name = plugin_name or str(plugin_meta.get("name", "") or "")
        entry = entry or str(plugin_meta.get("entry", "") or "")
    if not release_url or not plugin_name or not entry:
        logger.error("install response incomplete for plugin %s", plugin_id)
        return False

    release_request = urllib.request.Request(_require_web_url(release_url))
    with urllib.request.urlopen(release_request) as response:  # nosec B310 - validated http/https request only
        content = response.read()

    os.makedirs(plugin_dir, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        if entry not in archive.namelist():
            logger.error("entry file missing in zip: %s", entry)
            return False
        target_path = os.path.join(plugin_dir, _plugin_target_filename(plugin_name))
        with archive.open(entry) as source, open(target_path, "wb") as output:
            output.write(source.read())

    logger.info("plugin installed: %s -> %s", plugin_id, plugin_dir)
    return True
