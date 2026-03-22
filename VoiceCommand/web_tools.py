"""
웹 도구 모음 (Web Tools)
인터넷 검색 및 웹 페이지 내용 조회 기능을 제공합니다.

web_search: duckduckgo_search 라이브러리 사용 (선택적 의존성)
            미설치 시: pip install duckduckgo-search
web_fetch:  표준 라이브러리(urllib)만 사용
"""
import html
import logging
import re
import urllib.parse
import urllib.request
import warnings
from typing import Optional

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}
_RE_SCRIPT  = re.compile(r'<script[^>]*>.*?</script>', re.DOTALL | re.I)
_RE_STYLE   = re.compile(r'<style[^>]*>.*?</style>',  re.DOTALL | re.I)
_RE_TAG     = re.compile(r'<[^>]+>')
_RE_SPACES  = re.compile(r'\s+')
_RE_RESULT_LINK = re.compile(
    r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_RE_RESULT_SNIPPET = re.compile(
    r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(?P<snippet>.*?)</a>|'
    r'<div[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(?P<snippet_div>.*?)</div>',
    re.IGNORECASE | re.DOTALL,
)


def web_search(query: str, max_results: int = 5, num_results: Optional[int] = None) -> str:
    """
    DuckDuckGo를 통해 인터넷 검색 후 결과 반환.
    duckduckgo_search 미설치 시 HTML 검색 폴백을 사용합니다.
    """
    limit = int(num_results or max_results or 5)
    try:
        try:
            from ddgs import DDGS
        except ImportError:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                from duckduckgo_search import DDGS
    except ImportError:
        return _web_search_html_fallback(query, limit)

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=limit))
        if not results:
            return _web_search_html_fallback(query, limit)
        return _format_search_results(results)
    except Exception as e:
        logging.error(f"[WebTools] 검색 오류: {e}")
        fallback = _web_search_html_fallback(query, limit)
        if fallback.startswith("검색 오류:"):
            return f"검색 오류: {e}"
        return fallback


def web_fetch(url: str, max_chars: int = 3000) -> str:
    """
    URL의 HTML을 가져와 텍스트만 추출 후 반환.
    script/style 제거, HTML 태그 제거, 공백 정리 적용.
    """
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")

        # 불필요한 요소 제거
        text = _RE_SCRIPT.sub(" ", raw)
        text = _RE_STYLE.sub(" ", text)
        text = _RE_TAG.sub(" ", text)
        text = html.unescape(text)
        text = _RE_SPACES.sub(" ", text).strip()
        return text[:max_chars]

    except Exception as e:
        logging.error(f"[WebTools] fetch 오류 ({url}): {e}")
        return f"페이지 로드 오류: {e}"


def _clean_html_text(value: str) -> str:
    cleaned = _RE_TAG.sub(" ", value or "")
    cleaned = html.unescape(cleaned)
    return _RE_SPACES.sub(" ", cleaned).strip()


def _resolve_duckduckgo_href(href: str) -> str:
    href = html.unescape(href or "").strip()
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/l/?") or href.startswith("https://duckduckgo.com/l/?"):
        parsed = urllib.parse.urlparse(href if href.startswith("http") else "https://duckduckgo.com" + href)
        qs = urllib.parse.parse_qs(parsed.query)
        uddg = qs.get("uddg", [""])[0]
        return urllib.parse.unquote(uddg) if uddg else href
    return href


def _format_search_results(results: list) -> str:
    if not results:
        return "검색 결과가 없습니다."
    lines = []
    for i, r in enumerate(results, 1):
        title = (r.get("title") or "제목 없음").strip()
        body = (r.get("body") or "")[:200].strip()
        url = (r.get("href") or "").strip()
        lines.append(f"[{i}] {title}")
        if body:
            lines.append(f"    {body}")
        if url:
            lines.append(f"    URL: {url}")
    return "\n".join(lines)


def _web_search_html_fallback(query: str, max_results: int = 5) -> str:
    """의존성 없이 DuckDuckGo HTML 결과 페이지를 파싱하는 폴백."""
    try:
        encoded = urllib.parse.urlencode({"q": query})
        url = f"https://html.duckduckgo.com/html/?{encoded}"
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")

        links = list(_RE_RESULT_LINK.finditer(raw))
        snippets = list(_RE_RESULT_SNIPPET.finditer(raw))

        results = []
        for idx, match in enumerate(links[:max_results]):
            href = _resolve_duckduckgo_href(match.group("href"))
            title = _clean_html_text(match.group("title"))
            snippet = ""
            if idx < len(snippets):
                snippet = _clean_html_text(snippets[idx].group("snippet") or snippets[idx].group("snippet_div") or "")
            if title or href:
                results.append({"title": title or "제목 없음", "body": snippet, "href": href})

        if not results:
            return "검색 결과가 없습니다."
        logging.info(f"[WebTools] HTML 폴백 검색 사용: {query}")
        return _format_search_results(results)
    except Exception as e:
        logging.error(f"[WebTools] HTML 폴백 검색 오류: {e}")
        return f"검색 오류: {e}"
