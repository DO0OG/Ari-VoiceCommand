"""Telegram long-polling bridge for remote Ari commands.

The bridge delegates command handling to the existing ``AICommand.run_interaction``
path so tool execution, safety checks, memory, and streaming callbacks stay
consistent with the local text UI.
"""

from __future__ import annotations

import logging
import inspect
import json
import os
import re
import secrets
import shutil
import tempfile
from contextlib import nullcontext
from dataclasses import replace
import threading
import time
import traceback
from typing import Any, Callable, Iterable

try:
    import requests
except Exception:  # pragma: no cover - exercised only in minimal test envs
    requests = None

from agent.task_queue import AgentTaskQueue
from core.config_manager import ConfigManager
from i18n.translator import _
from services.messaging_bridge_base import ChatAuthorizer, IncomingMessage, StreamingTextBuffer

logger = logging.getLogger(__name__)

REMOTE_APPROVAL_TIMEOUT_SECONDS = 60
MAX_DOWNLOAD_BYTES = 10 * 1024 * 1024
MAX_VOICE_SECONDS = 120
VOICE_SAMPLE_RATE = 16000
_FILE_PATH_PATTERN = re.compile(r"[A-Za-z0-9_.\-]+(?:/[A-Za-z0-9_.\-]+)*")

CommandRunner = Callable[..., str]
ImageAnalyzer = Callable[[str, str], str]


class TelegramFileTooLarge(Exception):
    """Raised when a Telegram file exceeds the download limit."""


def _as_list(value: object) -> list[object]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in text.split(",") if part.strip()]


def _redact_token(text: str) -> str:
    # Telegram puts the bot token in the URL path ("/bot<token>/method") of request errors.
    return re.sub(r"/bot[^/\s'\"?]+", "/bot***", text)


