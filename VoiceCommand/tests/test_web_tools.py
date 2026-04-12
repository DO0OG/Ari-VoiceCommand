import os
import tempfile
import unittest
from unittest.mock import patch


from services import web_tools
from services.web_tools import SmartBrowser


class _TempBrowser(SmartBrowser):
    def __init__(self, selector_path: str, download_dir: str):
        self._selector_path_override = selector_path
        super().__init__(headless=True, download_dir=download_dir)

    def _selector_history_path(self) -> str:
        return self._selector_path_override

    def _action_plan_history_path(self) -> str:
        return self._selector_path_override.replace("selectors.json", "action_plans.json")


class WebToolsTests(unittest.TestCase):
    def test_is_safe_http_url_blocks_local_and_private_targets(self):
        blocked_urls = (
            "http://localhost:8000",
            "https://127.0.0.1/api",
            "https://10.0.0.25/status",
            "https://192.168.0.10/admin",
            "https://[::1]/",
            "https://[fe80::1]/",
            "https://0.0.0.0/",
            "file:///etc/passwd",
        )

        for url in blocked_urls:
            with self.subTest(url=url):
                self.assertFalse(web_tools._is_safe_http_url(url))

        self.assertTrue(web_tools._is_safe_http_url("https://example.com/path"))

    def test_create_search_client_prefers_ddgs_package_name(self):
        class _Client:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        with patch.dict("sys.modules", {"ddgs": type("Mod", (), {"DDGS": _Client})}):
            client = web_tools._create_search_client()

        self.assertIsInstance(client, _Client)

    def test_create_search_client_falls_back_to_legacy_package_name(self):
        class _Client:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        real_import = __import__

        def side_effect(name, global_ns=None, local_ns=None, fromlist=(), level=0):
            if name == "ddgs":
                raise ImportError("missing ddgs")
            return real_import(name, global_ns, local_ns, fromlist, level)

        fake_modules = {"duckduckgo_search": type("Mod", (), {"DDGS": _Client})}
        with patch.dict("sys.modules", fake_modules, clear=False):
            with patch("builtins.__import__", side_effect=side_effect):
                client = web_tools._create_search_client()

        self.assertIsInstance(client, _Client)

    def test_create_search_client_raises_when_all_packages_missing(self):
        with patch("builtins.__import__", side_effect=ImportError("missing")):
            with self.assertRaises(ImportError):
                web_tools._create_search_client()

    def test_selector_history_persists_between_instances(self):
        with tempfile.TemporaryDirectory() as tmp:
            selector_path = os.path.join(tmp, "selectors.json")
            browser = _TempBrowser(selector_path=selector_path, download_dir=tmp)
            browser._remember_selector("example.com", "login", "#submit")

            reloaded = _TempBrowser(selector_path=selector_path, download_dir=tmp)
            ordered = reloaded._ordered_selectors("example.com", "login", [".btn", "#submit"])

            self.assertEqual(ordered[0], "#submit")

    def test_state_includes_last_action_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            selector_path = os.path.join(tmp, "selectors.json")
            browser = _TempBrowser(selector_path=selector_path, download_dir=tmp)
            browser._last_action_summary = "성공: click"

            state = browser.get_state()

            self.assertIn("last_action_summary", state)
            self.assertEqual(state["last_action_summary"], "성공: click")

    def test_action_plan_persists_between_instances(self):
        with tempfile.TemporaryDirectory() as tmp:
            selector_path = os.path.join(tmp, "selectors.json")
            browser = _TempBrowser(selector_path=selector_path, download_dir=tmp)
            browser.remember_action_plan(
                "example.com",
                "로그인 후 다운로드",
                [{"type": "click", "selectors": ["#download"]}],
            )

            reloaded = _TempBrowser(selector_path=selector_path, download_dir=tmp)
            remembered = reloaded.get_action_plan("example.com", "로그인 후 다운로드")

            self.assertEqual(len(remembered), 1)
            self.assertEqual(remembered[0]["type"], "click")

    def test_action_plan_uses_similar_goal_hint_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            selector_path = os.path.join(tmp, "selectors.json")
            browser = _TempBrowser(selector_path=selector_path, download_dir=tmp)
            browser.remember_action_plan(
                "example.com",
                "로그인 후 다운로드",
                [{"type": "click", "selectors": ["#download"]}],
            )

            remembered = browser.get_action_plan("example.com", "다운로드 전에 로그인")

            self.assertEqual(len(remembered), 1)
            self.assertEqual(remembered[0]["type"], "click")

    def test_action_plan_prefers_page_specific_strategy(self):
        with tempfile.TemporaryDirectory() as tmp:
            selector_path = os.path.join(tmp, "selectors.json")
            browser = _TempBrowser(selector_path=selector_path, download_dir=tmp)
            browser.remember_action_plan(
                "example.com",
                "로그인 후 다운로드",
                [{"type": "click", "selectors": ["#page-download"]}],
                page_key="example.com|downloads",
            )
            browser.remember_action_plan(
                "example.com",
                "로그인 후 다운로드",
                [{"type": "click", "selectors": ["#generic-download"]}],
            )

            remembered = browser.get_action_plan("example.com", "로그인 후 다운로드", page_key="example.com|downloads")

            self.assertEqual(remembered[0]["selectors"][0], "#page-download")

    def test_failed_browser_results_are_not_persisted_as_action_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            selector_path = os.path.join(tmp, "selectors.json")
            browser = _TempBrowser(selector_path=selector_path, download_dir=tmp)
            self.assertFalse(browser._should_remember_action_plan(["성공: click", "실패: type"]))

            remembered = browser.get_action_plan("example.com", "로그인 후 다운로드")
            self.assertEqual(remembered, [])

    def test_wait_for_url_contains_matches_driver_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            selector_path = os.path.join(tmp, "selectors.json")
            browser = _TempBrowser(selector_path=selector_path, download_dir=tmp)

            class _Driver:
                current_url = "https://example.com/dashboard"
                title = "Dashboard"

            browser.driver = _Driver()
            matched = browser._wait_for_url_contains("dashboard", timeout=0.01)

            self.assertEqual(matched, "https://example.com/dashboard")

    def test_wait_for_title_contains_matches_driver_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            selector_path = os.path.join(tmp, "selectors.json")
            browser = _TempBrowser(selector_path=selector_path, download_dir=tmp)

            class _Driver:
                current_url = "https://example.com/dashboard"
                title = "Dashboard - Example"

            browser.driver = _Driver()
            matched = browser._wait_for_title_contains("example", timeout=0.01)

            self.assertEqual(matched, "Dashboard - Example")

    def test_execute_browser_action_supports_read_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            selector_path = os.path.join(tmp, "selectors.json")
            browser = _TempBrowser(selector_path=selector_path, download_dir=tmp)

            class _Driver:
                current_url = "https://example.com/dashboard"
                title = "Dashboard - Example"

            browser.driver = _Driver()
            result = browser._execute_browser_action({"type": "read_url"}, "example.com", None, None, None)

            self.assertIn("https://example.com/dashboard", result)

    def test_execute_browser_action_supports_wait_selector(self):
        with tempfile.TemporaryDirectory() as tmp:
            selector_path = os.path.join(tmp, "selectors.json")
            browser = _TempBrowser(selector_path=selector_path, download_dir=tmp)

            browser._find_element_for_action = lambda *_args, **_kwargs: (object(), "#download")
            result = browser._execute_browser_action(
                {"type": "wait_selector", "selectors": ["#download"]},
                "example.com",
                None,
                None,
                None,
            )

            self.assertEqual(result, "성공: wait_selector(#download)")

    def test_find_element_for_action_uses_text_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            selector_path = os.path.join(tmp, "selectors.json")
            browser = _TempBrowser(selector_path=selector_path, download_dir=tmp)
            marker = object()
            browser._find_element_by_text = lambda text_query: marker if text_query == "다운로드" else None

            found, matched = browser._find_element_for_action(
                {"type": "click_text", "text_contains": "다운로드", "selectors": []},
                "example.com",
                "download",
                None,
                None,
                None,
            )

            self.assertIs(found, marker)
            self.assertEqual(matched, "text:다운로드")


if __name__ == "__main__":
    unittest.main()
