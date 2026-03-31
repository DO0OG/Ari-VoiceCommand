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
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

MARKETPLACE_API = os.environ.get(
    "ARI_MARKETPLACE_API",
    "https://zuaxkndycqrgswcygtnl.supabase.co/functions/v1",
)
SUPABASE_ANON_KEY = os.environ.get("ARI_SUPABASE_ANON_KEY") or os.environ.get("SUPABASE_ANON_KEY", "")

_BASE_HEADERS = {
    "Content-Type": "application/json",
    "apikey": SUPABASE_ANON_KEY,
}


def _require_web_url(url: str) -> str:
    """Bandit B310 대응: http/https URL만 허용한다."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"허용되지 않는 URL입니다: {url}")
    return url


def _get(url: str) -> dict:
    req = urllib.request.Request(_require_web_url(url), headers=_BASE_HEADERS)
    with urllib.request.urlopen(req) as resp:  # nosec B310 - _require_web_url enforces http/https only
        return json.loads(resp.read().decode("utf-8"))


def _post(url: str, body: dict) -> dict:
    req = urllib.request.Request(
        _require_web_url(url),
        data=json.dumps(body).encode("utf-8"),
        headers=_BASE_HEADERS,
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:  # nosec B310 - _require_web_url enforces http/https only
        return json.loads(resp.read().decode("utf-8"))


def _plugin_target_filename(plugin_name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", (plugin_name or "plugin").strip())
    safe = safe.strip("._") or "plugin"
    return f"{safe}.zip"


def _resolve_zip_plugin_metadata(archive: zipfile.ZipFile, plugin_name: str, entry: str) -> tuple[str, str]:
    resolved_name = plugin_name
    resolved_entry = entry

    try:
        with archive.open("plugin.json") as meta_file:
            meta = json.loads(meta_file.read().decode("utf-8"))
        resolved_name = str(meta.get("name", "") or resolved_name)
        resolved_entry = str(meta.get("entry", "") or resolved_entry)
    except Exception as exc:
        logger.debug("ZIP 내부 plugin.json 재확인 실패: %s", exc)

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
    """마켓플레이스 플러그인 목록 조회."""
    query = urllib.parse.urlencode({"search": search, "sort": sort})
    return _get(f"{MARKETPLACE_API}/get-plugins?{query}").get("items", [])


def fetch_plugin(plugin_id: str) -> Optional[Dict]:
    """특정 플러그인 상세 조회."""
    try:
        return _get(f"{MARKETPLACE_API}/get-plugin?plugin_id={plugin_id}")
    except Exception as e:
        logger.error("플러그인 조회 실패: %s", e)
        return None


def install_plugin(plugin_id: str, plugin_dir: Optional[str] = None) -> bool:
    """
    플러그인을 설치합니다.
    1. install-plugin 호출 → install_count 증가 + release_url 획득
    2. ZIP 다운로드 후 plugin_dir에 ZIP 그대로 저장
    3. 실행 중인 PluginManager에 동적 로드
    """
    # 1. install-plugin 호출
    try:
        data = _post(f"{MARKETPLACE_API}/install-plugin", {"plugin_id": plugin_id})
    except Exception as e:
        logger.error("install-plugin 호출 실패: %s", e)
        return False

    release_url = data.get("release_url")
    plugin_name = str(data.get("name", "") or "")
    entry = str(data.get("entry", "") or "")
    if not plugin_name or not entry:
        plugin_meta = fetch_plugin(plugin_id) or {}
        plugin_name = plugin_name or str(plugin_meta.get("name", "") or "")
        entry = entry or str(plugin_meta.get("entry", "") or "")
    if not release_url or not plugin_name or not entry:
        logger.error(
            "install-plugin 응답/상세정보 누락 (plugin_id=%s, release_url=%s, name=%s, entry=%s)",
            plugin_id,
            bool(release_url),
            plugin_name,
            entry,
        )
        return False

    # 2. plugin_dir 결정
    if plugin_dir is None:
        try:
            from core.plugin_loader import get_plugin_manager
            plugin_dir = get_plugin_manager().plugin_dir()
        except Exception:
            plugin_dir = os.path.join(
                os.path.expanduser("~"), "AppData", "Roaming", "Ari", "plugins"
            )

    os.makedirs(plugin_dir, exist_ok=True)

    # 3. ZIP 다운로드 및 압축 해제 (루트 레벨 .py 파일만)
    try:
        with urllib.request.urlopen(_require_web_url(release_url)) as resp:  # nosec B310 - validated release_url
            content = resp.read()
    except Exception as e:
        logger.error("ZIP 다운로드 실패: %s", e)
        return False

    installed_files: List[str] = []
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        plugin_name, entry = _resolve_zip_plugin_metadata(archive, plugin_name, entry)
        if entry not in archive.namelist():
            logger.error("ZIP에 entry 파일이 없습니다: %s", entry)
            return False
        target_name = _plugin_target_filename(plugin_name)
        target_path = os.path.join(plugin_dir, target_name)
        with open(target_path, "wb") as output:
            output.write(content)
        installed_files.append(target_name)

    legacy_path = os.path.join(plugin_dir, f"{os.path.splitext(installed_files[0])[0]}.py")
    if os.path.exists(legacy_path):
        try:
            os.remove(legacy_path)
        except OSError as exc:
            logger.warning("기존 단일 파일 플러그인 제거 실패: %s", exc)

    if not installed_files:
        logger.error("설치할 entry 파일이 없습니다.")
        return False

    logger.info("플러그인 설치 완료: %s → %s", installed_files, plugin_dir)

    # 4. 실행 중인 PluginManager에 동적 로드
    try:
        from core.plugin_loader import get_plugin_manager
        pm = get_plugin_manager()
        for fname in installed_files:
            path = os.path.join(plugin_dir, fname)
            pm.unload_plugin(plugin_name)
            pm.load_plugin(path)
            logger.info("플러그인 로드: %s", fname)
    except Exception as e:
        logger.warning("동적 로드 실패 (재시작 시 적용됨): %s", e)

    return True
