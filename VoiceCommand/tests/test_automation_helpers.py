import os
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.automation_helpers import AutomationHelpers


class _TempAutomationHelpers(AutomationHelpers):
    def __init__(self, history_path: str):
        self._history_path_override = history_path
        super().__init__()

    def _window_target_history_path(self) -> str:
        return self._history_path_override

    def _desktop_workflow_history_path(self) -> str:
        return self._history_path_override.replace("window_targets.json", "desktop_workflows.json")


class AutomationHelpersTests(unittest.TestCase):
    def test_window_target_history_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            history_path = os.path.join(tmp, "window_targets.json")
            helper = _TempAutomationHelpers(history_path)
            helper.remember_window_target("메모장 열기", "제목 없음 - 메모장")

            reloaded = _TempAutomationHelpers(history_path)
            resolved = reloaded.resolve_window_target("메모장 열기", "메모장")

            self.assertEqual(resolved, "제목 없음 - 메모장")

    def test_desktop_workflow_plan_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            history_path = os.path.join(tmp, "window_targets.json")
            helper = _TempAutomationHelpers(history_path)
            helper.remember_desktop_workflow_plan("메모장에 메모 저장", [{"type": "hotkey", "keys": ["ctrl", "s"]}])

            reloaded = _TempAutomationHelpers(history_path)
            remembered = reloaded.get_desktop_workflow_plan("메모장에 메모 저장")

            self.assertEqual(len(remembered), 1)
            self.assertEqual(remembered[0]["type"], "hotkey")

    def test_window_target_history_uses_similar_goal_hint_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            history_path = os.path.join(tmp, "window_targets.json")
            helper = _TempAutomationHelpers(history_path)
            helper.remember_window_target("메모장에 메모 저장", "제목 없음 - 메모장")

            resolved = helper.resolve_window_target("메모장 저장 작업", "메모장")

            self.assertEqual(resolved, "제목 없음 - 메모장")

    def test_desktop_workflow_plan_uses_similar_goal_hint_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            history_path = os.path.join(tmp, "window_targets.json")
            helper = _TempAutomationHelpers(history_path)
            helper.remember_desktop_workflow_plan("메모장에 메모 저장", [{"type": "hotkey", "keys": ["ctrl", "s"]}])

            remembered = helper.get_desktop_workflow_plan("메모장 저장 작업")

            self.assertEqual(len(remembered), 1)
            self.assertEqual(remembered[0]["type"], "hotkey")

    def test_get_learned_strategies_merges_desktop_and_browser_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            history_path = os.path.join(tmp, "window_targets.json")
            helper = _TempAutomationHelpers(history_path)
            helper.remember_window_target("메모장에 메모 저장", "제목 없음 - 메모장")
            helper.remember_desktop_workflow_plan("메모장에 메모 저장", [{"type": "hotkey", "keys": ["ctrl", "s"]}])
            helper.get_browser_state = lambda: {
                "current_url": "https://example.com/dashboard",
                "action_plan_strategies": {
                    "example.com": {
                        "로그인 후 다운로드": [{"type": "click", "selectors": ["#download"]}]
                    }
                },
            }

            learned = helper.get_learned_strategies("다운로드 전에 로그인", domain="example.com")

            self.assertEqual(learned["browser_plan_key"], "로그인 후 다운로드")
            self.assertEqual(len(learned["browser_actions"]), 1)
            self.assertEqual(learned["browser_actions"][0]["type"], "click")
            self.assertEqual(learned["window_target"], "")

    def test_get_desktop_state_includes_learned_strategies(self):
        with tempfile.TemporaryDirectory() as tmp:
            history_path = os.path.join(tmp, "window_targets.json")
            helper = _TempAutomationHelpers(history_path)
            helper.get_browser_state = lambda: {}
            state = helper.get_desktop_state()

            self.assertIn("learned_strategies", state)
            self.assertIn("learned_strategy_summary", state)

    def test_get_learned_strategy_summary_is_human_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            history_path = os.path.join(tmp, "window_targets.json")
            helper = _TempAutomationHelpers(history_path)
            helper.remember_window_target("메모장에 메모 저장", "제목 없음 - 메모장")
            helper.remember_desktop_workflow_plan("메모장에 메모 저장", [{"type": "hotkey", "keys": ["ctrl", "s"]}])
            helper.get_browser_state = lambda: {
                "current_url": "https://example.com/dashboard",
                "action_plan_strategies": {
                    "example.com": {
                        "로그인 후 다운로드": [{"type": "click", "selectors": ["#download"]}]
                    }
                },
            }

            summary = helper.get_learned_strategy_summary("로그인 후 다운로드", domain="example.com")

            self.assertIn("domain=example.com", summary)
            self.assertIn("browser_plan=로그인 후 다운로드", summary)

    def test_get_planning_snapshot_summary_includes_state_and_learned_strategy(self):
        with tempfile.TemporaryDirectory() as tmp:
            history_path = os.path.join(tmp, "window_targets.json")
            helper = _TempAutomationHelpers(history_path)
            helper.get_active_window_title = lambda: "제목 없음 - 메모장"
            helper.list_open_windows = lambda limit=12: ["제목 없음 - 메모장", "Chrome"]
            helper.get_browser_state = lambda: {
                "current_url": "https://example.com/dashboard",
                "title": "Dashboard",
                "last_action_summary": "성공: wait_url(https://example.com/dashboard)",
                "action_plan_strategies": {
                    "example.com": {
                        "로그인 후 다운로드": [{"type": "click", "selectors": ["#download"]}]
                    }
                },
            }

            summary = helper.get_planning_snapshot_summary("로그인 후 다운로드", domain="example.com")

            self.assertIn("active_window=제목 없음 - 메모장", summary)
            self.assertIn("browser_url=https://example.com/dashboard", summary)
            self.assertIn("learned=domain=example.com", summary)

    def test_run_adaptive_browser_workflow_prefers_learned_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            history_path = os.path.join(tmp, "window_targets.json")
            helper = _TempAutomationHelpers(history_path)
            helper.get_browser_state = lambda: {
                "current_url": "https://example.com/dashboard",
                "action_plan_strategies": {
                    "example.com": {
                        "로그인 후 다운로드": [{"type": "click", "selectors": ["#download"]}]
                    }
                },
            }
            captured = {}
            helper.run_browser_actions = lambda url, actions, headless=False, goal_hint="": captured.update({
                "url": url,
                "actions": actions,
                "goal_hint": goal_hint,
            }) or {"summary": "ok", "state": {}}

            result = helper.run_adaptive_browser_workflow(
                "https://example.com/downloads",
                goal_hint="로그인 후 다운로드",
                fallback_actions=[{"type": "click", "selectors": ["#fallback"]}],
            )

            self.assertEqual(captured["goal_hint"], "로그인 후 다운로드")
            self.assertTrue(any(action.get("type") == "click" and action.get("selectors", [""])[0] == "#download" for action in captured["actions"]))
            self.assertIn("adaptive_plan", result)
            self.assertEqual(result["summary"], "ok")

    def test_run_resilient_browser_workflow_retries_until_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            history_path = os.path.join(tmp, "window_targets.json")
            helper = _TempAutomationHelpers(history_path)
            helper.get_browser_state = lambda: {
                "current_url": "https://example.com/dashboard",
                "action_plan_strategies": {
                    "example.com": {
                        "로그인 후 다운로드": [{"type": "click", "selectors": ["#download"]}]
                    }
                },
            }
            attempts = []

            def fake_run_browser_actions(url, actions, headless=False, goal_hint=""):
                attempts.append([dict(action) for action in actions])
                if len(attempts) == 1:
                    return {"summary": "실패: click", "state": {"attempt": 1}}
                return {"summary": "성공: download_wait", "state": {"attempt": 2}}

            helper.run_browser_actions = fake_run_browser_actions

            result = helper.run_resilient_browser_workflow(
                "https://example.com/downloads",
                goal_hint="로그인 후 다운로드",
                fallback_actions=[{"type": "download_wait", "timeout": 10.0}],
            )

            self.assertEqual(len(result["attempts"]), 2)
            self.assertEqual(result["selected_plan"]["plan_type"], "learned_only")
            self.assertEqual(result["state"]["attempt"], 2)
            self.assertEqual(len(attempts), 2)

    def test_run_adaptive_desktop_workflow_prefers_learned_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            history_path = os.path.join(tmp, "window_targets.json")
            helper = _TempAutomationHelpers(history_path)
            helper.remember_window_target("메모장에 메모 저장", "제목 없음 - 메모장")
            helper.remember_desktop_workflow_plan("메모장에 메모 저장", [{"type": "hotkey", "keys": ["ctrl", "s"]}])
            captured = {}
            helper.run_desktop_workflow = lambda goal_hint, app_target="", expected_window="", actions=None, timeout=10.0: captured.update({
                "goal_hint": goal_hint,
                "app_target": app_target,
                "expected_window": expected_window,
                "actions": actions,
            }) or {"opened": app_target, "window_title": expected_window, "actions": [], "state": {}}

            result = helper.run_adaptive_desktop_workflow(
                goal_hint="메모장에 메모 저장",
                app_target="notepad",
                expected_window="메모장",
                fallback_actions=[{"type": "type", "text": "hello"}],
            )

            self.assertEqual(captured["expected_window"], "제목 없음 - 메모장")
            self.assertTrue(any(action.get("type") == "hotkey" for action in captured["actions"]))
            self.assertIn("adaptive_plan", result)
            self.assertEqual(result["opened"], "notepad")

    def test_run_resilient_desktop_workflow_retries_until_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            history_path = os.path.join(tmp, "window_targets.json")
            helper = _TempAutomationHelpers(history_path)
            helper.remember_window_target("메모장에 메모 저장", "제목 없음 - 메모장")
            helper.remember_desktop_workflow_plan("메모장에 메모 저장", [{"type": "hotkey", "keys": ["ctrl", "s"]}])
            attempts = []

            def fake_run_desktop_workflow(goal_hint, app_target="", expected_window="", actions=None, timeout=10.0):
                attempts.append([dict(action) for action in actions or []])
                if len(attempts) == 1:
                    return {"opened": app_target, "window_title": expected_window, "actions": ["실패: hotkey(ctrl,s)"], "state": {"attempt": 1}}
                return {"opened": app_target, "window_title": expected_window, "actions": ["성공: type"], "state": {"attempt": 2}}

            helper.run_desktop_workflow = fake_run_desktop_workflow

            result = helper.run_resilient_desktop_workflow(
                goal_hint="메모장에 메모 저장",
                app_target="notepad",
                expected_window="메모장",
                fallback_actions=[{"type": "type", "text": "hello"}],
            )

            self.assertEqual(len(result["attempts"]), 2)
            self.assertEqual(result["selected_plan"]["plan_type"], "learned_only")
            self.assertEqual(result["state"]["attempt"], 2)
            self.assertEqual(len(attempts), 2)

    def test_build_adaptive_browser_plan_merges_learned_and_fallback_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            history_path = os.path.join(tmp, "window_targets.json")
            helper = _TempAutomationHelpers(history_path)
            helper.get_browser_state = lambda: {
                "current_url": "https://example.com/dashboard",
                "action_plan_strategies": {
                    "example.com": {
                        "로그인 후 다운로드": [
                            {"type": "click", "selectors": ["#download"]},
                            {"type": "wait_url", "contains": "dashboard"},
                        ]
                    }
                },
            }

            plan = helper.build_adaptive_browser_plan(
                url="https://example.com/downloads",
                goal_hint="로그인 후 다운로드",
                fallback_actions=[{"type": "download_wait", "timeout": 10.0}],
            )

            action_types = [action["type"] for action in plan["actions"]]
            self.assertIn("click", action_types)
            self.assertIn("wait_url", action_types)
            self.assertIn("download_wait", action_types)
            self.assertIn("read_url", action_types)
            self.assertIn("browser:reused", plan["summary"])

    def test_build_resilient_browser_plans_returns_distinct_attempts(self):
        with tempfile.TemporaryDirectory() as tmp:
            history_path = os.path.join(tmp, "window_targets.json")
            helper = _TempAutomationHelpers(history_path)
            helper.get_browser_state = lambda: {
                "current_url": "https://example.com/dashboard",
                "action_plan_strategies": {
                    "example.com": {
                        "로그인 후 다운로드": [{"type": "click", "selectors": ["#download"]}]
                    }
                },
            }

            plans = helper.build_resilient_browser_plans(
                url="https://example.com/downloads",
                goal_hint="로그인 후 다운로드",
                fallback_actions=[{"type": "download_wait", "timeout": 10.0}],
            )

            self.assertEqual([plan["plan_type"] for plan in plans], ["adaptive", "learned_only", "fallback_only"])

    def test_build_adaptive_desktop_plan_merges_learned_and_fallback_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            history_path = os.path.join(tmp, "window_targets.json")
            helper = _TempAutomationHelpers(history_path)
            helper.remember_window_target("메모장에 메모 저장", "제목 없음 - 메모장")
            helper.remember_desktop_workflow_plan("메모장에 메모 저장", [{"type": "hotkey", "keys": ["ctrl", "s"]}])

            plan = helper.build_adaptive_desktop_plan(
                goal_hint="메모장에 메모 저장",
                expected_window="메모장",
                fallback_actions=[{"type": "type", "text": "hello"}],
            )

            self.assertEqual(plan["expected_window"], "제목 없음 - 메모장")
            self.assertEqual(plan["actions"][0]["type"], "wait_window")
            self.assertEqual(plan["actions"][1]["type"], "focus")
            self.assertEqual(plan["actions"][2]["type"], "hotkey")
            self.assertEqual(plan["actions"][3]["type"], "type")
            self.assertEqual(plan["actions"][-1]["type"], "wait")
            self.assertIn("desktop:reused", plan["summary"])

    def test_build_resilient_desktop_plans_returns_distinct_attempts(self):
        with tempfile.TemporaryDirectory() as tmp:
            history_path = os.path.join(tmp, "window_targets.json")
            helper = _TempAutomationHelpers(history_path)
            helper.remember_window_target("메모장에 메모 저장", "제목 없음 - 메모장")
            helper.remember_desktop_workflow_plan("메모장에 메모 저장", [{"type": "hotkey", "keys": ["ctrl", "s"]}])

            plans = helper.build_resilient_desktop_plans(
                goal_hint="메모장에 메모 저장",
                expected_window="메모장",
                fallback_actions=[{"type": "type", "text": "hello"}],
            )

            self.assertEqual([plan["plan_type"] for plan in plans], ["adaptive", "learned_only", "fallback_only"])


if __name__ == "__main__":
    unittest.main()
