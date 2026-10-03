"""SKILL.md 기반 에이전트 스킬 설치기."""
from __future__ import annotations

import io
import json
import logging
import ntpath
import os
import re
import shutil
import stat
import tempfile
import urllib.parse
import urllib.request
import uuid
import zipfile
from datetime import datetime, timezone
from typing import List, Optional
from core.atomic_io import write_json_atomic
from i18n.translator import _

logger = logging.getLogger(__name__)

_META_FILE_NAME = ".ari_skill_meta.json"
_UPDATE_JOURNAL = ".ari-update-journal.json"
_SKILL_FILE_NAME = "SKILL.md"
_ALLOWED_HOSTS = {
    "github.com",
    "raw.githubusercontent.com",
    "codeload.github.com",
}
_GITHUB_TREE_RE = re.compile(
    r"^(?:https://github\.com/)?(?P<owner>[^/\s]+)/(?P<repo>[^/\s]+)(?:/tree/(?P<branch>[^/\s]+)(?:/(?P<path>.+))?)?$",
    re.IGNORECASE,
)


def _slugify(value: str) -> str:
    text = re.sub(r"[^\w.-]+", "-", str(value or "").strip(), flags=re.UNICODE)
    return text.strip("-._") or "skill"


def _require_https_url(url: str) -> str:
    parsed = urllib.parse.urlparse(str(url or "").strip())
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"허용되지 않는 URL입니다: {url}")
    host = parsed.hostname or ""
    if host.lower() not in _ALLOWED_HOSTS:
        raise ValueError(f"허용되지 않는 호스트입니다: {host}")
    return parsed.geturl()


