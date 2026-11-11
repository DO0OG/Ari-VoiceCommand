"""파일 백업 복구 이력을 색인 파일에 저장하고 읽는다."""
import json
import logging
import os
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


def append_backup_history(index_path: str, entry: Dict[str, str], limit: int) -> List[Dict[str, str]]:
    """항목을 더해 상한만큼만 남기고 색인을 원자적으로 저장한 뒤 이력을 돌려준다."""
    history = _read_backup_history(index_path)
    if history is None:
        # 읽지 못한 색인을 덮어쓰면 기존 이력이 사라진다.
        return [entry]
    history = (history + [entry])[-limit:]
    write_json_atomic(index_path, history, ensure_ascii=False, indent=2)
    return history
