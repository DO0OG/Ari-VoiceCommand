"""
GUI / 브라우저 / 앱 자동화 공통 헬퍼.
가능한 경우 pyautogui, pyperclip, pygetwindow, selenium을 활용하고,
미설치 시에는 명확한 오류를 반환합니다.
"""
import os
import ctypes
import time
import webbrowser
from typing import Optional


class AutomationHelpers:
    def __init__(self):
        self.desktop_path = os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), "Desktop")
        self._app_aliases = {
            "메모장": r"C:\Windows\system32\notepad.exe",
            "notepad": r"C:\Windows\system32\notepad.exe",
            "계산기": r"C:\Windows\System32\calc.exe",
            "calculator": r"C:\Windows\System32\calc.exe",
            "explorer": r"C:\Windows\explorer.exe",
            "파일 탐색기": r"C:\Windows\explorer.exe",
            "cmd": r"C:\Windows\System32\cmd.exe",
            "powershell": r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        }

    def open_url(self, url: str) -> str:
        webbrowser.open(url)
        return url

    def open_path(self, path: str) -> str:
        normalized = os.path.abspath(path)
        if not os.path.exists(normalized):
            raise FileNotFoundError(f"열 경로를 찾지 못했습니다: {path}")
        self._shell_open(normalized)
        return path

    def launch_app(self, target: str) -> str:
        normalized = (target or "").strip().strip('"')
        if not normalized:
            raise ValueError("실행할 대상이 비어 있습니다.")

        direct_target = normalized if os.path.exists(normalized) else self._app_aliases.get(normalized.lower(), "")
        if direct_target and os.path.exists(direct_target):
            self._shell_open(direct_target)
            return target

        for candidate in self._app_aliases.values():
            if normalized.lower() in os.path.basename(candidate).lower():
                self._shell_open(candidate)
                return target

        raise FileNotFoundError(f"실행 가능한 앱을 찾지 못했습니다: {target}")

    def wait_seconds(self, seconds: float) -> float:
        time.sleep(seconds)
        return seconds

    def click_screen(self, x: Optional[int] = None, y: Optional[int] = None, clicks: int = 1, button: str = "left") -> str:
        pg = self._get_pyautogui()
        if x is not None and y is not None:
            pg.click(x=x, y=y, clicks=clicks, button=button)
            return f"{x},{y}"
        pg.click(clicks=clicks, button=button)
        return "current_position"

    def move_mouse(self, x: int, y: int, duration: float = 0.2) -> str:
        pg = self._get_pyautogui()
        pg.moveTo(x, y, duration=duration)
        return f"{x},{y}"

    def type_text(self, text: str, interval: float = 0.02, use_clipboard: bool = True) -> str:
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
        pg = self._get_pyautogui()
        for key in keys:
            pg.press(key)
        return ",".join(keys)

    def hotkey(self, *keys: str) -> str:
        pg = self._get_pyautogui()
        pg.hotkey(*keys)
        return ",".join(keys)

    def screenshot(self, path: Optional[str] = None) -> str:
        pg = self._get_pyautogui()
        if not path:
            folder = os.path.join(self.desktop_path, "screenshots")
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, f"screenshot_{int(time.time())}.png")
        pg.screenshot(path)
        return path

    def write_clipboard(self, text: str) -> str:
        pc = self._get_pyperclip()
        pc.copy(text)
        return text

    def read_clipboard(self) -> str:
        pc = self._get_pyperclip()
        return pc.paste()

    def get_active_window_title(self) -> str:
        gw = self._get_pygetwindow()
        win = gw.getActiveWindow()
        return win.title if win else ""

    def wait_for_window(self, title_substring: str, timeout: float = 10.0) -> str:
        gw = self._get_pygetwindow()
        end = time.time() + timeout
        title_substring_lower = title_substring.lower()
        while time.time() < end:
            titles = [title for title in gw.getAllTitles() if title and title_substring_lower in title.lower()]
            if titles:
                return titles[0]
            time.sleep(0.2)
        raise TimeoutError(f"창을 찾지 못했습니다: {title_substring}")

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
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.options import Options
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            from webdriver_manager.chrome import ChromeDriverManager
            from selenium.webdriver.chrome.service import Service
        except ImportError as e:
            raise RuntimeError("selenium / webdriver-manager가 설치되어야 브라우저 로그인을 자동화할 수 있습니다.") from e

        options = Options()
        if headless:
            options.add_argument("--headless=new")
        options.add_argument("--disable-blink-features=AutomationControlled")
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        driver.get(url)

        wait = WebDriverWait(driver, 20)
        password_selector = password_selector or "input[type='" + "password" + "']"
        user_el = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, username_selector)))
        user_el.clear()
        user_el.send_keys(username)

        pass_el = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, password_selector)))
        pass_el.clear()
        pass_el.send_keys(password)

        if submit_selector:
            submit_el = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, submit_selector)))
            submit_el.click()

        return driver.current_url

    def _get_pyautogui(self):
        try:
            import pyautogui
            pyautogui.FAILSAFE = True
            return pyautogui
        except ImportError as e:
            raise RuntimeError("pyautogui가 설치되어야 GUI 자동화를 수행할 수 있습니다.") from e

    def _get_pyperclip(self):
        try:
            import pyperclip
            return pyperclip
        except ImportError as e:
            raise RuntimeError("pyperclip이 설치되어야 클립보드 작업을 수행할 수 있습니다.") from e

    def _get_pygetwindow(self):
        try:
            import pygetwindow
            return pygetwindow
        except ImportError as e:
            raise RuntimeError("pygetwindow가 설치되어야 창 상태를 조회할 수 있습니다.") from e

    def _shell_open(self, target: str):
        if os.name != "nt":
            raise RuntimeError("현재 환경에서는 Windows Shell 열기를 지원하지 않습니다.")
        result = ctypes.windll.shell32.ShellExecuteW(None, "open", target, None, None, 1)
        if result <= 32:
            raise OSError(f"ShellExecuteW 호출에 실패했습니다: {target}")