class SkillInstaller:
    """로컬/URL/GitHub 소스에서 스킬을 설치한다."""

    def __init__(self, skills_dir: str):
        self.skills_dir = skills_dir
        # update() 실행 중에만 채운다: 바뀐 스킬 폴더 → 보관 경로(새로 생긴 폴더는 None)
        self._update_backups: Optional[dict] = None
        os.makedirs(self.skills_dir, exist_ok=True)

    def install(self, source: str) -> List[str]:
        normalized = str(source or "").strip()
        if not normalized:
            raise ValueError("스킬 설치 원본이 비어 있습니다.")
        if os.path.isdir(normalized):
            return self._install_from_local_dir(normalized, normalized)
        if normalized.lower().startswith("https://"):
            return self._install_from_url(normalized, normalized)
        if _GITHUB_TREE_RE.match(normalized):
            return self._install_from_github(normalized, normalized)
        raise ValueError(f"지원하지 않는 스킬 원본입니다: {source}")

    def update(self, skill_dir: str) -> bool:
        if not os.path.isabs(skill_dir):
            skill_dir = os.path.join(self.skills_dir, skill_dir)
        meta_path = os.path.join(skill_dir, _META_FILE_NAME)
        try:
            with open(meta_path, "r", encoding="utf-8") as handle:
                metadata = json.load(handle)
        except Exception:
            return False
        source = str(metadata.get("source", "") or "").strip()
        if not source:
            return False
        was_enabled = bool(metadata.get("enabled", True))
        self._update_backups = {}
        enabled_by_name = {}
        for entry in os.listdir(self.skills_dir):
            meta_path = os.path.join(self.skills_dir, entry, _META_FILE_NAME)
            try:
                with open(meta_path, "r", encoding="utf-8") as handle:
                    enabled_by_name[entry] = bool(json.load(handle).get("enabled", True))
            except (OSError, ValueError, AttributeError):
                continue
        folder_name = os.path.basename(os.path.normpath(skill_dir))
        keep_journal = False
        try:
            installed_names = self.install(source)
            if folder_name not in installed_names:
                raise ValueError(_("skills.update_missing_existing"))
            for name in installed_names:
                enabled = was_enabled if name == folder_name else enabled_by_name.get(name, True)
                self._write_metadata(os.path.join(self.skills_dir, name), source, enabled=enabled)
            # 기록을 먼저 지운다. 백업을 지우다 종료돼도 반쯤 지워진 백업으로 되돌리지 않는다.
            self._clear_update_journal()
            for backup in self._update_backups.values():
                if backup:
                    shutil.rmtree(backup, ignore_errors=True)
            return True
        except Exception:
            # 한 폴더의 복구가 실패해도 나머지는 계속 되돌리고, 실패한 경로는 모아서 알린다.
            unrestored = []
            for destination, backup in reversed(tuple(self._update_backups.items())):
                try:
                    if backup:
                        if os.path.exists(backup):
                            shutil.rmtree(destination, ignore_errors=True)
                            os.replace(backup, destination)
                    elif os.path.exists(destination):
                        shutil.rmtree(destination, ignore_errors=True)
                        if os.path.exists(destination):
                            raise OSError("새 스킬 폴더를 지우지 못했습니다")
                except OSError as exc:
                    logger.warning("스킬 복구에 실패했습니다: %s (%s)", backup or destination, exc)
                    unrestored.append(backup or destination)
            if unrestored:
                # 되돌리지 못한 백업은 다음 시작 때 다시 복구를 시도하도록 기록을 남긴다.
                keep_journal = True
                raise RuntimeError(
                    _("skills.update_restore_failed").format(path=", ".join(unrestored))
                )
            raise
        finally:
            if not keep_journal:
                self._clear_update_journal()
            self._update_backups = None

    def _write_update_journal(self) -> None:
        entries = {
            os.path.basename(backup): os.path.basename(destination)
            for destination, backup in (self._update_backups or {}).items()
            if backup
        }
        path = os.path.join(self.skills_dir, _UPDATE_JOURNAL)
        if entries:
            write_json_atomic(path, entries, ensure_ascii=False, indent=2)
        else:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass

    def _clear_update_journal(self) -> None:
        try:
            os.unlink(os.path.join(self.skills_dir, _UPDATE_JOURNAL))
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.warning("스킬 업데이트 기록을 지우지 못했습니다: %s", exc)

    def _install_from_url(self, url: str, source_label: str) -> List[str]:
        validated = _require_https_url(url)
        with urllib.request.urlopen(urllib.request.Request(validated), timeout=30) as response:  # nosec B310
            content = response.read()
        if validated.lower().endswith(".zip"):
            return self._install_from_zip_bytes(content, source_label, None)

        parsed = urllib.parse.urlparse(validated)
        if parsed.path.lower().endswith("/skill.md"):
            folder_name = os.path.basename(os.path.dirname(parsed.path)) or "skill"
            with tempfile.TemporaryDirectory() as temp_dir:
                skill_dir = os.path.join(temp_dir, folder_name)
                os.makedirs(skill_dir, exist_ok=True)
                with open(os.path.join(skill_dir, _SKILL_FILE_NAME), "wb") as handle:
                    handle.write(content)
                return self._install_from_local_dir(skill_dir, source_label)
        raise ValueError("지원하지 않는 스킬 URL 형식입니다.")

    def _install_from_github(self, source: str, source_label: str) -> List[str]:
        match = _GITHUB_TREE_RE.match(source)
        if not match:
            raise ValueError(f"지원하지 않는 GitHub 스킬 경로입니다: {source}")
        owner = match.group("owner")
        repo = match.group("repo")
        branch = match.group("branch") or "main"
        subpath = match.group("path") or ""
        zip_url = f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/{branch}"
        with urllib.request.urlopen(urllib.request.Request(_require_https_url(zip_url)), timeout=30) as response:  # nosec B310
            content = response.read()
        return self._install_from_zip_bytes(content, source_label, subpath)

    def _install_from_zip_bytes(
        self,
        content: bytes,
        source_label: str,
        subpath: Optional[str],
    ) -> List[str]:
        installed: List[str] = []
        with tempfile.TemporaryDirectory() as temp_dir:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                root_prefix = self._zip_root_prefix(archive)
                normalized_subpath = str(subpath or "").strip("/\\")
                base_prefix = f"{root_prefix}{normalized_subpath}/" if normalized_subpath else root_prefix
                skill_dirs = self._discover_skill_dirs(archive, base_prefix)
                if not skill_dirs and normalized_subpath:
                    skill_dirs = self._discover_skill_dirs(archive, f"{base_prefix.rstrip('/')}/")
                if not skill_dirs:
                    raise ValueError("ZIP 안에서 SKILL.md를 찾지 못했습니다.")
                for skill_prefix in skill_dirs:
                    local_dir = self._extract_skill_dir(archive, skill_prefix, temp_dir)
                    installed.extend(self._install_from_local_dir(local_dir, source_label))
        return installed

    def _install_from_local_dir(self, source_dir: str, source_label: str) -> List[str]:
        source_dir = os.path.abspath(source_dir)
        skill_md = os.path.join(source_dir, _SKILL_FILE_NAME)
        if not os.path.isfile(skill_md):
            raise ValueError(f"SKILL.md를 찾지 못했습니다: {source_dir}")

        folder_name = _slugify(os.path.basename(source_dir))
        destination = os.path.join(self.skills_dir, folder_name)
        if os.path.abspath(source_dir) != os.path.abspath(destination):
            if self._update_backups is not None and destination not in self._update_backups:
                backup = None
                if os.path.isdir(destination):
                    backup = os.path.join(self.skills_dir, f".ari-update-backup-{uuid.uuid4().hex}")
                    self._update_backups[destination] = backup
                    self._write_update_journal()
                    os.replace(destination, backup)
                else:
                    self._update_backups[destination] = backup
            shutil.rmtree(destination, ignore_errors=True)
            shutil.copytree(
                source_dir,
                destination,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        self._write_metadata(destination, source_label)
        logger.info("[SkillInstaller] 스킬 설치 완료: %s", folder_name)
        return [folder_name]

    def _write_metadata(self, skill_dir: str, source_label: str, enabled: bool = True) -> None:
        metadata = {
            "enabled": enabled,
            "source": source_label,
            "installed_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        }
        with open(os.path.join(skill_dir, _META_FILE_NAME), "w", encoding="utf-8") as handle:
            json.dump(metadata, handle, ensure_ascii=False, indent=2)

    def _zip_root_prefix(self, archive: zipfile.ZipFile) -> str:
        names = [name for name in archive.namelist() if name]
        first = names[0] if names else ""
        if "/" not in first:
            return ""
        return first.split("/", 1)[0] + "/"

    def _discover_skill_dirs(self, archive: zipfile.ZipFile, base_prefix: str) -> List[str]:
        prefixes: List[str] = []
        normalized_base = base_prefix.strip("/")
        normalized_base = f"{normalized_base}/" if normalized_base else ""
        for name in archive.namelist():
            normalized_name = name.strip("/")
            if normalized_base and not normalized_name.startswith(normalized_base):
                continue
            if not normalized_name.endswith(f"/{_SKILL_FILE_NAME}") and normalized_name != _SKILL_FILE_NAME:
                continue
            folder = normalized_name[: -len(_SKILL_FILE_NAME)].rstrip("/")
            if folder and folder not in prefixes:
                prefixes.append(folder + "/")
        return prefixes

    def _extract_skill_dir(self, archive: zipfile.ZipFile, prefix: str, temp_dir: str) -> str:
        for member in archive.infolist():
            name = member.filename.replace("\\", "/")
            if (
                name.startswith("/")
                or ntpath.splitdrive(name)[0]
                or ".." in name.split("/")
                or ":" in name
                or stat.S_ISLNK(member.external_attr >> 16)
            ):
                raise ValueError(f"Unsafe ZIP entry: {member.filename}")
        normalized_prefix = prefix.strip("/") + "/"
        relative_root = os.path.basename(normalized_prefix.rstrip("/")) or "skill"
        target_root = os.path.realpath(os.path.join(temp_dir, relative_root))
        if os.path.commonpath([os.path.realpath(temp_dir), target_root]) != os.path.realpath(temp_dir):
            raise ValueError("Unsafe ZIP extraction root")
        os.makedirs(target_root, exist_ok=True)
        for member in archive.namelist():
            normalized_member = member.replace("\\", "/")
            if not normalized_member.startswith(normalized_prefix):
                continue
            relative_path = normalized_member[len(normalized_prefix) :]
            if not relative_path:
                continue
            destination = os.path.realpath(os.path.join(target_root, relative_path))
            if os.path.commonpath([target_root, destination]) != target_root:
                raise ValueError(f"Unsafe ZIP destination: {member}")
            if member.endswith("/"):
                os.makedirs(destination, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            with archive.open(member) as source_handle, open(destination, "wb") as destination_handle:
                shutil.copyfileobj(source_handle, destination_handle)
        return target_root
