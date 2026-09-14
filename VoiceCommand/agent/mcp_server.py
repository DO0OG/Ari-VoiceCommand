"""Ari 로컬 도구를 JSON-RPC 기반 MCP HTTP 엔드포인트로 노출한다."""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
import secrets
import threading
from typing import Any, Callable

log = logging.getLogger(__name__)


class AriMCPServer:
    """Use ARI_MCP_TOKEN and os.pathsep-separated ARI_MCP_ALLOWED_PATHS for HTTP access."""

    def __init__(self, tts_func: Callable[[str], None] | None = None, *,
                 token: str | None = None, allowed_paths: list[str] | None = None,
                 port: int = 8765):
        self.tts_func = tts_func
        self._token = token if token is not None else os.environ.get("ARI_MCP_TOKEN", "")
        roots = allowed_paths if allowed_paths is not None else (
            os.environ.get("ARI_MCP_ALLOWED_PATHS", "").split(os.pathsep)
        )
        self._allowed_paths = tuple(Path(root).expanduser().resolve() for root in roots if root)
        self._allowed_hosts = {f"{host}:{int(port)}" for host in ("127.0.0.1", "localhost", "[::1]")}
        from agent.automation_helpers import AutomationHelpers
        self._automation = AutomationHelpers()

    def create_app(self):
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse

        app = FastAPI(title="Ari Local MCP Server")

        @app.middleware("http")
        async def authenticate(request, call_next):
            hosts = request.headers.getlist("host")
            origins = request.headers.getlist("origin")
            if len(hosts) != 1 or hosts[0].lower() not in self._allowed_hosts:
                return JSONResponse({"error": "Invalid Host"}, status_code=403)
            if origins and (len(origins) != 1 or origins[0].lower() not in {
                f"http://{host}" for host in self._allowed_hosts
            }):
                return JSONResponse({"error": "Invalid Origin"}, status_code=403)
            if not self._token:
                return JSONResponse({"error": "MCP authentication token is not configured"}, status_code=503)
            authorization = request.headers.getlist("authorization")
            expected = f"Bearer {self._token}".encode("utf-8")
            if len(authorization) != 1 or not secrets.compare_digest(authorization[0].encode("utf-8"), expected):
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
            return await call_next(request)

        @app.post("/mcp")
        async def mcp(payload: dict[str, Any]):
            response = self.handle_jsonrpc(payload)
            return JSONResponse(response)

        return app

    def handle_jsonrpc(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_id = payload.get("id")
        method = str(payload.get("method", "") or "")
        params = payload.get("params") or {}
        try:
            if method == "initialize":
                return self._ok(request_id, {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": "ari-local-tools", "version": "1.0.0"},
                    "capabilities": {"tools": {}},
                })
            if method == "tools/list":
                return self._ok(request_id, {"tools": self._tool_schemas()})
            if method == "tools/call":
                name = str(params.get("name", "") or "")
                arguments = params.get("arguments") or {}
                return self._ok(request_id, {"content": [{"type": "text", "text": self._call_tool(name, arguments)}]})
            return self._error(request_id, -32601, f"Unknown method: {method}")
        except Exception as exc:
            log.error("[MCPServer] 요청 처리 실패: %s", exc, exc_info=True)
            return self._error(request_id, -32000, str(exc))

    def _call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        if name == "ari_tts":
            text = str(arguments.get("text", "") or "")
            if self.tts_func and text:
                self.tts_func(text)
            return "spoken"
        if name == "ari_notify":
            return self._notify(str(arguments.get("title", "Ari") or "Ari"), str(arguments.get("message", "") or ""))
        if name == "ari_open_app":
            return self._automation.launch_app(str(arguments.get("name", "") or ""))
        if name == "ari_take_screenshot":
            path = self._automation.screenshot()
            with open(path, "rb") as handle:
                encoded = base64.b64encode(handle.read()).decode("ascii")
            return encoded
        if name == "ari_get_system_info":
            return self._system_info()
        if name == "ari_read_file":
            return self._read_file(
                str(arguments.get("path", "") or ""),
                int(arguments.get("start_line", 1) or 1),
                arguments.get("end_line"),
            )
        if name == "ari_write_file":
            return self._write_file(
                str(arguments.get("path", "") or ""),
                str(arguments.get("content", "") or ""),
                str(arguments.get("mode", "overwrite") or "overwrite"),
            )
        raise ValueError(f"Unknown tool: {name}")

    def _resolve_allowed_path(self, path: str) -> str:
        candidate = Path(path).expanduser().resolve()
        if candidate.is_reserved() or any(":" in part for part in candidate.parts[1:]):
            raise PermissionError("Invalid file path")
        if not any(candidate.is_relative_to(root) for root in self._allowed_paths):
            raise PermissionError("File path is outside MCP allowed paths")
        return str(candidate)

    def _read_file(self, path: str, start_line: int = 1, end_line: int | None = None) -> str:
        if not path:
            return "error: path required"
        try:
            from agent.file_tools import read_file
            import json as _json
            result = read_file(self._resolve_allowed_path(path), start_line, end_line)
            return _json.dumps(result, ensure_ascii=False, default=str)
        except Exception as exc:
            log.error("[MCPServer] ari_read_file 실패: %s", exc)
            return f"error: {exc}"

    def _write_file(self, path: str, content: str, mode: str = "overwrite") -> str:
        if not path:
            return "error: path required"
        try:
            from agent.file_tools import write_file
            import json as _json
            result = write_file(self._resolve_allowed_path(path), content, mode)
            return _json.dumps(result, ensure_ascii=False, default=str)
        except Exception as exc:
            log.error("[MCPServer] ari_write_file 실패: %s", exc)
            return f"error: {exc}"

    def _notify(self, title: str, message: str) -> str:
        try:
            from PySide6.QtWidgets import QSystemTrayIcon
            if QSystemTrayIcon.supportsMessages():
                # 트레이 인스턴스가 없는 경우도 있어 텍스트 결과는 항상 반환한다.
                return f"{title}: {message}"
        except Exception as exc:
            log.debug("[MCPServer] system tray notification unavailable: %s", exc)
        return f"{title}: {message}"

    def _system_info(self) -> str:
        try:
            import json
            import psutil
            data = {
                "cpu_percent": psutil.cpu_percent(interval=0.1),
                "memory_percent": psutil.virtual_memory().percent,
                "apps": sorted({proc.info.get("name") or "" for proc in psutil.process_iter(["name"])})[:100],
            }
            return json.dumps(data, ensure_ascii=False)
        except Exception as exc:
            return f"system info unavailable: {exc}"

    def _tool_schemas(self) -> list[dict[str, Any]]:
        return [
            {"name": "ari_tts", "description": "Read text with Ari voice.", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
            {"name": "ari_notify", "description": "Show a local notification.", "inputSchema": {"type": "object", "properties": {"title": {"type": "string"}, "message": {"type": "string"}}, "required": ["message"]}},
            {"name": "ari_open_app", "description": "Open a local application.", "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
            {"name": "ari_take_screenshot", "description": "Take screenshot and return base64.", "inputSchema": {"type": "object", "properties": {}}},
            {"name": "ari_get_system_info", "description": "Return CPU, memory and app list.", "inputSchema": {"type": "object", "properties": {}}},
            {"name": "ari_read_file", "description": "Read file contents from the local filesystem.", "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}}, "required": ["path"]}},
            {"name": "ari_write_file", "description": "Write content to a local file (overwrite or append).", "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}, "mode": {"type": "string", "enum": ["overwrite", "append"]}}, "required": ["path", "content"]}},
        ]

    def _ok(self, request_id: Any, result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _error(self, request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def start_mcp_server_background(tts_func: Callable[[str], None] | None = None, port: int = 8765) -> threading.Thread | None:
    """uvicorn 서버를 데몬 스레드로 시작한다."""
    try:
        import uvicorn
        server = AriMCPServer(tts_func, port=port)
        app = server.create_app()

        def _run() -> None:
            uvicorn.run(app, host="127.0.0.1", port=int(port), log_level="warning")

        thread = threading.Thread(target=_run, name="AriMCPServer", daemon=True)
        thread.start()
        log.info("Ari MCP server started on http://127.0.0.1:%s/mcp", port)
        return thread
    except Exception as exc:
        log.error("Ari MCP server start failed: %s", exc, exc_info=True)
        return None
