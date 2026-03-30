"""Ari 앱에서 마켓플레이스를 조회하고 설치하는 클라이언트."""
from __future__ import annotations

import io
import json
import logging
import os
import urllib.parse
import urllib.request
import zipfile
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

MARKETPLACE_API = os.environ.get(
    "ARI_MARKETPLACE_API",
    "https://zuaxkndycqrgswcygtnl.supabase.co/functions/v1",
)
SUPABASE_ANON_KEY = os.environ.get(
    "ARI_SUPABASE_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inp1YXhrbmR5Y3FyZ3N3Y3lndG5sIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDMzMDM3MTQsImV4cCI6MjA1ODg3OTcxNH0.o-nIYgLdFkq9nfMqgBHyXMnJLmJCFhYrPZyv6p2jTfY",
)

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
    2. ZIP 다운로드 후 plugin_dir에 .py 파일 추출
    3. 실행 중인 PluginManager에 동적 로드
    """
    # 1. install-plugin 호출
    try:
        data = _post(f"{MARKETPLACE_API}/install-plugin", {"plugin_id": plugin_id})
    except Exception as e:
        logger.error("install-plugin 호출 실패: %s", e)
        return False

    release_url = data.get("release_url")
    if not release_url:
        logger.error("release_url 없음 (plugin_id=%s)", plugin_id)
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
        for member in archive.namelist():
            if member.endswith(".py") and "/" not in member and "\\" not in member:
                archive.extract(member, plugin_dir)
                installed_files.append(member)

    if not installed_files:
        logger.error("설치할 .py 파일이 없습니다.")
        return False

    logger.info("플러그인 설치 완료: %s → %s", installed_files, plugin_dir)

    # 4. 실행 중인 PluginManager에 동적 로드
    try:
        from core.plugin_loader import get_plugin_manager
        pm = get_plugin_manager()
        for fname in installed_files:
            path = os.path.join(plugin_dir, fname)
            pm.load_plugin(path)
            logger.info("플러그인 로드: %s", fname)
    except Exception as e:
        logger.warning("동적 로드 실패 (재시작 시 적용됨): %s", e)

    return True
