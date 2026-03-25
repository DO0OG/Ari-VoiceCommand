import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.real_verifier import RealVerifier


class _DummyExecResult:
    def __init__(self, success=True, output="", error=""):
        self.success = success
        self.output = output
        self.error = error


class _DummyStep:
    def __init__(self, description_kr):
        self.description_kr = description_kr


class _DummyStepResult:
    def __init__(self, description_kr, success=True, output="", error=""):
        self.step = _DummyStep(description_kr)
        self.exec_result = _DummyExecResult(success=success, output=output, error=error)


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


if __name__ == "__main__":
    unittest.main()
