"""증분 저장을 지원하는 레코드 스토어.

append-only .log 파일에 JSON Lines 형식으로 기록하고,
로그 라인이 기준치를 넘기면 메인 .json 파일과 병합(compaction)한다.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict
from typing import Any, Callable, List, TypeVar

T = TypeVar("T")


class RecordStore:
    COMPACT_THRESHOLD = 50

    def __init__(self, filepath: str, max_records: int = 500) -> None:
        self.filepath = filepath
        self.log_path = filepath + ".log"
        self.max_records = max_records
        self._lock = threading.RLock()

    def load(self, factory: Callable[[dict], T]) -> List[T]:
        records: list[dict] = []
        if os.path.exists(self.filepath):
            with open(self.filepath, "r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, list):
                records.extend(item for item in loaded if isinstance(item, dict))
        if os.path.exists(self.log_path):
            with open(self.log_path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if line:
                        records.append(json.loads(line))
        trimmed = records[-self.max_records :]
        return [factory(item) for item in trimmed]

    def append(self, record: Any) -> None:
        with self._lock:
            parent = os.path.dirname(self.log_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(self.log_path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
            if self._log_line_count() >= self.COMPACT_THRESHOLD:
                self._compact()

    def _log_line_count(self) -> int:
        if not os.path.exists(self.log_path):
            return 0
        with open(self.log_path, "r", encoding="utf-8") as handle:
            return sum(1 for line in handle if line.strip())

    def _compact(self) -> None:
        records = self.load(lambda item: item)
        parent = os.path.dirname(self.filepath)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(self.filepath, "w", encoding="utf-8") as handle:
            json.dump(records, handle, ensure_ascii=False, indent=2)
        if os.path.exists(self.log_path):
            os.remove(self.log_path)
