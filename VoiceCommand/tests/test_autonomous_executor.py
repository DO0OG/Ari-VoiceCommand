import os
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import agent.autonomous_executor as autonomous_executor_module
from agent.autonomous_executor import AutonomousExecutor


class AutonomousExecutorTests(unittest.TestCase):
    def test_runner_script_exposes_learned_strategies_helpers(self):
        executor = AutonomousExecutor()

        script = executor._build_python_runner_script("print('ok')")

        self.assertIn('"get_learned_strategies": _automation.get_learned_strategies', script)
        self.assertIn('"get_learned_strategy_summary": _automation.get_learned_strategy_summary', script)
        self.assertIn('"get_planning_snapshot": _automation.get_planning_snapshot', script)
        self.assertIn('"get_planning_snapshot_summary": _automation.get_planning_snapshot_summary', script)
        self.assertIn('"run_adaptive_browser_workflow": _automation.run_adaptive_browser_workflow', script)
        self.assertIn('"run_resilient_browser_workflow": _automation.run_resilient_browser_workflow', script)
        self.assertIn('"run_adaptive_desktop_workflow": _automation.run_adaptive_desktop_workflow', script)
        self.assertIn('"run_resilient_desktop_workflow": _automation.run_resilient_desktop_workflow', script)
        self.assertIn('"build_adaptive_browser_plan": _automation.build_adaptive_browser_plan', script)
        self.assertIn('"build_resilient_browser_plans": _automation.build_resilient_browser_plans', script)
        self.assertIn('"build_adaptive_desktop_plan": _automation.build_adaptive_desktop_plan', script)
        self.assertIn('"build_resilient_desktop_plans": _automation.build_resilient_desktop_plans', script)
        self.assertIn('"get_desktop_state": _automation.get_desktop_state', script)
        self.assertIn('"list_open_windows": _automation.list_open_windows', script)
        self.assertIn('"learned_strategies": _automation.get_learned_strategies()', script)
        self.assertIn('"learned_strategy_summary": _automation.get_learned_strategy_summary()', script)
        self.assertIn('"planning_snapshot": _automation.get_planning_snapshot()', script)
        self.assertIn('"planning_snapshot_summary": _automation.get_planning_snapshot_summary()', script)
        self.assertIn('"execution_policy": _automation.get_execution_policy()', script)
        self.assertIn('"execution_policy_summary": _automation.get_execution_policy_summary()', script)
        self.assertIn('execution_globals["get_state_transition_history"] = lambda: []', script)
        self.assertIn('execution_globals["get_backup_history"] = lambda: [dict(item) for item in _backup_history]', script)
        self.assertIn('execution_globals["restore_last_backup"] = _restore_last_backup', script)
        self.assertIn('execution_globals["get_recovery_candidates"] = lambda target_paths=None: [dict(item) for item in _backup_history[-5:]]', script)
        self.assertIn('execution_globals["get_recovery_guidance"] = lambda goal="", target_paths=None: "복구 히스토리 확인 가능" if _backup_history else ""', script)
        self.assertIn('execution_globals["get_recent_goal_episodes"] = lambda goal="", limit=3: ""', script)
        self.assertIn('"recent_state_transitions": []', script)
        self.assertIn('"backup_history": [dict(item) for item in _backup_history[-5:]]', script)
        self.assertIn('"recovery_candidates": [dict(item) for item in _backup_history[-5:]]', script)
        self.assertIn('"repo_root": repo_root', script)
        self.assertIn('"module_dir": module_dir', script)
        self.assertIn("os.chdir(repo_root)", script)

    def test_subprocess_kwargs_use_repo_root_and_background_flags(self):
        executor = AutonomousExecutor()

        kwargs = executor._build_subprocess_kwargs()

        self.assertEqual(kwargs["cwd"], executor._get_repo_root())
        if sys.platform == "win32":
            self.assertEqual(
                kwargs["creationflags"],
                getattr(autonomous_executor_module.subprocess, "CREATE_NO_WINDOW", 0),
            )
            self.assertEqual(kwargs["startupinfo"].wShowWindow, 0)

    def test_state_delta_summary_is_recorded_in_history(self):
        executor = AutonomousExecutor()
        snapshots = iter([
            {
                "active_window_title": "메모장",
                "open_window_titles": ["메모장"],
                "browser_state": {},
                "desktop_state": {},
                "learned_strategies": {},
                "learned_strategy_summary": "",
                "planning_snapshot": {},
                "planning_snapshot_summary": "",
                "last_execution_success": None,
                "last_execution_output": "",
                "last_execution_error": "",
            },
            {
                "active_window_title": "Chrome",
                "open_window_titles": ["메모장", "Example Domain - Chrome"],
                "browser_state": {"current_url": "https://example.com", "title": "Example Domain"},
                "desktop_state": {},
                "learned_strategies": {},
                "learned_strategy_summary": "",
                "planning_snapshot": {},
                "planning_snapshot_summary": "",
                "last_execution_success": None,
                "last_execution_output": "",
                "last_execution_error": "",
            },
        ])
        executor.get_runtime_state = lambda: next(snapshots)

        result = executor.run_shell("echo ok")

        self.assertTrue(result.success)
        self.assertIn("browser_url=https://example.com", result.state_delta_summary)
        runtime_state = executor.get_state_transition_history()
        self.assertTrue(runtime_state)
        self.assertIn("browser_url=https://example.com", runtime_state[-1]["summary"])

    def test_runtime_state_includes_execution_policy_and_backup_history(self):
        executor = AutonomousExecutor()
        executor._automation.get_execution_policy = lambda goal_hint="", domain="", expected_window="": {
            "recommended_browser_plan": {"plan_type": "adaptive", "score": 4.1},
            "recommended_desktop_plan": None,
        }
        executor._automation.get_execution_policy_summary = lambda goal_hint="", domain="", expected_window="": "browser=adaptive score=4.1"

        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "report.txt")
            with open(target, "w", encoding="utf-8") as handle:
                handle.write("before")
            executor._save_document(tmp, "report", "after", preferred_format="txt")
            state = executor.get_runtime_state()

        self.assertIn("execution_policy", state)
        self.assertIn("browser=adaptive", state.get("execution_policy_summary", ""))
        self.assertTrue(state.get("backup_history"))

    def test_recovery_candidates_filter_by_target_path(self):
        executor = AutonomousExecutor()
        with tempfile.TemporaryDirectory() as tmp:
            first = os.path.join(tmp, "one.txt")
            second = os.path.join(tmp, "two.txt")
            for path, content in ((first, "one"), (second, "two")):
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(content)
                executor._save_document(tmp, os.path.splitext(os.path.basename(path))[0], content + "_new", preferred_format="txt")

            candidates = executor.get_recovery_candidates([second])

        self.assertEqual(len(candidates), 1)
        self.assertTrue(candidates[0]["target_path"].endswith("two.txt"))

    def test_recovery_guidance_combines_episode_and_backup_context(self):
        executor = AutonomousExecutor()
        executor.get_recent_goal_episodes = lambda goal="", limit=3: "최근 유사 목표 에피소드:\n[실패] report overwrite"
        executor._backup_history = [
            {"target_path": r"C:\temp\report.txt", "backup_path": r"C:\temp\.ari_backups\report.txt"}
        ]

        guidance = executor.get_recovery_guidance(goal="report overwrite", target_paths=[r"C:\temp\report.txt"])

        self.assertIn("최근 유사 목표 에피소드", guidance)
        self.assertIn("restore_last_backup", guidance)

    def test_save_document_creates_backup_for_overwrite(self):
        executor = AutonomousExecutor()
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "report.txt")
            with open(target, "w", encoding="utf-8") as handle:
                handle.write("before")

            saved = executor._save_document(tmp, "report", "after", preferred_format="txt")

            self.assertEqual(saved, target)
            backups = executor.get_backup_history()
            self.assertEqual(len(backups), 1)
            self.assertEqual(os.path.abspath(backups[0]["target_path"]), os.path.abspath(target))

            restored = executor.restore_last_backup(target)
            self.assertEqual(os.path.abspath(restored), os.path.abspath(target))
            with open(target, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "before")

    def test_state_delta_tracks_removed_paths_and_browser_title_changes(self):
        executor = AutonomousExecutor()
        delta = executor._build_state_delta(
            {
                "active_window_title": "Chrome",
                "open_window_titles": ["Chrome", "메모장"],
                "browser_state": {"current_url": "", "title": "Old Title"},
                "desktop_state": {"desktop_sample_paths": [r"C:\temp\old.txt"]},
            },
            {
                "active_window_title": "Chrome",
                "open_window_titles": ["Chrome"],
                "browser_state": {"current_url": "", "title": "New Title"},
                "desktop_state": {"desktop_sample_paths": []},
            },
        )

        summary = executor._summarize_state_delta(delta)

        self.assertIn("browser_title=New Title", summary)
        self.assertIn("closed_windows=메모장", summary)
        self.assertIn("removed_paths=C:\\temp\\old.txt", summary)


if __name__ == "__main__":
    unittest.main()
