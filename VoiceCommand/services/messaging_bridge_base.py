"""Common primitives for remote messaging bridges."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable


@dataclass(frozen=True)
class IncomingMessage:
    """Normalized inbound message from a remote chat surface."""

    chat_id: str
    text: str
    user_id: str = ""
    message_id: int | None = None


class ChatAuthorizer:
    """Allow-list based chat authorization shared by bridge implementations."""

    def __init__(self, allowed_chat_ids: Iterable[object]):
        self._allowed = {
            str(chat_id).strip()
            for chat_id in allowed_chat_ids
            if str(chat_id).strip()
        }

    @property
    def configured(self) -> bool:
        return bool(self._allowed)

    def is_allowed(self, chat_id: object) -> bool:
        return str(chat_id).strip() in self._allowed


class StreamingTextBuffer:
    """Throttle streaming text updates before sending them to a chat client."""

    def __init__(self, emit: Callable[[str], None], *, min_chars: int = 80):
        self._emit = emit
        self._min_chars = max(1, int(min_chars or 1))
        self._buffer: list[str] = []
        self._last_sent = ""

    def append(self, delta: str) -> None:
        if not delta:
            return
        self._buffer.append(str(delta))
        current = self.text
        if len(current) - len(self._last_sent) >= self._min_chars or current.endswith((".", "!", "?", "\n")):
            self.flush()

    @property
    def text(self) -> str:
        return "".join(self._buffer)

    def flush(self) -> None:
        current = self.text.strip()
        if not current or current == self._last_sent:
            return
        self._emit(current)
        self._last_sent = current
