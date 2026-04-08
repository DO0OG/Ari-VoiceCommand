import unittest
from unittest.mock import patch


from agent.automation_helpers import AutomationHelpers


class _WorkflowHelper(AutomationHelpers):
    def __init__(self):
        self.events = []
        self.image_visibility_checks = 0
        super().__init__()

    def _load_window_target_history(self):
        return {}

    def _save_window_target_history(self):
        return None

    def launch_app(self, target: str) -> str:
        self.events.append(("launch", target))
        return target

    def wait_for_window(self, title_substring: str, timeout: float = 10.0, goal_hint: str = "") -> str:
        self.events.append(("wait", title_substring, goal_hint))
        self.remember_window_target(goal_hint or title_substring, "제목 없음 - 메모장")
        return "제목 없음 - 메모장"

    def focus_window(self, title_substring: str, goal_hint: str = "") -> bool:
        self.events.append(("focus", title_substring, goal_hint))
        return True

    def type_text(self, text: str, interval: float = 0.01, use_clipboard: bool = True) -> str:
        self.events.append(("type", text))
        return text

    def hotkey(self, *keys: str) -> str:
        self.events.append(("hotkey", keys))
        return ",".join(keys)

    def open_url(self, url: str) -> str:
        self.events.append(("open_url", url))
        return url

    def open_path(self, path: str) -> str:
        self.events.append(("open_path", path))
        return path

    def click_image(self, image_path: str, confidence: float = 0.8) -> bool:
        self.events.append(("click_image", image_path, confidence))
        return True

    def click_screen(self, x=None, y=None, clicks: int = 1, button: str = "left") -> str:
        self.events.append(("click", x, y, clicks, button))
        return "clicked"

    def is_image_visible(self, image_path: str, confidence: float = 0.8) -> bool:
        self.image_visibility_checks += 1
        self.events.append(("is_image_visible", image_path, confidence))
        return self.image_visibility_checks >= 2

    def write_clipboard(self, text: str) -> str:
        self.events.append(("write_clipboard", text))
        return text

    def read_clipboard(self) -> str:
        self.events.append(("read_clipboard",))
        return "copied text"

    def get_desktop_state(self) -> dict:
        return {"active_window_title": "제목 없음 - 메모장"}

    def find_windows(self, title_substring: str, limit: int = 5):
        class _Window:
            def __init__(self, title):
                self.title = title
                self.isMinimized = False

            def activate(self):
                return None

            def restore(self):
                return None

        return [_Window("제목 없음 - 메모장"), _Window("메모장 - 보조")] if "메모장" in title_substring else []


class DesktopWorkflowTests(unittest.TestCase):
    def test_run_desktop_workflow_executes_actions_and_returns_state(self):
        helper = _WorkflowHelper()

        result = helper.run_desktop_workflow(
            goal_hint="메모장에 메모 저장",
            app_target="notepad",
            expected_window="메모장",
            actions=[
                {"type": "type", "text": "hello"},
                {"type": "hotkey", "keys": ["ctrl", "s"]},
            ],
        )

        self.assertEqual(result["opened"], "notepad")
        self.assertEqual(result["window_title"], "제목 없음 - 메모장")
        self.assertIn("성공: type", result["actions"][0])
        self.assertIn("성공: hotkey", result["actions"][1])
        self.assertEqual(result["state"]["active_window_title"], "제목 없음 - 메모장")

    def test_run_desktop_workflow_supports_richer_action_types(self):
        helper = _WorkflowHelper()

        result = helper.run_desktop_workflow(
            goal_hint="브라우저 열고 이미지 클릭",
            app_target="chrome",
            expected_window="Chrome",
            actions=[
                {"type": "open_url", "url": "https://example.com"},
                {"type": "click_image", "image_path": "button.png", "confidence": 0.9},
                {"type": "wait_image", "image_path": "confirm.png", "confidence": 0.85, "timeout": 1.0},
                {"type": "click", "x": 10, "y": 20, "clicks": 2},
                {"type": "open_path", "path": r"C:\Temp"},
                {"type": "write_clipboard", "text": "memo"},
                {"type": "read_clipboard"},
                {"type": "wait_window", "window": "Chrome", "timeout": 1.0},
            ],
        )

        self.assertIn(("open_url", "https://example.com"), helper.events)
        self.assertIn(("open_path", r"C:\Temp"), helper.events)
        self.assertIn(("click_image", "button.png", 0.9), helper.events)
        self.assertIn(("click", 10, 20, 2, "left"), helper.events)
        self.assertIn(("write_clipboard", "memo"), helper.events)
        self.assertIn(("read_clipboard",), helper.events)
        self.assertTrue(any(item.startswith("성공: wait_image(") for item in result["actions"]))
        self.assertTrue(any(item.startswith("성공: wait_window(") for item in result["actions"]))

    def test_launch_app_resolves_executable_from_path_lookup(self):
        helper = AutomationHelpers()

        with patch("agent.automation_helpers.shutil.which", return_value=r"C:\Tools\custombrowser.exe"):
            with patch.object(helper, "_shell_open") as shell_open:
                launched = helper.launch_app("custombrowser")

        self.assertEqual(launched, "custombrowser")
        shell_open.assert_called_once_with(r"C:\Tools\custombrowser.exe")

    def test_failed_desktop_workflow_results_are_not_remembered(self):
        helper = AutomationHelpers()
        self.assertFalse(helper._should_remember_desktop_workflow(["성공: type", "실패: click_image(button.png)"]))

    def test_window_state_helpers_return_count_and_titles(self):
        helper = _WorkflowHelper()

        state = helper.get_window_state("메모장")

        self.assertTrue(state["exists"])
        self.assertEqual(state["count"], 2)
        self.assertIn("제목 없음 - 메모장", state["titles"])

    def test_run_desktop_workflow_supports_window_state_actions(self):
        helper = _WorkflowHelper()

        result = helper.run_desktop_workflow(
            goal_hint="메모장 상태 확인",
            expected_window="메모장",
            actions=[
                {"type": "wait_window_count", "window": "메모장", "minimum_count": 2, "timeout": 1.0},
                {"type": "focus_last_window", "window": "메모장"},
            ],
        )

        self.assertTrue(any(item.startswith("성공: wait_window_count(") for item in result["actions"]))
        self.assertTrue(any(item.startswith("성공: focus_last_window(") for item in result["actions"]))


if __name__ == "__main__":
    unittest.main()
