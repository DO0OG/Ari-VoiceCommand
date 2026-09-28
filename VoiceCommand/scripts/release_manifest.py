import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
MIN_UPDATABLE_FROM = "1.0.0"
GITHUB_HOST = "github.com"


def validate_version(version: str) -> None:
    if VERSION_PATTERN.fullmatch(version) is None:
        raise ValueError("version must use major.minor.patch[-prerelease] format")


def validate_release_identity(version: str, tag: str) -> None:
    validate_version(version)
    if tag != f"v{version}":
        raise ValueError("release tag must equal v + manifest version")


def validate_github_url(value: str) -> None:
    if not isinstance(value, str):
        raise ValueError("release URLs must be strings")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.netloc != GITHUB_HOST
        or parsed.hostname != GITHUB_HOST
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("release URLs must use the HTTPS github.com host")


def canonical_urls(repository: str, tag: str, installer_name: str) -> tuple[str, str]:
    if REPOSITORY_PATTERN.fullmatch(repository) is None:
        raise ValueError("repository must use owner/repository format")
    base = f"https://{GITHUB_HOST}/{repository}"
    installer_url = f"{base}/releases/download/{tag}/{installer_name}"
    notes_url = f"{base}/releases/tag/{tag}"
    return installer_url, notes_url


def file_integrity(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def build_manifest(
    installer_path: Path,
    version: str,
    tag: str,
    repository: str,
    min_updatable_from: str = MIN_UPDATABLE_FROM,
    released_at: str | None = None,
) -> dict[str, object]:
    validate_release_identity(version, tag)
    validate_version(min_updatable_from)
    if not installer_path.is_file():
        raise ValueError("installer file does not exist")
    installer_name = f"Ari-Setup-{version}.exe"
    if installer_path.name != installer_name:
        raise ValueError("installer filename must match the release version")
    installer_url, notes_url = canonical_urls(repository, tag, installer_name)
    size, sha256 = file_integrity(installer_path)
    timestamp = released_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "schema": 1,
        "version": version,
        "released_at": timestamp,
        "installer": {
            "name": installer_name,
            "url": installer_url,
            "size": size,
            "sha256": sha256,
        },
        "min_updatable_from": min_updatable_from,
        "notes_url": notes_url,
    }


def validate_manifest(
    manifest: object,
    installer_path: Path,
    tag: str,
    repository: str,
) -> None:
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be a JSON object")
    version = manifest.get("version")
    if not isinstance(version, str):
        raise ValueError("manifest version is required")
    validate_release_identity(version, tag)
    if manifest.get("schema") != 1 or isinstance(manifest.get("schema"), bool):
        raise ValueError("manifest schema must be 1")
    released_at = manifest.get("released_at")
    if not isinstance(released_at, str):
        raise ValueError("manifest released_at is required")
    try:
        datetime.strptime(released_at, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise ValueError("released_at must be a UTC ISO timestamp") from error
    installer = manifest.get("installer")
    if not isinstance(installer, dict):
        raise ValueError("manifest installer is required")
    expected_name = f"Ari-Setup-{version}.exe"
    if installer_path.name != expected_name:
        raise ValueError("installer filename must match the release version")
    if installer.get("name") != expected_name:
        raise ValueError("installer name must be the versioned Ari installer filename")
    expected_url, expected_notes_url = canonical_urls(repository, tag, expected_name)
    installer_url = installer.get("url")
    notes_url = manifest.get("notes_url")
    validate_github_url(installer_url)
    validate_github_url(notes_url)
    if installer_url != expected_url or notes_url != expected_notes_url:
        raise ValueError("manifest URLs must be the canonical versioned GitHub release URLs")
    size = installer.get("size")
    sha256 = installer.get("sha256")
    if not isinstance(size, int) or isinstance(size, bool) or size < 0:
        raise ValueError("installer size must be a non-negative integer")
    if not isinstance(sha256, str) or SHA256_PATTERN.fullmatch(sha256) is None:
        raise ValueError("installer sha256 must be 64 lowercase hexadecimal characters")
    if not isinstance(manifest.get("min_updatable_from"), str):
        raise ValueError("min_updatable_from is required")
    validate_version(manifest["min_updatable_from"])
    actual_size, actual_sha256 = file_integrity(installer_path)
    if size != actual_size or sha256 != actual_sha256:
        raise ValueError("manifest installer size or sha256 does not match the installer")


def write_text(path: Path, value: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(value)


def validate_checksum_file(checksum_path: Path, installer_path: Path, sha256: str) -> None:
    expected = f"{sha256}  {installer_path.name}\n"
    if checksum_path.read_text(encoding="utf-8") != expected:
        raise ValueError("SHA256SUMS.txt does not match the installer")


def create_release_assets(
    installer_path: Path,
    version: str,
    tag: str | None,
    repository: str,
    output_dir: Path,
    min_updatable_from: str = MIN_UPDATABLE_FROM,
) -> Path | None:
    if tag is None:
        return None
    manifest = build_manifest(installer_path, version, tag, repository, min_updatable_from)
    validate_manifest(manifest, installer_path, tag, repository)
    output_dir.mkdir(parents=True, exist_ok=True)
    prerelease = "-" in version
    manifest_path = output_dir / ("update-beta.json" if prerelease else "update.json")
    checksum_path = output_dir / "SHA256SUMS.txt"
    write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    write_text(checksum_path, f"{manifest['installer']['sha256']}  {installer_path.name}\n")
    validate_checksum_file(checksum_path, installer_path, manifest["installer"]["sha256"])
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--installer", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--min-updatable-from", default=MIN_UPDATABLE_FROM)
    arguments = parser.parse_args()
    try:
        manifest_path = create_release_assets(
            arguments.installer,
            arguments.version,
            arguments.tag,
            arguments.repository,
            arguments.output_dir,
            arguments.min_updatable_from,
        )
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(f"Created release assets for {arguments.tag}: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
