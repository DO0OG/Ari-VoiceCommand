"""MCP (Model Context Protocol) Streamable HTTP 클라이언트."""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional
from urllib.error import HTTPError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

_PROTOCOL_VERSION = "2025-03-26"
_USER_AGENT = "Ari-MCP-Client/1.0"

_INIT_PAYLOAD = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": _PROTOCOL_VERSION,
        "capabilities": {
            "roots": {"listChanged": False},
        },
        "clientInfo": {"name": "ari-skill-client", "version": "1.0"},
    },
}

_INITIALIZED_NOTIFICATION = {
    "jsonrpc": "2.0",
    "method": "notifications/initialized",
    "params": {},
}


def _require_https(url: str) -> str:
    normalized = str(url or "").strip()
    if not normalized.startswith("https://"):
        raise ValueError(f"HTTPS URL only: {url}")
    return normalized


class McpSession:
    """MCP 서버와의 단일 세션."""

    def __init__(self, endpoint: str, timeout: int = 30):
        self.endpoint = _require_https(endpoint)
        self.timeout = timeout
        self.session_id: Optional[str] = None
        self._tools_cache: Optional[List[dict]] = None
        self._notification_cb: Optional[Callable[[dict], None]] = None
        self._sse_thread: Optional[threading.Thread] = None
        self._sse_stop = threading.Event()

    def initialize(
        self,
        notification_cb: Optional[Callable[[dict], None]] = None,
    ) -> bool:
        """세션을 초기화하고 필요하면 GET SSE 리스너를 시작한다."""
        self._notification_cb = notification_cb
        try:
            request = Request(
                self.endpoint,
                data=json.dumps(_INIT_PAYLOAD).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                    "User-Agent": _USER_AGENT,
                },
                method="POST",
            )
            with urlopen(request, timeout=self.timeout) as response:  # nosec B310
                self.session_id = response.headers.get("Mcp-Session-Id", "") or None
                raw = response.read().decode("utf-8", errors="replace")
                content_type = response.headers.get("Content-Type", "")

            parsed = (
                self._parse_sse(raw)
                if "text/event-stream" in content_type.lower()
                else json.loads(raw or "{}")
            )
            logger.debug("[MCP] initialize 응답: %s", parsed)
        except Exception as exc:
            logger.error("[MCP] initialize 실패: %s", exc)
            return False

        try:
            self._post_notification(_INITIALIZED_NOTIFICATION)
        except Exception as exc:
            logger.warning("[MCP] notifications/initialized 전송 실패: %s", exc)

        if notification_cb and self.session_id:
            self._start_sse_listener()
        return True

    def list_tools(self) -> List[dict]:
        """사용 가능한 도구 목록을 조회한다."""
        if self._tools_cache is not None:
            return list(self._tools_cache)
        response = self._call_rpc("tools/list", {})
        tools = response.get("result", {}).get("tools", []) if isinstance(response, dict) else []
        self._tools_cache = list(tools)
        return list(self._tools_cache)

    def call_tool(self, tool_name: str, arguments: dict) -> str:
        """도구를 호출하고 사용자에게 보여줄 텍스트를 반환한다."""
        payload = {
            "jsonrpc": "2.0",
            "id": int(time.time() * 1000) % 1_000_000,
            "method": "tools/call",
            "params": {
                "name": str(tool_name or "").strip(),
                "arguments": dict(arguments or {}),
            },
        }
        try:
            response = self._post_rpc(payload)
            return self._extract_text(response)
        except Exception as exc:
            logger.error("[MCP] tool 호출 실패 (%s): %s", tool_name, exc)
            return f"[MCP error] {tool_name}: {exc}"

    def close(self) -> None:
        """세션을 종료한다."""
        self._sse_stop.set()
        if self._sse_thread and self._sse_thread.is_alive():
            self._sse_thread.join(timeout=2.0)

        if not self.session_id:
            return

        try:
            request = Request(
                self.endpoint,
                headers={
                    "Mcp-Session-Id": self.session_id,
                    "User-Agent": _USER_AGENT,
                },
                method="DELETE",
            )
            with urlopen(request, timeout=10) as _:  # nosec B310
                pass
        except HTTPError as exc:
            if exc.code != 405:
                logger.warning("[MCP] DELETE 세션 종료 실패: %s", exc)
        except Exception as exc:
            logger.warning("[MCP] 세션 종료 실패: %s", exc)
        finally:
            self.session_id = None

    def _start_sse_listener(self) -> None:
        def _listen() -> None:
            try:
                request = Request(
                    self.endpoint,
                    headers={
                        "Accept": "text/event-stream",
                        "Mcp-Session-Id": self.session_id or "",
                        "User-Agent": _USER_AGENT,
                    },
                    method="GET",
                )
                with urlopen(request, timeout=self.timeout) as response:  # nosec B310
                    for message in self._iter_sse_messages(response):
                        if self._sse_stop.is_set():
                            break
                        if self._notification_cb:
                            self._notification_cb(message)
            except Exception as exc:
                if not self._sse_stop.is_set():
                    logger.debug("[MCP] SSE listener 종료: %s", exc)

        self._sse_stop.clear()
        self._sse_thread = threading.Thread(
            target=_listen,
            daemon=True,
            name="MCP-SSE-Listener",
        )
        self._sse_thread.start()

    def _iter_sse_messages(self, response) -> List[dict]:
        messages: List[dict] = []
        lines: List[str] = []
        while not self._sse_stop.is_set():
            raw_line = response.readline()
            if isinstance(raw_line, bytes):
                line = raw_line.decode("utf-8", errors="replace")
            else:
                line = str(raw_line or "")
            if not line:
                break
            stripped = line.rstrip("\r\n")
            if stripped:
                lines.append(stripped)
                continue
            payload = self._parse_sse("\n".join(lines))
            if payload:
                messages.append(payload)
            lines.clear()
        if lines:
            payload = self._parse_sse("\n".join(lines))
            if payload:
                messages.append(payload)
        return messages

    def _call_rpc(self, method: str, params: dict) -> dict:
        payload = {
            "jsonrpc": "2.0",
            "id": int(time.time() * 1000) % 1_000_000,
            "method": method,
            "params": dict(params or {}),
        }
        return self._post_rpc(payload)

    def _post_rpc(self, payload: dict) -> dict:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": _USER_AGENT,
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id

        request = Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urlopen(request, timeout=self.timeout) as response:  # nosec B310
            content_type = response.headers.get("Content-Type", "")
            raw = response.read().decode("utf-8", errors="replace")

        if "text/event-stream" in content_type.lower():
            return self._parse_sse(raw)
        try:
            return json.loads(raw or "{}")
        except json.JSONDecodeError:
            return {"result": {"text": raw}}

    def _post_notification(self, payload: dict) -> None:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": _USER_AGENT,
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        request = Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urlopen(request, timeout=self.timeout) as _:  # nosec B310
            pass

    def _parse_sse(self, raw: str) -> dict:
        last_data: Optional[str] = None
        for line in str(raw or "").splitlines():
            if line.startswith("data:"):
                value = line[5:].strip()
                last_data = f"{last_data}\n{value}" if last_data else value
        if not last_data:
            return {}
        try:
            return json.loads(last_data)
        except json.JSONDecodeError:
            return {"result": {"text": last_data}}

    def _extract_text(self, result: dict) -> str:
        if "error" in result:
            error = result["error"]
            if isinstance(error, dict):
                return f"[MCP server error] {error.get('message', error)}"
            return f"[MCP server error] {error}"
        payload: Any = result.get("result", result)
        if isinstance(payload, dict):
            content = payload.get("content")
            if isinstance(content, list):
                texts = [
                    item.get("text", "")
                    for item in content
                    if isinstance(item, dict) and item.get("text")
                ]
                if texts:
                    return "\n".join(texts)
            if "text" in payload:
                return str(payload["text"])
        if isinstance(payload, str):
            return payload
        return json.dumps(payload, ensure_ascii=False, indent=2)


