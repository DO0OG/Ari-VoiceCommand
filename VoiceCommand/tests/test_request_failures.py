from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from openai import APIConnectionError, APITimeoutError
import httpx

from agent.llm_provider import LLMProvider


def status_error(status):
    error = RuntimeError("request failed")
    error.status_code = status
    return error


@pytest.mark.parametrize("error, expected", [
    (status_error(401), "인증"), (status_error(403), "인증"),
    (status_error(429), "요청 한도"), (status_error(500), "서버 오류"),
    (status_error(503), "서버 오류"), (RuntimeError("unknown"), "요청을 처리"),
    (APIConnectionError(request=httpx.Request("POST", "https://example.com")), "네트워크"),
    (APITimeoutError(request=httpx.Request("POST", "https://example.com")), "네트워크"),
])
def test_error_response_distinguishes_failures(error, expected):
    response = LLMProvider._error_response(error)
    assert expected in response
    assert "인터넷 연결이 없어서" not in response


@pytest.mark.parametrize("status", [400, 401, 403, 429])
def test_non_server_errors_do_not_switch_connections(status):
    provider = LLMProvider(model="primary")
    primary, secondary = Mock(), Mock()
    error = status_error(status)
    primary.chat.completions.create.side_effect = error
    with patch.object(provider, "get_role_fallback_targets", return_value=[(secondary, "gemini", "secondary")]):
        with pytest.raises(RuntimeError) as caught:
            provider._create_completion_with_fallback(primary, "groq", "primary", messages=[])
    assert caught.value is error
    secondary.chat.completions.create.assert_not_called()


@pytest.mark.parametrize("with_tools", [False, True])
def test_server_error_switches_connection_without_duplicate_history(with_tools):
    provider = LLMProvider(provider="nvidia_nim", model="primary")
    primary, secondary = Mock(), Mock()
    provider.client = primary
    primary.chat.completions.create.side_effect = status_error(500)
    secondary.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="완료", tool_calls=[]))],
    )
    targets = [(primary, "nvidia_nim", "primary"), (secondary, "groq", "secondary")]
    with patch.object(provider, "get_role_fallback_targets", return_value=targets), \
         patch.object(provider, "_get_skill_context", return_value={}), \
         patch.object(provider, "_build_system", return_value="system"), \
         patch("memory.memory_manager.get_memory_manager") as memory:
        memory.return_value.clean_response.side_effect = lambda value: value
        result = provider.chat_with_tools("안녕") if with_tools else provider.chat("안녕")
    assert result == ("완료", []) if with_tools else result == "완료"
    assert sum(item["role"] == "user" for item in provider._history_snapshot()) == 1
    first = primary.chat.completions.create.call_args.kwargs
    second = secondary.chat.completions.create.call_args.kwargs
    assert first["messages"] == second["messages"]
    assert second["model"] == "secondary"
    assert second["extra_body"] == {"reasoning_format": "hidden"}
    if with_tools:
        assert first["tools"] == second["tools"]
        assert first["tool_choice"] == second["tool_choice"]


def test_exhausted_server_errors_keep_server_diagnosis():
    provider = LLMProvider(model="primary")
    provider.client = Mock()
    provider.client.chat.completions.create.side_effect = status_error(500)
    with patch.object(provider, "_build_system", return_value="system"), \
         patch.object(provider, "_get_skill_context", return_value={}):
        response, calls = provider.chat_with_tools("안녕")
    assert "서버 오류" in response
    assert calls == []


def test_error_catalogs_compile_with_matching_entries(tmp_path):
    import gettext
    from pathlib import Path
    from scripts.compile_po import compile_po

    catalogs = {}
    for language in ("ko", "en", "ja"):
        source = Path(__file__).resolve().parents[1] / "i18n" / "locales" / language / "LC_MESSAGES" / "ari.po"
        destination = tmp_path / f"{language}.mo"
        compile_po(str(source), str(destination))
        with destination.open("rb") as stream:
            catalogs[language] = gettext.GNUTranslations(stream)
    assert catalogs["ko"]._catalog.keys() == catalogs["en"]._catalog.keys() == catalogs["ja"]._catalog.keys()
    errors = [status_error(401), status_error(429), status_error(500), ConnectionError(), RuntimeError()]
    for error in errors:
        message = LLMProvider._error_response(error)
        assert catalogs["ko"].gettext(message) == message
        assert catalogs["en"].gettext(message) != message
        assert catalogs["ja"].gettext(message) != message
