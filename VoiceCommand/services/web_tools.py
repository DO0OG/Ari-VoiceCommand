"""
웹 도구 모음 (Web Tools) — Phase 2.1 고도화
인터넷 검색, 페이지 조회 및 Selenium 기반의 스마트 브라우저 워크플로우를 제공합니다.
"""
import html
import logging
import os
import json
import re
import time
import urllib.parse
import urllib.request
import warnings
from typing import Optional, List, Dict, Any

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

# ── DuckDuckGo 검색 및 단순 Fetch ─────────────────────────────────────────────

def web_search(query: str, max_results: int = 5) -> str:
    """인터넷 검색 후 결과를 텍스트로 반환합니다."""
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        if not results: return "검색 결과가 없습니다."
        
        lines = []
        for i, r in enumerate(results, 1):
            lines.append(f"[{i}] {r.get('title', '제목 없음')}")
            lines.append(f"    {r.get('body', '')[:200]}")
            lines.append(f"    URL: {r.get('href', '')}")
        return "\n".join(lines)
    except Exception as e:
        logging.error(f"[WebTools] 검색 오류: {e}")
        return f"검색 중 오류 발생: {e}"

def web_fetch(url: str, max_chars: int = 3000) -> str:
    """URL의 본문 텍스트를 추출합니다."""
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return f"허용되지 않은 URL 스킴: {parsed.scheme or 'unknown'}"
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        
        # 스크립트, 스타일, 태그 제거
        text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', raw, flags=re.DOTALL | re.I)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = html.unescape(text)
        return re.sub(r'\s+', ' ', text).strip()[:max_chars]
    except Exception as e:
        return f"페이지 로드 실패: {e}"

# ── Selenium 스마트 브라우저 (Phase 2.1) ───────────────────────────────────────

