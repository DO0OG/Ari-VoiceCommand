"""Ari 앱에서 마켓플레이스를 조회하고 설치하는 클라이언트."""
from __future__ import annotations

import io
import json
import logging
import os
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


def fetch_plugins(search: str = "", sort: str = "install_count") -> List[Dict]:
    query = urllib.parse.urlencode({"search": search, "sort": sort})
    with urllib.request.urlopen(_require_web_url(f"{MARKETPLACE_API}/get-plugins?{query}")) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload.get("items", [])


def install_plugin(plugin_id: str, plugin_dir: str) -> bool:
    request = urllib.request.Request(
        _require_web_url(f"{MARKETPLACE_API}/install-plugin"),
        data=json.dumps({"plugin_id": plugin_id}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        data = json.loads(response.read().decode("utf-8"))

    release_url = data.get("release_url")
    if not release_url:
        logger.error("release_url missing for plugin %s", plugin_id)
        return False

    with urllib.request.urlopen(_require_web_url(release_url)) as response:
        content = response.read()

    os.makedirs(plugin_dir, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        for member in archive.namelist():
            if member.endswith(".py") and "/" not in member and "\\" not in member:
                archive.extract(member, plugin_dir)

    logger.info("plugin installed: %s -> %s", plugin_id, plugin_dir)
    return True
