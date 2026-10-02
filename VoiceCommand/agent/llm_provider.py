"""
다중 LLM 제공자 통합 — Groq, OpenAI, Anthropic, Mistral, Gemini, OpenRouter
모든 OpenAI-호환 제공자는 openai SDK + base_url 방식으로 통일.
Anthropic만 자체 SDK 사용.
"""
import base64
import ipaddress
import json
import logging
import math
import mimetypes
import os
import re
import threading
from datetime import datetime
from typing import Callable, List, Any
from urllib.parse import urlsplit

import httpx

from agent.assistant_text_utils import (
    analyze_tool_request,
    clean_tool_artifact_text,
    resolve_agent_task_goal,
)
from agent.response_cache import ResponseCache, build_response_cache_key
from agent.tool_schemas import CORE_TOOL_SCHEMAS, build_available_tools

from agent.provider_config import _PROVIDER_CONFIG, _KEY_MAP, get_provider_configs
from core.config_manager import ConfigManager
from core.settings_schema import DEFAULT_SETTINGS
from core.activity_monitor import get_activity_context
from core.mood_state import get_mood_state
from i18n.translator import _

_EN_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

from agent.tool_selection import _get_tool_instruction, _CORE_TOOL_NAMES, _TOOL_NAMES_BY_INTENT

