"""plugins/ 디렉터리 변경 감시."""
from __future__ import annotations

import logging
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


class _PluginEventHandler(FileSystemEventHandler):
    def __init__(self, plugin_manager, debounce_seconds: float = 1.0):
        self._plugin_manager = plugin_manager
        self._debounce_seconds = debounce_seconds
        self._pending: dict[str, tuple[float, str]] = {}

    def _schedule(self, path: str, action: str):
        self._pending[path] = (time.time(), action)

    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith(".py"):
            self._schedule(event.src_path, "load")

    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith(".py"):
            self._schedule(event.src_path, "reload")

    def on_deleted(self, event):
        if not event.is_directory and event.src_path.endswith(".py"):
            self._schedule(event.src_path, "unload")

    def flush_pending(self):
        now = time.time()
        completed = []
        for path, (scheduled_at, action) in list(self._pending.items()):
            if now - scheduled_at < self._debounce_seconds:
                continue
            plugin_name = Path(path).stem
            try:
                if action == "load":
                    self._plugin_manager.load_plugin(path)
                elif action == "reload":
                    self._plugin_manager.reload_plugin(plugin_name)
                elif action == "unload":
                    self._plugin_manager.unload_plugin(plugin_name)
                logging.info("[PluginWatcher] %s: %s", action, plugin_name)
            except Exception as exc:
                logging.error("[PluginWatcher] %s 실패 (%s): %s", action, plugin_name, exc)
            completed.append(path)
        for path in completed:
            self._pending.pop(path, None)


class PluginWatcher:
    def __init__(self, plugin_dir: str, plugin_manager):
        self._plugin_dir = plugin_dir
        self._handler = _PluginEventHandler(plugin_manager)
        self._observer = Observer()
        self._observer.schedule(self._handler, plugin_dir, recursive=False)

    def start(self):
        self._observer.start()
        logging.info("[PluginWatcher] 감시 시작: %s", self._plugin_dir)

    def stop(self):
        self._observer.stop()
        self._observer.join(timeout=2.0)

    def flush(self):
        self._handler.flush_pending()