class McpClientPool:
    """엔드포인트별 세션 풀."""

    def __init__(self):
        self._sessions: Dict[str, McpSession] = {}
        self._lock = threading.Lock()

    def get_session(
        self,
        endpoint: str,
        notification_cb: Optional[Callable[[dict], None]] = None,
    ) -> Optional[McpSession]:
        normalized = _require_https(endpoint)
        with self._lock:
            existing = self._sessions.get(normalized)
            if existing is not None:
                return existing
            session = McpSession(normalized)
            if not session.initialize(notification_cb=notification_cb):
                return None
            self._sessions[normalized] = session
            return session

    def list_tools(self, endpoint: str) -> List[dict]:
        session = self.get_session(endpoint)
        return session.list_tools() if session else []

    def call(self, endpoint: str, tool_name: str, arguments: dict) -> str:
        session = self.get_session(endpoint)
        if not session:
            return f"[MCP] Cannot connect to {endpoint}"
        return session.call_tool(tool_name, arguments)

    def close(self, endpoint: str) -> None:
        normalized = _require_https(endpoint)
        with self._lock:
            session = self._sessions.pop(normalized, None)
        if session:
            session.close()

    def close_all(self) -> None:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for session in sessions:
            try:
                session.close()
            except Exception as exc:
                logger.debug("[MCP] 세션 종료 생략: %s", exc)


_pool: Optional[McpClientPool] = None
_pool_lock = threading.Lock()


def get_mcp_pool() -> McpClientPool:
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = McpClientPool()
    return _pool


def reset_mcp_pool() -> None:
    global _pool
    with _pool_lock:
        if _pool is not None:
            _pool.close_all()
        _pool = None
