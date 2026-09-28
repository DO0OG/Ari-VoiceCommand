import hashlib
import json
import logging
import os
import stat
import tempfile
import threading
import time
import unicodedata
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_MAX_BYTES = 50 * 1024 * 1024


def build_tts_cache_key(
    provider, voice, rate, volume, emotion, language, text, *, pitch=None
):
    normalized_text = " ".join(unicodedata.normalize("NFC", text).split())
    fields = [provider, voice, rate, volume, emotion, language, normalized_text]
    if pitch is not None:
        fields.append(pitch)
    payload = json.dumps(
        fields,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class DiskTTSAudioCache:
    def __init__(self, cache_dir=None, max_bytes=DEFAULT_MAX_BYTES):
        self._cache_dir = Path(cache_dir) if cache_dir is not None else None
        self.max_bytes = max(0, int(max_bytes))
        self._lock = threading.RLock()

    def _directory(self):
        if self._cache_dir is None:
            from core.resource_manager import ResourceManager

            self._cache_dir = Path(ResourceManager.get_writable_path("tts_cache"))
        return self._cache_dir

    @staticmethod
    def _path_for_key(directory, key):
        name = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return directory / (name + ".pcm")

    def get(self, key):
        with self._lock:
            try:
                directory = self._directory()
                self._evict(directory)
                path = self._path_for_key(directory, key)
                pcm = path.read_bytes()
            except OSError:
                return None

            if not pcm:
                return None

            try:
                current = path.stat()
                touched_ns = max(time.time_ns(), current.st_mtime_ns + 1)
                os.utime(path, ns=(current.st_atime_ns, touched_ns))
            except OSError as exc:
                logger.debug("TTS 캐시 사용 시각 갱신 실패: %s", exc)
            return pcm

    def put(self, key, pcm):
        if not pcm or len(pcm) > self.max_bytes or self.max_bytes == 0:
            return

        with self._lock:
            temporary_path = None
            try:
                directory = self._directory()
                directory.mkdir(parents=True, exist_ok=True)
                target = self._path_for_key(directory, key)
                with tempfile.NamedTemporaryFile(
                    mode="wb", prefix=".tts-", suffix=".tmp", dir=directory, delete=False
                ) as temporary:
                    temporary_path = temporary.name
                    temporary.write(pcm)
                os.replace(temporary_path, target)
                temporary_path = None
                self._evict(directory)
            except OSError as exc:
                logger.debug("TTS 캐시 저장 실패: %s", exc)
            finally:
                if temporary_path is not None:
                    try:
                        os.unlink(temporary_path)
                    except OSError as exc:
                        logger.debug("TTS 캐시 임시 파일 삭제 실패: %s", exc)

    def _evict(self, directory):
        try:
            paths = list(directory.iterdir())
        except OSError:
            return

        entries = []
        total_bytes = 0
        for path in paths:
            if path.suffix != ".pcm":
                continue
            try:
                metadata = path.stat()
            except OSError:
                continue
            if not stat.S_ISREG(metadata.st_mode):
                continue
            entries.append((metadata.st_mtime_ns, path.name, path, metadata.st_size))
            total_bytes += metadata.st_size

        for _last_used, _name, path, size in sorted(entries):
            if total_bytes <= self.max_bytes:
                break
            try:
                path.unlink()
                total_bytes -= size
            except OSError:
                continue
