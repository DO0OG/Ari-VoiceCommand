import os
import sys
import unittest
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.real_verifier import RealVerifier


class _DummyExecResult:
    def __init__(self, success=True, output="", error="", state_delta_summary=""):
        self.success = success
        self.output = output
        self.error = error
        self.state_delta_summary = state_delta_summary


class _DummyStep:
    def __init__(self, description_kr):
        self.description_kr = description_kr


class _DummyStepResult:
    def __init__(self, description_kr, success=True, output="", error="", state_delta_summary=""):
        self.step = _DummyStep(description_kr)
        self.exec_result = _DummyExecResult(success=success, output=output, error=error, state_delta_summary=state_delta_summary)


class _DummyExecutor:
    def __init__(self):
        self.execution_globals = {
            "get_active_window_title": lambda: "",
            "list_open_windows": lambda: ["Chrome", "Example Domain - Chrome", "메모장"],
            "get_browser_state": lambda: {},
            "is_image_visible": lambda path, confidence=0.8: path.endswith("confirm.png"),
        }


class RealVerifierTests(unittest.TestCase):
    def test_open_action_can_verify_from_open_window_titles(self):
        verifier = RealVerifier(llm_provider=None, executor=_DummyExecutor())
        result = verifier.verify(
            "example 사이트 열어줘",
            [_DummyStepResult("브라우저 열기", output="opened https://example.com")],
        )

        self.assertTrue(result.verified)
        self.assertEqual(result.method, "heuristic")
        self.assertIn("Example Domain", result.evidence)

    def test_image_visibility_can_verify_gui_state(self):
        verifier = RealVerifier(llm_provider=None, executor=_DummyExecutor())
        result = verifier.verify(
            "확인 버튼이 보이는지 확인해줘",
            [_DummyStepResult("화면 상태 확인", output=r"template: C:\temp\confirm.png")],
        )

        self.assertTrue(result.verified)
        self.assertEqual(result.method, "heuristic")
        self.assertIn("confirm.png", result.evidence)

    def test_workflow_json_output_can_verify_desktop_state(self):
        verifier = RealVerifier(llm_provider=None, executor=_DummyExecutor())
        result = verifier.verify(
            "메모장에 메모 저장",
            [
                _DummyStepResult(
                    "데스크톱 앱 워크플로우 실행",
                    output='{"window_title":"제목 없음 - 메모장","actions":["성공: type","성공: hotkey(ctrl,s)"]}',
                )
            ],
        )

        self.assertTrue(result.verified)
        self.assertEqual(result.method, "heuristic")
        self.assertIn("메모장", result.evidence)

    def test_browser_last_action_summary_can_verify_state(self):
        executor = _DummyExecutor()
        executor.execution_globals["get_browser_state"] = lambda: {
            "last_action_summary": "성공: wait_url(https://example.com/dashboard) | 성공: click"
        }
        verifier = RealVerifier(llm_provider=None, executor=executor)

        result = verifier.verify(
            "대시보드 열어줘",
            [_DummyStepResult("브라우저 열기", output="opened browser")],
        )

        self.assertTrue(result.verified)
        self.assertEqual(result.method, "heuristic")
        self.assertIn("성공: wait_url", result.evidence)

    def test_state_delta_summary_can_verify_open_action(self):
        verifier = RealVerifier(llm_provider=None, executor=_DummyExecutor())
        result = verifier.verify(
            "example 사이트 열어줘",
            [_DummyStepResult("브라우저 열기", output="opened browser", state_delta_summary="browser_url=https://example.com | new_windows=Example Domain - Chrome")],
        )

        self.assertTrue(result.verified)
        self.assertEqual(result.method, "heuristic")
        self.assertIn("browser_url=https://example.com", result.evidence)

    def test_storage_verification_does_not_accept_wrong_folder_target(self):
        verifier = RealVerifier(llm_provider=None, executor=_DummyExecutor())

        result = verifier._heuristic_verify(
            '바탕화면에 "Ari autonomy test" 폴더를 만들고 보고서를 저장해줘',
            [_DummyStepResult("분석 보고서 저장", output=r"C:\Users\안지훈\Desktop\summary.md")],
        )

        self.assertIsNone(result)

    def test_extract_goal_folder_name_supports_unquoted_name(self):
        verifier = RealVerifier(llm_provider=None, executor=_DummyExecutor())

        folder_name = verifier._extract_goal_folder_name(
            "바탕화면에 Ari workspace audit 폴더를 만들고 보고서를 저장해줘"
        )

        self.assertEqual(folder_name, "Ari workspace audit")

    def test_ocr_verification_requires_named_folder_evidence(self):
        verifier = RealVerifier(llm_provider=None, executor=_DummyExecutor())
        step_results = [
            _DummyStepResult(
                "폴더 정리",
                output='{"lnk": 3, "desktop": 1, "json": 1}',
                state_delta_summary="new_paths=C:\\Users\\안지훈\\Desktop\\MEDIA",
            )
        ]

        with patch.object(
            RealVerifier,
            "_extract_expected_keywords",
            return_value=["Ari", "workspace", "audit", "Desktop", "summary"],
        ):
            with patch("agent.real_verifier.ocr_screen", return_value="Ari workspace audit Desktop summary"):
                result = verifier._ocr_verify(
                    "바탕화면에 Ari workspace audit 폴더를 만들고 보고서를 저장해줘",
                    step_results,
                )

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
