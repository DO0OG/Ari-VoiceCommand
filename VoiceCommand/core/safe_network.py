"""공개 HTTP 주소만 사용하는 네트워크 도구."""
from __future__ import annotations

import http.client
import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request


class UnsafeUrlError(ValueError):
    """공개 주소가 아닌 URL 또는 연결을 거부한다."""


def _is_public_address(value: str) -> bool:
    address = ipaddress.ip_address(str(value).split("%", 1)[0])
    if address.version == 6 and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_global and not address.is_multicast


def validate_public_http_url(url: str, *, allowed_schemes=("http", "https")) -> str:
    try:
        parsed = urllib.parse.urlsplit(url)
        scheme = parsed.scheme.lower()
        host = parsed.hostname
        port = parsed.port if parsed.port is not None else (443 if scheme == "https" else 80)
    except (AttributeError, TypeError, ValueError) as exc:
        raise UnsafeUrlError(f"잘못된 URL입니다: {exc}") from exc
    if scheme not in allowed_schemes:
        raise UnsafeUrlError(f"허용되지 않은 URL 스킴입니다: {scheme or '없음'}")
    if not host:
        raise UnsafeUrlError("호스트가 없는 URL입니다.")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeUrlError("사용자 정보가 포함된 URL입니다.")
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (OSError, socket.gaierror) as exc:
        raise UnsafeUrlError(f"호스트를 해석할 수 없습니다: {host}") from exc
    if not addresses:
        raise UnsafeUrlError(f"호스트를 해석할 수 없습니다: {host}")
    for result in addresses:
        try:
            address = result[4][0]
            safe = _is_public_address(address)
        except (IndexError, ValueError) as exc:
            raise UnsafeUrlError(f"잘못된 주소입니다: {host}") from exc
        if not safe:
            raise UnsafeUrlError(f"공개 주소가 아닙니다: {address}")
    return url


def validate_browser_url(url: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(url)
        scheme = parsed.scheme.lower()
        host = parsed.hostname
        port = parsed.port if parsed.port is not None else (443 if scheme == "https" else 80)
    except (AttributeError, TypeError, ValueError) as exc:
        raise UnsafeUrlError(f"잘못된 URL입니다. {exc}") from exc
    if scheme not in {"http", "https"}:
        raise UnsafeUrlError(f"허용되지 않은 URL 스킴입니다. {scheme or '없음'}")
    if not host:
        raise UnsafeUrlError("호스트가 없는 URL입니다.")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeUrlError("사용자 정보가 포함된 URL입니다.")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if host.lower() == "localhost":
            return url
        try:
            addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except (OSError, socket.gaierror) as exc:
            raise UnsafeUrlError(f"호스트를 해석할 수 없습니다: {host}") from exc
        if not addresses:
            raise UnsafeUrlError(f"호스트를 해석할 수 없습니다: {host}")
        for result in addresses:
            try:
                address = result[4][0]
                safe = _is_public_address(address)
            except (IndexError, ValueError) as exc:
                raise UnsafeUrlError(f"잘못된 주소입니다. {host}") from exc
            if not safe:
                raise UnsafeUrlError(f"공개 주소가 아닙니다: {address}")
    return url


def validate_browser_landing(start_url: str, current_url: str) -> None:
    try:
        parsed = urllib.parse.urlsplit(current_url)
    except (AttributeError, TypeError, ValueError) as exc:
        raise UnsafeUrlError(f"잘못된 URL입니다. {exc}") from exc
    if parsed.scheme.lower() not in {"http", "https"}:
        return
    validate_browser_url(current_url)
    host = parsed.hostname or ""
    try:
        address = ipaddress.ip_address(host)
        local = not _is_public_address(str(address))
    except ValueError:
        local = host.lower() == "localhost"
    start_host = (urllib.parse.urlsplit(start_url).hostname or "").lower()
    if local and start_host != host.lower():
        raise UnsafeUrlError(f"시작 주소와 다른 로컬 주소입니다: {host}")


def is_public_http_url(url: str) -> bool:
    try:
        validate_public_http_url(url)
    except UnsafeUrlError:
        return False
    return True


def _uses_proxy(url: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    scheme = parsed.scheme.lower()
    return scheme in urllib.request.getproxies() and not urllib.request.proxy_bypass(parsed.hostname or "")


def _checked_socket(connection: http.client.HTTPConnection) -> socket.socket:
    host = connection.host
    port = connection.port if connection.port is not None else (443 if isinstance(connection, http.client.HTTPSConnection) else 80)
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    for result in addresses:
        if not _is_public_address(result[4][0]):
            raise UnsafeUrlError(f"연결 주소가 공개 주소가 아닙니다: {result[4][0]}")
    errors = []
    for family, socktype, proto, _, sockaddr in addresses:
        sock = socket.socket(family, socktype, proto)
        try:
            if connection.timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                sock.settimeout(connection.timeout)
            if connection.source_address:
                sock.bind(connection.source_address)
            sock.connect(sockaddr)
            return sock
        except OSError as exc:
            errors.append(exc)
            sock.close()
    if errors:
        raise errors[-1]
    raise UnsafeUrlError(f"호스트를 해석할 수 없습니다: {host}")


class _SafeHTTPConnection(http.client.HTTPConnection):
    def connect(self):
        if self._safe_check:
            self.sock = _checked_socket(self)
            if self._tunnel_host:
                self._tunnel()
        else:
            super().connect()


class _SafeHTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        if self._safe_check:
            sock = _checked_socket(self)
            if self._tunnel_host:
                self.sock = sock
                self._tunnel()
                sock = self.sock
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        else:
            super().connect()


class _SafeHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        connection = type("RequestHTTPConnection", (_SafeHTTPConnection,), {"_safe_check": not _uses_proxy(req.full_url)})
        return self.do_open(connection, req)


class _SafeHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        connection = type("RequestHTTPSConnection", (_SafeHTTPSConnection,), {"_safe_check": not _uses_proxy(req.full_url)})
        kwargs = {"context": self._context}
        if hasattr(self, "_check_hostname"):
            kwargs["check_hostname"] = self._check_hostname
        return self.do_open(connection, req, **kwargs)


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, max_redirects, allowed_schemes):
        super().__init__()
        self.max_redirects = max_redirects
        self.allowed_schemes = allowed_schemes

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        count = getattr(req, "_safe_redirect_count", 0) + 1
        if count > self.max_redirects:
            raise urllib.error.HTTPError(req.full_url, code, "최대 리디렉션 횟수를 초과했습니다.", headers, fp)
        validate_public_http_url(newurl, allowed_schemes=self.allowed_schemes)
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            redirected._safe_redirect_count = count
        return redirected


def safe_urlopen(request_or_url, *, timeout, max_redirects=5, allowed_schemes=("http", "https")):
    request = request_or_url if isinstance(request_or_url, urllib.request.Request) else urllib.request.Request(request_or_url)
    validate_public_http_url(request.full_url, allowed_schemes=allowed_schemes)
    opener = urllib.request.build_opener(
        _SafeHTTPHandler(),
        _SafeHTTPSHandler(),
        _SafeRedirectHandler(max_redirects, allowed_schemes),
    )
    return opener.open(request, timeout=timeout)


def read_limited(response, max_bytes: int) -> bytes:
    data = response.read(max_bytes + 1)
    response._safe_network_truncated = len(data) > max_bytes
    return data[:max_bytes]
