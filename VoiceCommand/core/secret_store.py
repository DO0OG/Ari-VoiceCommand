"""사용자 계정에 묶인 별도 비밀 저장소. 평문 저장 대체 경로는 없다."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

from core.settings_schema import SENSITIVE_SETTINGS_KEYS


class SecretStoreError(RuntimeError):
    """비밀값을 포함하지 않는 저장소 오류."""


def _protect(data: bytes) -> bytes:
    if sys.platform != "win32":
        raise SecretStoreError("Encrypted storage requires Windows; use environment variables")
    try:
        import win32crypt
        return win32crypt.CryptProtectData(data, "Ari credentials", None, None, None, 1)
    except Exception:
        raise SecretStoreError("Credential encryption failed") from None


def _unprotect(data: bytes) -> bytes:
    if sys.platform != "win32":
        raise SecretStoreError("Encrypted storage requires Windows; use environment variables")
    try:
        import win32crypt
        return win32crypt.CryptUnprotectData(data, None, None, None, 1)[1]
    except Exception:
        raise SecretStoreError("Credential decryption failed") from None


def _write_encrypted(path: Path, data: bytes) -> None:
    """암호화·복호화 검증이 끝난 바이트만 원자적으로 기록한다."""
    encrypted = _protect(data)
    if _unprotect(encrypted) != data:
        raise SecretStoreError("Encrypted data verification failed")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = handle.name
            handle.write(encrypted)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            os.unlink(temporary)


class SecretStore:
    """암호화된 숫자·문자열 직렬화만 다루고 복호화 실패 파일은 보존한다."""

    def __init__(self, settings_path: str | Path):
        self.settings_path = Path(settings_path)
        self.path = self.settings_path.with_name("ari_secrets.dpapi")

    def read(self) -> dict[str, str]:
        try:
            encrypted = self.path.read_bytes()
        except FileNotFoundError:
            return {}
        except OSError:
            raise SecretStoreError("Credential store cannot be read") from None
        try:
            payload = json.loads(_unprotect(encrypted).decode("utf-8"))
            if payload["version"] != 1 or not isinstance(payload["secrets"], dict):
                raise ValueError()
            values = payload["secrets"]
            if any(key not in SENSITIVE_SETTINGS_KEYS or not isinstance(value, str)
                   for key, value in values.items()):
                raise ValueError()
            return values
        except Exception:
            raise SecretStoreError("Credential store cannot be decrypted") from None

    def write(self, values: dict[str, str]) -> None:
        if any(key not in SENSITIVE_SETTINGS_KEYS or not isinstance(value, str)
               for key, value in values.items()):
            raise SecretStoreError("Invalid credential fields")
        payload = json.dumps({"version": 1, "secrets": values}, ensure_ascii=False).encode("utf-8")
        _write_encrypted(self.path, payload)

    def restore(self, encrypted: bytes | None) -> None:
        """이전 암호문으로 되돌린다. 이전 상태가 없었다면 파일을 제거한다."""
        if encrypted is None:
            self.path.unlink(missing_ok=True)
            return
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path.parent, delete=False) as handle:
                temporary = handle.name
                handle.write(encrypted)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            temporary = None
        finally:
            if temporary is not None:
                os.unlink(temporary)

    def backup(self, original: bytes) -> Path:
        """마이그레이션 전 원본 전체를 암호화해 보관한다."""
        fingerprint = hashlib.sha256(original).hexdigest()[:16]
        backup = self.settings_path.with_name(f"ari_settings.pre-secrets.{fingerprint}.dpapi")
        if backup.exists():
            if _unprotect(backup.read_bytes()) != original:
                raise SecretStoreError("Credential backup verification failed")
        else:
            _write_encrypted(backup, original)
        return backup
