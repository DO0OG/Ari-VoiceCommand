"""JSON 파일 저장과 손상 파일 보존 유틸리티."""

import json
import os
import shutil
import tempfile
from datetime import datetime
from os import PathLike
from pathlib import Path
from typing import Any, Callable, TextIO


def _write_atomic(path: str | PathLike[str], write: Callable[[TextIO], None]) -> None:
    target = os.fspath(path)
    if os.path.islink(target):
        target = os.path.realpath(target)
    directory = os.path.dirname(target) or "."
    os.makedirs(directory, exist_ok=True)

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=directory,
            delete=False,
        ) as handle:
            temp_path = handle.name
            write(handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
        temp_path = None
    finally:
        if temp_path is not None:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def write_json_atomic(
    path: str | PathLike[str],
    obj: object,
    **dump_kwargs: Any,
) -> None:
    """같은 디렉터리의 임시 파일에 JSON을 쓴 뒤 원자적으로 교체한다."""

    def dump(handle: TextIO) -> None:
        json.dump(obj, handle, **dump_kwargs)

    _write_atomic(path, dump)


def write_text_atomic(path: str | PathLike[str], text: str) -> None:
    """같은 디렉터리의 임시 파일에 UTF-8 텍스트를 쓴 뒤 원자적으로 교체한다."""

    def write(handle: TextIO) -> None:
        handle.write(text)

    _write_atomic(path, write)


def write_bytes_atomic(path: str | PathLike[str], data: bytes) -> None:
    """같은 디렉터리의 임시 파일에 바이트를 쓴 뒤 원자적으로 교체한다."""
    target = os.fspath(path)
    if os.path.islink(target):
        target = os.path.realpath(target)
    directory = os.path.dirname(target) or "."
    os.makedirs(directory, exist_ok=True)

    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=directory,
            delete=False,
        ) as handle:
            temp_path = handle.name
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
        temp_path = None
    finally:
        if temp_path is not None:
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def backup_corrupt_file(path: str | PathLike[str]) -> Path:
    """손상된 파일을 같은 디렉터리에 겹치지 않는 이름으로 보존한다."""
    source = Path(path)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    index = 0

    with source.open("rb") as original:
        while True:
            collision = f"-{index}" if index else ""
            backup = source.with_name(
                f"{source.stem}.corrupt-{timestamp}{collision}{source.suffix}"
            )
            try:
                target_fd = os.open(
                    os.fspath(backup),
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
            except FileExistsError:
                index += 1
                continue

            complete = False
            try:
                with os.fdopen(target_fd, "wb") as destination:
                    shutil.copyfileobj(original, destination)
                complete = True
            finally:
                if not complete:
                    try:
                        backup.unlink()
                    except OSError:
                        pass
            return backup
