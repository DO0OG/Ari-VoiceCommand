"""공개 HTTP 주소만 사용하는 네트워크 도구."""
from __future__ import annotations

import http.client
import ipaddress
import logging
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
import zlib


class UnsafeUrlError(ValueError):
    """공개 주소가 아닌 URL 또는 연결을 거부한다."""


def _is_public_address(value: str) -> bool:
    address = ipaddress.ip_address(str(value).split("%", 1)[0])
    if address.version == 6 and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    elif address.version == 6 and address in ipaddress.ip_network("64:ff9b::/96"):
        address = ipaddress.IPv4Address(int(address) & 0xffffffff)
    elif address.version == 6 and address in ipaddress.ip_network("64:ff9b:1::/48"):
        return False
    return address.is_global and not address.is_multicast


def _parse_http_url(url: str, allowed_schemes, *, allow_local: bool):
    try:
        parsed = urllib.parse.urlsplit(url)
        scheme = parsed.scheme.lower()
        host = parsed.hostname
        port = parsed.port if parsed.port is not None else (443 if scheme == "https" else 80)
    except (AttributeError, TypeError, ValueError) as exc:
        raise UnsafeUrlError(f"잘못된 URL입니다. {exc}") from exc
    if scheme not in allowed_schemes:
        raise UnsafeUrlError(f"허용되지 않은 URL 스킴입니다: {scheme or '없음'}")
    if not host:
        raise UnsafeUrlError("호스트가 없는 URL입니다.")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeUrlError("사용자 정보가 포함된 URL입니다.")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        if allow_local or _is_public_address(str(literal)):
            return parsed, host, port, str(literal)
        raise UnsafeUrlError(f"공개 주소가 아닙니다: {host}")
    normalized_host = host[:-1] if host.endswith(".") else host
    last_label = normalized_host.rsplit(".", 1)[-1]
    if re.fullmatch(r"(?:[0-9]+|0x[0-9a-f]+)", last_label, re.IGNORECASE):
        raise UnsafeUrlError(f"표준 형식이 아닌 숫자 주소입니다: {host}")
    if allow_local and normalized_host.lower() == "localhost":
        return parsed, host, port, host
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
    pinned = next((item[4][0] for item in addresses if item[0] == socket.AF_INET), addresses[0][4][0])
    return parsed, host, port, pinned


def validate_public_http_url(url: str, *, allowed_schemes=("http", "https")) -> str:
    _parse_http_url(url, allowed_schemes, allow_local=False)
    return url


def validate_browser_url(url: str) -> str:
    _parse_http_url(url, ("http", "https"), allow_local=True)
    return url


def _normalized_host(host: str):
    try:
        address = ipaddress.ip_address(host)
        if address.version == 6 and address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        return address
    except ValueError:
        return (host[:-1] if host.endswith(".") else host).lower()


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
        local = not _is_public_address(host)
    except ValueError:
        local = (host[:-1] if host.endswith(".") else host).lower() == "localhost"
    start_host = urllib.parse.urlsplit(start_url).hostname or ""
    if local and _normalized_host(start_host) != _normalized_host(host):
        raise UnsafeUrlError(f"시작 주소와 다른 로컬 주소입니다: {host}")


def validate_browser_session(driver, start_url: str) -> None:
    """현재 페이지를 검사하고 위반 시 내용을 비운다. 요청이 전송된 뒤 검사하는 사후 방어다."""
    try:
        validate_browser_landing(start_url, str(getattr(driver, "current_url", "") or ""))
    except UnsafeUrlError:
        driver.get("about:blank")
        raise


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
        pinned = getattr(self, "_safe_proxy_ip", None)
        if pinned and self._tunnel_host:
            # 프록시가 이름을 다시 해석해 사설 주소로 가지 못하게, 검증한 IP로 CONNECT한다.
            # TLS 검증에는 원래 호스트 이름을 쓴다.
            origin_host = self._tunnel_host
            self._tunnel_host = f"[{pinned}]" if ":" in pinned else pinned
            try:
                http.client.HTTPConnection.connect(self)
            finally:
                self._tunnel_host = origin_host
            self.sock = self._context.wrap_socket(self.sock, server_hostname=origin_host)
            return
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
        proxied = _uses_proxy(req.full_url)
        address = getattr(req, "_safe_destination_ip", None) if proxied else None
        if address:
            # 프록시에 보내는 요청 대상을 검증한 IP로 바꾸고, Host에는 원래 이름을 남긴다.
            original = urllib.parse.urlsplit(req.full_url)
            port = "" if original.port is None else f":{original.port}"
            origin_host = original.hostname or ""
            req.selector = urllib.parse.urlunsplit(
                original._replace(netloc=(f"[{address}]" if ":" in address else address) + port)
            )
            req.remove_header("Host")
            req.add_unredirected_header("Host", (f"[{origin_host}]" if ":" in origin_host else origin_host) + port)
        connection = type("RequestHTTPConnection", (_SafeHTTPConnection,), {"_safe_check": not proxied})
        return self.do_open(connection, req)


