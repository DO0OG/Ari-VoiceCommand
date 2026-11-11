import contextlib
import io
import os
import runpy
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


import agent.autonomous_executor as autonomous_executor_module
from agent.autonomous_executor import AutonomousExecutor
from agent.backup_history import append_backup_history, load_backup_history
from core.resource_manager import ResourceManager


class AutonomousExecutorTests(unittest.TestCase):
    def setUp(self):
        # 백업 이력 색인이 실제 사용자 데이터 폴더에 쌓이지 않게 격리한다.
        data_dir = tempfile.TemporaryDirectory()
        self.addCleanup(data_dir.cleanup)
        env_patch = patch.dict(os.environ, {"ARI_APP_DATA_DIR": data_dir.name})
        env_patch.start()
        self.addCleanup(env_patch.stop)
        ResourceManager.reset_cache()
        self.addCleanup(ResourceManager.reset_cache)

    def test_build_child_env_filters_expanded_sensitive_prefixes(self):
        filtered_value = "blocked"
        fake_env = {
            "PATH": "allowed",
            "AWS_SECRET_ACCESS_KEY": filtered_value,
            "AZURE_OPENAI_KEY": filtered_value,
            "GOOGLE_API_KEY": filtered_value,
            "GITHUB_TOKEN": filtered_value,
            "MY_OPENAI_API_KEY": filtered_value,
            "FISH_API_KEY": filtered_value,
            "PRIVATE_TOKEN": filtered_value,
            "CUSTOM_VALUE": "allowed",
        }

        with patch.dict(autonomous_executor_module.os.environ, fake_env, clear=True):
            child_env = autonomous_executor_module._build_child_env()

        self.assertEqual(child_env["PATH"], "allowed")
        self.assertEqual(child_env["CUSTOM_VALUE"], "allowed")
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", child_env)
        self.assertNotIn("AZURE_OPENAI_KEY", child_env)
        self.assertNotIn("GOOGLE_API_KEY", child_env)
        self.assertNotIn("GITHUB_TOKEN", child_env)
        self.assertNotIn("MY_OPENAI_API_KEY", child_env)
        self.assertNotIn("FISH_API_KEY", child_env)
        self.assertNotIn("PRIVATE_TOKEN", child_env)

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
        self.assertEqual(kwargs["stdin"], autonomous_executor_module.subprocess.DEVNULL)
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
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "report.txt")
            backup_path = os.path.join(tmp, "backup_report.txt")
            with open(backup_path, "w", encoding="utf-8") as handle:
                handle.write("before")
            append_backup_history(
                ResourceManager.get_writable_path("backup_history.json"),
                {"target_path": target, "backup_path": backup_path},
                20,
            )

            guidance = executor.get_recovery_guidance(goal="report overwrite", target_paths=[target])

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

    def test_backup_history_is_restored_by_a_new_executor(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "report.txt")
            with open(target, "w", encoding="utf-8") as handle:
                handle.write("before")
            AutonomousExecutor()._save_document(tmp, "report", "after", preferred_format="txt")

            later = AutonomousExecutor()
            self.assertEqual(len(later.get_backup_history()), 1)
            restored = later.restore_last_backup(target)

            self.assertEqual(os.path.abspath(restored), os.path.abspath(target))
            with open(target, "r", encoding="utf-8") as handle:
                self.assertEqual(handle.read(), "before")

    def test_backup_history_drops_entries_whose_backup_file_is_gone(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "report.txt")
            with open(target, "w", encoding="utf-8") as handle:
                handle.write("before")
            executor = AutonomousExecutor()
            executor._save_document(tmp, "report", "after", preferred_format="txt")
            os.remove(executor.get_backup_history()[0]["backup_path"])

            later = AutonomousExecutor()

            self.assertEqual(later.get_recovery_candidates([target]), [])
            with self.assertRaises(FileNotFoundError):
                later.restore_last_backup(target)

    def test_corrupt_backup_index_starts_empty_and_keeps_backup_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "report.txt")
            with open(target, "w", encoding="utf-8") as handle:
                handle.write("before")
            executor = AutonomousExecutor()
            executor._save_document(tmp, "report", "after", preferred_format="txt")
            backup_path = executor.get_backup_history()[0]["backup_path"]
            index_path = ResourceManager.get_writable_path("backup_history.json")
            with open(index_path, "w", encoding="utf-8") as handle:
                handle.write("{broken")

            later = AutonomousExecutor()

            self.assertEqual(later.get_backup_history(), [])
            self.assertTrue(os.path.exists(backup_path))
            later._save_document(tmp, "report", "again", preferred_format="txt")
            self.assertEqual(len(later.get_backup_history()), 1)

    def test_backup_history_waits_for_recent_lock_without_losing_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            index_path = os.path.join(tmp, "backup_history.json")
            lock_path = index_path + ".lock"
            entries = []
            for name in ("first.txt", "second.txt"):
                target = os.path.join(tmp, name)
                with open(target, "w", encoding="utf-8") as handle:
                    handle.write(name)
                entries.append({"target_path": target, "backup_path": target})
            with open(lock_path, "w", encoding="utf-8"):
                pass

            start_writes = threading.Barrier(3)
            errors = []

            def append_entry(entry):
                start_writes.wait(timeout=5)
                try:
                    append_backup_history(index_path, entry, 20)
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=append_entry, args=(entry,)) for entry in entries]
            for thread in threads:
                thread.start()
            release_lock = threading.Timer(0.1, os.remove, args=(lock_path,))
            release_lock.start()
            start_writes.wait(timeout=5)
            for thread in threads:
                thread.join(timeout=5)
            release_lock.join(timeout=5)

            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(errors, [])
            saved = load_backup_history(index_path)
            self.assertEqual(len(saved), len(entries))
            self.assertEqual(
                {item["target_path"] for item in saved},
                {item["target_path"] for item in entries},
            )

    def test_backup_history_removes_stale_lock_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            index_path = os.path.join(tmp, "backup_history.json")
            lock_path = index_path + ".lock"
            target = os.path.join(tmp, "report.txt")
            with open(target, "w", encoding="utf-8") as handle:
                handle.write("backup")
            with open(lock_path, "w", encoding="utf-8"):
                pass
            stale_time = time.time() - 11
            os.utime(lock_path, (stale_time, stale_time))
            entry = {"target_path": target, "backup_path": target}

            self.assertEqual(append_backup_history(index_path, entry, 20), [entry])
            self.assertFalse(os.path.exists(lock_path))

    def test_unreadable_backup_index_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "report.txt")
            with open(target, "w", encoding="utf-8") as handle:
                handle.write("before")
            executor = AutonomousExecutor()
            executor._save_document(tmp, "report", "after", preferred_format="txt")
            saved = executor.get_backup_history()
            index_path = ResourceManager.get_writable_path("backup_history.json")
            entry = {"target_path": target, "backup_path": target}

            with patch("agent.backup_history.open", side_effect=PermissionError("locked"), create=True):
                self.assertEqual(append_backup_history(index_path, entry, 20), [entry])

            self.assertEqual(executor.get_backup_history(), saved)

    def test_python_runner_reads_backup_history_saved_by_another_executor(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "report.txt")
            with open(target, "w", encoding="utf-8") as handle:
                handle.write("before")
            AutonomousExecutor()._save_document(tmp, "report", "after", preferred_format="txt")
            runner = AutonomousExecutor()._write_python_runner(
                "restored = restore_last_backup(%r)\nprint(os.path.basename(restored))" % target
            )
            self.addCleanup(os.remove, runner)

            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                runpy.run_path(runner, run_name="__main__")

            self.assertEqual(output.getvalue().strip(), "report.txt")
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

    def test_run_python_returns_failed_result_when_safety_check_raises(self):
        executor = AutonomousExecutor()
        executor._capture_runtime_state = lambda: {}
        executor._attach_state_snapshot = lambda result, state_before: None
        executor._record_history = lambda result: None
        executor._safety = SimpleNamespace(check_python=lambda code: (_ for _ in ()).throw(RuntimeError("boom")))

        result = executor.run_python("print('x')")

        self.assertFalse(result.success)
        self.assertIn("boom", result.error)

    def test_run_python_releases_semaphore_when_state_capture_fails(self):
        executor = AutonomousExecutor()
        executor._capture_runtime_state = lambda: (_ for _ in ()).throw(RuntimeError("state boom"))
        executor._attach_state_snapshot = lambda result, state_before: None
        executor._record_history = lambda result: None

        result = executor.run_python("print('x')")

        self.assertFalse(result.success)
        self.assertIn("state boom", result.error)
        self.assertTrue(executor._python_slots.acquire(blocking=False))
        executor._python_slots.release()

    def test_normalize_python_code_splits_simple_semicolon_chain(self):
        executor = AutonomousExecutor()

        normalized = executor._normalize_python_code(
            "import os; x = os.getcwd(); y = x.split('\\\\'); print(y[-1])"
        )

        self.assertEqual(
            normalized,
            "import os\nx = os.getcwd()\ny = x.split('\\\\')\nprint(y[-1])",
        )

    def test_normalize_python_code_preserves_one_line_suite_semicolons(self):
        executor = AutonomousExecutor()

        normalized = executor._normalize_python_code("if ready: step_one(); step_two()")

        self.assertEqual(normalized, "if ready: step_one(); step_two()")

    def test_process_kill_stops_child_processes_on_windows(self):
        process = MagicMock(pid=4321)

        with (
            patch("agent.autonomous_executor.sys.platform", "win32"),
            patch("agent.autonomous_executor.subprocess.run") as run_mock,
        ):
            autonomous_executor_module._kill_process_tree(process)

        self.assertEqual(run_mock.call_args.args[0], ["taskkill", "/F", "/T", "/PID", "4321"])
        process.kill.assert_called_once()

    def test_do_run_shell_uses_filtered_child_environment(self):
        executor = AutonomousExecutor()
        fake_process = MagicMock()
        fake_process.communicate.return_value = ("ok", "")
        fake_process.returncode = 0

        with (
            patch("agent.autonomous_executor._build_child_env", return_value={"PATH": "safe"}) as env_mock,
            patch("agent.autonomous_executor.subprocess.Popen", return_value=fake_process) as popen_mock,
        ):
            result = executor._do_run_shell("echo ok")

        self.assertTrue(result.success)
        env_mock.assert_called_once()
        self.assertEqual(popen_mock.call_args.kwargs["env"]["PATH"], "safe")
        self.assertNotIn("OPENAI_API_KEY", popen_mock.call_args.kwargs["env"])

    def test_get_runtime_state_falls_back_when_automation_helpers_raise(self):
        executor = AutonomousExecutor()
        executor._automation.get_browser_state = lambda: (_ for _ in ()).throw(RuntimeError("browser fail"))
        executor._automation.get_active_window_title = lambda: (_ for _ in ()).throw(RuntimeError("window fail"))
        executor._automation.list_open_windows = lambda: (_ for _ in ()).throw(RuntimeError("list fail"))
        executor._automation.get_desktop_state = lambda: (_ for _ in ()).throw(RuntimeError("desktop fail"))
        executor._automation.get_learned_strategies = lambda: (_ for _ in ()).throw(RuntimeError("strategy fail"))
        executor._automation.get_learned_strategy_summary = lambda: (_ for _ in ()).throw(RuntimeError("summary fail"))
        executor._automation.get_planning_snapshot = lambda: (_ for _ in ()).throw(RuntimeError("planning fail"))
        executor._automation.get_planning_snapshot_summary = lambda: (_ for _ in ()).throw(RuntimeError("planning summary fail"))
        executor._automation.get_execution_policy = lambda: (_ for _ in ()).throw(RuntimeError("policy fail"))
        executor._automation.get_execution_policy_summary = lambda: (_ for _ in ()).throw(RuntimeError("policy summary fail"))

        state = executor.get_runtime_state()

        self.assertEqual(state["browser_state"], {})
        self.assertEqual(state["active_window_title"], "")
        self.assertEqual(state["open_window_titles"], [])
        self.assertEqual(state["desktop_state"], {})
        self.assertEqual(state["learned_strategies"], {})
        self.assertEqual(state["learned_strategy_summary"], "")
        self.assertEqual(state["planning_snapshot"], {})
        self.assertEqual(state["planning_snapshot_summary"], "")
        self.assertEqual(state["execution_policy"], {})
        self.assertEqual(state["execution_policy_summary"], "")

    def test_save_document_wraps_backup_errors(self):
        executor = AutonomousExecutor()
        executor._backup_file_if_exists = lambda path: (_ for _ in ()).throw(RuntimeError("backup fail"))

        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(RuntimeError):
                executor._save_document(tmp, "report", "content", preferred_format="txt")


if __name__ == "__main__":
    unittest.main()
