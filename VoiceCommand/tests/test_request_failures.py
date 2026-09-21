import gettext
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from agent.llm_provider import LLMProvider


def status_error(status):
    error = RuntimeError("request failed")
    error.status_code = status
    return error


# 제공자 라이브러리는 예외 클래스 이름으로만 구분되므로(_error_response 참고)
# 같은 이름의 대역으로 분기를 확인한다.  테스트가 특정 라이브러리를 직접
# 끌어오지 않게 하려는 의도다.
class APIConnectionError(Exception):
    pass


class APITimeoutError(Exception):
    pass


class RequestFailureMessageTests(unittest.TestCase):
    def test_error_response_distinguishes_failures(self):
        cases = [
            (status_error(401), "인증"),
            (status_error(403), "인증"),
            (status_error(429), "요청 한도"),
            (status_error(500), "서버 오류"),
            (status_error(503), "서버 오류"),
            (RuntimeError("unknown"), "요청을 처리"),
            (APIConnectionError("connection failed"), "네트워크"),
            (APITimeoutError("timed out"), "네트워크"),
        ]
        for error, expected in cases:
            with self.subTest(error=type(error).__name__, status=getattr(error, "status_code", None)):
                response = LLMProvider._error_response(error)
                self.assertIn(expected, response)
                self.assertNotIn("인터넷 연결이 없어서", response)

    def test_non_server_errors_do_not_switch_connections(self):
        for status in (400, 401, 403, 429):
            with self.subTest(status=status):
                provider = LLMProvider(model="primary")
                primary, secondary = Mock(), Mock()
                error = status_error(status)
                primary.chat.completions.create.side_effect = error
                with patch.object(
                    provider,
                    "get_role_fallback_targets",
                    return_value=[(secondary, "gemini", "secondary")],
                ):
                    with self.assertRaises(RuntimeError) as caught:
                        provider._create_completion_with_fallback(
                            primary, "groq", "primary", messages=[]
                        )
                self.assertIs(caught.exception, error)
                secondary.chat.completions.create.assert_not_called()

    def test_server_error_switches_connection_without_duplicate_history(self):
        for with_tools in (False, True):
            with self.subTest(with_tools=with_tools):
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

                self.assertEqual(result, ("완료", []) if with_tools else "완료")
                user_turns = sum(item["role"] == "user" for item in provider._history_snapshot())
                self.assertEqual(user_turns, 1)
                first = primary.chat.completions.create.call_args.kwargs
                second = secondary.chat.completions.create.call_args.kwargs
                self.assertEqual(first["messages"], second["messages"])
                self.assertEqual(second["model"], "secondary")
                self.assertEqual(second["extra_body"], {"reasoning_format": "hidden"})
                if with_tools:
                    self.assertEqual(first["tools"], second["tools"])
                    self.assertEqual(first["tool_choice"], second["tool_choice"])

    def test_exhausted_server_errors_keep_server_diagnosis(self):
        provider = LLMProvider(model="primary")
        provider.client = Mock()
        provider.client.chat.completions.create.side_effect = status_error(500)
        with patch.object(provider, "_build_system", return_value="system"), \
                patch.object(provider, "_get_skill_context", return_value={}):
            response, calls = provider.chat_with_tools("안녕")
        self.assertIn("서버 오류", response)
        self.assertEqual(calls, [])

    def test_error_catalogs_compile_with_matching_entries(self):
        from scripts.compile_po import compile_po

        locales = Path(__file__).resolve().parents[1] / "i18n" / "locales"
        catalogs = {}
        with tempfile.TemporaryDirectory() as temp_dir:
            for language in ("ko", "en", "ja"):
                source = locales / language / "LC_MESSAGES" / "ari.po"
                destination = Path(temp_dir) / f"{language}.mo"
                compile_po(str(source), str(destination))
                with destination.open("rb") as stream:
                    catalogs[language] = gettext.GNUTranslations(stream)

        self.assertEqual(catalogs["ko"]._catalog.keys(), catalogs["en"]._catalog.keys())
        self.assertEqual(catalogs["ko"]._catalog.keys(), catalogs["ja"]._catalog.keys())

        errors = [status_error(401), status_error(429), status_error(500), ConnectionError(), RuntimeError()]
        for error in errors:
            message = LLMProvider._error_response(error)
            with self.subTest(message=message):
                self.assertEqual(catalogs["ko"].gettext(message), message)
                self.assertNotEqual(catalogs["en"].gettext(message), message)
                self.assertNotEqual(catalogs["ja"].gettext(message), message)


if __name__ == "__main__":
    unittest.main()