class _SafeHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        proxied = _uses_proxy(req.full_url)
        kwargs = {"context": self._context}
        if hasattr(self, "_check_hostname"):
            kwargs["check_hostname"] = self._check_hostname
        address = getattr(req, "_safe_destination_ip", None) if proxied else None
        if address:
            pinned = type(
                "RequestHTTPSConnection", (_SafeHTTPSConnection,), {"_safe_check": False, "_safe_proxy_ip": address}
            )
            try:
                return self.do_open(pinned, req, **kwargs)
            except urllib.error.URLError as exc:
                # IP 목적지를 거절하는 프록시에서는 호스트 이름으로 한 번 더 보낸다.
                if "Tunnel connection failed" not in str(exc.reason):
                    raise
                logging.info("프록시가 IP 목적지 연결을 거절해 호스트 이름으로 다시 시도합니다: %s", exc.reason)
        connection = type("RequestHTTPSConnection", (_SafeHTTPSConnection,), {"_safe_check": not proxied})
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
        _parsed, _host, _port, address = _parse_http_url(newurl, self.allowed_schemes, allow_local=False)
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            redirected._safe_redirect_count = count
            redirected._safe_destination_ip = address
        return redirected


def safe_urlopen(request_or_url, *, timeout, max_redirects=5, allowed_schemes=("http", "https")):
    request = request_or_url if isinstance(request_or_url, urllib.request.Request) else urllib.request.Request(request_or_url)
    if not request.has_header("Accept-encoding"):
        request.add_header("Accept-encoding", "identity")
    _parsed, _host, _port, address = _parse_http_url(request.full_url, allowed_schemes, allow_local=False)
    request._safe_destination_ip = address
    opener = urllib.request.build_opener(
        _SafeHTTPHandler(),
        _SafeHTTPSHandler(),
        _SafeRedirectHandler(max_redirects, allowed_schemes),
    )
    return opener.open(request, timeout=timeout)


_COMPRESSED_INPUT_SLACK = 64 * 1024


def read_limited(response, max_bytes: int) -> bytes:
    encoding = getattr(response, "headers", {}).get("Content-Encoding", "").strip().lower()
    if encoding not in {"gzip", "deflate"}:
        data = response.read(max_bytes + 1)
        response._safe_network_truncated = len(data) > max_bytes
        return data[:max_bytes]

    wbits = 31 if encoding == "gzip" else zlib.MAX_WBITS
    decoder = zlib.decompressobj(wbits)
    output = bytearray()
    truncated = False
    # 압축 입력에도 상한을 둔다. 출력이 늘지 않는 빈 멤버가 끝없이 이어질 수 있기 때문이다.
    # 압축 헤더나 압축되지 않는 본문 때문에 입력이 출력보다 조금 클 수 있어 여유를 둔다.
    input_limit = max_bytes + _COMPRESSED_INPUT_SLACK
    input_size = 0
    first_chunk = True
    while True:
        chunk = response.read(min(64 * 1024, input_limit - input_size + 1))
        if not chunk:
            break
        input_size += len(chunk)
        if input_size > input_limit:
            chunk = chunk[:input_limit - (input_size - len(chunk))]
            input_size = input_limit
            truncated = True
        pending = chunk
        while pending:
            if decoder.eof:
                if encoding != "gzip":
                    raise ValueError("압축 응답 뒤에 잘못된 데이터가 있습니다.")
                decoder = zlib.decompressobj(wbits)
            try:
                decoded = decoder.decompress(pending, max_bytes + 1 - len(output))
            except zlib.error as exc:
                if encoding == "deflate" and first_chunk and not output:
                    decoder = zlib.decompressobj(-zlib.MAX_WBITS)
                    try:
                        decoded = decoder.decompress(pending, max_bytes + 1 - len(output))
                    except zlib.error as raw_exc:
                        raise ValueError("압축 응답을 해제할 수 없습니다.") from raw_exc
                else:
                    raise ValueError("압축 응답을 해제할 수 없습니다.") from exc
            output.extend(decoded)
            if len(output) > max_bytes:
                truncated = True
                break
            first_chunk = False
            pending = decoder.unused_data if decoder.eof else decoder.unconsumed_tail
        if truncated:
            break
    if not truncated and input_size and not decoder.eof:
        raise ValueError("압축 응답이 끝나기 전에 스트림이 종료되었습니다.")
    response._safe_network_truncated = truncated
    return bytes(output[:max_bytes])
