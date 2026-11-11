"""파일 백업 복구 이력을 색인 파일에 저장하고 읽는다."""
import json
import logging
import os
import time
from typing import Dict, List, Optional

from core.atomic_io import backup_corrupt_file, write_json_atomic


def _read_backup_history(index_path: str) -> Optional[List[Dict[str, str]]]:
    """색인을 읽는다. 일시적으로 읽지 못하면 None, 손상됐으면 빈 이력이다."""
    if not os.path.isfile(index_path):
        return []
    try:
        with open(index_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, list):
            raise ValueError("백업 이력 형식이 올바르지 않습니다.")
    except OSError as exc:
        logging.warning("백업 이력을 읽지 못했습니다: %s", exc)
        return None
    except ValueError as exc:
        logging.warning("손상된 백업 이력을 비우고 시작합니다: %s", exc)
        try:
            backup_corrupt_file(index_path)
        except OSError as backup_exc:
            logging.warning("손상된 백업 이력 보존 실패: %s", backup_exc)
        return []
    return [
        {"target_path": item["target_path"], "backup_path": item["backup_path"]}
        for item in payload
        if isinstance(item, dict)
        and isinstance(item.get("target_path"), str)
        and isinstance(item.get("backup_path"), str)
        and os.path.exists(item["backup_path"])
    ]


def load_backup_history(index_path: str) -> List[Dict[str, str]]:
    """색인을 읽어 백업 파일이 남아 있는 항목만 돌려준다."""
    return _read_backup_history(index_path) or []


def _acquire_backup_history_lock(lock_path: str) -> Optional[int]:
    deadline = time.monotonic() + 2.0
    while True:
        if time.monotonic() >= deadline:
            logging.warning("백업 이력 잠금 대기 시간이 초과되어 잠금 없이 기록합니다.")
            return None
        try:
            return os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(lock_path) > 10.0:
                    os.unlink(lock_path)
                    continue
            except OSError:
                pass
        except PermissionError:
            # Windows 에서는 지워지는 중인 잠금 파일을 만들려 하면 권한 오류가 나므로 기한 안에서 다시 시도한다.
            pass
        except OSError as exc:
            logging.warning("백업 이력 잠금을 얻지 못했습니다: %s", exc)
            return None

        remaining = deadline - time.monotonic()
        if remaining > 0:
            time.sleep(min(0.05, remaining))


def append_backup_history(index_path: str, entry: Dict[str, str], limit: int) -> List[Dict[str, str]]:
    """항목을 더해 상한만큼만 남기고 색인을 원자적으로 저장한 뒤 이력을 돌려준다."""
    lock_path = index_path + ".lock"
    # 백업 기록은 잠금 획득 실패와 관계없이 이어간다.
    lock_fd = _acquire_backup_history_lock(lock_path)
    try:
        history = _read_backup_history(index_path)
        if history is None:
            # 읽지 못한 색인을 덮어쓰면 기존 이력이 사라진다.
            return [entry]
        history = (history + [entry])[-limit:]
        write_json_atomic(index_path, history, ensure_ascii=False, indent=2)
        return history
    finally:
        if lock_fd is not None:
            try:
                os.close(lock_fd)
            except OSError as exc:
                logging.warning("백업 이력 잠금 파일을 닫지 못했습니다: %s", exc)
            try:
                os.unlink(lock_path)
            except FileNotFoundError:
                pass
            except OSError as exc:
                logging.warning("백업 이력 잠금 파일을 정리하지 못했습니다: %s", exc)
