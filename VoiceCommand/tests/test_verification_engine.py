import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.verification_engine import VerificationEngine


def _step_result(content="", description="단계", success=True, output="", error=""):
    return SimpleNamespace(
        step=SimpleNamespace(content=content, description_kr=description),
        exec_result=SimpleNamespace(success=success, output=output, error=error),
    )


class _PlannerStub:
    def __init__(self, *, developer_goal=True, allowed=True, verify_result=None):
        self._developer_goal = developer_goal
        self._allowed = allowed
        self.verify = MagicMock(return_value=verify_result or {"achieved": True, "summary": "플래너 검증"})

    def is_developer_goal(self, goal: str) -> bool:
        return self._developer_goal

    def is_allowed_developer_path(self, path: str, goal: str = "", context=None) -> bool:
        del goal, context
        return self._allowed


class VerificationEngineTests(unittest.TestCase):
    def test_invalid_developer_validation_rejects_py_compile_only(self):
        engine = VerificationEngine(_PlannerStub())

        self.assertTrue(
            engine._contains_invalid_developer_validation(
                "py -3.11 -m py_compile VoiceCommand/agent/foo.py"
            )
        )

    def test_invalid_developer_validation_rejects_non_voicecommand_tests_path(self):
        engine = VerificationEngine(_PlannerStub())

        self.assertTrue(
            engine._contains_invalid_developer_validation(
                "pytest tests/test_llm_provider.py"
            )
        )

    def test_valid_developer_validation_accepts_validate_repo_and_unittest(self):
        engine = VerificationEngine(_PlannerStub())

        self.assertTrue(
            engine._is_valid_developer_validation_signal(
                "py -3.11 VoiceCommand/validate_repo.py --compile-only\n"
                "python -m unittest VoiceCommand.tests.test_llm_provider"
            )
        )

    def test_verify_developer_goal_requires_code_change_and_validation(self):
        engine = VerificationEngine(_PlannerStub())

        verified, summary = engine.verify(
            "VoiceCommand 저장소 전체 파악 후 코드 변경 및 검증까지 완료",
            [_step_result(content="print('scan')", description="저장소 구조 스캔", output="scan done")],
        )

        self.assertFalse(verified)
        self.assertIn("실제 코드 변경과 검증", summary)

    def test_verify_developer_goal_rejects_scope_violation(self):
        engine = VerificationEngine(_PlannerStub(allowed=False))

        verified, summary = engine.verify(
            "VoiceCommand 저장소 전체 파악 후 코드 변경 및 검증까지 완료",
            [
                _step_result(
                    content="Path('market/ari_integration/ui/settings_dialog_patch.py').write_text('x')",
                    description="파일 수정",
                    output='{"target_file":"market/ari_integration/ui/settings_dialog_patch.py"}',
                )
            ],
        )

        self.assertFalse(verified)
        self.assertIn("허용 범위를 벗어난", summary)

    def test_verify_falls_back_to_planner_when_real_verifier_unavailable(self):
        planner = _PlannerStub(
            developer_goal=False,
            verify_result={"achieved": True, "summary": "플래너 폴백 성공"},
        )
        engine = VerificationEngine(planner)

        with patch("agent.real_verifier.get_real_verifier", side_effect=RuntimeError("unavailable")):
            verified, summary = engine.verify(
                "일반 사용자 목표",
                [_step_result(content="edit_file()", description="파일 수정", success=True, output="done")],
            )

        self.assertTrue(verified)
        self.assertEqual(summary, "플래너 폴백 성공")
        planner.verify.assert_called_once()

    def test_verify_returns_step_failure_before_planner_fallback(self):
        planner = _PlannerStub(developer_goal=False)
        engine = VerificationEngine(planner)

        with patch("agent.real_verifier.get_real_verifier", side_effect=RuntimeError("unavailable")):
            verified, summary = engine.verify(
                "일반 사용자 목표",
                [_step_result(content="edit_file()", description="파일 수정", success=False, error="boom")],
            )

        self.assertFalse(verified)
        self.assertEqual(summary, "일부 단계 실패")
        planner.verify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
