import socket
import unittest
import gzip
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

from core.safe_network import (
    UnsafeUrlError,
    _SafeHTTPConnection,
    _SafeHTTPSHandler,
    _SafeRedirectHandler,
    read_limited,
    safe_urlopen,
    validate_browser_landing,
    validate_browser_url,
    validate_public_http_url,
)


def _result(address):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    sockaddr = (address, 443, 0, 0) if family == socket.AF_INET6 else (address, 443)
    return (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)


class SafeNetworkTests(unittest.TestCase):
    def test_https_handler_does_not_require_check_hostname_attribute(self):
        handler = object.__new__(_SafeHTTPSHandler)
        handler._context = object()
        handler.do_open = lambda connection, request, **kwargs: kwargs
        with patch("core.safe_network._uses_proxy", return_value=False):
            kwargs = handler.https_open(Request("https://example.com"))
        self.assertEqual(kwargs, {"context": handler._context})

    def test_browser_accepts_localhost_and_standard_ip_literals(self):
        for url in ("http://localhost:3000/", "http://127.0.0.1:8080/", "http://192.168.0.10/"):
            with self.subTest(url=url):
                self.assertEqual(validate_browser_url(url), url)

    def test_browser_rejects_nonstandard_ip_forms_and_private_dns(self):
        blocked = ("http://2130706433/", "http://0x7f000001/", "http://0177.0.0.1/", "http://private.example/")
        def resolve(host, *args, **kwargs):
            address = "10.0.0.1" if host == "private.example" else "127.0.0.1"
            return [_result(address)]
        with patch("core.safe_network.socket.getaddrinfo", side_effect=resolve):
            for url in blocked:
                with self.subTest(url=url), self.assertRaises(UnsafeUrlError):
                    validate_browser_url(url)

    def test_browser_landing_rejects_public_to_local_and_other_local_host(self):
        with patch("core.safe_network.socket.getaddrinfo", return_value=[_result("93.184.216.34")]):
            with self.assertRaises(UnsafeUrlError):
                validate_browser_landing("https://example.com", "http://localhost/private")
        with self.assertRaises(UnsafeUrlError):
            validate_browser_landing("http://localhost:3000", "http://127.0.0.1/private")
        validate_browser_landing("http://localhost:3000", "http://localhost:3000/next")

    def test_browser_landing_normalizes_ipv6_literals(self):
        validate_browser_landing("http://[0:0:0:0:0:0:0:1]/", "http://[::1]/")

    def test_nonstandard_numeric_hosts_are_rejected_before_dns(self):
        for host in ("0x08080808", "134744072", "010.010.010.010"):
            for validate in (validate_public_http_url, validate_browser_url):
                with self.subTest(host=host, validate=validate.__name__), patch(
                    "core.safe_network.socket.getaddrinfo"
                ) as resolve:
                    with self.assertRaises(UnsafeUrlError):
                        validate(f"http://{host}/")
                    resolve.assert_not_called()

        with patch("core.safe_network.socket.getaddrinfo", return_value=[_result("93.184.216.34")]) as resolve:
            for validate in (validate_public_http_url, validate_browser_url):
                validate("http://8.8.8.8/")
                validate("http://example.com/")
            self.assertEqual(resolve.call_count, 2)

    def test_web_fetch_still_rejects_localhost(self):
        from services.web_tools import web_fetch

        result = web_fetch("http://localhost/")
        self.assertIn("허용되지 않은 URL입니다", result)

    def test_rejects_unsafe_url_forms(self):
        blocked = (
            "http://2130706433/", "http://0x7f000001/", "http://0177.0.0.1/",
            "http://localhost/", "http://10.0.0.1/", "http://[::1]/",
            "http://[fc00::1]/", "http://[fe80::1]/", "http://[::ffff:127.0.0.1]/",
            "http://user:pass@example.com/", "ftp://example.com/", "file:///tmp/x",
        )
        with patch("core.safe_network.socket.getaddrinfo", side_effect=lambda host, *a, **k: [_result({
            "localhost": "127.0.0.1", "2130706433": "127.0.0.1", "0x7f000001": "127.0.0.1",
            "0177.0.0.1": "127.0.0.1", "10.0.0.1": "10.0.0.1", "::1": "::1",
            "fc00::1": "fc00::1", "fe80::1": "fe80::1", "::ffff:127.0.0.1": "::ffff:127.0.0.1",
        }.get(host, "93.184.216.34"))]):
            for url in blocked:
                with self.subTest(url=url), self.assertRaises(UnsafeUrlError):
                    validate_public_http_url(url)
        with self.assertRaises(UnsafeUrlError):
            validate_public_http_url("http:///missing-host")

    def test_rejects_resolution_failure_or_any_private_answer(self):
        with patch("core.safe_network.socket.getaddrinfo", side_effect=socket.gaierror("no host")):
            with self.assertRaises(UnsafeUrlError):
                validate_public_http_url("https://example.com")
        with patch("core.safe_network.socket.getaddrinfo", return_value=[_result("93.184.216.34"), _result("192.168.1.2")]):
            with self.assertRaises(UnsafeUrlError):
                validate_public_http_url("https://example.com")

    def test_accepts_public_host_and_returns_original_url(self):
        url = "https://example.com/a?q=1"
        with patch("core.safe_network.socket.getaddrinfo", return_value=[_result("93.184.216.34")]):
            self.assertEqual(validate_public_http_url(url), url)

    def test_redirect_validates_each_hop_and_enforces_limit(self):
        handler = _SafeRedirectHandler(5, ("http", "https"))
        response = BytesIO()
        headers = {"Location": "https://public.example/next"}
        with patch("core.safe_network.socket.getaddrinfo", return_value=[_result("93.184.216.34")]):
            first = handler.redirect_request(Request("https://start.example"), response, 302, "Found", headers, headers["Location"])
            self.assertEqual(first._safe_redirect_count, 1)
            headers["Location"] = "https://public.example/second"
            second = handler.redirect_request(first, response, 302, "Found", headers, headers["Location"])
            self.assertEqual(second._safe_redirect_count, 2)
        headers["Location"] = "https://private.example/"
        with patch("core.safe_network.socket.getaddrinfo", return_value=[_result("10.0.0.1")]):
            with self.assertRaises(UnsafeUrlError):
                handler.redirect_request(second, response, 302, "Found", headers, headers["Location"])
        limited = _SafeRedirectHandler(0, ("http", "https"))
        with self.assertRaises(HTTPError):
            limited.redirect_request(Request("https://start.example"), response, 302, "Found", headers, "https://next.example")

    def test_connection_rejects_private_dns_before_socket_creation(self):
        connection = _SafeHTTPConnection("example.com", 80)
        connection._safe_check = True
        with patch("core.safe_network.socket.getaddrinfo", return_value=[_result("192.168.1.3")]), patch(
            "core.safe_network.socket.socket"
        ) as make_socket:
            with self.assertRaises(UnsafeUrlError):
                connection.connect()
        make_socket.assert_not_called()

    def test_read_limited_reads_only_one_byte_over_limit(self):
        class Response:
            def __init__(self):
                self.requested = None

            def read(self, size):
                self.requested = size
                return b"abcdef"[:size]

        response = Response()
        self.assertEqual(read_limited(response, 4), b"abcd")
        self.assertEqual(response.requested, 5)
        self.assertTrue(response._safe_network_truncated)

    def test_read_limited_decompresses_gzip_and_marks_expanded_limit(self):
        class Response(BytesIO):
            headers = {"Content-Encoding": "gzip"}

        body = gzip.compress(b"expanded content")
        response = Response(body)
        self.assertEqual(read_limited(response, 100), b"expanded content")
        self.assertFalse(response._safe_network_truncated)

        response = Response(body)
        self.assertEqual(read_limited(response, 8), b"expanded")
        self.assertTrue(response._safe_network_truncated)

    def test_read_limited_rejects_gzip_trailing_data_with_bounded_reads(self):
        class Response(BytesIO):
            headers = {"Content-Encoding": "gzip"}

            def __init__(self, body):
                super().__init__(body)
                self.read_total = 0

            def read(self, size=-1):
                data = super().read(size)
                self.read_total += len(data)
                return data

        response = Response(gzip.compress(b"x") + b"z" * 10000)
        with self.assertRaises(ValueError):
            read_limited(response, 64)

        # 출력이 늘지 않는 빈 멤버가 이어져도 입력 상한에서 멈춘다.
        response = Response(gzip.compress(b"x") + gzip.compress(b"") * 20000)
        self.assertEqual(read_limited(response, 64), b"x")
        self.assertTrue(response._safe_network_truncated)
        self.assertLessEqual(response.read_total, 64 + 64 * 1024 + 1)

    def test_read_limited_decompresses_concatenated_gzip_members(self):
        class Response(BytesIO):
            headers = {"Content-Encoding": "gzip"}

        response = Response(gzip.compress(b"first") + gzip.compress(b"second"))
        self.assertEqual(read_limited(response, 100), b"firstsecond")

    def test_read_limited_rejects_truncated_gzip(self):
        class Response(BytesIO):
            headers = {"Content-Encoding": "gzip"}

        response = Response(gzip.compress(b"complete")[:-3])
        with self.assertRaises(ValueError):
            read_limited(response, 100)

        # 본문이 없는 응답은 압축 표시가 있어도 빈 본문으로 본다.
        self.assertEqual(read_limited(Response(b""), 100), b"")

    def test_read_limited_decompresses_both_deflate_formats(self):
        import zlib

        class Response(BytesIO):
            headers = {"Content-Encoding": "deflate"}

        for body in (zlib.compress(b"deflate body"), zlib.compress(b"deflate body", wbits=-zlib.MAX_WBITS)):
            with self.subTest(raw=body[:2] != b"\x78\x9c"):
                response = Response(body)
                self.assertEqual(read_limited(response, 100), b"deflate body")

    def test_safe_urlopen_adds_identity_encoding_unless_caller_set_it(self):
        class Opener:
            def open(self, request, timeout):
                return request

        with patch("core.safe_network.validate_public_http_url"), patch(
            "core.safe_network.urllib.request.build_opener", return_value=Opener()
        ):
            request = safe_urlopen("https://example.com", timeout=1)
            self.assertEqual(request.get_header("Accept-encoding"), "identity")
            custom = Request("https://example.com", headers={"Accept-Encoding": "gzip"})
            result = safe_urlopen(custom, timeout=1)
            self.assertEqual(result.get_header("Accept-encoding"), "gzip")


if __name__ == "__main__":
    unittest.main()
