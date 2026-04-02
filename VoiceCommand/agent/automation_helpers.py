"""
GUI / 브라우저 / 앱 자동화 공통 헬퍼 (Phase 2.1 고도화)
pyautogui, pyperclip, pygetwindow, selenium을 활용하여 강력한 자동화 환경을 제공합니다.
"""
import os
import ctypes
import time
import webbrowser
import logging
import json
import re
import shutil
from typing import Optional, List, Any

logger = logging.getLogger(__name__)

_APP_ALIAS_CANDIDATES = {
    "메모장": ("notepad",),
    "notepad": ("notepad",),
    "계산기": ("calc", "calculator"),
    "calculator": ("calc", "calculator"),
    "explorer": ("explorer",),
    "파일 탐색기": ("explorer",),
    "cmd": ("cmd",),
    "powershell": ("powershell", "pwsh"),
    "chrome": ("chrome",),
    "크롬": ("chrome",),
    "msedge": ("msedge", "edge"),
    "edge": ("msedge", "edge"),
    "엣지": ("msedge", "edge"),
    "code": ("code", "code-insiders"),
    "vscode": ("code", "code-insiders"),
    "visual studio code": ("code", "code-insiders"),
}


class AutomationHelpers:
    def __init__(self):
        self.desktop_path = os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), "Desktop")
        self._app_aliases = {key: tuple(values) for key, values in _APP_ALIAS_CANDIDATES.items()}
        self._window_target_history = self._load_window_target_history()
        self._desktop_workflow_history = self._load_desktop_workflow_history()

    # ── 앱 및 URL 제어 ─────────────────────────────────────────────────────────

    def open_url(self, url: str) -> str:
        """웹 브라우저로 URL을 엽니다."""
        self._shell_open(url)
        return url

    def open_path(self, path: str) -> str:
        """파일 탐색기 등으로 경로를 열거나 파일을 실행합니다."""
        normalized = os.path.abspath(path)
        if not os.path.exists(normalized):
            raise FileNotFoundError(f"열 경로를 찾지 못했습니다: {path}")
        self._shell_open(normalized)
        return path

    def launch_app(self, target: str) -> str:
        """이름 또는 경로로 앱을 실행합니다."""
        normalized = (target or "").strip().strip('"')
        if not normalized:
            raise ValueError("실행할 대상이 비어 있습니다.")

        if os.path.exists(normalized):
            self._shell_open(os.path.abspath(normalized))
            return target

        for candidate in self._iter_launch_candidates(normalized):
            resolved_exec = self._resolve_executable_target(candidate)
            launch_target = resolved_exec or candidate
            try:
                self._shell_open(launch_target)
                return target
            except OSError:
                continue

        raise FileNotFoundError(f"실행 가능한 앱을 찾지 못했습니다: {target}")

    def _resolve_executable_target(self, target: str) -> str:
        normalized = (target or "").strip().strip('"')
        if not normalized:
            return ""
        candidates = [normalized]
        if not normalized.lower().endswith(".exe"):
            candidates.append(f"{normalized}.exe")
        for candidate in candidates:
            found = shutil.which(candidate)
            if found:
                return found
        return ""

    def _iter_launch_candidates(self, target: str) -> List[str]:
        normalized = (target or "").strip().strip('"')
        lowered = normalized.lower()
        candidates: List[str] = []

        self._extend_unique(candidates, self._app_aliases.get(lowered, ()))
        if lowered not in self._app_aliases and normalized:
            self._extend_unique(candidates, (normalized,))

        for alias, alias_candidates in self._app_aliases.items():
            if not lowered or alias == lowered:
                continue
            if lowered in alias or alias in lowered:
                self._extend_unique(candidates, alias_candidates)

        return candidates

    @staticmethod
    def _extend_unique(target: List[str], values) -> None:
        for value in values:
            if value and value not in target:
                target.append(value)

    # ── 마우스 및 키보드 제어 ───────────────────────────────────────────────────

    def wait_seconds(self, seconds: float) -> float:
        """지정된 시간(초) 동안 대기합니다."""
        time.sleep(seconds)
        return seconds

    def click_screen(self, x: Optional[int] = None, y: Optional[int] = None, clicks: int = 1, button: str = "left") -> str:
        """화면의 특정 좌표 또는 현재 위치를 클릭합니다."""
        pg = self._get_pyautogui()
        if x is not None and y is not None:
            pg.click(x=x, y=y, clicks=clicks, button=button)
            return f"{x},{y}"
        pg.click(clicks=clicks, button=button)
        return "current_position"

    def click_image(self, image_path: str, confidence: float = 0.8) -> bool:
        """화면에서 이미지를 찾아 클릭합니다 (이미지 인식 기반)."""
        pg = self._get_pyautogui()
        try:
            # opencv-python 필요
            pos = pg.locateCenterOnScreen(image_path, confidence=confidence)
            if pos:
                pg.click(pos)
                return True
        except Exception as e:
            logger.warning(f"click_image 실패: {e}")
        return False

    def is_image_visible(self, image_path: str, confidence: float = 0.8) -> bool:
        """지정한 이미지가 현재 화면에 보이는지 읽기 전용으로 확인합니다."""
        pg = self._get_pyautogui()
        try:
            pos = pg.locateCenterOnScreen(image_path, confidence=confidence)
            return bool(pos)
        except Exception as e:
            logger.warning(f"is_image_visible 실패: {e}")
            return False

    def move_mouse(self, x: int, y: int, duration: float = 0.2) -> str:
        """마우스 커서를 이동합니다."""
        pg = self._get_pyautogui()
        pg.moveTo(x, y, duration=duration)
        return f"{x},{y}"

    def type_text(self, text: str, interval: float = 0.01, use_clipboard: bool = True) -> str:
        """텍스트를 입력합니다. 한글 대응을 위해 기본적으로 클립보드를 사용합니다."""
        pg = self._get_pyautogui()
        if use_clipboard:
            try:
                self.write_clipboard(text)
                pg.hotkey("ctrl", "v")
                return text
            except Exception:
                use_clipboard = False
        pg.write(text, interval=interval)
        return text

    def press_keys(self, *keys: str) -> str:
        """하나 이상의 키를 순서대로 누릅니다."""
        pg = self._get_pyautogui()
        for key in keys:
            pg.press(key)
        return ",".join(keys)

    def hotkey(self, *keys: str) -> str:
        """조합 키를 누릅니다 (예: 'ctrl', 'c')."""
        pg = self._get_pyautogui()
        pg.hotkey(*keys)
        return ",".join(keys)

    # ── 창 제어 ───────────────────────────────────────────────────────────────

    def get_active_window_title(self) -> str:
        """현재 활성화된 창의 제목을 가져옵니다."""
        gw = self._get_pygetwindow()
        win = gw.getActiveWindow()
        return win.title if win else ""

    def list_open_windows(self, limit: int = 12) -> List[str]:
        """현재 열려 있는 창 제목 목록을 반환합니다."""
        gw = self._get_pygetwindow()
        titles: List[str] = []
        for win in gw.getAllWindows():
            title = (getattr(win, "title", "") or "").strip()
            if not title or title in titles:
                continue
            titles.append(title)
            if len(titles) >= limit:
                break
        return titles

    def find_window(self, title_substring: str) -> Optional[Any]:
        """제목에 특정 문자열이 포함된 창 객체를 찾습니다."""
        gw = self._get_pygetwindow()
        titles = gw.getWindowsWithTitle(title_substring)
        return titles[0] if titles else None

    def find_windows(self, title_substring: str, limit: int = 5) -> List[Any]:
        """제목에 특정 문자열이 포함된 창 목록을 반환합니다."""
        gw = self._get_pygetwindow()
        return list(gw.getWindowsWithTitle(title_substring))[:limit]

    def get_window_state(self, title_substring: str) -> dict:
        """창 존재 여부, 개수, 대표 제목을 반환합니다."""
        windows = self.find_windows(title_substring)
        titles = [(getattr(win, "title", "") or "").strip() for win in windows]
        titles = [title for title in titles if title]
        return {
            "query": title_substring,
            "count": len(titles),
            "titles": titles,
            "exists": bool(titles),
            "active_window_title": self.get_active_window_title(),
        }

    def focus_window(self, title_substring: str, goal_hint: str = "") -> bool:
        """특정 창을 찾아 활성화(포커스)합니다."""
        target = self.resolve_window_target(goal_hint, title_substring)
        win = self.find_window(target)
        if win:
            try:
                if win.isMinimized:
                    win.restore()
                win.activate()
                self.remember_window_target(goal_hint or title_substring, win.title)
                return True
            except Exception:
                return False
        return False

    def wait_for_window(self, title_substring: str, timeout: float = 10.0, goal_hint: str = "") -> str:
        """특정 창이 나타날 때까지 대기합니다."""
        end = time.time() + timeout
        target = self.resolve_window_target(goal_hint, title_substring)
        while time.time() < end:
            win = self.find_window(target)
            if win:
                self.remember_window_target(goal_hint or title_substring, win.title)
                return win.title
            time.sleep(0.5)
        raise TimeoutError(f"창을 찾지 못했습니다: {target}")

    def wait_for_window_state(self, title_substring: str, minimum_count: int = 1, timeout: float = 10.0) -> dict:
        """특정 창이 원하는 개수 이상 나타날 때까지 대기합니다."""
        end = time.time() + timeout
        while time.time() < end:
            state = self.get_window_state(title_substring)
            if state["count"] >= minimum_count:
                return state
            time.sleep(0.5)
        raise TimeoutError(f"창 상태를 만족하지 못했습니다: {title_substring} >= {minimum_count}")

    # ── 클립보드 및 기타 ────────────────────────────────────────────────────────

    def write_clipboard(self, text: str) -> str:
        pc = self._get_pyperclip()
        pc.copy(text)
        return text

    def read_clipboard(self) -> str:
        pc = self._get_pyperclip()
        return pc.paste()

    def screenshot(self, path: Optional[str] = None) -> str:
        pg = self._get_pyautogui()
        if not path:
            folder = os.path.join(self.desktop_path, "screenshots")
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, f"screenshot_{int(time.time())}.png")
        pg.screenshot(path)
        return path

    # ── 브라우저 전용 (Selenium) ───────────────────────────────────────────────

    def browser_login(
        self,
        url: str,
        username: str,
        password: str,
        username_selector: str = "input[type='email'],input[name='email'],input[name='username'],input[type='text']",
        password_selector: Optional[str] = None,
        submit_selector: str = "button[type='submit'],input[type='submit']",
        headless: bool = False,
    ) -> str:
        """브라우저를 열어 로그인을 시도합니다."""
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            from webdriver_manager.chrome import ChromeDriverManager
            from selenium.webdriver.chrome.service import Service
        except ImportError as e:
            raise RuntimeError("selenium / webdriver-manager가 설치되어야 합니다.") from e

        options = Options()
        if headless:
            options.add_argument("--headless=new")
        options.add_argument("--disable-blink-features=AutomationControlled")
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        
        try:
            driver.get(url)
            wait = WebDriverWait(driver, 20)
            password_selector = password_selector or "input[type='password']"
            
            user_el = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, username_selector)))
            user_el.clear()
            user_el.send_keys(username)

            pass_el = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, password_selector)))
            pass_el.clear()
            pass_el.send_keys(password)

            if submit_selector:
                submit_el = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, submit_selector)))
                submit_el.click()
                time.sleep(2)  # 로그인 처리 대기

            return driver.current_url
        finally:
            if headless:
                driver.quit()

    def get_browser_state(self) -> dict:
        """공유 스마트 브라우저의 현재 상태를 읽기 전용으로 반환합니다."""
        try:
            from services.web_tools import get_smart_browser
        except Exception:
            from services.web_tools import get_smart_browser
        return get_smart_browser().get_state()

    def get_browser_current_url(self) -> str:
        state = self.get_browser_state()
        return str(state.get("current_url", ""))

    def get_learned_strategies(self, goal_hint: str = "", domain: str = "") -> dict:
        """현재까지 축적된 브라우저/데스크톱 전략을 읽기 전용으로 반환합니다."""
        normalized_goal = self._normalize_goal_hint(goal_hint)
        browser_state = self.get_browser_state()
        browser_plans = browser_state.get("action_plan_strategies", {}) if isinstance(browser_state, dict) else {}
        resolved_domain = (domain or "").strip().lower()

        if not resolved_domain and browser_state:
            current_url = str(browser_state.get("current_url", "") or "")
            if current_url:
                resolved_domain = current_url.split("//", 1)[-1].split("/", 1)[0].lower()

        browser_actions = []
        browser_plan_key = ""
        if resolved_domain and isinstance(browser_plans, dict):
            domain_plans = browser_plans.get(resolved_domain, {}) or {}
            if normalized_goal:
                browser_plan_key = self._find_similar_goal_key(normalized_goal, domain_plans)
            elif domain_plans:
                browser_plan_key = next(iter(domain_plans))
            if browser_plan_key:
                browser_actions = list(domain_plans.get(browser_plan_key, []))

        window_key = self._find_similar_goal_key(normalized_goal, self._window_target_history) if normalized_goal else ""
        workflow_key = self._find_similar_goal_key(normalized_goal, self._desktop_workflow_history) if normalized_goal else ""

        return {
            "goal_hint": goal_hint,
            "resolved_domain": resolved_domain,
            "browser_plan_key": browser_plan_key,
            "browser_actions": browser_actions,
            "window_target_key": window_key,
            "window_target": self._window_target_history.get(window_key, "") if window_key else "",
            "desktop_workflow_key": workflow_key,
            "desktop_workflow_actions": list(self._desktop_workflow_history.get(workflow_key, [])) if workflow_key else [],
        }

    def get_learned_strategy_summary(self, goal_hint: str = "", domain: str = "") -> str:
        """LLM이 바로 참고하기 쉬운 학습 전략 요약 문자열을 반환합니다."""
        learned = self.get_learned_strategies(goal_hint=goal_hint, domain=domain)
        lines: List[str] = []
        if learned.get("resolved_domain"):
            lines.append(f"domain={learned['resolved_domain']}")
        if learned.get("browser_plan_key"):
            browser_actions = learned.get("browser_actions", [])
            lines.append(f"browser_plan={learned['browser_plan_key']} ({len(browser_actions)} actions)")
        if learned.get("window_target"):
            lines.append(f"window_target={learned['window_target']}")
        if learned.get("desktop_workflow_key"):
            workflow_actions = learned.get("desktop_workflow_actions", [])
            lines.append(f"desktop_workflow={learned['desktop_workflow_key']} ({len(workflow_actions)} actions)")
        return " | ".join(lines)

    def get_planning_snapshot(self, goal_hint: str = "", domain: str = "") -> dict:
        """플래너와 self-fix가 바로 참고할 수 있는 현재 상태 + 학습 전략 스냅샷."""
        browser_state = self.get_browser_state()
        active_window = ""
        open_windows: List[str] = []
        try:
            active_window = self.get_active_window_title()
        except Exception:
            active_window = ""
        try:
            open_windows = self.list_open_windows()
        except Exception:
            open_windows = []
        learned = self.get_learned_strategies(goal_hint=goal_hint, domain=domain)
        execution_policy = self.get_execution_policy(goal_hint=goal_hint, domain=domain)
        return {
            "goal_hint": goal_hint,
            "active_window_title": active_window,
            "open_window_titles": open_windows[:6],
            "browser_current_url": str(browser_state.get("current_url", "") or ""),
            "browser_title": str(browser_state.get("title", "") or ""),
            "browser_last_action_summary": str(browser_state.get("last_action_summary", "") or ""),
            "learned_strategy_summary": self.get_learned_strategy_summary(goal_hint=goal_hint, domain=domain),
            "learned_strategies": learned,
            "execution_policy": execution_policy,
            "execution_policy_summary": self.get_execution_policy_summary(goal_hint=goal_hint, domain=domain),
        }

    def get_planning_snapshot_summary(self, goal_hint: str = "", domain: str = "") -> str:
        snapshot = self.get_planning_snapshot(goal_hint=goal_hint, domain=domain)
        lines: List[str] = []
        if snapshot.get("active_window_title"):
            lines.append(f"active_window={snapshot['active_window_title']}")
        open_windows = snapshot.get("open_window_titles") or []
        if open_windows:
            lines.append(f"open_windows={', '.join(open_windows[:3])}")
        if snapshot.get("browser_title"):
            lines.append(f"browser_title={snapshot['browser_title']}")
        if snapshot.get("browser_current_url"):
            lines.append(f"browser_url={snapshot['browser_current_url']}")
        if snapshot.get("browser_last_action_summary"):
            lines.append(f"browser_last={snapshot['browser_last_action_summary']}")
        if snapshot.get("learned_strategy_summary"):
            lines.append(f"learned={snapshot['learned_strategy_summary']}")
        if snapshot.get("execution_policy_summary"):
            lines.append(f"policy={snapshot['execution_policy_summary']}")
        return " | ".join(lines)

    def get_desktop_state(self) -> dict:
        """현재 데스크톱/브라우저/창 상태를 한 번에 요약합니다."""
        active_window = ""
        open_windows: List[str] = []
        browser_state = {}
        try:
            active_window = self.get_active_window_title()
        except Exception:
            active_window = ""
        try:
            open_windows = self.list_open_windows()
        except Exception:
            open_windows = []
        try:
            browser_state = self.get_browser_state()
        except Exception:
            browser_state = {}
        return {
            "active_window_title": active_window,
            "open_window_titles": open_windows,
            "browser_state": browser_state,
            "desktop_sample_paths": self._sample_directory_entries(self.desktop_path),
            "window_state_samples": {
                title: self.get_window_state(title)
                for title in open_windows[:3]
            },
            "window_target_history": self._window_target_history,
            "desktop_workflow_history": self._desktop_workflow_history,
            "learned_strategies": self.get_learned_strategies(),
            "learned_strategy_summary": self.get_learned_strategy_summary(),
            "planning_snapshot": self.get_planning_snapshot(),
            "planning_snapshot_summary": self.get_planning_snapshot_summary(),
            "execution_policy": self.get_execution_policy(),
            "execution_policy_summary": self.get_execution_policy_summary(),
        }

    def get_execution_policy(self, goal_hint: str = "", domain: str = "", expected_window: str = "") -> dict:
        browser_plans = self.build_resilient_browser_plans(
            url=f"https://{domain}" if domain and "://" not in domain else "",
            goal_hint=goal_hint,
            fallback_actions=[],
        ) if (goal_hint or domain) else []
        desktop_plans = self.build_resilient_desktop_plans(
            goal_hint=goal_hint,
            expected_window=expected_window,
            fallback_actions=[],
        ) if (goal_hint or expected_window) else []
        return {
            "goal_hint": goal_hint,
            "domain": domain,
            "expected_window": expected_window,
            "recommended_browser_plan": browser_plans[0] if browser_plans else None,
            "recommended_desktop_plan": desktop_plans[0] if desktop_plans else None,
        }

    def get_execution_policy_summary(self, goal_hint: str = "", domain: str = "", expected_window: str = "") -> str:
        policy = self.get_execution_policy(goal_hint=goal_hint, domain=domain, expected_window=expected_window)
        lines: List[str] = []
        browser_plan = policy.get("recommended_browser_plan") or {}
        desktop_plan = policy.get("recommended_desktop_plan") or {}
        if browser_plan:
            lines.append(
                f"browser={browser_plan.get('plan_type')} score={browser_plan.get('score')} reason={browser_plan.get('selection_reason','')}"
            )
        if desktop_plan:
            lines.append(
                f"desktop={desktop_plan.get('plan_type')} score={desktop_plan.get('score')} reason={desktop_plan.get('selection_reason','')}"
            )
        return " | ".join([line for line in lines if line][:2])

    def _sample_directory_entries(self, directory: str, limit: int = 8) -> List[str]:
        """상태 비교용으로 디렉터리 엔트리 일부만 가볍게 수집합니다."""
        normalized = os.path.abspath(directory or "")
        if not normalized or not os.path.isdir(normalized):
            return []
        try:
            entries = sorted(os.listdir(normalized))[:limit]
        except OSError:
            return []
        return [os.path.join(normalized, name) for name in entries]

    def wait_for_download(self, timeout: float = 30.0, stable_seconds: float = 1.5) -> str:
        """브라우저 다운로드 폴더에서 다운로드 완료 파일을 대기합니다."""
        try:
            from services.web_tools import get_smart_browser
        except Exception:
            from services.web_tools import get_smart_browser
        return get_smart_browser().wait_for_download(timeout=timeout, stable_seconds=stable_seconds)

    def suggest_browser_actions(self, goal_hint: str, domain: str = "") -> List[dict]:
        learned = self.get_learned_strategies(goal_hint=goal_hint, domain=domain)
        return list(learned.get("browser_actions", []))

    def build_adaptive_browser_plan(
        self,
        url: str,
        goal_hint: str,
        fallback_actions: Optional[List[dict]] = None,
    ) -> dict:
        normalized_url = (url or "").strip()
        domain = normalized_url.split("//", 1)[-1].split("/", 1)[0].lower() if normalized_url else ""
        learned_actions = self.suggest_browser_actions(goal_hint=goal_hint, domain=domain)
        merged_actions = self._merge_action_sequences(learned_actions, list(fallback_actions or []))
        browser_state = self.get_browser_state()
        merged_actions = self._augment_browser_plan_with_state(
            merged_actions,
            browser_state=browser_state,
            domain=domain,
        )
        return {
            "goal_hint": goal_hint,
            "domain": domain,
            "learned_actions": learned_actions,
            "fallback_actions": list(fallback_actions or []),
            "actions": merged_actions,
            "summary": self._describe_action_plan("browser", goal_hint, merged_actions, bool(learned_actions)),
        }

    def build_resilient_browser_plans(
        self,
        url: str,
        goal_hint: str,
        fallback_actions: Optional[List[dict]] = None,
    ) -> List[dict]:
        normalized_url = (url or "").strip()
        domain = normalized_url.split("//", 1)[-1].split("/", 1)[0].lower() if normalized_url else ""
        fallback_list = list(fallback_actions or [])
        learned_actions = self.suggest_browser_actions(goal_hint=goal_hint, domain=domain)
        browser_state = self.get_browser_state()
        plan_specs = [
            ("adaptive", self._merge_action_sequences(learned_actions, fallback_list), bool(learned_actions)),
            ("learned_only", list(learned_actions), bool(learned_actions)),
            ("fallback_only", fallback_list, False),
        ]
        plans: List[dict] = []
        for plan_type, raw_actions, reused in plan_specs:
            if not raw_actions:
                continue
            actions = self._augment_browser_plan_with_state(
                list(raw_actions),
                browser_state=browser_state,
                domain=domain,
            )
            if not actions:
                continue
            if any(existing["actions"] == actions for existing in plans):
                continue
            plan = {
                "plan_type": plan_type,
                "goal_hint": goal_hint,
                "domain": domain,
                "actions": actions,
                "summary": self._describe_action_plan(
                    f"browser:{plan_type}",
                    goal_hint,
                    actions,
                    reused,
                ),
            }
            plan["score"] = self._score_browser_plan(plan, browser_state=browser_state, requested_url=normalized_url)
            plan["selection_reason"] = self._describe_browser_plan_reason(plan, browser_state=browser_state, requested_url=normalized_url)
            plans.append(plan)
        return sorted(plans, key=self._plan_sort_key, reverse=True)

    def run_browser_actions(self, url: str, actions: list, headless: bool = False, goal_hint: str = "") -> dict:
        """공유 스마트 브라우저로 상태 인식 기반 액션 시퀀스를 수행합니다."""
        try:
            from services.web_tools import get_smart_browser
        except Exception:
            from services.web_tools import get_smart_browser
        browser = get_smart_browser(headless=headless)
        summary = browser.navigate_and_action(url, actions, goal_hint=goal_hint)
        return {"summary": summary, "state": browser.get_state()}

    def run_adaptive_browser_workflow(
        self,
        url: str,
        goal_hint: str,
        fallback_actions: Optional[List[dict]] = None,
        headless: bool = False,
    ) -> dict:
        """과거 성공 브라우저 전략을 우선 적용하고 없으면 fallback으로 실행."""
        plan = self.build_adaptive_browser_plan(url=url, goal_hint=goal_hint, fallback_actions=fallback_actions)
        result = self.run_browser_actions((url or "").strip(), actions=plan["actions"], headless=headless, goal_hint=goal_hint)
        result["adaptive_plan"] = plan
        return result

    def run_resilient_browser_workflow(
        self,
        url: str,
        goal_hint: str,
        fallback_actions: Optional[List[dict]] = None,
        headless: bool = False,
    ) -> dict:
        plans = self.build_resilient_browser_plans(url=url, goal_hint=goal_hint, fallback_actions=fallback_actions)
        attempts: List[dict] = []
        for plan in plans:
            result = self.run_browser_actions(
                (url or "").strip(),
                actions=plan["actions"],
                headless=headless,
                goal_hint=goal_hint,
            )
            attempt = {
                "plan_type": plan["plan_type"],
                "summary": result.get("summary", ""),
                "state": result.get("state", {}),
                "plan": plan,
            }
            attempts.append(attempt)
            if self._workflow_succeeded(attempt["summary"]):
                result["adaptive_plan"] = self.build_adaptive_browser_plan(
                    url=url,
                    goal_hint=goal_hint,
                    fallback_actions=fallback_actions,
                )
                result["resilient_plans"] = plans
                result["attempts"] = attempts
                result["selected_plan"] = plan
                return result

        if attempts:
            last_attempt = attempts[-1]
            return {
                "summary": last_attempt["summary"],
                "state": last_attempt.get("state", {}),
                "adaptive_plan": self.build_adaptive_browser_plan(
                    url=url,
                    goal_hint=goal_hint,
                    fallback_actions=fallback_actions,
                ),
                "resilient_plans": plans,
                "attempts": attempts,
                "selected_plan": last_attempt["plan"],
            }

        adaptive_plan = self.build_adaptive_browser_plan(
            url=url,
            goal_hint=goal_hint,
            fallback_actions=fallback_actions,
        )
        return {
            "summary": "실패: 실행 가능한 브라우저 액션 계획이 없습니다.",
            "state": self.get_browser_state(),
            "adaptive_plan": adaptive_plan,
            "resilient_plans": plans,
            "attempts": [],
            "selected_plan": None,
        }

    def suggest_desktop_workflow(self, goal_hint: str) -> dict:
        learned = self.get_learned_strategies(goal_hint=goal_hint)
        return {
            "window_target": learned.get("window_target", ""),
            "actions": list(learned.get("desktop_workflow_actions", [])),
            "summary": learned.get("desktop_workflow_key", ""),
        }

    def build_adaptive_desktop_plan(
        self,
        goal_hint: str,
        expected_window: str = "",
        fallback_actions: Optional[List[dict]] = None,
    ) -> dict:
        suggestion = self.suggest_desktop_workflow(goal_hint)
        learned_actions = list(suggestion.get("actions", []))
        merged_actions = self._merge_action_sequences(learned_actions, list(fallback_actions or []))
        resolved_window = suggestion.get("window_target") or expected_window
        merged_actions = self._augment_desktop_plan_with_state(
            merged_actions,
            expected_window=resolved_window,
        )
        return {
            "goal_hint": goal_hint,
            "expected_window": resolved_window,
            "learned_actions": learned_actions,
            "fallback_actions": list(fallback_actions or []),
            "actions": merged_actions,
            "summary": self._describe_action_plan("desktop", goal_hint, merged_actions, bool(learned_actions)),
        }

    def build_resilient_desktop_plans(
        self,
        goal_hint: str,
        expected_window: str = "",
        fallback_actions: Optional[List[dict]] = None,
    ) -> List[dict]:
        suggestion = self.suggest_desktop_workflow(goal_hint)
        learned_actions = list(suggestion.get("actions", []))
        fallback_list = list(fallback_actions or [])
        resolved_window = suggestion.get("window_target") or expected_window
        plan_specs = [
            ("adaptive", self._merge_action_sequences(learned_actions, fallback_list), bool(learned_actions)),
            ("learned_only", learned_actions, bool(learned_actions)),
            ("fallback_only", fallback_list, False),
        ]
        plans: List[dict] = []
        for plan_type, raw_actions, reused in plan_specs:
            if not raw_actions:
                continue
            actions = self._augment_desktop_plan_with_state(
                list(raw_actions),
                expected_window=resolved_window,
            )
            if not actions:
                continue
            if any(existing["actions"] == actions and existing["expected_window"] == resolved_window for existing in plans):
                continue
            plan = {
                "plan_type": plan_type,
                "goal_hint": goal_hint,
                "expected_window": resolved_window,
                "actions": actions,
                "summary": self._describe_action_plan(
                    f"desktop:{plan_type}",
                    goal_hint,
                    actions,
                    reused,
                ),
            }
            plan["score"] = self._score_desktop_plan(plan)
            plan["selection_reason"] = self._describe_desktop_plan_reason(plan)
            plans.append(plan)
        return sorted(plans, key=self._plan_sort_key, reverse=True)

    def run_desktop_workflow(
        self,
        goal_hint: str,
        app_target: str = "",
        expected_window: str = "",
        actions: Optional[List[dict]] = None,
        timeout: float = 10.0,
    ) -> dict:
        """앱 실행/창 대기/포커스/후속 액션을 하나의 데스크톱 워크플로우로 수행합니다."""
        actions = actions or self.get_desktop_workflow_plan(goal_hint)
        opened = ""
        window_title = ""
        if app_target:
            opened = self.launch_app(app_target)
        if expected_window:
            window_title = self.wait_for_window(expected_window, timeout=timeout, goal_hint=goal_hint)
            self.focus_window(expected_window, goal_hint=goal_hint)

        action_results: List[str] = []
        for action in actions:
            try:
                action_results.append(
                    self._execute_desktop_action(
                        action,
                        expected_window=expected_window,
                        timeout=timeout,
                        goal_hint=goal_hint,
                    )
                )
            except Exception as e:
                act_type = (action.get("type") or "").strip()
                action_results.append(f"오류: {act_type} ({str(e)[:60]})")

        if goal_hint and actions and self._should_remember_desktop_workflow(action_results):
            self.remember_desktop_workflow_plan(goal_hint, actions)

        return {
            "opened": opened,
            "window_title": window_title,
            "actions": action_results,
            "state": self.get_desktop_state(),
        }

    def run_adaptive_desktop_workflow(
        self,
        goal_hint: str,
        app_target: str = "",
        expected_window: str = "",
        fallback_actions: Optional[List[dict]] = None,
        timeout: float = 10.0,
    ) -> dict:
        """과거 성공 데스크톱 전략을 우선 적용하고 없으면 fallback으로 실행."""
        plan = self.build_adaptive_desktop_plan(
            goal_hint=goal_hint,
            expected_window=expected_window,
            fallback_actions=fallback_actions,
        )
        result = self.run_desktop_workflow(
            goal_hint=goal_hint,
            app_target=app_target,
            expected_window=plan["expected_window"],
            actions=plan["actions"],
            timeout=timeout,
        )
        result["adaptive_plan"] = plan
        return result

    def run_resilient_desktop_workflow(
        self,
        goal_hint: str,
        app_target: str = "",
        expected_window: str = "",
        fallback_actions: Optional[List[dict]] = None,
        timeout: float = 10.0,
    ) -> dict:
        plans = self.build_resilient_desktop_plans(
            goal_hint=goal_hint,
            expected_window=expected_window,
            fallback_actions=fallback_actions,
        )
        attempts: List[dict] = []
        for plan in plans:
            result = self.run_desktop_workflow(
                goal_hint=goal_hint,
                app_target=app_target,
                expected_window=plan["expected_window"],
                actions=plan["actions"],
                timeout=timeout,
            )
            attempt_summary = " | ".join(result.get("actions", []))
            attempt = {
                "plan_type": plan["plan_type"],
                "summary": attempt_summary,
                "window_title": result.get("window_title", ""),
                "opened": result.get("opened", ""),
                "state": result.get("state", {}),
                "plan": plan,
            }
            attempts.append(attempt)
            if self._workflow_succeeded(attempt_summary):
                result["adaptive_plan"] = self.build_adaptive_desktop_plan(
                    goal_hint=goal_hint,
                    expected_window=expected_window,
                    fallback_actions=fallback_actions,
                )
                result["resilient_plans"] = plans
                result["attempts"] = attempts
                result["selected_plan"] = plan
                return result

        if attempts:
            last_attempt = attempts[-1]
            return {
                "opened": last_attempt.get("opened", ""),
                "window_title": last_attempt.get("window_title", ""),
                "actions": last_attempt["summary"].split(" | ") if last_attempt["summary"] else [],
                "state": last_attempt.get("state", {}),
                "adaptive_plan": self.build_adaptive_desktop_plan(
                    goal_hint=goal_hint,
                    expected_window=expected_window,
                    fallback_actions=fallback_actions,
                ),
                "resilient_plans": plans,
                "attempts": attempts,
                "selected_plan": last_attempt["plan"],
            }

        adaptive_plan = self.build_adaptive_desktop_plan(
            goal_hint=goal_hint,
            expected_window=expected_window,
            fallback_actions=fallback_actions,
        )
        return {
            "opened": "",
            "window_title": "",
            "actions": ["실패: 실행 가능한 데스크톱 액션 계획이 없습니다."],
            "state": self.get_desktop_state(),
            "adaptive_plan": adaptive_plan,
            "resilient_plans": plans,
            "attempts": [],
            "selected_plan": None,
        }

    def _execute_desktop_action(self, action: dict, expected_window: str, timeout: float, goal_hint: str) -> str:
        act_type = (action.get("type") or "").strip()
        if act_type == "hotkey":
            keys = action.get("keys", [])
            self.hotkey(*keys)
            return f"성공: hotkey({','.join(keys)})"
        if act_type == "type":
            self.type_text(action.get("text", ""), use_clipboard=bool(action.get("use_clipboard", True)))
            return "성공: type"
        if act_type == "press":
            keys = action.get("keys", [])
            self.press_keys(*keys)
            return f"성공: press({','.join(keys)})"
        if act_type == "wait":
            seconds = float(action.get("seconds", 1.0))
            self.wait_seconds(seconds)
            return f"성공: wait({seconds})"
        if act_type == "open_url":
            opened_url = self.open_url(action.get("url", ""))
            return f"성공: open_url({opened_url})"
        if act_type == "open_path":
            opened_path = self.open_path(action.get("path", ""))
            return f"성공: open_path({opened_path})"
        if act_type == "launch":
            launched = self.launch_app(action.get("target", ""))
            return f"성공: launch({launched})"
        if act_type == "focus":
            target = action.get("window") or expected_window
            focused = self.focus_window(target, goal_hint=goal_hint)
            return f"성공: focus({target})" if focused else f"실패: focus({target})"
        if act_type == "wait_window":
            target = action.get("window") or expected_window
            found = self.wait_for_window(target, timeout=float(action.get("timeout", timeout)), goal_hint=goal_hint)
            return f"성공: wait_window({found})"
        if act_type == "wait_window_count":
            target = action.get("window") or expected_window
            state = self.wait_for_window_state(
                target,
                minimum_count=int(action.get("minimum_count", 1)),
                timeout=float(action.get("timeout", timeout)),
            )
            return f"성공: wait_window_count({state['count']})"
        if act_type == "focus_last_window":
            target = action.get("window") or expected_window
            windows = self.find_windows(target)
            if windows:
                win = windows[-1]
                try:
                    if getattr(win, "isMinimized", False):
                        win.restore()
                    win.activate()
                    return f"성공: focus_last_window({getattr(win, 'title', target)})"
                except Exception:
                    return f"실패: focus_last_window({target})"
            return f"실패: focus_last_window({target})"
        if act_type == "click_image":
            image_path = action.get("image_path", "")
            clicked = self.click_image(image_path, confidence=float(action.get("confidence", 0.8)))
            return f"성공: click_image({image_path})" if clicked else f"실패: click_image({image_path})"
        if act_type == "wait_image":
            image_path = action.get("image_path", "")
            visible = self._wait_for_image_visible(
                image_path,
                timeout=float(action.get("timeout", timeout)),
                confidence=float(action.get("confidence", 0.8)),
            )
            return f"성공: wait_image({image_path})" if visible else f"실패: wait_image({image_path})"
        if act_type == "click":
            self.click_screen(
                x=action.get("x"),
                y=action.get("y"),
                clicks=int(action.get("clicks", 1)),
                button=str(action.get("button", "left")),
            )
            return "성공: click"
        if act_type == "write_clipboard":
            self.write_clipboard(action.get("text", ""))
            return "성공: write_clipboard"
        if act_type == "read_clipboard":
            clip_text = self.read_clipboard()
            return f"성공: read_clipboard({clip_text[:40]})"
        return f"건너뜀: {act_type or 'unknown'}"

    def _plan_sort_key(self, plan: dict) -> tuple:
        priority = {
            "adaptive": 3,
            "learned_only": 2,
            "fallback_only": 1,
        }
        return (
            float(plan.get("score", 0.0)),
            priority.get(str(plan.get("plan_type", "")), 0),
        )

    def _score_browser_plan(self, plan: dict, browser_state: dict, requested_url: str = "") -> float:
        score = 0.0
        plan_type = str(plan.get("plan_type", "") or "")
        if plan_type == "adaptive":
            score += 3.0
        elif plan_type == "learned_only":
            score += 2.0
        elif plan_type == "fallback_only":
            score += 1.0
        actions = list(plan.get("actions", []))
        score += min(len(actions), 6) * 0.1
        current_url = str((browser_state or {}).get("current_url", "") or "").lower()
        requested = str(requested_url or "").lower()
        if current_url and requested:
            current_domain = current_url.split("//", 1)[-1].split("/", 1)[0]
            requested_domain = requested.split("//", 1)[-1].split("/", 1)[0]
            if current_domain == requested_domain:
                score += 1.0
            if requested in current_url:
                score += 0.5
        if any((action.get("type") or "") == "wait_url" for action in actions):
            score += 0.2
        if any((action.get("type") or "") == "download_wait" for action in actions):
            score += 0.2
        return round(score, 3)

    def _describe_browser_plan_reason(self, plan: dict, browser_state: dict, requested_url: str = "") -> str:
        reasons: List[str] = []
        plan_type = str(plan.get("plan_type", "") or "")
        if plan_type == "adaptive":
            reasons.append("학습 전략과 fallback을 함께 사용")
        elif plan_type == "learned_only":
            reasons.append("과거 성공 전략 우선")
        elif plan_type == "fallback_only":
            reasons.append("기본 fallback 전략")
        current_url = str((browser_state or {}).get("current_url", "") or "")
        if current_url and requested_url:
            current_domain = current_url.lower().split("//", 1)[-1].split("/", 1)[0]
            requested_domain = requested_url.lower().split("//", 1)[-1].split("/", 1)[0]
            if current_domain == requested_domain:
                reasons.append("현재 브라우저 도메인 일치")
        return " | ".join(reasons[:3])

    def _score_desktop_plan(self, plan: dict) -> float:
        score = 0.0
        plan_type = str(plan.get("plan_type", "") or "")
        if plan_type == "adaptive":
            score += 3.0
        elif plan_type == "learned_only":
            score += 2.0
        elif plan_type == "fallback_only":
            score += 1.0
        actions = list(plan.get("actions", []))
        score += min(len(actions), 6) * 0.1
        expected_window = str(plan.get("expected_window", "") or "")
        if expected_window:
            score += 0.6
        if any((action.get("type") or "") == "focus" for action in actions):
            score += 0.2
        if any((action.get("type") or "") == "wait_window" for action in actions):
            score += 0.2
        return round(score, 3)

    def _describe_desktop_plan_reason(self, plan: dict) -> str:
        reasons: List[str] = []
        plan_type = str(plan.get("plan_type", "") or "")
        if plan_type == "adaptive":
            reasons.append("학습된 창 타깃과 fallback 결합")
        elif plan_type == "learned_only":
            reasons.append("과거 성공 데스크톱 워크플로우 우선")
        elif plan_type == "fallback_only":
            reasons.append("기본 fallback 워크플로우")
        if plan.get("expected_window"):
            reasons.append("대상 창 대기/포커스 가능")
        return " | ".join(reasons[:3])

    def _workflow_succeeded(self, summary: str) -> bool:
        normalized = (summary or "").strip().lower()
        if not normalized:
            return False
        if "실패:" in normalized or "오류:" in normalized or "error" in normalized:
            return False
        return "성공:" in normalized or "downloaded:" in normalized or "download complete:" in normalized

    def resolve_window_target(self, goal_hint: str, fallback: str = "") -> str:
        key = self._normalize_goal_hint(goal_hint)
        remembered = self._window_target_history.get(key, "")
        if not remembered:
            similar_key = self._find_similar_goal_key(key, self._window_target_history)
            remembered = self._window_target_history.get(similar_key, "")
        return remembered or fallback

    def remember_window_target(self, goal_hint: str, window_title: str) -> None:
        key = self._normalize_goal_hint(goal_hint)
        title = (window_title or "").strip()
        if not key or not title:
            return
        self._window_target_history[key] = title
        self._save_window_target_history()

    def remember_desktop_workflow_plan(self, goal_hint: str, actions: List[dict]) -> None:
        key = self._normalize_goal_hint(goal_hint)
        if not key or not actions:
            return
        self._desktop_workflow_history[key] = [
            {str(k): v for k, v in action.items()}
            for action in actions
            if isinstance(action, dict)
        ]
        self._save_desktop_workflow_history()

    def get_desktop_workflow_plan(self, goal_hint: str) -> List[dict]:
        key = self._normalize_goal_hint(goal_hint)
        remembered = self._desktop_workflow_history.get(key)
        if remembered:
            return list(remembered)
        similar_key = self._find_similar_goal_key(key, self._desktop_workflow_history)
        if similar_key:
            return list(self._desktop_workflow_history.get(similar_key, []))
        return []

    # ── 라이브러리 지연 로딩 ─────────────────────────────────────────────────────

    def _get_pyautogui(self):
        try:
            import pyautogui
            pyautogui.FAILSAFE = True
            return pyautogui
        except ImportError as e:
            raise RuntimeError("pyautogui가 설치되어야 합니다.") from e

    def _get_pyperclip(self):
        try:
            import pyperclip
            return pyperclip
        except ImportError as e:
            raise RuntimeError("pyperclip이 설치되어야 합니다.") from e

    def _get_pygetwindow(self):
        try:
            import pygetwindow
            return pygetwindow
        except ImportError as e:
            raise RuntimeError("pygetwindow가 설치되어야 합니다.") from e

    def _shell_open(self, target: str):
        if os.name != "nt":
            webbrowser.open(target) # 폴백
            return
        # SW_SHOWNOACTIVATE(4): 창은 띄우되 포커스를 뺏지 않도록 실행
        result = ctypes.windll.shell32.ShellExecuteW(None, "open", target, None, None, 4)
        if result <= 32:
            raise OSError(f"ShellExecuteW 호출 실패: {target}")

    def _window_target_history_path(self) -> str:
        try:
            from core.resource_manager import ResourceManager
            return ResourceManager.get_writable_path("desktop_window_targets.json")
        except Exception:
            return os.path.join(os.path.dirname(__file__), "desktop_window_targets.json")

    def _load_window_target_history(self) -> dict:
        path = self._window_target_history_path()
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items() if v}
        except Exception as e:
            logger.warning(f"window target history load failed: {e}")
        return {}

    def _save_window_target_history(self) -> None:
        path = self._window_target_history_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(self._window_target_history, handle, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"window target history save failed: {e}")

    def _desktop_workflow_history_path(self) -> str:
        try:
            from core.resource_manager import ResourceManager
            return ResourceManager.get_writable_path("desktop_workflow_plans.json")
        except Exception:
            return os.path.join(os.path.dirname(__file__), "desktop_workflow_plans.json")

    def _load_desktop_workflow_history(self) -> dict:
        path = self._desktop_workflow_history_path()
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                return {
                    str(key): [item for item in value if isinstance(item, dict)]
                    for key, value in data.items()
                    if isinstance(value, list)
                }
        except Exception as e:
            logger.warning(f"desktop workflow history load failed: {e}")
        return {}

    def _save_desktop_workflow_history(self) -> None:
        path = self._desktop_workflow_history_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(self._desktop_workflow_history, handle, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"desktop workflow history save failed: {e}")

    def _normalize_goal_hint(self, goal_hint: str) -> str:
        normalized = re.sub(r"\s+", " ", (goal_hint or "").strip().lower())
        return re.sub(r"[^a-z0-9가-힣 _-]", "", normalized)[:80]

    def _tokenize_goal_hint(self, goal_hint: str) -> set[str]:
        tokens = set()
        for token in re.findall(r"[a-z0-9가-힣]+", (goal_hint or "").lower()):
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

    def _find_similar_goal_key(self, key: str, mapping: dict) -> str:
        if not key or not mapping:
            return ""
        target_tokens = self._tokenize_goal_hint(key)
        best_key = ""
        best_score = 0.0
        for candidate in mapping:
            candidate_tokens = self._tokenize_goal_hint(candidate)
            if not target_tokens or not candidate_tokens:
                continue
            score = self._token_overlap_score(target_tokens, candidate_tokens)
            if score > best_score:
                best_score = score
                best_key = candidate
        return best_key if best_score >= 0.34 else ""

    def _should_remember_desktop_workflow(self, action_results: List[str]) -> bool:
        return (
            bool(action_results)
            and any(item.startswith("성공:") for item in action_results)
            and not any(item.startswith(("실패:", "오류:")) for item in action_results)
        )

    def _wait_for_image_visible(self, image_path: str, timeout: float = 10.0, confidence: float = 0.8) -> bool:
        if not image_path:
            return False
        end = time.time() + timeout
        while time.time() < end:
            if self.is_image_visible(image_path, confidence=confidence):
                return True
            time.sleep(0.3)
        return False

    def _merge_action_sequences(self, learned_actions: List[dict], fallback_actions: List[dict]) -> List[dict]:
        merged: List[dict] = []
        seen: set[str] = set()
        for action in [*(learned_actions or []), *(fallback_actions or [])]:
            if not isinstance(action, dict):
                continue
            fingerprint = self._fingerprint_action(action)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            merged.append({str(k): v for k, v in action.items()})
        return merged

    def _fingerprint_action(self, action: dict) -> str:
        act_type = str(action.get("type", "")).strip().lower()
        target = (
            str(action.get("window", ""))
            or str(action.get("url", ""))
            or str(action.get("path", ""))
            or str(action.get("image_path", ""))
            or str(action.get("text", ""))[:40]
            or ",".join(map(str, action.get("keys", [])))
        )
        return f"{act_type}|{target.strip().lower()}"

    def _describe_action_plan(self, kind: str, goal_hint: str, actions: List[dict], reused: bool) -> str:
        action_types = [str(action.get("type", "")).strip() for action in actions if isinstance(action, dict)]
        action_text = ", ".join(action_types[:5])
        reused_text = "reused" if reused else "fallback"
        return f"{kind}:{reused_text}:{goal_hint} [{action_text}]"

    def _augment_browser_plan_with_state(self, actions: List[dict], browser_state: dict, domain: str) -> List[dict]:
        augmented = list(actions or [])
        current_url = str((browser_state or {}).get("current_url", "") or "")
        current_title = str((browser_state or {}).get("title", "") or "")
        last_summary = str((browser_state or {}).get("last_action_summary", "") or "")

        if domain and not self._has_action_type(augmented, "wait_url"):
            augmented.insert(0, {"type": "wait_url", "contains": domain, "timeout": 10.0})
        if current_title and not self._has_action_type(augmented, "read_title"):
            augmented.append({"type": "read_title"})
        if current_url and not self._has_action_type(augmented, "read_url"):
            augmented.append({"type": "read_url"})
        if last_summary and "성공:" in last_summary and not self._has_action_type(augmented, "read_links"):
            augmented.append({"type": "read_links", "selector": "a", "limit": 5})
        return self._merge_action_sequences([], augmented)

    def _augment_desktop_plan_with_state(self, actions: List[dict], expected_window: str) -> List[dict]:
        augmented = list(actions or [])
        if expected_window and not self._has_action_type(augmented, "wait_window"):
            augmented.insert(0, {"type": "wait_window", "window": expected_window, "timeout": 10.0})
        if expected_window and not self._has_action_type(augmented, "focus"):
            augmented.insert(1 if augmented else 0, {"type": "focus", "window": expected_window})
        if not self._has_action_type(augmented, "wait"):
            augmented.append({"type": "wait", "seconds": 0.5})
        return self._merge_action_sequences([], augmented)

    def _has_action_type(self, actions: List[dict], action_type: str) -> bool:
        target = (action_type or "").strip().lower()
        return any(str(action.get("type", "")).strip().lower() == target for action in actions if isinstance(action, dict))