class SmartBrowser:
    """상태 인식 및 셀렉터 전략을 지원하는 지능형 브라우저 제어기."""
    
    def __init__(self, headless: bool = False, download_dir: Optional[str] = None):
        self.driver = None
        self.headless = headless
        self.download_dir = download_dir or os.path.join(os.path.expanduser("~"), "Downloads")
        self._selector_history: Dict[str, Dict[str, str]] = self._load_selector_history()
        self._action_plan_history: Dict[str, Dict[str, List[Dict[str, Any]]]] = self._load_action_plan_history()
        self._last_action_summary = ""

    def _ensure_driver(self):
        if self.driver: return
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.chrome.service import Service
            from webdriver_manager.chrome import ChromeDriverManager
            
            opts = Options()
            if self.headless: opts.add_argument("--headless=new")
            opts.add_experimental_option("prefs", {"download.default_directory": self.download_dir})
            
            self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)
        except Exception as e:
            logging.error(f"[SmartBrowser] 드라이버 초기화 실패: {e}")
            raise

    def navigate_and_action(self, url: str, actions: List[Dict[str, Any]], goal_hint: str = "") -> str:
        """지정된 URL로 이동하여 일련의 작업을 수행합니다.
        actions 예: [{"type": "click", "selectors": ["#login", ".btn-submit"]}, {"type": "type", "text": "...", "selectors": ["input[name='q']"]}]
        """
        self._ensure_driver()
        self.driver.get(url)
        
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        results = []
        wait = WebDriverWait(self.driver, 15)

        current_domain = urllib.parse.urlparse(url).netloc or "global"
        page_key = self._page_key(url)
        plan_key = self._normalize_plan_key(goal_hint)
        if not actions and plan_key:
            remembered_actions = self.get_action_plan(current_domain, plan_key, page_key=page_key)
            if remembered_actions:
                actions = remembered_actions

        for action in actions:
            try:
                results.append(self._execute_browser_action(action, current_domain, wait, By, EC))
            except Exception as e:
                act_type = action.get("type")
                results.append(f"오류: {act_type} ({str(e)[:50]})")

        self._last_action_summary = " | ".join(results)
        if plan_key and actions and self._should_remember_action_plan(results):
            self.remember_action_plan(current_domain, plan_key, actions, page_key=page_key)
        return self._last_action_summary

    def _execute_browser_action(self, action: Dict[str, Any], current_domain: str, wait, by_module, ec_module) -> str:
        act_type = action.get("type")
        action_key = action.get("key") or action.get("name") or act_type or "action"

        if act_type == "download_wait":
            downloaded = self.wait_for_download(timeout=float(action.get("timeout", 30.0)))
            return f"다운로드 완료: {downloaded}"
        if act_type == "wait_url":
            fragment = str(action.get("contains", "")).strip()
            matched = self._wait_for_url_contains(fragment, timeout=float(action.get("timeout", 15.0)))
            return f"성공: wait_url({matched})" if matched else f"실패: wait_url({fragment})"
        if act_type == "wait_title":
            fragment = str(action.get("contains", "")).strip()
            matched = self._wait_for_title_contains(fragment, timeout=float(action.get("timeout", 15.0)))
            return f"성공: wait_title({matched})" if matched else f"실패: wait_title({fragment})"
        if act_type == "read_title":
            return f"제목: {getattr(self.driver, 'title', '')[:120]}"
        if act_type == "read_url":
            return f"URL: {getattr(self.driver, 'current_url', '')[:200]}"
        if act_type == "read_links":
            selector = action.get("selector", "a")
            links = self.driver.find_elements(by_module.CSS_SELECTOR, selector)
            hrefs = [link.get_attribute("href") for link in links[: int(action.get("limit", 5))]]
            return "링크: " + ", ".join([href for href in hrefs if href])
        if act_type == "wait_selector":
            _, matched_selector = self._find_element_for_action(action, current_domain, action_key, wait, by_module, ec_module)
            return f"성공: wait_selector({matched_selector})" if matched_selector else "실패: wait_selector"

        found_el, matched_selector = self._find_element_for_action(action, current_domain, action_key, wait, by_module, ec_module)
        if not found_el:
            return f"실패: {act_type} (셀렉터를 찾을 수 없음)"

        if act_type == "click":
            wait.until(ec_module.element_to_be_clickable((by_module.CSS_SELECTOR, matched_selector))).click()
            return "성공: click"
        if act_type == "click_text":
            found_el.click()
            return "성공: click_text"
        if act_type == "type":
            found_el.clear()
            found_el.send_keys(action.get("text", ""))
            return "성공: type"
        if act_type == "wait":
            wait.until(ec_module.presence_of_element_located((by_module.CSS_SELECTOR, matched_selector)))
            return "성공: wait"
        if act_type == "read":
            return f"읽기: {found_el.text[:120]}"
        return f"건너뜀: {act_type or 'unknown'}"

    def _find_element_for_action(self, action: Dict[str, Any], current_domain: str, action_key: str, wait, by_module, ec_module):
        selectors = self._ordered_selectors(current_domain, action_key, action.get("selectors", []))
        found_el = None
        matched_selector = ""
        for sel in selectors:
            try:
                found_el = wait.until(ec_module.presence_of_element_located((by_module.CSS_SELECTOR, sel)))
                if found_el:
                    matched_selector = sel
                    self._remember_selector(current_domain, action_key, sel)
                    break
            except Exception as exc:
                logging.debug(f"[SmartBrowser] 셀렉터 실패: {sel} ({exc})")
        return found_el, matched_selector

    def _wait_for_url_contains(self, fragment: str, timeout: float = 15.0) -> str:
        target = (fragment or "").strip().lower()
        if not self.driver or not target:
            return ""
        end = time.time() + timeout
        while time.time() < end:
            current_url = str(getattr(self.driver, "current_url", "") or "")
            if target in current_url.lower():
                return current_url
            time.sleep(0.3)
        return ""

    def _wait_for_title_contains(self, fragment: str, timeout: float = 15.0) -> str:
        target = (fragment or "").strip().lower()
        if not self.driver or not target:
            return ""
        end = time.time() + timeout
        while time.time() < end:
            title = str(getattr(self.driver, "title", "") or "")
            if target in title.lower():
                return title
            time.sleep(0.3)
        return ""

    def login_and_run(self, url: str, login_action: Dict[str, Any], followup_actions: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """로그인 후 반복 작업을 이어서 수행합니다."""
        actions = [login_action]
        if followup_actions:
            actions.extend(followup_actions)
        summary = self.navigate_and_action(url, actions)
        state = self.get_state()
        return {"summary": summary, "state": state}

    def get_state(self) -> Dict[str, Any]:
        """현재 브라우저 상태를 요약합니다."""
        if not self.driver:
            return {
                "ready": False,
                "current_url": "",
                "title": "",
            "download_dir": self.download_dir,
            "page_fingerprint": "",
            "selector_strategies": self._selector_history,
            "action_plan_strategies": self._action_plan_history,
            "last_action_summary": self._last_action_summary,
        }

        current_url = getattr(self.driver, "current_url", "")
        return {
            "ready": True,
            "current_url": current_url,
            "title": getattr(self.driver, "title", ""),
            "download_dir": self.download_dir,
            "page_fingerprint": self._page_key(current_url),
            "selector_strategies": self._selector_history,
            "action_plan_strategies": self._action_plan_history,
            "last_action_summary": self._last_action_summary,
        }

    def wait_for_download(self, timeout: float = 30.0, stable_seconds: float = 1.5) -> str:
        """다운로드 완료 파일을 감지해 경로를 반환합니다."""
        end = time.time() + timeout
        last_seen: Dict[str, tuple[int, float]] = {}
        while time.time() < end:
            try:
                entries = [
                    os.path.join(self.download_dir, name)
                    for name in os.listdir(self.download_dir)
                ]
            except FileNotFoundError:
                entries = []

            for path in entries:
                if not os.path.isfile(path):
                    continue
                name = os.path.basename(path).lower()
                if name.endswith((".crdownload", ".part", ".tmp")):
                    continue
                size = os.path.getsize(path)
                prev = last_seen.get(path)
                now = time.time()
                if prev and prev[0] == size and now - prev[1] >= stable_seconds:
                    return path
                last_seen[path] = (size, now)
            time.sleep(0.5)
        raise TimeoutError("다운로드 완료 파일을 찾지 못했습니다.")

    def _ordered_selectors(self, domain: str, action_key: str, selectors: List[str]) -> List[str]:
        remembered = self._selector_history.get(domain, {}).get(action_key)
        if remembered:
            return [remembered, *[sel for sel in selectors if sel != remembered]]
        return selectors

    def _remember_selector(self, domain: str, action_key: str, selector: str) -> None:
        self._selector_history.setdefault(domain, {})[action_key] = selector
        self._save_selector_history()

    def _selector_history_path(self) -> str:
        try:
            from core.resource_manager import ResourceManager
            return ResourceManager.get_writable_path("browser_selector_history.json")
        except Exception:
            return os.path.join(os.path.dirname(__file__), "browser_selector_history.json")

    def _action_plan_history_path(self) -> str:
        try:
            from core.resource_manager import ResourceManager
            return ResourceManager.get_writable_path("browser_action_plans.json")
        except Exception:
            return os.path.join(os.path.dirname(__file__), "browser_action_plans.json")

    def _load_selector_history(self) -> Dict[str, Dict[str, str]]:
        path = self._selector_history_path()
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                return {
                    str(domain): {str(k): str(v) for k, v in (mapping or {}).items()}
                    for domain, mapping in data.items()
                }
        except Exception as e:
            logging.warning(f"[SmartBrowser] 셀렉터 히스토리 로드 실패: {e}")
        return {}

    def _save_selector_history(self) -> None:
        path = self._selector_history_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(self._selector_history, handle, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.warning(f"[SmartBrowser] 셀렉터 히스토리 저장 실패: {e}")

    def _load_action_plan_history(self) -> Dict[str, Dict[str, List[Dict[str, Any]]]]:
        path = self._action_plan_history_path()
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                normalized: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
                for domain, mapping in data.items():
                    if not isinstance(mapping, dict):
                        continue
                    normalized[str(domain)] = {}
                    for key, actions in mapping.items():
                        if isinstance(actions, list):
                            normalized[str(domain)][str(key)] = [action for action in actions if isinstance(action, dict)]
                return normalized
        except Exception as e:
            logging.warning(f"[SmartBrowser] 액션 플랜 로드 실패: {e}")
        return {}

    def _save_action_plan_history(self) -> None:
        path = self._action_plan_history_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(self._action_plan_history, handle, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.warning(f"[SmartBrowser] 액션 플랜 저장 실패: {e}")

    def _normalize_plan_key(self, goal_hint: str) -> str:
        key = re.sub(r"\s+", " ", (goal_hint or "").strip().lower())
        return re.sub(r"[^a-z0-9가-힣 _-]", "", key)[:80]

    def _should_remember_action_plan(self, results: List[str]) -> bool:
        return (
            bool(results)
            and any(item.startswith("성공:") or item.startswith("다운로드 완료:") for item in results)
            and not any(item.startswith(("실패:", "오류:")) for item in results)
        )

    def _tokenize_plan_key(self, key: str) -> set[str]:
        tokens = set()
        for token in re.findall(r"[a-z0-9가-힣]+", (key or "").lower()):
            normalized = self._normalize_similarity_token(token)
            if len(normalized) >= 2:
                tokens.add(normalized)
        return tokens

    def _normalize_similarity_token(self, token: str) -> str:
        normalized = token.strip().lower()
        for suffix in ("에서", "에게", "으로", "로", "까지", "부터", "하고", "후", "전", "에", "을", "를", "은", "는", "이", "가", "와", "과", "도", "만"):
            if normalized.endswith(suffix) and len(normalized) > len(suffix) + 1:
                return normalized[: -len(suffix)]
        return normalized

    def _token_overlap_score(self, left: set[str], right: set[str]) -> float:
        if not left or not right:
            return 0.0
        overlap = 0
        for token in left:
            if any(token == candidate or token in candidate or candidate in token for candidate in right):
                overlap += 1
        return overlap / max(len(left), len(right))

    def _find_similar_plan_key(self, domain: str, goal_hint: str) -> str:
        plan_key = self._normalize_plan_key(goal_hint)
        if not domain or not plan_key:
            return ""
        domain_plans = self._action_plan_history.get(domain, {})
        if plan_key in domain_plans:
            return plan_key

        target_tokens = self._tokenize_plan_key(plan_key)
        best_key = ""
        best_score = 0.0
        for candidate in domain_plans:
            candidate_tokens = self._tokenize_plan_key(candidate)
            if not target_tokens or not candidate_tokens:
                continue
            score = self._token_overlap_score(target_tokens, candidate_tokens)
            if score > best_score:
                best_score = score
                best_key = candidate
        return best_key if best_score >= 0.34 else ""

    def remember_action_plan(self, domain: str, goal_hint: str, actions: List[Dict[str, Any]], page_key: str = "") -> None:
        plan_key = self._normalize_plan_key(goal_hint)
        if not domain or not plan_key or not actions:
            return
        cleaned_actions = [{str(k): v for k, v in action.items()} for action in actions if isinstance(action, dict)]
        if not cleaned_actions:
            return
        domain_bucket = self._action_plan_history.setdefault(domain, {})
        domain_bucket[plan_key] = cleaned_actions
        if page_key:
            domain_bucket[f"{page_key}::{plan_key}"] = cleaned_actions
        self._save_action_plan_history()

    def get_action_plan(self, domain: str, goal_hint: str, page_key: str = "") -> List[Dict[str, Any]]:
        plan_key = self._normalize_plan_key(goal_hint)
        if not domain or not plan_key:
            return []
        domain_plans = self._action_plan_history.get(domain, {})
        if page_key:
            page_plan_key = f"{page_key}::{plan_key}"
            remembered = domain_plans.get(page_plan_key)
            if remembered:
                return list(remembered)
        remembered = domain_plans.get(plan_key)
        if remembered:
            return list(remembered)
        similar_key = self._find_similar_plan_key(domain, goal_hint)
        if similar_key:
            return list(domain_plans.get(similar_key, []))
        return []

    def _page_key(self, url: str) -> str:
        parsed = urllib.parse.urlparse(url or "")
        domain = parsed.netloc.lower()
        path = parsed.path.strip("/").lower()
        if not domain:
            return ""
        if not path:
            return domain
        head = path.split("/", 1)[0]
        return f"{domain}|{head}"

    def close(self):
        if self.driver:
            self.driver.quit()
            self.driver = None

# 싱글톤 브라우저 (필요 시 사용)
_browser_instance: Optional[SmartBrowser] = None

def get_smart_browser(headless=False) -> SmartBrowser:
    global _browser_instance
    if _browser_instance is None:
        _browser_instance = SmartBrowser(headless=headless)
    return _browser_instance
