"""사용자 플러그인 로더.

`plugins/*.py`와 `plugins/*.zip` 파일을 스캔하고, 각 플러그인의
`register(context)` 함수를 호출해 확장 기능을 로드합니다.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import os
import shutil
import sys
import threading
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from types import FunctionType
from types import ModuleType
from typing import Callable, Dict, List, Optional, Tuple, cast


logger = logging.getLogger(__name__)

PLUGIN_API_VERSION = "1.0"
_COMPATIBLE_API_VERSIONS = {"1.0"}

MenuActionCallback = Callable[[], None]
MenuRegistrar = Callable[[str, MenuActionCallback], object]
CommandRegistrar = Callable[[object], object]
ToolRegistrar = Callable[[dict[str, object], Callable[[dict[str, object]], Optional[str]]], object]
CharacterPackRegistrar = Callable[[str, object], object]
SandboxRunner = Callable[[str, int], object]
CharacterMenuToggle = Callable[[bool], object]


def _get_unregister_character_pack(widget: object) -> Optional[Callable[[str], None]]:
    candidate = getattr(widget, "unregister_character_pack", None)
    if callable(candidate):
        return cast(Callable[[str], None], candidate)
    return None


@dataclass
class PluginContext:
    app: object = None
    tray_icon: object = None
    character_widget: object = None
    text_interface: object = None
    register_menu_action: Optional[MenuRegistrar] = None
    register_command: Optional[CommandRegistrar] = None
    register_tool: Optional[ToolRegistrar] = None
    register_character_pack: Optional[CharacterPackRegistrar] = None
    run_sandboxed: Optional[SandboxRunner] = None
    set_character_menu_enabled: Optional[CharacterMenuToggle] = None  # callable(bool) — 캐릭터 우클릭 메뉴 표시 여부 제어


@dataclass
class PluginInfo:
    name: str
    version: str
    description: str
    path: str
    entry: str = ""
    sys_path_entry: str = ""
    runtime_path: str = ""
    enabled: bool = True
    loaded: bool = False
    error: str = ""
    exports: Dict[str, object] = field(default_factory=dict)
    api_version: str = "1.0"
    registered_menu_actions: List[object] = field(default_factory=list)
    registered_commands: List[object] = field(default_factory=list)
    registered_tools: List[str] = field(default_factory=list)
    registered_character_packs: List[str] = field(default_factory=list)
    character_menu_disabled: bool = False  # 이 플러그인이 캐릭터 우클릭 메뉴를 비활성화했는지


class PluginManager:
    def __init__(self):
        self._plugins: List[PluginInfo] = []
        self._modules: Dict[str, ModuleType] = {}
        self._context: Optional[PluginContext] = None

    def plugin_dir(self) -> str:
        try:
            from core.resource_manager import ResourceManager
            return ResourceManager.ensure_plugin_files()
        except (ImportError, AttributeError):
            project_root = os.path.dirname(os.path.dirname(__file__))
            runtime_plugins = os.path.join(project_root, ".ari_runtime", "plugins")
            source_plugins = os.path.join(project_root, "plugins")
            os.makedirs(runtime_plugins, exist_ok=True)
            if os.path.isdir(source_plugins):
                for name in os.listdir(source_plugins):
                    src = os.path.join(source_plugins, name)
                    dst = os.path.join(runtime_plugins, name)
                    if os.path.isfile(src) and not os.path.exists(dst):
                        shutil.copy2(src, dst)
            return runtime_plugins

    def _plugin_runtime_dir(self) -> str:
        try:
            from core.resource_manager import ResourceManager
            path = ResourceManager.get_writable_path("plugin_runtime")
        except Exception:
            path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".ari_runtime", "plugin_runtime")
        os.makedirs(path, exist_ok=True)
        return path

    def _runtime_extract_dir(self, plugin_path: str) -> str:
        stat = os.stat(plugin_path)
        digest = hashlib.sha256(f"{plugin_path}:{stat.st_mtime_ns}:{stat.st_size}".encode("utf-8")).hexdigest()[:12]
        stem = os.path.splitext(os.path.basename(plugin_path))[0]
        return os.path.join(self._plugin_runtime_dir(), f"{stem}_{digest}")

    def _zip_metadata(self, path: str) -> dict[str, object]:
        with zipfile.ZipFile(path) as archive:
            with archive.open("plugin.json") as handle:
                return json.loads(handle.read().decode("utf-8"))

    def _validate_zip_member_path(self, base_dir: str, member_name: str) -> Path:
        normalized_member = str(member_name or "").replace("\\", "/").strip("/")
        if not normalized_member:
            return Path(base_dir).resolve()
        base_path = Path(base_dir).resolve()
        target_path = (base_path / normalized_member).resolve()
        try:
            target_path.relative_to(base_path)
        except ValueError as exc:
            raise RuntimeError(f"ZIP 경로 이탈이 감지되어 설치를 중단합니다: {member_name}") from exc
        return target_path

    def _safe_extract_archive(self, archive: zipfile.ZipFile, extract_dir: str) -> None:
        base_path = Path(extract_dir).resolve()
        for member in archive.infolist():
            target_path = self._validate_zip_member_path(str(base_path), member.filename)
            if member.is_dir():
                target_path.mkdir(parents=True, exist_ok=True)
                continue
            target_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member, "r") as source, open(target_path, "wb") as destination:
                shutil.copyfileobj(source, destination)

    def _inspect_python_source(self, module_path: str) -> None:
        try:
            with open(module_path, "r", encoding="utf-8") as handle:
                source = handle.read()
        except UnicodeDecodeError as exc:
            raise RuntimeError(f"플러그인 소스 인코딩을 읽을 수 없습니다: {module_path}") from exc
        from agent.safety_checker import DangerLevel, get_safety_checker
        report = get_safety_checker().check_python(source)
        if report.level == DangerLevel.DANGEROUS:
            raise RuntimeError(f"플러그인 안전 검사 실패: {report.summary}")

    def _plugin_stub(self, path: str) -> PluginInfo:
        stem = os.path.splitext(os.path.basename(path))[0]
        info = PluginInfo(
            name=stem,
            version="0.1.0",
            description="",
            path=path,
        )
        if path.endswith(".zip"):
            try:
                meta = self._zip_metadata(path)
                info.name = str(meta.get("name", stem))
                info.version = str(meta.get("version", "0.1.0"))
                info.description = str(meta.get("description", ""))
                info.entry = str(meta.get("entry", ""))
                info.api_version = str(meta.get("api_version", "1.0"))
            except Exception as exc:
                info.error = f"plugin.json 읽기 실패: {exc}"
        return info

    def discover_plugins(self) -> List[PluginInfo]:
        directory = self.plugin_dir()
        os.makedirs(directory, exist_ok=True)
        discovered: List[PluginInfo] = []
        for name in sorted(os.listdir(directory)):
            if name.startswith("_"):
                continue
            path = os.path.join(directory, name)
            if not os.path.isfile(path):
                continue
            if not (name.endswith(".py") or name.endswith(".zip")):
                continue
            discovered.append(self._plugin_stub(path))
        self._plugins = discovered
        return list(discovered)

    def load_plugins(self, context: Optional[PluginContext] = None) -> List[PluginInfo]:
        context = context or PluginContext()
        if context.run_sandboxed is None:
            from core.plugin_sandbox import run_sandboxed as _sandbox_fn
            context.run_sandboxed = _sandbox_fn
        self._context = context
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

    def load_plugin(self, path: str, context: Optional[PluginContext] = None) -> PluginInfo:
        active_context = context or self._context or PluginContext()
        if active_context.run_sandboxed is None:
            from core.plugin_sandbox import run_sandboxed as _sandbox_fn
            active_context.run_sandboxed = _sandbox_fn
        self._context = active_context
        plugin = self._plugin_stub(path)
        existing = next(
            (
                item for item in self._plugins
                if item.path == path or item.name == plugin.name
            ),
            None,
        )
        if existing is not None:
            self.unload_plugin(existing.name)
        info = self._load_single_plugin(plugin, active_context)
        self._plugins = [item for item in self._plugins if item.name != info.name]
        self._plugins.append(info)
        self._plugins.sort(key=lambda item: item.name)
        return info

    def reload_plugin(self, plugin_name: str) -> Optional[PluginInfo]:
        path = self._find_plugin_path(plugin_name)
        if not path:
            return None
        self.unload_plugin(plugin_name)
        return self.load_plugin(path)

    def unload_plugin(self, plugin_name: str) -> bool:
        plugin = next((item for item in self._plugins if item.name == plugin_name), None)
        if plugin is None:
            return False

        for action in plugin.registered_menu_actions:
            if self._context and getattr(self._context, "tray_icon", None) and hasattr(self._context.tray_icon, "remove_plugin_menu_action"):
                self._context.tray_icon.remove_plugin_menu_action(action)
        if self._context and getattr(self._context, "register_command", None):
            registry_owner = getattr(self._context.register_command, "__self__", None)
            if registry_owner and hasattr(registry_owner, "unregister_command"):
                for command in plugin.registered_commands:
                    registry_owner.unregister_command(command)
        for tool_name in plugin.registered_tools:
            self._unregister_tool(tool_name)
        if self._context and getattr(self._context, "character_widget", None):
            widget = self._context.character_widget
            unregister_character_pack = _get_unregister_character_pack(widget)
            if unregister_character_pack is not None:
                for pack_name in plugin.registered_character_packs:
                    unregister_character_pack(pack_name)

        # 이 플러그인이 캐릭터 메뉴를 비활성화했다면 복원
        if plugin.character_menu_disabled and self._context and self._context.set_character_menu_enabled:
            try:
                self._context.set_character_menu_enabled(True)
            except Exception as exc:
                logger.debug("[PluginLoader] 캐릭터 메뉴 복원 실패 (%s): %s", plugin_name, exc)

        module = self._modules.pop(plugin_name, None)
        if module is not None:
            sys.modules.pop(module.__name__, None)
        if plugin.sys_path_entry:
            try:
                sys.path.remove(plugin.sys_path_entry)
            except ValueError:
                pass
        if plugin.runtime_path:
            try:
                shutil.rmtree(plugin.runtime_path)
            except OSError as exc:
                logger.warning("[PluginLoader] 런타임 디렉터리 정리 실패 (%s): %s", plugin.runtime_path, exc)

        self._plugins = [item for item in self._plugins if item.name != plugin_name]
        logger.info("[PluginLoader] 플러그인 언로드: %s", plugin_name)
        return True

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
        module_path, sys_path_entry = self._resolve_load_target(plugin)
        if plugin.runtime_path:
            for dirpath, _, filenames in os.walk(plugin.runtime_path):
                for fname in filenames:
                    if fname.endswith(".py"):
                        self._inspect_python_source(os.path.join(dirpath, fname))
        else:
            self._inspect_python_source(module_path)
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        if spec is None or spec.loader is None:
            raise RuntimeError("플러그인 모듈 스펙 생성 실패")
        module = importlib.util.module_from_spec(spec)
        if sys_path_entry and sys_path_entry not in sys.path:
            sys.path.insert(0, sys_path_entry)
            plugin.sys_path_entry = sys_path_entry
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
        tracked_context = self._wrap_context(context, plugin)
        exports = self._invoke_register(register, tracked_context) or {}
        if isinstance(exports, dict):
            plugin.exports = exports
        plugin.loaded = True
        plugin.error = ""
        return plugin

    def _resolve_load_target(self, plugin: PluginInfo) -> Tuple[str, str]:
        if plugin.path.endswith(".py"):
            return plugin.path, os.path.dirname(plugin.path)

        meta = self._zip_metadata(plugin.path)
        entry = str(meta.get("entry", "") or "").strip()
        if not entry:
            raise RuntimeError("plugin.json에 entry가 없습니다.")
        entry_normalized = unicodedata.normalize("NFKC", entry)
        if "/" in entry_normalized or "\\" in entry_normalized or ".." in entry_normalized:
            raise RuntimeError(f"entry는 ZIP 루트 파일이어야 합니다: {entry!r}")

        extract_dir = self._runtime_extract_dir(plugin.path)
        if os.path.isdir(extract_dir):
            shutil.rmtree(extract_dir, ignore_errors=True)
        os.makedirs(extract_dir, exist_ok=True)
        with zipfile.ZipFile(plugin.path) as archive:
            self._safe_extract_archive(archive, extract_dir)

        module_path = os.path.join(extract_dir, entry)
        if not os.path.exists(module_path):
            raise RuntimeError(f"ZIP 내부 entry 파일을 찾을 수 없습니다: {entry}")

        plugin.entry = entry
        plugin.runtime_path = extract_dir
        plugin.sys_path_entry = extract_dir
        return module_path, extract_dir

    def _invoke_register(self, register: FunctionType, context: PluginContext) -> object:
        return register(context)

    def _wrap_context(self, context: PluginContext, plugin: PluginInfo) -> PluginContext:
        def _register_menu_action(label, callback):
            if not context.register_menu_action:
                return None
            action = context.register_menu_action(label, callback)
            if action is not None:
                plugin.registered_menu_actions.append(action)
            return action

        def _register_command(command):
            if not context.register_command:
                return None
            result = context.register_command(command)
            plugin.registered_commands.append(command)
            return result

        def _register_tool(schema, handler):
            if not context.register_tool:
                return None
            result = context.register_tool(schema, handler)
            tool_name = str(schema.get("function", {}).get("name", "") or "")
            if tool_name:
                plugin.registered_tools.append(tool_name)
            return result

        def _register_character_pack(pack_name: str, directory: str, activate: bool = False):
            if not context.register_character_pack:
                return False
            result = bool(context.register_character_pack(pack_name, directory, activate))
            if result:
                plugin.registered_character_packs.append(str(pack_name))
            return result

        def _set_character_menu_enabled(enabled: bool):
            if not context.set_character_menu_enabled:
                return
            context.set_character_menu_enabled(enabled)
            # 비활성화 시 추적 (언로드 시 자동 복원에 사용)
            plugin.character_menu_disabled = not enabled

        return PluginContext(
            app=context.app,
            tray_icon=context.tray_icon,
            character_widget=context.character_widget,
            text_interface=context.text_interface,
            register_menu_action=_register_menu_action,
            register_command=_register_command,
            register_tool=_register_tool,
            register_character_pack=_register_character_pack,
            run_sandboxed=context.run_sandboxed,
            set_character_menu_enabled=_set_character_menu_enabled,
        )

    def _find_plugin_path(self, plugin_name: str) -> str:
        for plugin in self.discover_plugins():
            if plugin.name == plugin_name:
                return plugin.path
        direct = os.path.join(self.plugin_dir(), f"{plugin_name}.py")
        if os.path.exists(direct):
            return direct
        zipped = os.path.join(self.plugin_dir(), f"{plugin_name}.zip")
        return zipped if os.path.exists(zipped) else ""

    def _unregister_tool(self, tool_name: str) -> None:
        try:
            from agent.llm_provider import get_llm_provider
            get_llm_provider().unregister_plugin_tool(tool_name)
        except Exception as exc:
            logger.debug("[PluginLoader] LLM 도구 제거 생략 (%s): %s", tool_name, exc)

        try:
            from core.VoiceCommand import _state
            from commands.ai_command import AICommand

            cmd_registry = _state.command_registry
            ai_command = next(
                (cmd for cmd in getattr(cmd_registry, "commands", []) if isinstance(cmd, AICommand)),
                None,
            )
            if ai_command:
                ai_command.unregister_plugin_tool_handler(tool_name)
        except Exception as exc:
            logger.debug("[PluginLoader] AICommand 도구 제거 생략 (%s): %s", tool_name, exc)


_plugin_manager: Optional[PluginManager] = None
_plugin_manager_lock = threading.Lock()


def get_plugin_manager() -> PluginManager:
    global _plugin_manager
    if _plugin_manager is None:
        with _plugin_manager_lock:
            if _plugin_manager is None:
                _plugin_manager = PluginManager()
    return _plugin_manager