class TelegramApiClient:
    """Small Telegram Bot API client using the existing requests dependency."""

    def __init__(self, bot_token: str, *, timeout: float = 20.0, session: Any = None):
        if not bot_token:
            raise ValueError("bot_token is required")
        if requests is None and session is None:
            raise RuntimeError("requests is required for TelegramApiClient")
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self._file_base_url = f"https://api.telegram.org/file/bot{bot_token}"
        self.timeout = float(timeout or 20.0)
        self.session = session or requests.Session()

    def get_updates(self, *, offset: int | None = None, timeout: int = 25) -> list[dict]:
        payload: dict[str, object] = {"timeout": int(timeout), "allowed_updates": json.dumps(["message", "callback_query"])}
        if offset is not None:
            payload["offset"] = offset
        response = self.session.get(f"{self.base_url}/getUpdates", params=payload, timeout=self.timeout + timeout)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram getUpdates failed: {data!r}")
        return list(data.get("result") or [])

    def send_message(self, chat_id: str, text: str, *, reply_to_message_id: int | None = None, reply_markup: dict | None = None) -> int | None:
        if len(text) > 4096:
            first_id = None
            for offset in range(0, len(text), 4096):
                message_id = self.send_message(chat_id, text[offset:offset + 4096], reply_to_message_id=reply_to_message_id)
                if offset == 0:
                    first_id = message_id
            return first_id
        payload: dict[str, object] = {"chat_id": chat_id, "text": text}
        if reply_to_message_id is not None:
            payload["reply_to_message_id"] = reply_to_message_id
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        response = self.session.post(f"{self.base_url}/sendMessage", json=payload, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram sendMessage failed: {data!r}")
        message = data.get("result") or {}
        return message.get("message_id")

    def edit_message(self, chat_id: str, message_id: int, text: str, *, reply_markup: dict | None = None) -> None:
        payload = {"chat_id": chat_id, "message_id": message_id, "text": text[:4096]}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        response = self.session.post(f"{self.base_url}/editMessageText", json=payload, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram editMessageText failed: {data!r}")

    def answer_callback_query(self, callback_query_id: str) -> None:
        response = self.session.post(
            f"{self.base_url}/answerCallbackQuery",
            json={"callback_query_id": callback_query_id},
            timeout=self.timeout,
        )
        response.raise_for_status()
        if not response.json().get("ok"):
            raise RuntimeError("Telegram answerCallbackQuery failed")

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

    def download_file(self, file_id: str, *, max_bytes: int = MAX_DOWNLOAD_BYTES) -> bytes:
        response = self.session.get(f"{self.base_url}/getFile", params={"file_id": file_id}, timeout=self.timeout)
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(f"Telegram getFile failed: {data!r}")
        info = data.get("result") or {}
        file_path = str(info.get("file_path") or "")
        # 상대 경로만 허용해 내려받기 주소가 Telegram API 호스트를 벗어나지 못하게 한다.
        if not _FILE_PATH_PATTERN.fullmatch(file_path) or ".." in file_path.split("/"):
            raise RuntimeError("Telegram getFile returned an invalid file_path")
        size = info.get("file_size")
        if isinstance(size, int) and size > max_bytes:
            raise TelegramFileTooLarge(size)
        response = self.session.get(
            f"{self._file_base_url}/{file_path}", timeout=self.timeout, stream=True, allow_redirects=False)
        try:
            response.raise_for_status()
            if response.status_code != 200:
                raise RuntimeError(f"Telegram file download failed: HTTP {response.status_code}")
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(chunk_size=65536):
                total += len(chunk)
                if total > max_bytes:
                    raise TelegramFileTooLarge(total)
                chunks.append(chunk)
        finally:
            response.close()
        return b"".join(chunks)


def _create_stt_provider():
    from core.stt_provider import create_stt_provider

    return create_stt_provider(ConfigManager.load_settings())


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
        remote_approval_enabled: bool = False,
        voice_enabled: bool = False,
        photo_enabled: bool = False,
        image_analyzer: ImageAnalyzer | None = None,
        stt_factory: Callable[[], Any] | None = None,
    ):
        self.client = client
        self.command_runner = command_runner
        self.authorizer = ChatAuthorizer(allowed_chat_ids)
        self.queue = queue or AgentTaskQueue(max_workers=1)
        self.poll_timeout = max(1, int(poll_timeout or 25))
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._offset: int | None = None
        self.remote_approval_enabled = remote_approval_enabled is True
        self._approval_lock = threading.Lock()
        self._pending_approval: dict | None = None
        self.voice_enabled = voice_enabled is True
        self.photo_enabled = photo_enabled is True
        self.image_analyzer = image_analyzer
        self._stt_factory = stt_factory or _create_stt_provider
        self._stt: Any = None

    @classmethod
    def from_settings(cls, command_runner: CommandRunner, image_analyzer: ImageAnalyzer | None = None) -> "TelegramBridge | None":
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
            remote_approval_enabled=ConfigManager.get("telegram_remote_approval_enabled", False) is True,
            voice_enabled=ConfigManager.get("telegram_voice_enabled", False) is True,
            photo_enabled=ConfigManager.get("telegram_photo_enabled", False) is True,
            image_analyzer=image_analyzer,
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
        self._deny_pending_approval()
        if self._thread:
            self._thread.join(timeout=2.0)
        self.queue.shutdown(cancel_pending=True)
        # WhisperSTTProvider에는 공개 종료 메서드가 없고 __del__이 워커를 종료하므로 참조를 놓는다.
        self._stt = None

    def run_forever(self) -> None:
        while not self._stop_event.is_set():
            try:
                for update in self.client.get_updates(offset=self._offset, timeout=self.poll_timeout):
                    self._offset = int(update.get("update_id", 0)) + 1
                    if "callback_query" in update:
                        self._handle_callback_query(update["callback_query"])
                        continue
                    incoming = self._parse_update(update)
                    if incoming is not None:
                        self.handle_message(incoming)
            except Exception as exc:
                self._deny_pending_approval()
                logger.warning("[TelegramBridge] polling failed: %s", _redact_token(str(exc)))
                time.sleep(3.0)

    def _deny_pending_approval(self) -> None:
        with self._approval_lock:
            pending = self._pending_approval
            if pending is not None:
                pending["approved"] = False
                pending["event"].set()

    def _request_remote_approval(self, incoming: IncomingMessage, action_desc: str, report) -> bool:
        if not self.remote_approval_enabled or not self.authorizer.is_allowed(incoming.chat_id):
            return False
        nonce = secrets.token_hex(16)
        pending = {
            "chat_id": incoming.chat_id, "nonce": nonce, "event": threading.Event(),
            "approved": False, "claimed": False,
            "deadline": time.monotonic() + REMOTE_APPROVAL_TIMEOUT_SECONDS,
        }
        with self._approval_lock:
            if self._pending_approval is not None or self._stop_event.is_set():
                return False
            self._pending_approval = pending
        try:
            text = _("위험 작업 확인\n작업: {action_desc}\n위험 요약: {summary}\n{seconds}초 안에 승인하거나 거부해 주세요.",
                     action_desc=action_desc[:1500], summary=report.summary[:1500],
                     seconds=REMOTE_APPROVAL_TIMEOUT_SECONDS)
            message_id = self.client.send_message(
                incoming.chat_id, text, reply_to_message_id=incoming.message_id,
                reply_markup={"inline_keyboard": [[
                    {"text": _("승인"), "callback_data": f"{nonce}:approve"},
                    {"text": _("거부"), "callback_data": f"{nonce}:deny"},
                ]]},
            )
            if message_id is None:
                return False
            signaled = pending["event"].wait(max(0.0, pending["deadline"] - time.monotonic()))
            with self._approval_lock:
                self._pending_approval = None
                expired = not signaled or time.monotonic() >= pending["deadline"]
                approved = not expired and pending["approved"] and not self._stop_event.is_set()
            if expired:
                status = _("시간 초과: 작업이 거부되었습니다.")
            elif approved:
                status = _("승인됨")
            else:
                status = _("거부됨")
            self.client.edit_message(incoming.chat_id, message_id, status,
                                     reply_markup={"inline_keyboard": []})
            # 결과 메시지를 고치는 동안 중지됐으면 승인을 받았더라도 실행하지 않는다.
            return bool(approved) and not self._stop_event.is_set()
        except Exception as exc:
            logger.warning("[TelegramBridge] remote approval failed: %s", _redact_token(str(exc)))
            return False
        finally:
            with self._approval_lock:
                if self._pending_approval is pending:
                    self._pending_approval = None

    def _handle_callback_query(self, query: dict) -> None:
        if not self.remote_approval_enabled:
            return
        chat_id = str(((query.get("message") or {}).get("chat") or {}).get("id") or "")
        if not self.authorizer.is_allowed(chat_id):
            return
        with self._approval_lock:
            pending = self._pending_approval
            if (pending is None or chat_id != pending["chat_id"] or pending["claimed"]
                    or pending["event"].is_set() or time.monotonic() >= pending["deadline"]):
                return
            data = query.get("data")
            if data not in (f"{pending['nonce']}:approve", f"{pending['nonce']}:deny"):
                return
            pending["claimed"] = True
        approved = False
        try:
            self.client.answer_callback_query(query["id"])
            approved = data == f"{pending['nonce']}:approve"
        except Exception as exc:
            logger.warning("[TelegramBridge] callback response failed: %s", _redact_token(str(exc)))
        with self._approval_lock:
            if self._pending_approval is pending and not pending["event"].is_set():
                pending["approved"] = approved and time.monotonic() < pending["deadline"]
                pending["event"].set()

    def _parse_update(self, update: dict) -> IncomingMessage | None:
        message = update.get("message") or {}
        text = str(message.get("text") or "").strip()
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id") or "").strip()
        media = None if text else self._parse_media(message)
        if (not text and media is None) or not chat_id:
            return None
        if media is not None:
            text = str(message.get("caption") or "").strip()
        sender = message.get("from") or {}
        return IncomingMessage(
            chat_id=chat_id,
            text=text,
            user_id=str(sender.get("id") or ""),
            message_id=message.get("message_id"),
            media=media,
        )

    def _parse_media(self, message: dict) -> dict | None:
        voice = message.get("voice")
        if self.voice_enabled and isinstance(voice, dict) and voice.get("file_id"):
            return {"kind": "voice", "file_id": voice["file_id"],
                    "file_size": voice.get("file_size"), "duration": voice.get("duration")}
        photos = [item for item in message.get("photo") or [] if isinstance(item, dict) and item.get("file_id")]
        if self.photo_enabled and photos:
            best = max(photos, key=lambda item: (item.get("width") or 0) * (item.get("height") or 0))
            return {"kind": "photo", "file_id": best["file_id"], "file_size": best.get("file_size")}
        return None

    def handle_message(self, incoming: IncomingMessage) -> str | None:
        if not self.authorizer.configured or not self.authorizer.is_allowed(incoming.chat_id):
            logger.warning("[TelegramBridge] rejected unauthorized chat_id=%s user_id=%s", incoming.chat_id, incoming.user_id)
            return None
        task_id = self.queue.submit(
            incoming.text or (incoming.media or {}).get("kind", ""),
            lambda cancel_event: self._run_queued_message(incoming, cancel_event),
            priority=10,
        )
        logger.info("[TelegramBridge] queued task=%s chat_id=%s", task_id, incoming.chat_id)
        return task_id

    def _run_queued_message(self, incoming: IncomingMessage, cancel_event: threading.Event) -> str:
        try:
            run = self._run_media if incoming.media else self._run_message
            return run(incoming, cancel_event)
        except Exception as exc:
            # 작업 큐가 예외를 traceback과 함께 기록하므로 토큰이 든 원본 예외를 그대로 넘기지 않는다.
            raise RuntimeError(_redact_token(str(exc))) from None

    def _run_message(self, incoming: IncomingMessage, cancel_event: threading.Event) -> str:
        if cancel_event.is_set():
            return "cancelled"
        status_id = self.client.send_message(
            incoming.chat_id,
            "Processing...",
            reply_to_message_id=incoming.message_id,
        )
        last_text = {"value": ""}
        image_paths: list[str] = []

        def collect_image(name: str, result: str | None) -> None:
            if name == "take_screenshot":
                path = result
            elif name == "generate_image":
                try:
                    payload = json.loads(result or "{}")
                except (TypeError, ValueError):
                    return
                path = payload.get("path") if isinstance(payload, dict) else None
            else:
                return
            if isinstance(path, str) and os.path.isfile(path) and path.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                if path not in image_paths:
                    image_paths.append(path)

        def emit_update(text: str) -> None:
            if cancel_event.is_set():
                return
            last_text["value"] = text
            if status_id is not None:
                try:
                    self.client.edit_message(incoming.chat_id, status_id, text)
                    return
                except Exception as exc:
                    logger.debug("[TelegramBridge] edit failed, sending new message: %s", _redact_token(str(exc)))
            self.client.send_message(incoming.chat_id, text[:4096])

        stream = StreamingTextBuffer(emit_update)
        try:
            try:
                parameters = inspect.signature(self.command_runner).parameters
            except (TypeError, ValueError):
                parameters = {}
            scope = nullcontext()
            if self.remote_approval_enabled:
                from agent.confirmation_manager import remote_approval_scope
                scope = remote_approval_scope(
                    lambda action, report: self._request_remote_approval(incoming, action, report))
            with scope:
                if "tool_result_callback" in parameters:
                    result = self.command_runner(incoming.text, stream.append, tool_result_callback=collect_image)
                else:
                    result = self.command_runner(incoming.text, stream.append)
        except Exception as exc:
            logger.error("[TelegramBridge] command failed chat_id=%s\n%s", incoming.chat_id, _redact_token(traceback.format_exc()))
            try:
                emit_update(f"Error: {_redact_token(str(exc))}")
            except Exception:
                logger.debug("[TelegramBridge] error notification failed\n%s", _redact_token(traceback.format_exc()))
            raise
        stream.flush()
        final = (result or stream.text or last_text["value"] or "Done.").strip()
        for image_path in image_paths:
            try:
                self.client.send_photo(incoming.chat_id, image_path, caption="screenshot")
            except Exception as exc:
                logger.warning("[TelegramBridge] image send failed: %s", _redact_token(str(exc)))
        if final != last_text["value"] or len(final) > 4096:
            emit_update(final[:4096])
            if not cancel_event.is_set():
                for offset in range(4096, len(final), 4096):
                    self.client.send_message(incoming.chat_id, final[offset:offset + 4096])
        return final

    def _reply(self, incoming: IncomingMessage, text: str) -> str:
        self.client.send_message(incoming.chat_id, text, reply_to_message_id=incoming.message_id)
        return text

    def _reply_too_large(self, incoming: IncomingMessage) -> str:
        return self._reply(incoming, _("파일 크기나 길이가 한도를 넘어 처리하지 않았어요. (최대 {mb}MB, 음성은 최대 {seconds}초)",
                                       mb=MAX_DOWNLOAD_BYTES // (1024 * 1024), seconds=MAX_VOICE_SECONDS))

    def _run_media(self, incoming: IncomingMessage, cancel_event: threading.Event) -> str:
        if cancel_event.is_set():
            return "cancelled"
        try:
            if incoming.media["kind"] == "voice":
                return self._run_voice(incoming, cancel_event)
            return self._run_photo(incoming, cancel_event)
        except Exception as exc:
            logger.error("[TelegramBridge] media failed chat_id=%s\n%s", incoming.chat_id, _redact_token(traceback.format_exc()))
            try:
                self._reply(incoming, f"Error: {_redact_token(str(exc))}")
            except Exception:
                logger.debug("[TelegramBridge] error notification failed\n%s", _redact_token(traceback.format_exc()))
            raise

    def _run_voice(self, incoming: IncomingMessage, cancel_event: threading.Event) -> str:
        media = incoming.media
        if ConfigManager.get("stt_provider", "google") != "whisper":
            return self._reply(incoming, _("음성 메모는 음성 인식을 로컬 Whisper로 설정했을 때만 처리할 수 있어요."))
        size, duration = media.get("file_size"), media.get("duration")
        if (isinstance(size, int) and size > MAX_DOWNLOAD_BYTES) or (isinstance(duration, (int, float)) and duration > MAX_VOICE_SECONDS):
            return self._reply_too_large(incoming)
        try:
            data = self.client.download_file(media["file_id"], max_bytes=MAX_DOWNLOAD_BYTES)
        except TelegramFileTooLarge:
            return self._reply_too_large(incoming)
        from audio.mp3_decoder import AudioTooLongError, decode_ogg_to_pcm

        try:
            pcm = decode_ogg_to_pcm(data, VOICE_SAMPLE_RATE, MAX_VOICE_SECONDS * VOICE_SAMPLE_RATE)
        except AudioTooLongError:
            return self._reply_too_large(incoming)
        import speech_recognition as sr

        if self._stt is None:
            self._stt = self._stt_factory()
        text = str(self._stt.transcribe(sr.AudioData(pcm, VOICE_SAMPLE_RATE, 2), mode="command") or "").strip()
        if cancel_event.is_set():
            return "cancelled"
        if not text:
            return self._reply(incoming, _("음성을 알아듣지 못했어요."))
        self._reply(incoming, _("들은 내용: {text}", text=text))
        # 글 메시지와 같은 경로를 타야 위험 작업 확인·원격 승인이 그대로 적용된다.
        return self._run_message(replace(incoming, text=text, media=None), cancel_event)

    def _run_photo(self, incoming: IncomingMessage, cancel_event: threading.Event) -> str:
        media = incoming.media
        size = media.get("file_size")
        if isinstance(size, int) and size > MAX_DOWNLOAD_BYTES:
            return self._reply_too_large(incoming)
        failure = _("사진을 분석하지 못했어요.")
        if self.image_analyzer is None:
            return self._reply(incoming, failure)
        question = incoming.text or _("이 이미지를 설명해줘.")
        work_dir = tempfile.mkdtemp(prefix="ari_telegram_")
        try:
            try:
                data = self.client.download_file(media["file_id"], max_bytes=MAX_DOWNLOAD_BYTES)
            except TelegramFileTooLarge:
                return self._reply_too_large(incoming)
            image_path = os.path.join(work_dir, "photo.jpg")
            with open(image_path, "wb") as image_file:
                image_file.write(data)
            if cancel_event.is_set():
                return "cancelled"
            result = self.image_analyzer(image_path, question)
        finally:
            shutil.rmtree(work_dir, ignore_errors=True)
        if cancel_event.is_set():
            return "cancelled"
        text = str(result or "").strip() or failure
        for offset in range(0, len(text), 4096):
            self.client.send_message(incoming.chat_id, text[offset:offset + 4096],
                                     reply_to_message_id=incoming.message_id if offset == 0 else None)
        return text


def start_telegram_bridge(command_runner: CommandRunner, image_analyzer: ImageAnalyzer | None = None) -> TelegramBridge | None:
    bridge = TelegramBridge.from_settings(command_runner, image_analyzer)
    if bridge is not None:
        bridge.start()
    return bridge