class LLMProvider:
    """단일 인터페이스로 여러 LLM 제공자를 지원하는 클래스."""

    def __init__(self, provider="groq", api_key="", model="",
                 planner_model="", execution_model="",
                 planner_provider="", execution_provider="",
                 planner_api_key="", execution_api_key="",
                 memory_extractor_provider="", memory_extractor_model="",
                 memory_extractor_api_key="",
                 system_prompt="", personality="", scenario="", history_instruction="",
                 response_verbosity="concise", router_enabled=DEFAULT_SETTINGS["llm_router_enabled"],
                 provider_configs=None, personality_examples_en="", personality_examples_ja=""):
        self.provider = provider
        self.api_key = api_key
        self.provider_configs = {
            name: dict(config) for name, config in (
                _PROVIDER_CONFIG if provider_configs is None else provider_configs
            ).items()
        }
        self.model = model.strip()
        # 역할별 제공자 (비어있으면 기본 제공자 사용)
        self.planner_provider = planner_provider.strip() or provider
        self.execution_provider = execution_provider.strip() or provider

        def role_model_default(selected):
            if selected == provider or (provider in _PROVIDER_CONFIG and selected in _PROVIDER_CONFIG):
                return self.model
            return self.provider_configs.get(selected, {}).get("default_model", "")

        self.planner_model = planner_model.strip() or role_model_default(self.planner_provider)
        self.execution_model = execution_model.strip() or role_model_default(self.execution_provider)
        self.memory_extractor_provider = (
            memory_extractor_provider.strip() or self.execution_provider
        )
        self.memory_extractor_model = memory_extractor_model.strip() or (
            self.execution_model
            if self.memory_extractor_provider == self.execution_provider
            else role_model_default(self.memory_extractor_provider)
        )
        self.system_prompt = system_prompt
        self.personality = personality
        self.scenario = scenario
        self.router_enabled = bool(router_enabled)
        self.conversation_history = []
        self._history_lock = threading.RLock()
        # 설정 재구성 도중 제공자·모델·client가 섞여 읽히지 않게 한다.
        self._config_lock = threading.RLock()
        self._active_stream_lock = threading.Lock()
        self._active_stream = None
        self._active_stream_cancel_event = None
        self.max_history = 10
        self.max_context_tokens = self._load_int_setting("max_context_tokens", 8000)
        self._tool_streaming_support: dict[str, bool] = {}
        self.client = None
        self.planner_client = None   # None = 기본 client 사용
        self.execution_client = None  # None = 기본 client 사용
        self.memory_extractor_client = None
        self._plugin_tools: list = []
        self._plugin_tool_intents: dict[str, set[str]] = {}
        self._response_cache = ResponseCache.from_config()
        from core.rp_generator import RPGenerator
        self.rp_generator = RPGenerator()
        self.rp_generator.set_config(
            personality=personality,
            scenario=scenario,
            system_prompt=system_prompt,
            history_instruction=history_instruction,
            personality_examples_en=personality_examples_en,
            personality_examples_ja=personality_examples_ja,
            response_verbosity=response_verbosity,
        )

        if api_key or provider == "ollama" or not self.provider_configs.get(provider, {}).get("requires_api_key", True):
            self._init_client()
        # 별도 제공자가 지정된 경우 추가 클라이언트 초기화
        if planner_provider and planner_provider != provider and (
            planner_api_key or not self.provider_configs.get(planner_provider, {}).get("requires_api_key", True)
        ):
            self.planner_client = self._make_client(
                self.planner_provider, planner_api_key, role="planner"
            )
            if self.planner_client:
                logging.info("플래너 클라이언트 초기화 완료 (%s / %s)", self.planner_provider, self.planner_model)
        elif self.client and (
            self._read_timeout_seconds(self.provider, "planner")
            != self._read_timeout_seconds(self.provider, "default")
        ):
            self.planner_client = self._make_client(
                self.planner_provider, planner_api_key or api_key, role="planner"
            )
        if execution_provider and execution_provider != provider and (
            execution_api_key or not self.provider_configs.get(execution_provider, {}).get("requires_api_key", True)
        ):
            self.execution_client = self._make_client(
                self.execution_provider, execution_api_key, role="execution"
            )
            if self.execution_client:
                logging.info("실행 클라이언트 초기화 완료 (%s / %s)", self.execution_provider, self.execution_model)
        if self.memory_extractor_provider not in {provider, self.execution_provider} and (
            memory_extractor_api_key
            or not self.provider_configs.get(self.memory_extractor_provider, {}).get(
                "requires_api_key", True
            )
        ):
            self.memory_extractor_client = self._make_client(
                self.memory_extractor_provider,
                memory_extractor_api_key,
                role="execution",
            )

    # ── 초기화 ─────────────────────────────────────────────────────────────────

    def _make_client(self, provider: str, api_key: str, role: str = "default"):
        """제공자와 API 키로 클라이언트 객체를 생성한다."""
        cfg = self.provider_configs.get(provider)
        if cfg is None:
            return None
        try:
            timeout = httpx.Timeout(
                self._read_timeout_seconds(provider, role),
                connect=5.0,
            )
            if provider == "anthropic":
                import anthropic
                return anthropic.Anthropic(
                    api_key=api_key,
                    timeout=timeout,
                    max_retries=1,
                )
            else:
                from openai import OpenAI
                kwargs = {"api_key": api_key, "timeout": timeout, "max_retries": 1}
                if provider == "ollama":
                    kwargs["api_key"] = api_key or "ollama"
                    kwargs["base_url"] = self._get_ollama_url()
                elif cfg.get("base_url"):
                    kwargs["base_url"] = cfg["base_url"]
                if self._is_custom_provider(provider) and not api_key:
                    # OpenAI SDK는 키를 필수로 받지만 로컬 서버 설정에서는 키가 선택 사항입니다.
                    kwargs["api_key"] = "custom-provider"
                if provider == "openrouter":
                    kwargs["default_headers"] = {
                        "HTTP-Referer": "https://github.com/Ari-Assistant",
                        "X-Title": "Ari Voice Assistant",
                    }
                return OpenAI(**kwargs)
        except Exception as e:
            self._log_provider_exception(logging.error, "LLM 클라이언트 초기화 실패", provider, e)
            return None

    def _read_timeout_seconds(self, provider: str, role: str) -> float:
        if self._is_local_provider(provider):
            key, default = "llm_timeout_local_seconds", 120
        else:
            key, default = {
                "planner": ("llm_timeout_planner_seconds", 90),
                "execution": ("llm_timeout_chat_seconds", 30),
            }.get(role, ("llm_timeout_chat_seconds", 30))
        return self._load_timeout_seconds(key, default)

    def _load_timeout_seconds(self, key: str, default: int) -> float:
        try:
            value = ConfigManager.get(key, default)
        except (ImportError, OSError, RuntimeError, TypeError, ValueError):
            return float(default)
        if isinstance(value, bool):
            return float(default)
        try:
            seconds = float(value)
        except (OverflowError, TypeError, ValueError):
            return float(default)
        if not math.isfinite(seconds) or seconds <= 0:
            return float(default)
        return seconds

    def _is_local_provider(self, provider: str) -> bool:
        if provider in {"ollama", "local", "localai", "lmstudio", "lm_studio", "llamacpp"}:
            return True
        endpoint = self.provider_configs.get(provider, {}).get("base_url")
        try:
            hostname = urlsplit(str(endpoint or "")).hostname
        except ValueError:
            return False
        if not hostname:
            return False
        if hostname == "localhost" or hostname.endswith((".localhost", ".local")):
            return True
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError:
            return False
        return address.is_loopback or address.is_private or address.is_link_local

    def _is_custom_provider(self, provider: str) -> bool:
        return provider in self.provider_configs and provider not in _PROVIDER_CONFIG

    def _log_provider_exception(self, log, message: str, provider: str, error: Exception) -> None:
        if self._is_custom_provider(provider):
            log("%s (custom provider): %s", message, type(error).__name__)
        else:
            log("%s (%s): %s", message, provider, error)

    @staticmethod
    def _safe_custom_provider_error(error: Exception) -> Exception:
        safe_error = RuntimeError("Custom provider request failed")
        status = getattr(error, "status_code", None)
        if isinstance(status, int):
            safe_error.status_code = status
        return safe_error

    def _sanitize_custom_stream(self, stream, provider: str = ""):
        try:
            yield from stream
        except Exception as exc:
            if provider and self._is_streaming_unsupported_error(exc):
                self._tool_streaming_support[provider] = False
            if self._is_timeout_error(exc):
                raise TimeoutError("Custom provider stream timed out") from None
            raise self._safe_custom_provider_error(exc) from None

    @staticmethod
    def _is_timeout_error(error: Exception) -> bool:
        return (
            isinstance(error, (TimeoutError, httpx.TimeoutException))
            or "timeout" in type(error).__name__.lower()
        )

    @staticmethod
    def _is_streaming_unsupported_error(error: Exception) -> bool:
        status = getattr(error, "status_code", None)
        if status not in {400, 404, 422}:
            return False
        message = str(error).lower()
        return "stream" in message and any(
            phrase in message
            for phrase in (
                "not support",
                "unsupported",
                "not allowed",
                "unknown parameter",
                "unrecognized",
            )
        )

    @staticmethod
    def _response_field(value, name: str, default=None):
        if isinstance(value, dict):
            return value.get(name, default)
        return getattr(value, name, default)

    @staticmethod
    def _is_structured_response(text: str) -> bool:
        candidate = str(text or "").lstrip()
        return candidate.startswith("{") or candidate.startswith(chr(96) * 3)

    def _get_ollama_url(self) -> str:
        try:
            return ConfigManager.get("ollama_base_url", "http://localhost:11434/v1")
        except Exception as exc:
            logging.debug("[LLMProvider] ollama_base_url 조회 실패, 기본값 사용: %s", exc)
            return "http://localhost:11434/v1"

    def _init_client(self):
        self.client = self._make_client(self.provider, self.api_key)
        if self.client:
            logging.info("LLM 클라이언트 초기화 완료 (%s / %s)", self.provider, self.model)
            logging.info(
                "  - Planner: %s/%s, Execution: %s/%s",
                self.planner_provider,
                self.planner_model,
                self.execution_provider,
                self.execution_model,
            )

    # ── 도구 정의 ──────────────────────────────────────────────────────────────

    def get_available_tools(self):
        """OpenAI-호환 function calling 스키마"""
        plugin_tools = sorted(
            self._plugin_tools,
            key=lambda tool: str((tool.get("function") or {}).get("name", "")),
        )
        return build_available_tools(plugin_tools)

    def get_available_functions(self):
        return [t["function"] for t in self.get_available_tools()]

    def register_plugin_tool(
        self,
        schema: dict,
        intents: list[str] | None = None,
    ) -> None:
        """플러그인 도구 스키마를 등록한다."""
        tool_name = str(schema.get("function", {}).get("name", "") or "")
        self._plugin_tools = [
            tool for tool in self._plugin_tools
            if tool.get("function", {}).get("name", "") != tool_name
        ]
        self._plugin_tools.append(schema)
        if intents is None:
            self._plugin_tool_intents.pop(tool_name, None)
        else:
            self._plugin_tool_intents[tool_name] = {
                normalized
                for intent in intents
                if (normalized := str(intent).strip().lower())
            }

    def unregister_plugin_tool(self, tool_name: str) -> None:
        self._plugin_tools = [
            tool for tool in self._plugin_tools
            if tool.get("function", {}).get("name", "") != tool_name
        ]
        self._plugin_tool_intents.pop(tool_name, None)

    # ── 대화 ───────────────────────────────────────────────────────────────────

    def add_to_history(self, role, content):
        with self._history_lock:
            self.conversation_history.append({"role": role, "content": content})
            if len(self.conversation_history) > self.max_history * 2:
                self.conversation_history = self.conversation_history[-self.max_history * 2:]
            # Never retain a result after its corresponding tool-use turn was trimmed.
            while self.conversation_history and self._is_tool_result_message(self.conversation_history[0]):
                self.conversation_history.pop(0)

    def mark_last_response_interrupted(
        self,
        expected_response: str,
        interrupted_response: str,
    ) -> bool:
        """LLM 문맥의 마지막 응답을 중단된 내용으로 바꾼다."""
        expected = str(expected_response or "").strip()
        replacement = str(interrupted_response or "").strip()
        if not replacement:
            return False
        with self._history_lock:
            for message in reversed(self.conversation_history):
                if message.get("role") != "assistant":
                    continue
                response = message.get("content")
                if not isinstance(response, str):
                    continue
                if expected and expected not in response:
                    continue
                message["content"] = replacement
                return True
            self.conversation_history.append(
                {"role": "assistant", "content": replacement}
            )
            return True

    def _set_active_stream(self, stream, cancel_event) -> None:
        with self._active_stream_lock:
            self._active_stream = stream
            self._active_stream_cancel_event = cancel_event

    def _clear_active_stream(self, stream) -> None:
        with self._active_stream_lock:
            if self._active_stream is stream:
                self._active_stream = None
                self._active_stream_cancel_event = None

    def stop_stream(self) -> bool:
        """활성 LLM 스트림을 닫는다."""
        with self._active_stream_lock:
            stream = self._active_stream
            cancel_event = self._active_stream_cancel_event
        if stream is None:
            return False
        if cancel_event is not None:
            cancel_event.set()
        close = getattr(stream, "close", None)
        if callable(close):
            try:
                close()
            except (OSError, RuntimeError, TypeError, ValueError, httpx.HTTPError) as exc:
                logging.debug("LLM 스트림 닫기 생략: %s", exc)
        return True

    @staticmethod
    def _is_tool_result_message(message: dict) -> bool:
        content = message.get("content")
        return message.get("role") == "user" and isinstance(content, list) and any(
            block.get("type") == "tool_result" for block in content
        )

    def clear_history(self, keep_current_turn=False):
        with self._history_lock:
            history = self.conversation_history
            start = len(history)
            if keep_current_turn:
                # 도구 호출 도중에 모두 지우면 그 호출과 결과의 짝이 깨지므로 이번 요청부터는 남긴다.
                for index in range(len(history) - 1, -1, -1):
                    message = history[index]
                    if message.get("role") == "user" and isinstance(message.get("content"), str):
                        start = index
                        break
            self.conversation_history = history[start:]

    def _history_snapshot(self) -> list[dict]:
        with self._history_lock:
            return list(self.conversation_history)

    def _load_int_setting(self, key: str, default: int) -> int:
        try:
            return int(ConfigManager.get(key, default) or default)
        except Exception:
            return default

    def _estimate_tokens(self, messages: list[dict]) -> int:
        total = 0
        for message in messages:
            content = message.get("content", "")
            if isinstance(content, list):
                content = json.dumps(content, ensure_ascii=False, default=str)
            total += max(1, len(str(content or "")) // 3)
        return total

    def _compact_history_message(self, message: dict) -> dict:
        compacted = dict(message)
        content = compacted.get("content")
        if isinstance(content, str) and len(content) > 2000:
            compacted["content"] = f"[도구 결과 요약: {len(content)}자]"
        return compacted

    @staticmethod
    def _has_tool_blocks(message: dict) -> bool:
        content = message.get("content")
        return isinstance(content, list) and any(
            isinstance(block, dict) and block.get("type") in ("tool_use", "tool_result")
            for block in content
        )

    def _history_for_context(self, max_tokens: int | None = None, tool_blocks: bool = True) -> list[dict]:
        budget = int(max_tokens or self.max_context_tokens or 8000)
        with self._history_lock:
            history = list(self.conversation_history)
        if not tool_blocks:
            # Anthropic 형식의 도구 블록은 다른 제공자가 받지 못한다.
            # 뺀 자리에서 같은 역할이 이어지면 역할 교대를 요구하는 서버가 거절하므로 합친다.
            kept, dropped = [], False
            for message in history:
                if self._has_tool_blocks(message):
                    dropped = True
                    continue
                previous = kept[-1] if kept else {}
                if (
                    dropped
                    and previous.get("role") == message.get("role")
                    and isinstance(previous.get("content"), str)
                    and isinstance(message.get("content"), str)
                ):
                    kept[-1] = {**previous, "content": f"{previous['content']}\n\n{message['content']}"}
                else:
                    kept.append(message)
                dropped = False
            history = kept
        cleaned_history = []
        index = 0
        while index < len(history):
            message = history[index]
            content = message.get("content")
            tool_uses = (
                [block for block in content if isinstance(block, dict) and block.get("type") == "tool_use"]
                if message.get("role") == "assistant" and isinstance(content, list)
                else []
            )
            if tool_uses:
                result_message = history[index + 1] if index + 1 < len(history) else {}
                result_content = result_message.get("content")
                tool_results = (
                    [block for block in result_content if isinstance(block, dict) and block.get("type") == "tool_result"]
                    if result_message.get("role") == "user" and isinstance(result_content, list)
                    else []
                )
                use_ids = [block.get("id") for block in tool_uses]
                result_ids = [block.get("tool_use_id") for block in tool_results]
                if (
                    use_ids
                    and None not in use_ids
                    and len(use_ids) == len(set(use_ids))
                    and use_ids == result_ids
                ):
                    cleaned_history.extend((message, result_message))
                    index += 2
                else:
                    index += 1
                    if index < len(history) and self._is_tool_result_message(history[index]):
                        index += 1
                continue
            if self._is_tool_result_message(message):
                index += 1
                continue
            cleaned_history.append(message)
            index += 1
        history = cleaned_history
        selected: list[dict] = []
        used = 0
        while history:
            message = history.pop()
            group = [self._compact_history_message(message)]
            if self._is_tool_result_message(message):
                if not history:
                    break
                group.insert(0, self._compact_history_message(history.pop()))
            cost = self._estimate_tokens(group)
            if selected and used + cost > budget:
                break
            selected.extend(reversed(group))
            used += cost
        selected.reverse()
        return selected

    def _estimate_max_tokens(self, message: str) -> int:
        length = len(message or "")
        if length < 20:
            return 200
        if length < 60:
            return 400
        if length < 150:
            return 600
        return 800

    def _should_cache(self, message: str) -> bool:
        text = (message or "").lower()
        skip_keywords = (
            "날씨", "기온", "시간", "몇 시", "temperature", "weather", "forecast",
            "예약", "스케줄", "일정", "저장", "실행", "삭제", "이동", "복사",
            "tool", "명령", "지금", "현재", "today", "now",
        )
        static_signals = (
            "뭐야", "뭐에요", "설명", "알려줘", "란", "의미", "정의",
            "what is", "explain", "tell me about",
        )
        return any(signal in text for signal in static_signals) and not any(keyword in text for keyword in skip_keywords)

    def _offline_response(self, message: str) -> str:
        return _("(걱정) 연결 설정을 확인해주세요. 기본 명령은 그대로 쓸 수 있어요.")

    @staticmethod
    def _error_response(error: Exception) -> str:
        status = getattr(error, "status_code", None)
        if status in {401, 403}:
            return _("(걱정) 인증에 실패했어요. 설정에서 인증 정보를 확인해주세요.")
        if status == 429:
            return _("(걱정) 요청 한도를 초과했어요. 잠시 후 다시 시도해주세요.")
        if isinstance(status, int) and 500 <= status < 600:
            return _("(걱정) 서버 오류로 요청을 처리하지 못했어요. 잠시 후 다시 시도해주세요.")
        if isinstance(error, (ConnectionError, TimeoutError)) or type(error).__name__ in {
            "APIConnectionError", "APITimeoutError", "ConnectError", "ConnectTimeout", "ReadTimeout",
        }:
            return _("(걱정) 서버에 연결할 수 없어요. 네트워크 상태를 확인해주세요.")
        return _("(걱정) 요청을 처리하지 못했어요. 잠시 후 다시 시도해주세요.")

    def _create_completion_with_fallback(
        self,
        client,
        provider,
        model,
        *,
        _return_target: bool = False,
        _excluded_targets: set[tuple[str, str]] | None = None,
        **kwargs,
    ):
        targets = [(client, provider, model)]
        excluded_targets = set(_excluded_targets or ())
        attempted = set()
        last_error = None
        last_backend = ""
        while targets:
            candidate, backend, selected = targets.pop(0)
            target_key = (str(backend or ""), str(selected or ""))
            if (
                backend in attempted
                or backend == "anthropic"
                or target_key in excluded_targets
            ):
                continue
            attempted.add(backend)
            try:
                response = candidate.chat.completions.create(
                    model=selected, **kwargs, extra_body=self._reasoning_extra_body(backend),
                )
                if kwargs.get("stream") and self._is_custom_provider(backend):
                    response = self._sanitize_custom_stream(response, backend)
                if _return_target:
                    return response, (candidate, backend, selected)
                return response
            except Exception as exc:
                status = getattr(exc, "status_code", None)
                if (
                    kwargs.get("stream")
                    and self._is_custom_provider(backend)
                    and self._is_streaming_unsupported_error(exc)
                ):
                    self._tool_streaming_support[backend] = False
                is_server_error = isinstance(status, int) and 500 <= status < 600
                if not is_server_error and not self._is_timeout_error(exc):
                    if self._is_custom_provider(backend):
                        raise self._safe_custom_provider_error(exc) from None
                    raise
                last_error = exc
                last_backend = backend
                if len(attempted) == 1:
                    targets.extend(self.get_role_fallback_targets())
        if last_error is not None:
            if self._is_custom_provider(last_backend):
                raise self._safe_custom_provider_error(last_error) from None
            raise last_error
        raise RuntimeError("요청을 전송할 연결이 없습니다.")

    def _consume_tool_call_stream(self, stream, stream_callback, cancel_event=None):
        text_parts = []
        pending_text = ""
        suppress_text = False
        tool_call_parts = {}

        def emit_content(delta: str) -> None:
            nonlocal pending_text, suppress_text
            if not stream_callback or suppress_text:
                return
            pending_text += delta
            candidate = pending_text.lstrip()
            if not candidate:
                return
            if candidate.startswith("{") or candidate.startswith(chr(96) * 3):
                suppress_text = True
                pending_text = ""
                return
            if candidate in {chr(96), chr(96) * 2}:
                return
            stream_callback(pending_text)
            pending_text = ""

        for chunk in stream:
            if cancel_event is not None and cancel_event.is_set():
                break
            choices = self._response_field(chunk, "choices", []) or []
            if not choices:
                continue
            delta = self._response_field(choices[0], "delta", {}) or {}
            content = self._response_field(delta, "content", "") or ""
            if isinstance(content, str) and content:
                text_parts.append(content)
                emit_content(content)

            for tool_delta in self._response_field(delta, "tool_calls", []) or []:
                index = self._response_field(tool_delta, "index")
                if index is None:
                    index = 0
                else:
                    try:
                        index = int(index)
                    except (TypeError, ValueError):
                        index = len(tool_call_parts)
                partial = tool_call_parts.setdefault(
                    index,
                    {"id": "", "name": "", "argument_parts": [], "arguments": None},
                )
                call_id = self._response_field(tool_delta, "id")
                if call_id and not partial["id"]:
                    partial["id"] = str(call_id)
                function = self._response_field(tool_delta, "function", {}) or {}
                name = self._response_field(function, "name")
                if name:
                    partial["name"] += str(name)
                arguments = self._response_field(function, "arguments")
                if isinstance(arguments, (dict, list)):
                    partial["arguments"] = arguments
                elif arguments:
                    partial["argument_parts"].append(str(arguments))

        if (
            pending_text.strip()
            and not suppress_text
            and stream_callback
            and not (cancel_event is not None and cancel_event.is_set())
        ):
            stream_callback(pending_text)

        tool_calls = []
        for index in sorted(tool_call_parts):
            partial = tool_call_parts[index]
            arguments = partial["arguments"]
            if arguments is None:
                arguments = "".join(partial["argument_parts"])
            tool_calls.append({
                "id": partial["id"] or f"tool_call_{index}",
                "function": {
                    "name": partial["name"],
                    "arguments": arguments,
                },
            })
        return "".join(text_parts), tool_calls

    def _stream_tool_completion(
        self,
        client,
        provider: str,
        model: str,
        request_kwargs: dict,
        stream_callback,
        cancel_event=None,
    ):
        emitted_text = False
        emitted_parts: List[str] = []
        cancel_event = cancel_event or threading.Event()

        def track_emitted_text(text: str) -> None:
            nonlocal emitted_text
            emitted_text = True
            emitted_parts.append(text)
            stream_callback(text)

        next_client, next_provider, next_model = client, provider, model
        excluded_targets: set[tuple[str, str]] = set()
        timeout_errors = (TimeoutError, httpx.TimeoutException)
        try:
            from openai import APITimeoutError
        except ImportError:
            pass
        else:
            timeout_errors += (APITimeoutError,)
        while True:
            if cancel_event.is_set():
                return "".join(emitted_parts), []
            stream, active_target = self._create_completion_with_fallback(
                next_client,
                next_provider,
                next_model,
                _return_target=True,
                _excluded_targets=excluded_targets,
                **request_kwargs,
                stream=True,
            )
            _, active_provider, active_model = active_target
            self._set_active_stream(stream, cancel_event)
            try:
                text, tool_calls = self._consume_tool_call_stream(
                    stream,
                    track_emitted_text,
                    cancel_event,
                )
            except timeout_errors:
                if cancel_event.is_set():
                    return "".join(emitted_parts), []
                active_key = (str(active_provider or ""), str(active_model or ""))
                if emitted_text:
                    raise
                excluded_targets.add(active_key)
                next_target = next(
                    (
                        target
                        for target in self.get_role_fallback_targets()
                        if (str(target[1] or ""), str(target[2] or ""))
                        not in excluded_targets
                    ),
                    None,
                )
                if next_target is None:
                    raise
                next_client, next_provider, next_model = next_target
                continue
            finally:
                self._clear_active_stream(stream)

            if self._is_custom_provider(active_provider):
                self._tool_streaming_support[active_provider] = True
            return text, tool_calls

    def _build_cache_key(
        self,
        user_message: str,
        include_context: bool,
        *,
        provider: str | None = None,
        model: str | None = None,
        situation_signature: str = "",
    ) -> str:
        cache_message = user_message
        if situation_signature:
            cache_message = f"{user_message}\0{situation_signature}"
        return build_response_cache_key(
            cache_message,
            provider=provider or self.provider,
            model=model or self.model,
            system_prompt=self.system_prompt,
            personality=self.personality,
            scenario=self.scenario,
            history_instruction=self.rp_generator.history_instruction,
            include_context=include_context,
        )

    def _has_any_client(self) -> bool:
        return any((self.client, self.planner_client, self.execution_client))

    def _missing_model_response(self, provider: str, role: str = "default") -> str:
        label = self.provider_configs.get(provider, {}).get("label", provider)
        role_label = {
            "planner": "플래너",
            "execution": "실행",
        }.get(role, "기본")
        return f"{label} {role_label} 모델이 설정되지 않았습니다. 설정에서 선택한 모델을 지정해주세요."

    def get_role_target(self, role: str) -> tuple[Any, str, str]:
        """역할의 (client, provider, model)을 재구성 도중의 값이 섞이지 않게 한 번에 돌려준다."""
        with self._config_lock:
            return self._read_role_target(role)

    def _get_role_target(self, role: str) -> tuple[Any, str, str]:
        return self.get_role_target(role)

    def _read_role_target(self, role: str) -> tuple[Any, str, str]:
        if role == "planner":
            provider = self.planner_provider
            model = self.planner_model
            client = self.planner_client or (self.client if provider == self.provider else None)
        elif role == "execution":
            provider = self.execution_provider
            model = self.execution_model
            client = self.execution_client or (self.client if provider == self.provider else None)
        elif role == "memory_extractor":
            provider = self.memory_extractor_provider
            model = self.memory_extractor_model
            if provider == self.execution_provider:
                client = self.execution_client or (
                    self.client if provider == self.provider else None
                )
            else:
                client = self.memory_extractor_client or (
                    self.client if provider == self.provider else None
                )
            if not client:
                return self._get_role_target("execution")
        else:
            provider = self.provider
            model = self.model
            client = self.client

        if client:
            return client, provider, model

        logging.warning("[LLMRouter] %s 역할 클라이언트가 없어 기본 모델로 폴백합니다.", role)
        return self.client, self.provider, self.model

    def extract_memory_suggestions(self, user_message: str) -> str:
        """사용자 발화에서 기억 후보 JSON을 반환한다."""
        client, provider, model = self._get_role_target("memory_extractor")
        if not client or not model:
            raise RuntimeError("기억 추출 모델이 설정되지 않았습니다.")
        instructions = (
            "Extract only personal facts, preferences, and profile details explicitly stated "
            "in the user utterance. Return one JSON object with keys facts, preferences, bio. "
            "Every item must include evidence copied exactly from the utterance, no more than "
            "60 characters. Use facts [{key,value,kind,evidence,confidence}], where kind is "
            "stable, state, or plan. Use preferences [{category,value,evidence}] and bio "
            "[{field,value,evidence}], where field is name, location, interests, or memos. "
            "Use empty arrays when there is no supported item. Do not infer or add explanations."
        )
        if provider == "anthropic":
            response = client.messages.create(
                model=model,
                system=instructions,
                max_tokens=700,
                temperature=0,
                messages=[{"role": "user", "content": user_message}],
            )
            blocks = self._response_field(response, "content", []) or []
            return "".join(
                str(self._response_field(block, "text", ""))
                for block in blocks
                if self._response_field(block, "text", "")
            )

        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": instructions},
                {"role": "user", "content": user_message},
            ],
            temperature=0,
            max_tokens=700,
            extra_body=self._reasoning_extra_body(provider),
        )
        choices = self._response_field(response, "choices", []) or []
        if not choices:
            return ""
        message = self._response_field(choices[0], "message", {}) or {}
        content = self._response_field(message, "content", "")
        return content if isinstance(content, str) else ""

    def get_role_fallback_targets(self, preferred_role: str = "default") -> list[tuple[Any, str, str]]:
        role_order = {
            "planner": ("planner", "default", "execution"),
            "execution": ("execution", "default", "planner"),
            "default": ("default", "planner", "execution"),
        }.get(preferred_role, ("default", "planner", "execution"))
        targets: list[tuple[Any, str, str]] = []
        seen: set[tuple[str, str]] = set()
        for role in role_order:
            client, provider, model = self._get_role_target(role)
            key = (str(provider or ""), str(model or ""))
            if not client or not model or key in seen:
                continue
            seen.add(key)
            targets.append((client, provider, model))
        return targets

    def _reasoning_extra_body(self, provider: str) -> dict:
        """Groq의 reasoning 계열 모델(gpt-oss, qwen3 등)이 사고 과정(체인 오브
        소트)을 그대로 최종 응답 content에 섞어 보내는 것을 막는다.
        reasoning_format=hidden 이면 최종 답변만 content에 담겨 온다."""
        if provider == "groq":
            return {"reasoning_format": "hidden"}
        if provider == "nvidia_nim":
            # Nemotron 3 계열은 추론이 기본으로 켜져 있고 태그 없이 content에 섞인다(모델 카드 기준).
            return {"chat_template_kwargs": {"enable_thinking": False}}
        return {}

    def _resolve_route(self, user_message: str, model_override: str = "") -> tuple[Any, str, str]:
        with self._config_lock:
            provider = self.provider
            model = model_override or self.model
            client = self.client
        if model_override or not self.router_enabled:
            return client, provider, model
        try:
            from agent.llm_router import get_llm_router
            route = get_llm_router().route(user_message, {})
            return self._get_role_target(route.role)
        except Exception as e:
            logging.debug("[LLMRouter] 라우팅 생략: %s", e)
        return client, provider, model

    def chat(
        self,
        user_message,
        include_context=True,
        model_override="",
        system_override="",
        stream_callback=None,
        save_history=True,
        include_history=True,
        cancel_event=None,
    ):
        """단순 대화"""
        cancel_event = cancel_event or threading.Event()
        if not self._has_any_client():
            return "AI 기능이 비활성화되어 있습니다."

        provider = self.provider
        try:
            client, provider, model = self._resolve_route(user_message, model_override)
            if not client:
                return self._offline_response(user_message)
            if not model:
                logging.warning("[LLMProvider] 모델 미설정: provider=%s", provider)
                return self._missing_model_response(provider)
            situation_prompt = (
                self._build_situation_prompt() if include_history else ""
            )
            cache_key = self._build_cache_key(
                user_message,
                include_context,
                provider=provider,
                model=model,
                situation_signature=situation_prompt,
            )
            should_cache = include_history and self._should_cache(user_message)
            cached = self._response_cache.get(cache_key) if should_cache else None
            if cached:
                if save_history:
                    from memory.memory_manager import get_memory_manager
                    memory_manager = get_memory_manager()
                    self.add_to_history("user", user_message)
                    memory_manager.process_interaction(
                        user_message,
                        cached,
                        memory_extractor=self.extract_memory_suggestions,
                        extract_response_info=False,
                    )
                    cached = memory_manager.clean_response(cached)
                    self.add_to_history("assistant", self._clean_response(cached))
                if stream_callback:
                    self._emit_stream_text(cached, stream_callback)
                return cached
            system_content = (
                self._build_system(
                    include_context,
                    user_message=user_message,
                    situation_prompt=situation_prompt,
                )
                if not system_override
                else self._append_situation_prompt(system_override, situation_prompt)
            )
            messages = [{"role": "system", "content": system_content}]
            if include_history:
                messages.extend(self._history_for_context(tool_blocks=provider == "anthropic"))
            messages.append({"role": "user", "content": user_message})
            if save_history:
                self.add_to_history("user", user_message)

            if provider == "anthropic":
                resp = client.messages.create(
                    model=model, max_tokens=400, system=messages[0]["content"],
                    messages=messages[1:]
                )
                raw_msg = resp.content[0].text
                if stream_callback and raw_msg:
                    self._emit_stream_text(raw_msg, stream_callback)
            else:
                raw_msg = self._stream_or_chat_completion(
                    client,
                    model=model,
                    messages=messages,
                    temperature=0.7,
                    max_tokens=self._estimate_max_tokens(user_message),
                    stream_callback=stream_callback,
                    provider=provider,
                    cancel_event=cancel_event,
                )

            if cancel_event is not None and cancel_event.is_set():
                return raw_msg

            if save_history:
                from memory.memory_manager import get_memory_manager
                memory_manager = get_memory_manager()
                memory_manager.process_interaction(
                    user_message,
                    raw_msg,
                    memory_extractor=self.extract_memory_suggestions,
                )
                raw_msg = memory_manager.clean_response(raw_msg)
            msg = self._clean_response(raw_msg)
            if save_history:
                self.add_to_history("assistant", msg)
            if msg and should_cache:
                self._response_cache.set(cache_key, msg)
            return msg
        except Exception as e:
            if cancel_event is not None and cancel_event.is_set():
                return ""
            self._log_provider_exception(logging.error, "LLM chat 오류", provider, e)
            return self._error_response(e)

    def chat_with_tools(
        self,
        user_message,
        include_context=True,
        model_override="",
        stream_callback=None,
        cancel_event=None,
        record_interaction=True,
    ):
        """도구 포함 대화"""
        cancel_event = cancel_event or threading.Event()
        if not self._has_any_client():
            return "AI 기능 비활성화 상태입니다.", []

        provider = self.provider
        try:
            client, provider, model = self._resolve_route(user_message, model_override)
            if not client:
                return self._offline_response(user_message), []
            if not model:
                logging.warning("[LLMProvider] 도구 대화 모델 미설정: provider=%s", provider)
                return self._missing_model_response(provider), []
            self.add_to_history("user", user_message)
            skill_ctx = self._get_skill_context(user_message)
            situation_prompt = self._build_situation_prompt()
            messages = [{
                "role": "system",
                "content": self._build_system(
                    include_context,
                    user_message=user_message,
                    situation_prompt=situation_prompt,
                ),
            }]
            messages.extend(self._history_for_context(tool_blocks=provider == "anthropic"))
            
            request_ctx = self._analyze_request(user_message)
            if skill_ctx.get("force_web_search"):
                request_ctx["force_tool"] = True
                request_ctx["preferred_tool"] = "web_search"
                required_tool_names = set(skill_ctx.get("required_tool_names", []))
                required_tool_names.add("web_search")
                skill_ctx = {**skill_ctx, "required_tool_names": sorted(required_tool_names)}
            if skill_ctx.get("search_query_template"):
                request_ctx["search_query_hint"] = self._build_search_query_hint(
                    skill_ctx.get("search_query_template", ""),
                    user_message,
                )
            if skill_ctx.get("force_web_search") and provider == "gemini":
                messages[0]["content"] += "\n\n" + self._get_force_web_search_instruction(
                    request_ctx.get("search_query_hint", "") or skill_ctx.get("search_query_template", ""),
                )
            if skill_ctx.get("preferred_tool") and not request_ctx.get("preferred_tool"):
                request_ctx["preferred_tool"] = skill_ctx["preferred_tool"]
            tools, tool_choice = self._select_tools_for_request(
                request_ctx,
                required_tool_names=set(skill_ctx.get("required_tool_names", [])),
            )

            if provider == "anthropic":
                # Anthropic tool use is more complex, using simple fallback for now
                return self._anthropic_chat(
                    user_message,
                    include_context,
                    use_tools=True,
                    model_override=model,
                    client_override=client,
                    stream_callback=stream_callback,
                    tools=tools,
                    tool_choice=tool_choice,
                    record_interaction=record_interaction,
                )

            request_kwargs = {
                "messages": messages,
                "tools": tools,
                "tool_choice": tool_choice,
                "temperature": 0.1 if request_ctx["force_tool"] else 0.3,
                "max_tokens": self._estimate_max_tokens(user_message) + 200,
            }
            raw_msg = ""
            raw_tool_calls = []
            streamed_response = False
            streaming_enabled = bool(self._load_int_setting("llm_streaming_enabled", 1))
            if (
                stream_callback
                and streaming_enabled
                and self._tool_streaming_support.get(provider) is not False
            ):
                try:
                    raw_msg, raw_tool_calls = self._stream_tool_completion(
                        client,
                        provider,
                        model,
                        request_kwargs,
                        stream_callback,
                        cancel_event,
                    )
                    streamed_response = True
                except RuntimeError:
                    if (
                        not self._is_custom_provider(provider)
                        or self._tool_streaming_support.get(provider) is not False
                    ):
                        raise
                    logging.debug(
                        "[LLMProvider] 사용자 정의 제공자 스트리밍 미지원, 일반 요청으로 폴백"
                    )

            if cancel_event is not None and cancel_event.is_set():
                return raw_msg, []

            if not streamed_response:
                response = self._create_completion_with_fallback(
                    client,
                    provider,
                    model,
                    **request_kwargs,
                )
                choices = self._response_field(response, "choices", []) or []
                choice = choices[0]
                message = self._response_field(choice, "message", {}) or {}
                raw_msg = self._response_field(message, "content", "") or ""
                raw_tool_calls = self._response_field(message, "tool_calls", []) or []

            tool_calls = []
            if raw_tool_calls:
                from memory.memory_manager import get_memory_manager
                ctx_mgr = get_memory_manager().context_manager
                for tc in raw_tool_calls:
                    function = self._response_field(tc, "function", {}) or {}
                    name = self._response_field(function, "name", "") or ""
                    raw_arguments = self._response_field(function, "arguments", "")
                    try:
                        args = (
                            raw_arguments
                            if isinstance(raw_arguments, dict)
                            else json.loads(raw_arguments or "{}")
                        )
                        if not isinstance(args, dict):
                            args = {}
                    except (TypeError, json.JSONDecodeError) as exc:
                        logging.debug("[LLMProvider] tool arguments 파싱 실패, 빈 값 사용: %s", exc)
                        args = {}
                    args = self._normalize_tool_arguments(name, args, user_message)
                    if name == "web_search" and not str(args.get("query", "") or "").strip():
                        query_hint = str(request_ctx.get("search_query_hint", "") or "").strip()
                        args["query"] = query_hint or user_message
                    tool_calls.append({
                        "id": self._response_field(tc, "id") or "tool_call",
                        "name": name,
                        "arguments": args,
                    })
                    ctx_mgr.record_command(name, args)

            if not tool_calls and raw_msg:
                tool_calls = self._fallback_tool_calls_from_text(raw_msg, user_message, request_ctx)
                if tool_calls:
                    raw_msg = re.sub(r'```.*?```', '', raw_msg, flags=re.DOTALL)
                    raw_msg = re.sub(r'\{.*\}', '', raw_msg, flags=re.DOTALL)
            
            from memory.memory_manager import get_memory_manager
            memory_manager = get_memory_manager()
            if not tool_calls:
                if record_interaction:
                    memory_manager.process_interaction(
                        user_message,
                        raw_msg,
                        memory_extractor=self.extract_memory_suggestions,
                    )
                else:
                    memory_manager.extract_response_tags(raw_msg, user_message)
            if self._is_structured_response(raw_msg):
                msg = raw_msg.strip()
            else:
                msg = self._clean_response(memory_manager.clean_response(raw_msg))
            if stream_callback and msg and not tool_calls and not streamed_response:
                self._emit_stream_text(msg, stream_callback)
            if msg:
                self.add_to_history("assistant", msg)
            return msg, tool_calls
        except Exception as e:
            if cancel_event is not None and cancel_event.is_set():
                return "", []
            self._log_provider_exception(logging.error, "LLM chat_with_tools 오류", provider, e)
            return self._error_response(e), []

    def stream_chat(
        self,
        messages: list[dict],
        on_token: Callable[[str], None] | None,
        on_done: Callable[[str, list], None] | None,
        **kwargs,
    ) -> str:
        """제공자별 스트리밍 응답을 공통 콜백 인터페이스로 전달한다."""
        cancel_event = kwargs.get("cancel_event") or threading.Event()
        client, provider, model = self._resolve_route(
            str(messages[-1].get("content", "")) if messages else "",
            kwargs.get("model_override", ""),
        )
        if not client or not model:
            text = self._offline_response("")
            if on_done:
                on_done(text, [])
            return text
        full_text = ""
        tool_calls: list = []
        try:
            messages = self._with_situation_prompt(messages)
            if provider == "anthropic":
                system = ""
                anthropic_messages = messages
                if messages and messages[0].get("role") == "system":
                    system = str(messages[0].get("content", ""))
                    anthropic_messages = messages[1:]
                with client.messages.stream(
                    model=model,
                    max_tokens=int(kwargs.get("max_tokens", 1000)),
                    system=system,
                    messages=anthropic_messages,
                ) as stream:
                    self._set_active_stream(stream, cancel_event)
                    try:
                        for text in stream.text_stream:
                            if cancel_event.is_set():
                                break
                            if text:
                                full_text += text
                                if on_token:
                                    on_token(text)
                    finally:
                        self._clear_active_stream(stream)
            else:
                stream = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=float(kwargs.get("temperature", 0.7)),
                    max_tokens=int(kwargs.get("max_tokens", 1000)),
                    stream=True,
                    extra_body=self._reasoning_extra_body(provider),
                )
                self._set_active_stream(stream, cancel_event)
                try:
                    for chunk in stream:
                        if cancel_event.is_set():
                            break
                        choice = chunk.choices[0]
                        delta = getattr(choice, "delta", None)
                        text = getattr(delta, "content", "") or ""
                        if text:
                            full_text += text
                            if on_token:
                                on_token(text)
                        for tc in getattr(delta, "tool_calls", None) or []:
                            tool_calls.append(tc)
                finally:
                    self._clear_active_stream(stream)
        except Exception as exc:
            self._log_provider_exception(logging.debug, "[LLMProvider] stream_chat 폴백", provider, exc)
            if not cancel_event.is_set():
                try:
                    full_text = self._stream_or_chat_completion(
                        client,
                        model=model,
                        messages=messages,
                        temperature=float(kwargs.get("temperature", 0.7)),
                        max_tokens=int(kwargs.get("max_tokens", 1000)),
                        stream_callback=on_token,
                        provider=provider,
                        cancel_event=cancel_event,
                    )
                except Exception as fallback_error:
                    if not self._is_custom_provider(provider):
                        raise
                    self._log_provider_exception(
                        logging.error,
                        "[LLMProvider] stream_chat 실패",
                        provider,
                        fallback_error,
                    )
                    full_text = self._error_response(fallback_error)
        if on_done:
            on_done(full_text, tool_calls)
        return full_text

    def analyze_image(self, image_path_or_b64: str, prompt: str = "") -> str:
        """이미지 파일 또는 base64 문자열을 현재 제공자 비전 모델로 분석한다."""
        provider = self.provider
        try:
            from core.config_manager import ConfigManager
            if not bool(ConfigManager.get("vision_enabled", True)):
                return "이미지 분석 기능이 설정에서 비활성화되어 있습니다."
        except Exception:
            pass
        if not self._has_any_client():
            return "AI 기능이 비활성화되어 있습니다."
        prompt = prompt or "이미지 내용을 설명해 주세요."
        try:
            client, provider, model = self._resolve_route(prompt)
            if not client or not model:
                return self._offline_response(prompt)
            data, media_type = self._load_image_base64(image_path_or_b64)
            if provider == "anthropic":
                resp = client.messages.create(
                    model=model,
                    max_tokens=800,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}},
                            {"type": "text", "text": prompt},
                        ],
                    }],
                )
                return self._clean_response(" ".join([b.text for b in resp.content if getattr(b, "type", "") == "text"]))
            if provider in {"openai", "groq", "mistral", "gemini", "openrouter", "nvidia_nim", "ollama"}:
                image_url = f"data:{media_type};base64,{data}"
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": image_url}},
                        ],
                    }],
                    max_tokens=800,
                    extra_body=self._reasoning_extra_body(provider),
                )
                return self._clean_response(resp.choices[0].message.content or "")
        except Exception as exc:
            self._log_provider_exception(logging.warning, "[LLMProvider] 비전 분석 실패, OCR 폴백 시도", provider, exc)
        return self._ocr_image_fallback(image_path_or_b64, prompt)

    def _load_image_base64(self, image_path_or_b64: str) -> tuple[str, str]:
        raw = str(image_path_or_b64 or "").strip()
        media_type = "image/png"
        if os.path.exists(raw):
            guessed = mimetypes.guess_type(raw)[0]
            if guessed and guessed.startswith("image/"):
                media_type = guessed
            with open(raw, "rb") as f:
                return base64.b64encode(f.read()).decode("ascii"), media_type
        if raw.startswith("data:"):
            partitioned = raw.partition(",")
            header, data = partitioned[0], partitioned[2]
            media = header[5:].split(";")[0]
            return data, media or media_type
        return raw, media_type

    def _ocr_image_fallback(self, image_path_or_b64: str, prompt: str) -> str:
        try:
            from agent.ocr_helper import ocr_image_file
            if os.path.exists(str(image_path_or_b64)):
                text = ocr_image_file(str(image_path_or_b64))
                return f"{prompt}\n\n[OCR 결과]\n{text}".strip()
        except Exception as exc:
            logging.debug("[LLMProvider] OCR 폴백 실패: %s", exc)
        return "현재 제공자에서 이미지 분석을 사용할 수 없습니다."

    def feed_tool_result(
        self,
        original_msg: str,
        tool_calls: list,
        results: list,
        model_override="",
        stream_callback=None,
        cancel_event=None,
    ) -> str:
        """도구 결과 피드백"""
        if cancel_event is not None and cancel_event.is_set():
            return ""
        model = model_override or self.model
        provider = self.provider
        if not self._has_any_client():
            return "도구 결과 처리 실패: AI 기능이 비활성화되어 있습니다."
        try:
            client, provider, model = self._resolve_route(original_msg, model_override)
            if not client:
                return "도구 결과 처리 실패: AI 클라이언트가 없습니다."
            if not model:
                logging.warning("[LLMProvider] tool_result 모델 미설정: provider=%s", provider)
                return self._missing_model_response(provider)
            if not tool_calls or len(tool_calls) != len(results):
                raise ValueError("Every tool call must have exactly one result")
            if provider == "anthropic":
                return self._anthropic_feed_tool_result(
                    original_msg,
                    tool_calls,
                    results,
                    model_override=model,
                    client_override=client,
                    stream_callback=stream_callback,
                )

            assistant_tool_calls = []
            for tc in tool_calls:
                assistant_tool_calls.append({
                    "id": tc.get("id", tc.get("name", "tool_0")),
                    "type": "function",
                    "function": {"name": tc.get("name", ""), "arguments": json.dumps(tc.get("arguments", {}), ensure_ascii=False)},
                })

            tool_result_messages = []
            for tc, result in zip(tool_calls, results):
                tool_result_messages.append({
                    "role": "tool", "tool_call_id": tc.get("id", tc.get("name", "tool_0")), "content": str(result)
                })

            messages = [{
                "role": "system",
                "content": "\n\n".join(
                    part for part in (
                        self._build_system(user_message=original_msg),
                        self._get_source_attribution_instruction(),
                    )
                    if part
                ),
            }]
            messages.extend(self._history_for_context(tool_blocks=provider == "anthropic"))
            messages.append({"role": "assistant", "content": None, "tool_calls": assistant_tool_calls})
            messages.extend(tool_result_messages)

            response = client.chat.completions.create(
                model=model, messages=messages, temperature=0.7,
                max_tokens=self._estimate_max_tokens(original_msg),
                extra_body=self._reasoning_extra_body(provider),
            )
            if cancel_event is not None and cancel_event.is_set():
                return ""
            msg = self._clean_response(response.choices[0].message.content or "")
            if stream_callback and msg:
                self._emit_stream_text(msg, stream_callback)
            if msg:
                self.add_to_history("assistant", msg)
            return msg
        except Exception as e:
            if cancel_event is not None and cancel_event.is_set():
                return ""
            self._log_provider_exception(logging.error, "feed_tool_result 오류", provider, e)
            return self._error_response(e) if self._is_custom_provider(provider) else f"도구 결과 처리 실패: {e}"

    @staticmethod
    def _tool_result_text(result) -> str:
        return _("도구가 완료됐지만 반환값이 없습니다.") if result is None else str(result)

    def record_tool_result(self, tool_calls: list, results: list, response: str) -> None:
        """호출 없이 도구 결과와 로컬 응답을 대화 이력에 기록한다."""
        if not tool_calls or len(tool_calls) != len(results):
            raise ValueError("Every tool call must have exactly one result")

        history = self._history_snapshot()
        previous = history[-1] if history else {}
        content = previous.get("content", [])
        blocks = (
            [block for block in content if block.get("type") == "tool_use"]
            if isinstance(content, list)
            else []
        )
        if blocks:
            expected = [
                {"id": call["id"], "name": call["name"], "input": call.get("arguments", {})}
                for call in tool_calls
            ]
            actual = [{key: block[key] for key in ("id", "name", "input")} for block in blocks]
            if previous.get("role") != "assistant" or actual != expected:
                raise ValueError("Tool results do not match the preceding assistant tool-use turn")
            result_content = [
                {"type": "tool_result", "tool_use_id": call["id"], "content": self._tool_result_text(result)}
                for call, result in zip(tool_calls, results)
            ]
            self.add_to_history("user", result_content)
        if response:
            self.add_to_history("assistant", response)

    def _anthropic_chat(
        self,
        user_message,
        include_context,
        use_tools,
        model_override="",
        client_override=None,
        stream_callback=None,
        tools=None,
        tool_choice="auto",
        record_interaction=True,
    ):
        model = model_override or self.model
        client = client_override or self.client
        try:
            system = self._build_system(include_context, user_message=user_message)
            messages = self._history_for_context()
            kwargs = {
                "model": model,
                "max_tokens": self._estimate_max_tokens(user_message) + 200,
                "system": system,
                "messages": messages,
            }
            if use_tools:
                if tools is None:
                    request_ctx = self._analyze_request(user_message)
                    tools, tool_choice = self._select_tools_for_request(request_ctx)
                kwargs["tools"] = [{
                    "name": tool["function"]["name"],
                    "description": tool["function"]["description"],
                    "input_schema": tool["function"]["parameters"],
                } for tool in tools]
                if tool_choice == "required":
                    kwargs["tool_choice"] = {"type": "any"}
                elif isinstance(tool_choice, dict):
                    name = tool_choice.get("function", {}).get("name", "")
                    if name:
                        kwargs["tool_choice"] = {"type": "tool", "name": name}
                else:
                    kwargs["tool_choice"] = {"type": "auto"}
            
            resp = client.messages.create(**kwargs)
            tool_calls, text_parts = [], []
            for b in resp.content:
                if b.type == "tool_use":
                    tool_calls.append({"id": b.id, "name": b.name, "arguments": b.input})
                elif b.type == "text":
                    text_parts.append(b.text)
            
            raw_msg = " ".join(text_parts)
            msg = self._clean_response(raw_msg)
            if use_tools and not tool_calls:
                from memory.memory_manager import get_memory_manager
                memory_manager = get_memory_manager()
                if record_interaction:
                    memory_manager.process_interaction(
                        user_message,
                        raw_msg,
                        memory_extractor=self.extract_memory_suggestions,
                    )
                else:
                    memory_manager.extract_response_tags(raw_msg, user_message)
            if stream_callback and msg and not tool_calls:
                self._emit_stream_text(msg, stream_callback)
            if tool_calls:
                self.add_to_history("assistant", [
                    block.model_dump(exclude_none=True) if hasattr(block, "model_dump") else dict(vars(block))
                    for block in resp.content
                ])
            elif msg:
                self.add_to_history("assistant", msg)
            return msg, tool_calls
        except Exception as e:
            logging.error("Anthropic API 오류: %s", e)
            return self._error_response(e), []

    def _anthropic_feed_tool_result(self, original_msg, tool_calls, results, model_override="", client_override=None, stream_callback=None):
        model = model_override or self.model
        client = client_override or self.client
        try:
            if not tool_calls or len(tool_calls) != len(results):
                raise ValueError("Every tool call must have exactly one result")
            results_content = [{"type": "tool_result", "tool_use_id": tc["id"], "content": self._tool_result_text(result)} for tc, result in zip(tool_calls, results)]
            with self._history_lock:
                history = self._history_snapshot()
                result_message = {"role": "user", "content": results_content}
                already_recorded = bool(history and history[-1] == result_message)
                previous = history[-2] if already_recorded and len(history) > 1 else (history[-1] if history else {})
                content = previous.get("content", [])
                blocks = [b for b in content if b.get("type") == "tool_use"] if isinstance(content, list) else []
                expected = [{"id": tc["id"], "name": tc["name"], "input": tc.get("arguments", {})} for tc in tool_calls]
                actual = [{key: b[key] for key in ("id", "name", "input")} for b in blocks]
                if previous.get("role") != "assistant" or actual != expected:
                    raise ValueError("Tool results do not match the preceding assistant tool-use turn")
                if not already_recorded:
                    self.add_to_history("user", results_content)
                messages = self._history_for_context()
            resp = client.messages.create(
                model=model,
                max_tokens=500,
                system=self._build_system(user_message=original_msg),
                messages=messages,
                tools=[{
                    "name": tool["function"]["name"],
                    "description": tool["function"]["description"],
                    "input_schema": tool["function"]["parameters"],
                } for tool in self.get_available_tools()],
                tool_choice={"type": "none"},
            )
            msg = self._clean_response(" ".join([b.text for b in resp.content if b.type == "text"]))
            if stream_callback and msg:
                self._emit_stream_text(msg, stream_callback)
            if msg:
                self.add_to_history("assistant", msg)
            return msg
        except Exception as e:
            logging.error("Anthropic feed 오류: %s", e)
            return f"도구 결과 처리 실패: {e}"

    def _stream_or_chat_completion(
        self,
        client,
        *,
        model: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        stream_callback=None,
        provider: str = "",
        cancel_event=None,
    ) -> str:
        cancel_event = cancel_event or threading.Event()
        if cancel_event.is_set():
            return ""
        streaming_enabled = bool(self._load_int_setting("llm_streaming_enabled", 1))
        if not stream_callback or not streaming_enabled:
            resp = self._create_completion_with_fallback(
                client, provider, model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return resp.choices[0].message.content or ""
        parts: List[str] = []
        stream = None
        try:
            stream = self._create_completion_with_fallback(
                client, provider, model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            self._set_active_stream(stream, cancel_event)
            for chunk in stream:
                if cancel_event.is_set():
                    break
                try:
                    delta = chunk.choices[0].delta.content or ""
                except Exception as exc:
                    logging.debug("[LLMProvider] 스트리밍 delta 추출 실패: %s", exc)
                    delta = ""
                if not delta:
                    continue
                parts.append(delta)
                stream_callback(delta)
            text = "".join(parts)
            if cancel_event.is_set() or text:
                return text
        except Exception as exc:
            if cancel_event.is_set():
                return "".join(parts)
            self._log_provider_exception(logging.debug, "[LLMProvider] 스트리밍 폴백", provider, exc)
        finally:
            if stream is not None:
                self._clear_active_stream(stream)
        if cancel_event.is_set():
            return "".join(parts)
        resp = self._create_completion_with_fallback(
            client, provider, model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        text = resp.choices[0].message.content or ""
        self._emit_stream_text(text, stream_callback)
        return text

    def _emit_stream_text(self, text: str, stream_callback, chunk_size: int = 24) -> None:
        if not stream_callback or not text:
            return
        for start in range(0, len(text), chunk_size):
            chunk = text[start:start + chunk_size]
            if chunk:
                stream_callback(chunk)

    def _analyze_request(self, user_message: str) -> dict:
        ctx = analyze_tool_request(user_message)
        ctx.setdefault("intent", "conversation")
        return ctx

    def _select_tools_for_request(self, ctx: dict, required_tool_names: set[str] | None = None):
        required_tool_names = set(required_tool_names or set())
        tools = self.get_available_tools()
        intent = str(ctx.get("intent", "conversation") or "conversation").strip().lower()
        if ctx.get("preferred_tool"):
            preferred_name = ctx["preferred_tool"]
            filtered = [
                tool
                for tool in tools
                if tool["function"]["name"] == preferred_name
                and (
                    preferred_name in _CORE_TOOL_NAMES
                    or self._plugin_tool_is_allowed_for_intent(preferred_name, intent)
                )
            ]
            if required_tool_names:
                filtered.extend(
                    tool for tool in tools
                    if tool["function"]["name"] in required_tool_names
                    and tool["function"]["name"] != preferred_name
                    and (
                        tool["function"]["name"] in _CORE_TOOL_NAMES
                        or self._plugin_tool_is_allowed_for_intent(
                            tool["function"]["name"], intent
                        )
                    )
                )
            if filtered:
                if any(tool["function"]["name"] == preferred_name for tool in filtered):
                    return filtered, {
                        "type": "function",
                        "function": {"name": preferred_name},
                    }

        allowed_names = _TOOL_NAMES_BY_INTENT.get(intent)
        filtered = []
        for tool in tools:
            name = tool["function"]["name"]
            if name in _CORE_TOOL_NAMES:
                if allowed_names is None:
                    if not required_tool_names or name in required_tool_names:
                        filtered.append(tool)
                elif name in allowed_names or name in required_tool_names:
                    filtered.append(tool)
            elif name in required_tool_names or self._plugin_tool_is_allowed_for_intent(
                name, intent
            ):
                filtered.append(tool)
        if filtered:
            tools = filtered
        return tools, "required" if ctx.get("force_tool") else "auto"

    def _plugin_tool_is_allowed_for_intent(self, tool_name: str, intent: str) -> bool:
        intents = self._plugin_tool_intents.get(tool_name)
        if intents is None:
            return intent != "conversation"
        return intent in intents

    def _normalize_tool_arguments(self, name, args, user_msg):
        n = dict(args or {})
        if name == "run_agent_task":
            detailed_request = (n.get("explanation") or user_msg or "").strip()
            current_goal = (n.get("goal") or "").strip()
            resolved_goal = resolve_agent_task_goal(current_goal, detailed_request)
            if resolved_goal:
                n["goal"] = resolved_goal
        return n

    def _fallback_tool_calls_from_text(self, raw, msg, ctx):
        if ctx.get("preferred_tool") == "web_search":
            query = str(ctx.get("search_query_hint", "") or "").strip() or msg
            return [{"id": "fb_1", "name": "web_search", "arguments": {"query": query, "max_results": 5}}]
        if "execute_python_code" in raw or ctx.get("force_tool"):
            return [{"id": "fb_1", "name": "run_agent_task", "arguments": {"goal": msg, "explanation": "진행할게요."}}]
        return []

    def _get_skill_context(self, user_message: str) -> dict:
        if not str(user_message or "").strip():
            return {
                "skills": [],
                "prompt": "",
                "required_tool_names": [],
                "preferred_tool": "",
                "force_web_search": False,
                "escalate_to_agent": False,
                "search_query_template": "",
            }
        try:
            from agent.skill_manager import get_skill_manager

            return get_skill_manager().build_match_context(user_message)
        except Exception as exc:
            logging.debug("[LLMProvider] 스킬 컨텍스트 주입 생략: %s", exc)
            return {
                "skills": [],
                "prompt": "",
                "required_tool_names": [],
                "preferred_tool": "",
                "force_web_search": False,
                "escalate_to_agent": False,
                "search_query_template": "",
            }

    def _get_source_attribution_instruction(self) -> str:
        from i18n.translator import _

        return _(
            "[실시간 데이터 응답 지침]\n"
            "- 검색 결과에 없는 정보는 절대 지어내지 마세요.\n"
            "- 정보가 없으면 '검색 결과에서 확인하지 못했습니다'라고 솔직하게 말하세요.\n"
            "- 데이터 출처(웹 검색, 공식 API 등)를 짧게 언급하세요."
        )

    def _get_force_web_search_instruction(self, query_hint: str) -> str:
        from i18n.translator import _

        guidance = _(
            "이 요청은 최신 실시간 데이터가 필요합니다. 반드시 web_search 도구를 먼저 호출하세요."
        )
        query_hint = str(query_hint or "").strip()
        if not query_hint:
            return guidance
        return guidance + "\n" + _("권장 검색어: {query}").format(query=query_hint)

    def _build_search_query_hint(self, template: str, user_message: str) -> str:
        template = str(template or "").strip()
        if not template:
            return ""
        import datetime

        today = datetime.date.today()
        date_hint = self._extract_date_hint(user_message, today) or today.isoformat()
        return template.replace("{date}", date_hint)

    def _extract_date_hint(self, user_message: str, today) -> str:
        text = str(user_message or "").strip()
        iso_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
        if iso_match:
            return iso_match.group(1)
        month_day_match = re.search(r"(\d{1,2})\s*[월月]\s*(\d{1,2})\s*[일日]", text)
        if month_day_match:
            month = int(month_day_match.group(1))
            day = int(month_day_match.group(2))
            try:
                return today.replace(month=month, day=day).isoformat()
            except ValueError:
                return ""
        en_match = re.search(
            r"\b(january|february|march|april|may|june|july|august|september|october|november|december|"
            r"jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\s+(\d{1,2})\b",
            text,
            re.IGNORECASE,
        )
        if en_match:
            month = _EN_MONTHS[en_match.group(1).lower()]
            day = int(en_match.group(2))
            try:
                return today.replace(month=month, day=day).isoformat()
            except ValueError:
                return ""
        return ""

    def _build_situation_prompt(self) -> str:
        now = datetime.now()
        metrics = {
            "last_interaction_elapsed_minutes": None,
            "today_interaction_count": 0,
            "continuous_use_minutes": 0,
            "local_time": now.strftime("%H:%M"),
            "recent_praise_count": 0,
        }
        try:
            from memory.user_context import get_context_manager
            metrics = get_context_manager().get_situation_metrics()
        except (AttributeError, ImportError, OSError, TypeError, ValueError) as exc:
            logging.debug("[LLMProvider] 상황 메타데이터 조회 실패: %s", exc)

        try:
            from core.window_inspector import get_foreground_fullscreen
            fullscreen = get_foreground_fullscreen()
        except (
            AttributeError,
            ImportError,
            OSError,
            OverflowError,
            TypeError,
            ValueError,
        ) as exc:
            logging.debug("[LLMProvider] 전체 화면 상태 조회 실패: %s", exc)
            fullscreen = None

        elapsed_minutes = metrics.get("last_interaction_elapsed_minutes")
        elapsed_value = (
            _("없음")
            if elapsed_minutes is None
            else self._format_situation_duration(elapsed_minutes)
        )
        template = _("[상황] 전{elapsed} · 오늘{today}회 · 연속{continuous} · 시각{time} · 칭찬24h {praise}회")
        prompt = template.format(
            elapsed=elapsed_value,
            today=self._format_situation_count(
                metrics.get("today_interaction_count", 0)
            ),
            continuous=self._format_situation_duration(
                metrics.get("continuous_use_minutes", 0)
            ),
            time=str(metrics.get("local_time", now.strftime("%H:%M")))[:5],
            praise=self._format_situation_count(
                metrics.get("recent_praise_count", 0)
            ),
        )
        if fullscreen is True:
            prompt += _(" · 전체 화면: {fullscreen}").format(fullscreen=_("예"))
        elif fullscreen is False:
            prompt += _(" · 전체 화면: {fullscreen}").format(fullscreen=_("아니요"))

        mood_label = _("평온")
        mood_state = get_mood_state()
        if mood_state is not None:
            try:
                mood_valence, _mood_arousal = mood_state.values()
            except (ArithmeticError, RuntimeError, TypeError, ValueError) as exc:
                logging.debug("[LLMProvider] 기분 상태 조회 실패: %s", exc)
            else:
                if mood_valence >= 0.2:
                    mood_label = _("좋음")
                elif mood_valence <= -0.2:
                    mood_label = _("가라앉음")
        prompt += _(" · 기분 {mood}").format(mood=mood_label)
        return prompt

    @staticmethod
    def _format_situation_count(value: Any) -> str:
        try:
            count = max(0, int(value))
        except (OverflowError, TypeError, ValueError):
            return "0"
        return "999+" if count > 999 else str(count)

    @staticmethod
    def _format_situation_duration(value: Any) -> str:
        try:
            minutes = max(0, int(value))
        except (OverflowError, TypeError, ValueError):
            minutes = 0
        if minutes >= 60:
            hours = minutes // 60
            return _(
                "{hours}시간", hours="999+" if hours > 999 else hours
            )
        return _("{minutes}분", minutes=min(minutes, 999))

    @staticmethod
    def _append_situation_prompt(system_prompt: str, situation_prompt: str) -> str:
        prompt = str(system_prompt or "").rstrip()
        situation = str(situation_prompt or "").strip()
        if not situation or situation in prompt or any(
            line.startswith(("[상황] ", "[Situation] ", "[状況] "))
            for line in prompt.splitlines()
        ):
            return prompt
        return f"{prompt}\n\n{situation}" if prompt else situation

    def _with_situation_prompt(self, messages: list[dict]) -> list[dict]:
        situation_prompt = self._build_situation_prompt()
        prepared = [dict(message) for message in messages]
        for index, message in enumerate(prepared):
            if message.get("role") == "system":
                prepared[index]["content"] = self._append_situation_prompt(
                    str(message.get("content", "")), situation_prompt
                )
                break
        else:
            prepared.insert(0, {"role": "system", "content": situation_prompt})
        return prepared

    def _build_system(self, include_context=False, user_message="", situation_prompt=None):
        try:
            from i18n.translator import get_language
            lang = get_language()
        except Exception as exc:
            logging.debug("[LLMProvider] 언어 설정 조회 실패, ko 기본값 사용: %s", exc)
            lang = "ko"
        _BASE_PROMPT = {
            "ko": "당신은 AI 어시스턴트 아리입니다.",
            "en": "You are Ari, an AI assistant.",
            "ja": "あなたはAIアシスタントのAriです。",
        }
        _LANG_INSTRUCTION = {
            "ko": "항상 한국어로 응답하세요.",
            "en": "Always respond in English.",
            "ja": "常に日本語で応答してください。",
        }
        parts: List[str] = []
        base_prompt = self.system_prompt or _BASE_PROMPT.get(lang, _BASE_PROMPT["ko"])
        parts.append(self.rp_generator.build_system_prompt(base_prompt))
        parts.append(_get_tool_instruction())
        parts.append(_LANG_INSTRUCTION.get(lang, _LANG_INSTRUCTION["ko"]))
        time_prompt = ""
        if include_context:
            try:
                from memory.user_profile_engine import get_user_profile_engine
                profile_prompt = get_user_profile_engine().get_prompt_injection()
                if profile_prompt:
                    parts.append(profile_prompt)
            except Exception as e:
                logging.debug("[LLM] 사용자 프로파일 주입 실패: %s", e)
            try:
                from memory.memory_manager import get_memory_manager
                memory_manager = get_memory_manager()
                facts_prompt = memory_manager.get_top_facts_prompt(
                    n=3,
                    query=user_message,
                )
                if facts_prompt:
                    parts.append(facts_prompt)
            except Exception as e:
                logging.debug("[LLM] 사실 주입 실패: %s", e)
            try:
                from memory.memory_manager import get_memory_manager
                memory_manager = get_memory_manager()
                context_prompt = memory_manager.get_full_context_prompt(
                    include_profile=False,
                    include_facts=False,
                    include_time=False,
                )
                if context_prompt:
                    parts.append(f"[대화 컨텍스트]\n{context_prompt}")
                time_prompt = memory_manager.get_current_time_prompt()
            except Exception as e:
                logging.debug("[LLM] 메모리 컨텍스트 주입 실패: %s", e)
        skill_ctx = self._get_skill_context(user_message)
        if skill_ctx.get("prompt"):
            parts.append(skill_ctx["prompt"])
        situation = (
            situation_prompt
            if situation_prompt is not None
            else self._build_situation_prompt()
        )
        if situation:
            parts.append(situation)
        if include_context:
            activity_context = get_activity_context()
            if activity_context:
                parts.append(activity_context)
        if include_context and time_prompt:
            parts.append(time_prompt)
        return "\n\n".join(part for part in parts if part)

    def _clean_response(self, text):
        return clean_tool_artifact_text(text, remove_memory_tags=True)

    def _filter_korean(self, text):
        return self._clean_response(text)


# ── 싱글톤 팩토리 ──────────────────────────────────────────────────────────────

_instance: LLMProvider | None = None
_instance_lock = threading.Lock()

def _build_llm_provider() -> LLMProvider:
    try:
        from core.config_manager import ConfigManager
        s = dict(ConfigManager.load_settings())
    except Exception as exc:
        logging.debug("[LLMProvider] 설정 로드 실패, 기본 LLM 설정 사용: %s", exc)
        s = {}
    from core.custom_llm_providers import custom_api_key_name, normalize_custom_provider_settings

    normalize_custom_provider_settings(s)
    provider_configs = get_provider_configs(s)

    def select_provider(setting_key, model_key, fallback):
        selected = s.get(setting_key, "") or fallback
        if selected not in provider_configs:
            # 역할 제공자는 기본 제공자로, 기본 제공자는 groq로 돌린다.
            selected = fallback if fallback in provider_configs else "groq"
            s[setting_key] = selected
            s[model_key] = ""
        return selected

    provider = select_provider("llm_provider", "llm_model", "groq")
    planner_provider = select_provider("llm_planner_provider", "llm_planner_model", provider)
    execution_provider = select_provider("llm_execution_provider", "llm_execution_model", provider)
    memory_extractor_provider = select_provider(
        "llm_memory_extractor_provider",
        "llm_memory_extractor_model",
        execution_provider,
    )

    def provider_key(selected):
        if selected == "ollama":
            return "ollama"
        key_name = _KEY_MAP.get(selected)
        if key_name is None and selected in provider_configs and selected not in _PROVIDER_CONFIG:
            key_name = custom_api_key_name(selected)
        return s.get(key_name, "") if key_name else ""

    api_key = provider_key(provider)
    planner_api_key = provider_key(planner_provider) if planner_provider != provider else ""
    execution_api_key = provider_key(execution_provider) if execution_provider != provider else ""
    memory_extractor_api_key = (
        provider_key(memory_extractor_provider)
        if memory_extractor_provider not in {provider, execution_provider}
        else ""
    )
    model = s.get("llm_model", "") or ""
    if not model and provider not in _PROVIDER_CONFIG:
        model = provider_configs[provider].get("default_model", "") or ""

    def role_model(setting_key, selected):
        value = s.get(setting_key, "") or ""
        if value or selected == provider:
            return value or model
        if selected not in _PROVIDER_CONFIG:
            return provider_configs[selected].get("default_model", "") or ""
        return ""

    planner_model = role_model("llm_planner_model", planner_provider)
    execution_model = role_model("llm_execution_model", execution_provider)
    memory_extractor_model = s.get("llm_memory_extractor_model", "") or ""
    if memory_extractor_provider != execution_provider and not memory_extractor_model:
        memory_extractor_model = (
            model
            if memory_extractor_provider == provider
            else provider_configs[memory_extractor_provider].get("default_model", "")
        )

    return LLMProvider(
        provider=provider, api_key=api_key,
        model=model,
        planner_model=planner_model,
        execution_model=execution_model,
        planner_provider=planner_provider if planner_provider != provider else "",
        execution_provider=execution_provider if execution_provider != provider else "",
        planner_api_key=planner_api_key,
        execution_api_key=execution_api_key,
        memory_extractor_provider=memory_extractor_provider,
        memory_extractor_model=memory_extractor_model,
        memory_extractor_api_key=memory_extractor_api_key,
        system_prompt=s.get("system_prompt", ""),
        personality=s.get("personality", ""),
        scenario=s.get("scenario", ""),
        history_instruction=s.get("history_instruction", ""),
        personality_examples_en=s.get("personality_examples_en", ""),
        personality_examples_ja=s.get("personality_examples_ja", ""),
        response_verbosity=s.get("response_verbosity", "concise"),
        router_enabled=s.get("llm_router_enabled", DEFAULT_SETTINGS["llm_router_enabled"]),
        provider_configs=provider_configs,
    )


def get_llm_provider() -> LLMProvider:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = _build_llm_provider()
    return _instance


# 교체된 클라이언트를 닫기 전에 진행 중인 요청이 끝나기를 기다리는 시간.
# 옛 클라이언트는 교체 전에 시작한 요청만 쓴다. 그 요청의 재시도·대체 모델 전환·이어받기가
# 모두 끝날 만큼 길게 잡는다(요청 제한 시간 90초 기준으로 최악의 경우에도 넉넉하다).
# ponytail: 고정 대기 시간, 요청별 사용 추적이 필요해지면 그때 바꾼다.
_OBSOLETE_CLIENT_CLOSE_DELAY_SECONDS = 1800.0


def reload_llm_provider() -> None:
    if _instance is None:
        return
    with _instance_lock:
        instance = _instance
        if instance is None:
            return
        replacement = _build_llm_provider()

        preserved = {
            "conversation_history", "_history_lock", "_config_lock",
            "_active_stream_lock", "_active_stream", "_active_stream_cancel_event",
            "_plugin_tools", "_plugin_tool_intents",
        }
        clients = ("client", "planner_client", "execution_client", "memory_extractor_client")
        old_clients = [getattr(instance, name, None) for name in clients]
        config = (
            "provider_configs", "provider", "api_key", "model", "planner_provider",
            "planner_model", "execution_provider", "execution_model",
            "memory_extractor_provider", "memory_extractor_model",
        )
        # 진행 중인 호출이 기존 기록과 스트림 상태를 계속 사용하도록 보존한다.
        with instance._config_lock:
            for name in config:
                setattr(instance, name, getattr(replacement, name))
            for name, value in replacement.__dict__.items():
                if name not in preserved and name not in clients and name not in config:
                    setattr(instance, name, value)
            for name in clients:
                setattr(instance, name, getattr(replacement, name))

        new_client_ids = {id(getattr(instance, name, None)) for name in clients}
        obsolete = []
        for client in old_clients:
            if client is None or id(client) in new_client_ids:
                continue
            if all(client is not seen for seen in obsolete):
                obsolete.append(client)
        if obsolete:
            # 다른 스레드의 진행 중인 요청이 옛 클라이언트를 쓰고 있을 수 있어 바로 닫지 않는다.
            timer = threading.Timer(
                _OBSOLETE_CLIENT_CLOSE_DELAY_SECONDS,
                _close_obsolete_clients,
                args=(instance, obsolete),
            )
            timer.daemon = True
            timer.start()


def _close_obsolete_clients(instance, obsolete_clients) -> None:
    active_stream_lock = getattr(instance, "_active_stream_lock", None)
    if active_stream_lock is not None:
        with active_stream_lock:
            if instance._active_stream is not None:
                # 스트림이 아직 쓰는 중이면 닫지 않고 참조가 풀릴 때 정리되게 둔다.
                return
    for client in obsolete_clients:
        try:
            client.close()
        except Exception as exc:
            logging.debug("이전 LLM 클라이언트 종료 실패: %s", exc)


def reset_llm_provider():
    global _instance
    _instance = None
