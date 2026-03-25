"""사용자 플러그인 로더.

`plugins/*.py` 파일을 스캔하고, 각 모듈의 `register(context)` 함수를 호출해
확장 기능을 로드합니다.
"""
from __future__ import annotations

import importlib.util
import logging
import os
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


@dataclass
class PluginContext:
    app: Any = None
    tray_icon: Any = None
    character_widget: Any = None
    text_interface: Any = None


@dataclass
class PluginInfo:
    name: str
    version: str
    description: str
    path: str
    enabled: bool = True
    loaded: bool = False
    error: str = ""
    exports: Dict[str, Any] = field(default_factory=dict)


class PluginManager:
    def __init__(self):
        self._plugins: List[PluginInfo] = []
        self._modules: Dict[str, ModuleType] = {}

    def plugin_dir(self) -> str:
        try:
            from core.resource_manager import ResourceManager
            return ResourceManager.ensure_plugin_files()
        except Exception:
            return os.path.join(os.path.dirname(os.path.dirname(__file__)), "plugins")

    def discover_plugins(self) -> List[PluginInfo]:
        directory = self.plugin_dir()
        os.makedirs(directory, exist_ok=True)
        discovered: List[PluginInfo] = []
        for name in sorted(os.listdir(directory)):
            if not name.endswith(".py") or name.startswith("_"):
                continue
            path = os.path.join(directory, name)
            discovered.append(
                PluginInfo(
                    name=os.path.splitext(name)[0],
                    version="0.1.0",
                    description="",
                    path=path,
                )
            )
        self._plugins = discovered
        return list(discovered)

    def load_plugins(self, context: Optional[PluginContext] = None) -> List[PluginInfo]:
        context = context or PluginContext()
        loaded_plugins: List[PluginInfo] = []
        for plugin in self.discover_plugins():
            try:
                info = self._load_single_plugin(plugin, context)
            except Exception as exc:
                plugin.loaded = False
                plugin.error = str(exc)
                logger.warning(f"[PluginLoader] 플러그인 로드 실패: {plugin.path} ({exc})")
                info = plugin
            loaded_plugins.append(info)
        self._plugins = loaded_plugins
        return list(loaded_plugins)

    def list_plugins(self) -> List[PluginInfo]:
        return list(self._plugins)

    def summary(self) -> List[Dict[str, str]]:
        return [
            {
                "name": plugin.name,
                "version": plugin.version,
                "description": plugin.description,
                "path": plugin.path,
                "loaded": str(plugin.loaded),
                "error": plugin.error,
            }
            for plugin in self._plugins
        ]

    def _load_single_plugin(self, plugin: PluginInfo, context: PluginContext) -> PluginInfo:
        module_name = f"ari_user_plugin_{plugin.name}"
        spec = importlib.util.spec_from_file_location(module_name, plugin.path)
        if spec is None or spec.loader is None:
            raise RuntimeError("플러그인 모듈 스펙 생성 실패")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self._modules[plugin.name] = module

        metadata = getattr(module, "PLUGIN_INFO", {}) or {}
        plugin.name = str(metadata.get("name", plugin.name))
        plugin.version = str(metadata.get("version", "0.1.0"))
        plugin.description = str(metadata.get("description", ""))

        register = getattr(module, "register", None)
        if callable(register):
            exports = register(context) or {}
            if isinstance(exports, dict):
                plugin.exports = exports
        plugin.loaded = True
        plugin.error = ""
        return plugin


_plugin_manager: Optional[PluginManager] = None


def get_plugin_manager() -> PluginManager:
    global _plugin_manager
    if _plugin_manager is None:
        _plugin_manager = PluginManager()
    return _plugin_manager
