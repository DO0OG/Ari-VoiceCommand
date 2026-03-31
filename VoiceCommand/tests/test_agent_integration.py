import os
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.agent_orchestrator import AgentOrchestrator, StepResult
from agent.agent_planner import AgentPlanner, ActionStep
from agent.autonomous_executor import AutonomousExecutor, ExecutionResult
from agent.strategy_memory import StrategyMemory
from tests.support import DummyLLMProvider


class AgentIntegrationTests(unittest.TestCase):
    def _execute_template_steps(self, goal: str, desktop_path: str):
        planner = AgentPlanner(DummyLLMProvider())
        executor = AutonomousExecutor()
        executor.execution_globals["desktop_path"] = desktop_path
        orchestrator = AgentOrchestrator(executor, planner)
        steps = planner.decompose(goal, {})
        context = {}
        results = []
        for step in steps:
            if step.condition and not orchestrator._eval_condition(step.condition, context):
                continue
            result = executor.run_python(step.content, extra_globals={"step_outputs": dict(context)})
            self.assertTrue(result.success, msg=result.error or result.output)
            context[f"step_{step.step_id}_output"] = result.output[:300]
            results.append(result)
        return steps, results, context

    def test_create_folder_template_executes_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            goal = "바탕화면에 samplefolder 폴더 만들어줘"
            steps, results, _ = self._execute_template_steps(goal, tmp)
            self.assertEqual(len(steps), 1)
            self.assertEqual(len(results), 1)
            self.assertTrue(os.path.isdir(os.path.join(tmp, "samplefolder")))

    def test_directory_listing_template_saves_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "alpha.txt"), "w", encoding="utf-8") as handle:
                handle.write("hello")

            goal = "바탕화면 폴더 목록 저장해줘"
            _, _, context = self._execute_template_steps(goal, tmp)
            saved_path = context.get("step_1_output", "").strip()
            self.assertTrue(saved_path)
            self.assertTrue(os.path.exists(saved_path))

    def test_system_status_goal_builds_template_without_save(self):
        planner = AgentPlanner(DummyLLMProvider())
        steps = planner.decompose("시스템 상태 확인해줘", {})
        self.assertTrue(steps)
        self.assertEqual(len(steps), 1)
        self.assertIn("psutil.virtual_memory", steps[0].content)

    def test_security_audit_goal_builds_security_template(self):
        planner = AgentPlanner(DummyLLMProvider())
        steps = planner.decompose("자체 보안 점검 진행해줘", {})
        self.assertTrue(steps)
        self.assertEqual(len(steps), 1)
        self.assertIn("Windows Defender", steps[0].content)
        self.assertIn("netsh", steps[0].content)

    def test_strategy_memory_uses_token_similarity(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = StrategyMemory(filepath=os.path.join(tmp, "strategy.json"))
            mem.record("회의록 요약 작성", [], True, duration_ms=100)
            mem.record("브라우저 자동 로그인", [], False, error="timeout", failure_kind="timeout")
            context = mem.get_relevant_context("회의록 작성")
            self.assertIn("회의록 요약 작성", context)
            self.assertIn("회의록", mem._records[0].goal_tokens)

    def test_browser_download_goal_builds_template(self):
        planner = AgentPlanner(DummyLLMProvider())
        steps = planner.decompose("https://example.com 에서 파일 다운로드해서 저장해줘", {})
        self.assertTrue(steps)
        self.assertEqual(steps[0].description_kr, "다운로드 결과 폴더 준비")
        self.assertIn("run_resilient_browser_workflow", steps[1].content)
        self.assertIn("goal_hint", steps[1].content)
        self.assertIn("click_text", steps[1].content)

    def test_browser_link_collection_goal_builds_template(self):
        planner = AgentPlanner(DummyLLMProvider())
        steps = planner.decompose("https://example.com 링크 목록 수집해줘", {})
        self.assertTrue(steps)
        self.assertEqual(len(steps), 1)
        self.assertIn("read_links", steps[0].content)
        self.assertIn("run_resilient_browser_workflow", steps[0].content)

    def test_browser_link_collection_save_goal_builds_template(self):
        planner = AgentPlanner(DummyLLMProvider())
        steps = planner.decompose("https://example.com 링크 목록 수집해서 저장해줘", {})
        self.assertTrue(steps)
        self.assertEqual(len(steps), 3)
        self.assertIn("read_links", steps[1].content)
        self.assertIn("save_document", steps[2].content)

    def test_browser_login_goal_builds_template(self):
        planner = AgentPlanner(DummyLLMProvider())
        steps = planner.decompose("https://example.com 로그인 페이지 열어줘", {})
        self.assertTrue(steps)
        self.assertEqual(len(steps), 1)
        self.assertIn("click_text", steps[0].content)
        self.assertIn("로그인", steps[0].content)

    def test_browser_input_goal_builds_template(self):
        planner = AgentPlanner(DummyLLMProvider())
        steps = planner.decompose('https://example.com 검색창에 "아리" 입력해줘', {})
        self.assertTrue(steps)
        self.assertEqual(len(steps), 1)
        self.assertIn("'type'", steps[0].content)
        self.assertIn("아리", steps[0].content)

    def test_browser_input_save_goal_builds_template(self):
        planner = AgentPlanner(DummyLLMProvider())
        steps = planner.decompose('https://example.com 검색창에 "아리" 입력하고 저장해줘', {})
        self.assertTrue(steps)
        self.assertEqual(len(steps), 3)
        self.assertIn("'type'", steps[1].content)
        self.assertIn("save_document", steps[2].content)

    def test_browser_login_and_collect_goal_builds_template(self):
        planner = AgentPlanner(DummyLLMProvider())
        steps = planner.decompose("https://example.com 로그인 후 링크 수집해줘", {})
        self.assertTrue(steps)
        self.assertEqual(len(steps), 1)
        self.assertIn("click_text", steps[0].content)
        self.assertIn("read_links", steps[0].content)

    def test_notepad_goal_builds_desktop_workflow_template(self):
        planner = AgentPlanner(DummyLLMProvider())
        steps = planner._build_template_plan('메모장 열고 "테스트 메모" 입력해줘')
        self.assertTrue(steps)
        self.assertEqual(steps[0].description_kr, "데스크톱 앱 워크플로우 실행")
        self.assertIn("run_resilient_desktop_workflow", steps[0].content)
        self.assertIn("테스트 메모", steps[0].content)

    def test_explorer_goal_builds_desktop_workflow_template(self):
        planner = AgentPlanner(DummyLLMProvider())
        steps = planner._build_template_plan(r"C:\Users\runneradmin\Desktop 탐색기 열어줘")
        self.assertTrue(steps)
        self.assertIn("run_resilient_desktop_workflow", steps[0].content)
        self.assertIn(r"C:\\Users\\runneradmin\\Desktop", steps[0].content)

    def test_chrome_url_goal_builds_desktop_workflow_template(self):
        planner = AgentPlanner(DummyLLMProvider())
        steps = planner._build_template_plan("크롬으로 https://example.com 열어줘")
        self.assertTrue(steps)
        self.assertIn("run_resilient_desktop_workflow", steps[0].content)
        self.assertIn("open_url", steps[0].content)
        self.assertIn("https://example.com", steps[0].content)

    def test_vscode_goal_builds_desktop_workflow_template(self):
        planner = AgentPlanner(DummyLLMProvider())
        steps = planner._build_template_plan("VSCode 열어줘")
        self.assertTrue(steps)
        self.assertIn("run_resilient_desktop_workflow", steps[0].content)
        self.assertIn('"code"', steps[0].content)

    def test_calculator_goal_builds_desktop_workflow_template(self):
        planner = AgentPlanner(DummyLLMProvider())
        steps = planner._build_template_plan("계산기 실행해줘")
        self.assertTrue(steps)
        self.assertIn("run_resilient_desktop_workflow", steps[0].content)
        self.assertIn('"calculator"', steps[0].content)

    def test_rename_template_executes_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = os.path.join(tmp, "before.txt")
            with open(original, "w", encoding="utf-8") as handle:
                handle.write("rename me")

            goal = f"{original} rename to after.txt"
            _, results, _ = self._execute_template_steps(goal, tmp)

            self.assertEqual(len(results), 1)
            self.assertTrue(os.path.exists(os.path.join(tmp, "after.txt")))
            self.assertFalse(os.path.exists(original))

    def test_batch_rename_goal_builds_template(self):
        planner = AgentPlanner(DummyLLMProvider())
        steps = planner._build_template_plan(r"C:\temp 폴더 파일 이름 일괄 변경해줘")
        self.assertTrue(steps)
        self.assertIn("batch_rename_files", steps[0].content)

    def test_file_set_scan_goal_builds_template(self):
        planner = AgentPlanner(DummyLLMProvider())
        steps = planner._build_template_plan(r"C:\temp 폴더 대량 파일 세트 인식해줘")
        self.assertTrue(steps)
        self.assertIn("detect_file_set", steps[0].content)

    def test_downloads_folder_organize_goal_builds_template_without_explicit_path(self):
        planner = AgentPlanner(DummyLLMProvider())
        steps = planner.decompose("다운로드 폴더 정리해줘", {})
        self.assertTrue(steps)
        self.assertIn("organize_folder", steps[0].content)
        self.assertIn("Downloads", steps[0].content)

    def test_desktop_file_set_scan_goal_builds_template_without_explicit_path(self):
        planner = AgentPlanner(DummyLLMProvider())
        steps = planner.decompose("바탕화면 파일 세트 확인해줘", {})
        self.assertTrue(steps)
        self.assertIn("detect_file_set", steps[0].content)

    def test_organize_folder_template_executes_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "alpha.txt"), "w", encoding="utf-8") as handle:
                handle.write("a")
            with open(os.path.join(tmp, "beta.csv"), "w", encoding="utf-8") as handle:
                handle.write("col\n1\n")

            goal = f"{tmp} 폴더 확장자별로 정리해줘"
            _, results, _ = self._execute_template_steps(goal, tmp)

            self.assertEqual(len(results), 1)
            self.assertTrue(os.path.exists(os.path.join(tmp, "txt", "alpha.txt")))
            self.assertTrue(os.path.exists(os.path.join(tmp, "csv", "beta.csv")))

    def test_data_analysis_template_saves_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = os.path.join(tmp, "sample.csv")
            with open(csv_path, "w", encoding="utf-8") as handle:
                handle.write("name,score\nari,10\n")

            goal = f"{csv_path} CSV 분석해서 저장해줘"
            _, results, context = self._execute_template_steps(goal, tmp)

            self.assertEqual(len(results), 2)
            saved_path = context.get("step_1_output", "").strip()
            self.assertTrue(saved_path)
            self.assertTrue(os.path.exists(saved_path))
            with open(saved_path, "r", encoding="utf-8") as handle:
                report = handle.read()
            self.assertIn("row_count", report)

    def test_dependency_grouping_parallelizes_independent_read_steps(self):
        orchestrator = AgentOrchestrator(AutonomousExecutor(), AgentPlanner(DummyLLMProvider()))
        steps = [
            ActionStep(step_id=0, step_type="python", content="print('a')", description_kr="첫 읽기"),
            ActionStep(step_id=1, step_type="python", content="print('b')", description_kr="둘째 읽기"),
            ActionStep(step_id=2, step_type="python", content="open_url('https://example.com')", description_kr="브라우저 열기"),
            ActionStep(step_id=3, step_type="python", content="focus_window('Example Domain')", description_kr="브라우저 포커스"),
            ActionStep(step_id=4, step_type="python", content="print(step_outputs.get('step_2_output',''))", description_kr="브라우저 결과 확인"),
        ]

        groups = orchestrator._group_by_dependency(steps)

        self.assertEqual([step.step_id for step in groups[0]], [0, 1, 2])
        self.assertEqual([step.step_id for step in groups[1]], [3, 4])

    def test_dependency_grouping_separates_window_target_conflicts(self):
        orchestrator = AgentOrchestrator(AutonomousExecutor(), AgentPlanner(DummyLLMProvider()))
        steps = [
            ActionStep(step_id=0, step_type="python", content="run_desktop_workflow(goal_hint='메모장 저장', expected_window='메모장')", description_kr="메모장 작업"),
            ActionStep(step_id=1, step_type="python", content="run_desktop_workflow(goal_hint='메모장 저장', expected_window='메모장')", description_kr="메모장 후속 작업"),
        ]

        groups = orchestrator._group_by_dependency(steps)

        self.assertEqual(len(groups), 2)

    def test_adaptive_context_includes_state_change_summary(self):
        orchestrator = AgentOrchestrator(AutonomousExecutor(), AgentPlanner(DummyLLMProvider()))
        step = ActionStep(step_id=0, step_type="python", content="open_url('https://example.com')", description_kr="브라우저 열기")
        exec_result = ExecutionResult(
            success=False,
            error="timeout",
            state_delta_summary="browser_url=https://example.com | new_windows=Example Domain - Chrome",
        )

        context = orchestrator._build_adaptive_context([
            StepResult(step=step, exec_result=exec_result, failure_kind="timeout")
        ])

        self.assertIn("browser_url=https://example.com", context.get("실패_후_상태변화", ""))
        self.assertIn("timeout", context.get("재계획_이유", ""))
        self.assertIn("example.com", context.get("실패_대상_도메인", ""))
        if context.get("복구_가이드"):
            self.assertIn("restore_last_backup", context.get("복구_가이드", ""))

    def test_runtime_context_tracks_last_targets(self):
        orchestrator = AgentOrchestrator(AutonomousExecutor(), AgentPlanner(DummyLLMProvider()))
        context = {}
        exec_result = ExecutionResult(
            success=True,
            output="opened https://example.com",
            code_or_cmd='open_url("https://example.com/dashboard"); wait_for_window(title_substring="Chrome", goal_hint="대시보드")',
            state_delta_summary="browser_url=https://example.com/dashboard | new_windows=Dashboard - Chrome",
        )

        orchestrator._update_runtime_context(context, exec_result)

        self.assertIn("example.com", context.get("last_target_domains", ""))
        self.assertIn("Chrome", context.get("last_target_windows", ""))
        self.assertIn("대시보드", context.get("last_goal_hints", ""))

    def test_runtime_context_tracks_execution_policy_and_backups(self):
        orchestrator = AgentOrchestrator(AutonomousExecutor(), AgentPlanner(DummyLLMProvider()))
        orchestrator.executor.get_runtime_state = lambda: {
            "active_window_title": "",
            "open_window_titles": [],
            "browser_state": {},
            "desktop_state": {},
            "learned_strategies": {},
            "learned_strategy_summary": "",
            "planning_snapshot": {},
            "planning_snapshot_summary": "",
            "execution_policy": {"recommended_browser_plan": {"plan_type": "adaptive"}},
            "execution_policy_summary": "browser=adaptive score=4.0",
            "last_execution_success": True,
            "last_execution_output": "",
            "last_execution_error": "",
            "last_state_delta_summary": "",
            "recent_state_transitions": [],
            "backup_history": [{"target_path": r"C:\\temp\\report.txt", "backup_path": r"C:\\temp\\.ari_backups\\1_report.txt"}],
            "recovery_candidates": [{"target_path": r"C:\\temp\\report.txt", "backup_path": r"C:\\temp\\.ari_backups\\1_report.txt"}],
        }
        context = {}

        orchestrator._update_runtime_context(context, ExecutionResult(success=True))

        self.assertIn("browser=adaptive", context.get("execution_policy_summary", ""))
        self.assertIn("recommended_browser_plan", context.get("execution_policy_json", ""))
        self.assertIn(".ari_backups", context.get("backup_history_json", ""))
        self.assertIn(".ari_backups", context.get("recovery_candidates_json", ""))


if __name__ == "__main__":
    unittest.main()
