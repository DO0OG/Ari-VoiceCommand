"""Telegram long-polling bridge for remote Ari commands.

The bridge delegates command handling to the existing ``AICommand.run_interaction``
path so tool execution, safety checks, memory, and streaming callbacks stay
consistent with the local text UI.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from typing import Any, Callable, Iterable, Optional

try:
    import requests
except Exception:  # pragma: no cover - exercised only in minimal test envs
    requests = None

from agent.task_queue import AgentTaskQueue
from core.config_manager import ConfigManager
from services.messaging_bridge_base import ChatAuthorizer, IncomingMessage, StreamingTextBuffer

logger = logging.getLogger(__name__)

CommandRunner = Callable[[str, Optional[Callable[[str], None]]], str]


def _as_list(value: object) -> list[object]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in text.split(",") if part.strip()]


class TelegramApiClient:
    """Small Telegram Bot API client using the existing requests dependency."""

    def __init__(self, bot_token: str, *, timeout: float = 20.0, session: Any = None):
        if not bot_token:
            raise ValueError("bot_token is required")
        if requests is None and session is None:
            raise RuntimeError("requests is required for TelegramApiClient")
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.timeout = float(timeout or 20.0)
        self.session = session or requests.Session()

    def get_updates(self, *, offset: int | None = None, timeout: int = 25) -> list[dict]:
        payload: dict[str, object] = {"timeout": int(timeout), "allowed_updates": ["message"]}
        if offset is not None:
            payload["offset"] = offset
        response = self.session.get(f"{self.base_url}/getUpdates", params=payload, timeout=self.timeout + timeout)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram getUpdates failed: {data!r}")
        return list(data.get("result") or [])

    def send_message(self, chat_id: str, text: str, *, reply_to_message_id: int | None = None) -> int | None:
        payload: dict[str, object] = {"chat_id": chat_id, "text": text[:4096]}
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = reply_to_message_id
        response = self.session.post(f"{self.base_url}/sendMessage", json=payload, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram sendMessage failed: {data!r}")
        message = data.get("result") or {}
        return message.get("message_id")

    def edit_message(self, chat_id: str, message_id: int, text: str) -> None:
        payload = {"chat_id": chat_id, "message_id": message_id, "text": text[:4096]}
        response = self.session.post(f"{self.base_url}/editMessageText", json=payload, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram editMessageText failed: {data!r}")

    def send_photo(self, chat_id: str, image_path: str, *, caption: str = "") -> int | None:
        with open(image_path, "rb") as image_file:
            response = self.session.post(
                f"{self.base_url}/sendPhoto",
                data={"chat_id": chat_id, "caption": caption[:1024]},
                files={"photo": image_file},
                timeout=self.timeout,
            )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram sendPhoto failed: {data!r}")
        message = data.get("result") or {}
        return message.get("message_id")


class TelegramBridge:
    """Background Telegram long-polling runner."""

    def __init__(
        self,
        client: TelegramApiClient,
        command_runner: CommandRunner,
        *,
        allowed_chat_ids: Iterable[object],
        queue: AgentTaskQueue | None = None,
        poll_timeout: int = 25,
    ):
        self.client = client
        self.command_runner = command_runner
        self.authorizer = ChatAuthorizer(allowed_chat_ids)
        self.queue = queue or AgentTaskQueue(max_workers=1)
        self.poll_timeout = max(1, int(poll_timeout or 25))
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._offset: int | None = None

    @classmethod
    def from_settings(cls, command_runner: CommandRunner) -> "TelegramBridge | None":
        if not bool(ConfigManager.get("telegram_enabled", False)):
            return None
        token = str(ConfigManager.get("telegram_bot_token", "") or "").strip()
        allowed = _as_list(ConfigManager.get("telegram_allowed_chat_ids", []))
        if not token:
            logger.warning("[TelegramBridge] enabled but telegram_bot_token is empty")
            return None
        if not allowed:
            logger.warning("[TelegramBridge] enabled but telegram_allowed_chat_ids is empty")
            return None
        timeout = int(ConfigManager.get("telegram_poll_timeout_seconds", 25) or 25)
        return cls(
            TelegramApiClient(token),
            command_runner,
            allowed_chat_ids=allowed,
            poll_timeout=timeout,
        )

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self.run_forever, name="ari-telegram-bridge", daemon=True)
        self._thread.start()
        logger.info("[TelegramBridge] started")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
        self.queue.shutdown(cancel_pending=True)

    def run_forever(self) -> None:
        while not self._stop_event.is_set():
            try:
                for update in self.client.get_updates(offset=self._offset, timeout=self.poll_timeout):
                    self._offset = int(update.get("update_id", 0)) + 1
                    incoming = self._parse_update(update)
                    if incoming is not None:
                        self.handle_message(incoming)
            except Exception as exc:
                logger.warning("[TelegramBridge] polling failed: %s", exc)
                time.sleep(3.0)

    def _parse_update(self, update: dict) -> IncomingMessage | None:
        message = update.get("message") or {}
        text = str(message.get("text") or "").strip()
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id") or "").strip()
        if not text or not chat_id:
            return None
        sender = message.get("from") or {}
        return IncomingMessage(
            chat_id=chat_id,
            text=text,
            user_id=str(sender.get("id") or ""),
            message_id=message.get("message_id"),
        )

    def handle_message(self, incoming: IncomingMessage) -> str | None:
        if not self.authorizer.configured or not self.authorizer.is_allowed(incoming.chat_id):
            logger.warning("[TelegramBridge] rejected unauthorized chat_id=%s user_id=%s", incoming.chat_id, incoming.user_id)
            return None
        task_id = self.queue.submit(
            incoming.text,
            lambda cancel_event: self._run_message(incoming, cancel_event),
            priority=10,
        )
        logger.info("[TelegramBridge] queued task=%s chat_id=%s", task_id, incoming.chat_id)
        return task_id

    def _run_message(self, incoming: IncomingMessage, cancel_event: threading.Event) -> str:
        if cancel_event.is_set():
            return "cancelled"
        status_id = self.client.send_message(
            incoming.chat_id,
            "Processing...",
            reply_to_message_id=incoming.message_id,
        )
        last_text = {"value": ""}

        def emit_update(text: str) -> None:
            if cancel_event.is_set():
                return
            last_text["value"] = text
            if status_id is not None:
                try:
                    self.client.edit_message(incoming.chat_id, status_id, text)
                    return
                except Exception as exc:
                    logger.debug("[TelegramBridge] edit failed, sending new message: %s", exc)
            self.client.send_message(incoming.chat_id, text)

        stream = StreamingTextBuffer(emit_update)
        try:
            result = self.command_runner(incoming.text, stream.append)
        except Exception as exc:
            logger.exception("[TelegramBridge] command failed chat_id=%s", incoming.chat_id)
            try:
                emit_update(f"Error: {exc}")
            except Exception:
                logger.debug("[TelegramBridge] error notification failed", exc_info=True)
            raise
        stream.flush()
        final = (result or stream.text or last_text["value"] or "Done.").strip()
        image_path = self._extract_image_path(final)
        if image_path:
            try:
                self.client.send_photo(incoming.chat_id, image_path, caption="screenshot")
            except Exception as exc:
                logger.warning("[TelegramBridge] image send failed: %s", exc)
        if final != last_text["value"]:
            emit_update(final)
        return final

    def _extract_image_path(self, text: str) -> str:
        candidates = [str(text or "").strip()]
        candidates.extend(re.findall(r"([A-Za-z]:\\[^\r\n]+?\.(?:png|jpg|jpeg|webp))", text or "", flags=re.IGNORECASE))
        candidates.extend(re.findall(r"(/[^\r\n]+?\.(?:png|jpg|jpeg|webp))", text or "", flags=re.IGNORECASE))
        for candidate in candidates:
            path = candidate.strip().strip("\"'")
            if os.path.isfile(path) and path.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                return path
        return ""


def start_telegram_bridge(command_runner: CommandRunner) -> TelegramBridge | None:
    bridge = TelegramBridge.from_settings(command_runner)
    if bridge is not None:
        bridge.start()
    return bridge
