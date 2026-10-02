import os
import socket
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
    def setUp(self):
        self.dns = patch("core.safe_network.socket.getaddrinfo", return_value=[(
            socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443)
        )])
        self.dns.start()
        self.addCleanup(self.dns.stop)

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

        addresses = {
            "localhost": "127.0.0.1", "127.0.0.1": "127.0.0.1", "10.0.0.25": "10.0.0.25",
            "192.168.0.10": "192.168.0.10", "::1": "::1", "fe80::1": "fe80::1", "0.0.0.0": "0.0.0.0",
        }
        def resolve(host, *args, **kwargs):
            address = addresses.get(host, "93.184.216.34")
            family = socket.AF_INET6 if ":" in address else socket.AF_INET
            sockaddr = (address, 443, 0, 0) if family == socket.AF_INET6 else (address, 443)
            return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)]
        with patch("core.safe_network.socket.getaddrinfo", side_effect=resolve):
            for url in blocked_urls:
                with self.subTest(url=url):
                    self.assertFalse(web_tools._is_safe_http_url(url))
            self.assertTrue(web_tools._is_safe_http_url("https://example.com/path"))

    def test_web_fetch_limits_body_and_rejects_binary_content_type(self):
        class Response:
            def __init__(self, payload, content_type):
                self.payload = payload
                self.headers = {"Content-Type": content_type}
                self.read_sizes = []

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, size):
                self.read_sizes.append(size)
                return self.payload[:size]

        body = Response(b"a" * (2 * 1024 * 1024 + 10), "text/plain")
        with patch.object(web_tools, "safe_urlopen", return_value=body):
            text = web_tools.web_fetch("https://example.com")
        self.assertEqual(body.read_sizes, [2 * 1024 * 1024 + 1])
        self.assertEqual(len(text), 3000)

        binary = Response(b"image", "image/png")
        with patch.object(web_tools, "safe_urlopen", return_value=binary):
            result = web_tools.web_fetch("https://example.com")
        self.assertIn("텍스트가 아닌 응답입니다: image/png", result)
        self.assertEqual(binary.read_sizes, [])

    def test_web_fetch_returns_unsafe_url_reason(self):
        with patch.object(web_tools, "validate_public_http_url", side_effect=web_tools.UnsafeUrlError("공개 주소가 아닙니다")):
            result = web_tools.web_fetch("http://127.0.0.1")
        self.assertIn("허용되지 않은 URL입니다: 공개 주소가 아닙니다", result)

    def test_browser_rejects_before_navigation_and_blanks_unsafe_redirect(self):
        class Driver:
            current_url = ""

            def __init__(self, current_url=""):
                self.current_url = current_url
                self.visited = []

            def get(self, url):
                self.visited.append(url)

        browser = SmartBrowser.__new__(SmartBrowser)
        driver = Driver()
        browser.driver = driver
        browser._ensure_driver = lambda: None
        with patch.object(web_tools, "validate_browser_url", side_effect=web_tools.UnsafeUrlError("blocked")):
            with self.assertRaises(web_tools.UnsafeUrlError):
                browser.navigate_and_action("http://127.0.0.1", [])
        self.assertEqual(driver.visited, [])

        driver = Driver("http://127.0.0.1/private")
        browser.driver = driver
        with patch("core.safe_network.socket.getaddrinfo", return_value=[(
            socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443)
        )]):
            with self.assertRaises(web_tools.UnsafeUrlError):
                browser.navigate_and_action("https://example.com", [])
        self.assertEqual(driver.visited, ["https://example.com", "about:blank"])

    def test_wait_for_download_stability_clock_restarts_only_when_size_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "download.bin")
            with open(path, "wb") as handle:
                handle.write(b"x")
            browser = SmartBrowser.__new__(SmartBrowser)
            browser.download_dir = tmp

            with patch.object(web_tools.time, "time", side_effect=(0, 0, 0, 0.5, 0.5, 1, 1, 1.5, 1.5, 2.1, 2.1)), \
                 patch.object(web_tools.time, "sleep"), \
                 patch.object(web_tools.os.path, "getsize", side_effect=(1, 1, 2, 2, 2)):
                result = browser.wait_for_download(timeout=10, stable_seconds=1)

        self.assertEqual(result, path)

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
