"""사용자 플러그인 로더.

`plugins/*.py` 파일을 스캔하고, 각 모듈의 `register(context)` 함수를 호출해
확장 기능을 로드합니다.
"""
from __future__ import annotations

import importlib.util
import logging
import os
from dataclasses import dataclass, field
from types import FunctionType
from types import ModuleType
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)

PLUGIN_API_VERSION = "1.0"
_COMPATIBLE_API_VERSIONS = {"1.0"}


@dataclass
class PluginContext:
    app: Any = None
    tray_icon: Any = None
    character_widget: Any = None
    text_interface: Any = None
    register_menu_action: Any = None
    register_command: Any = None
    register_tool: Any = None
    run_sandboxed: Any = None


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
    api_version: str = "1.0"


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
        if context.run_sandboxed is None:
            from core.plugin_sandbox import run_sandboxed as _sandbox_fn
            context.run_sandboxed = _sandbox_fn
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
                "api_version": plugin.api_version,
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
        api_ver = str(metadata.get("api_version", "1.0"))
        if api_ver not in _COMPATIBLE_API_VERSIONS:
            raise RuntimeError(
                f"호환되지 않는 플러그인 API 버전: {api_ver!r} "
                f"(지원: {sorted(_COMPATIBLE_API_VERSIONS)})"
            )
        plugin.api_version = api_ver

        register = getattr(module, "register", None)
        if register is None:
            plugin.loaded = True
            plugin.error = ""
            return plugin
        if not isinstance(register, FunctionType):
            raise TypeError("register는 callable이어야 합니다.")
        exports = self._invoke_register(register, context) or {}
        if isinstance(exports, dict):
            plugin.exports = exports
        plugin.loaded = True
        plugin.error = ""
        return plugin

    def _invoke_register(self, register: FunctionType, context: PluginContext) -> Any:
        return register(context)


_plugin_manager: Optional[PluginManager] = None


def get_plugin_manager() -> PluginManager:
    global _plugin_manager
    if _plugin_manager is None:
        _plugin_manager = PluginManager()
    return _plugin_manager
