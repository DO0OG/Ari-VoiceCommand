import os
import sys
import unittest
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.real_verifier import RealVerifier, VerificationResult


class _DummyExecResult:
    def __init__(self, success=True, output="", error="", state_delta_summary=""):
        self.success = success
        self.output = output
        self.error = error
        self.state_delta_summary = state_delta_summary


class _DummyStep:
    def __init__(self, description_kr, content=""):
        self.description_kr = description_kr
        self.content = content


class _DummyStepResult:
    def __init__(self, description_kr, success=True, output="", error="", state_delta_summary="", content=""):
        self.step = _DummyStep(description_kr, content=content)
        self.exec_result = _DummyExecResult(success=success, output=output, error=error, state_delta_summary=state_delta_summary)


class _DummyExecutor:
    def __init__(self):
        self.execution_globals = {
            "get_active_window_title": lambda: "",
            "list_open_windows": lambda: ["Chrome", "Example Domain - Chrome", "메모장"],
            "get_browser_state": lambda: {},
            "is_image_visible": lambda path, confidence=0.8: path.endswith("confirm.png"),
        }


class _FakeCompletionClient:
    def __init__(self, response_text="print(True)"):
        self.response_text = response_text
        self.calls = []
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return type(
            "Resp",
            (),
            {
                "choices": [
                    type(
                        "Choice",
                        (),
                        {"message": type("Msg", (), {"content": self.response_text})()},
                    )()
                ]
            },
        )()


class _SequencedCompletionClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        current = self.responses.pop(0)
        if isinstance(current, Exception):
            raise current
        content, finish_reason = current
        return type(
            "Resp",
            (),
            {
                "choices": [
                    type(
                        "Choice",
                        (),
                        {
                            "message": type("Msg", (), {"content": content})(),
                            "finish_reason": finish_reason,
                        },
                    )()
                ]
            },
        )()


class _PlannerFallbackLLM:
    def __init__(self, planner_client, base_client, execution_client):
        self.client = base_client
        self.provider = "nvidia_nim"
        self.model = "selected-base-model"
        self.planner_client = planner_client
        self.planner_provider = "gemini"
        self.planner_model = "selected-planner-model"
        self.execution_client = execution_client
        self.execution_provider = "groq"
        self.execution_model = "selected-execution-model"

    def get_role_fallback_targets(self, role):
        if role == "planner":
            return [
                (self.planner_client, self.planner_provider, self.planner_model),
                (self.client, self.provider, self.model),
                (self.execution_client, self.execution_provider, self.execution_model),
            ]
        return [(self.client, self.provider, self.model)]


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

    def test_generate_verification_code_uses_planner_client_and_model(self):
        base_client = _FakeCompletionClient("print(False)")
        planner_client = _FakeCompletionClient("print(True)")
        llm = type(
            "LLM",
            (),
            {
                "client": base_client,
                "provider": "nvidia_nim",
                "model": "base-model",
                "planner_client": planner_client,
                "planner_provider": "gemini",
                "planner_model": "gemini-2.5-flash",
            },
        )()
        verifier = RealVerifier(llm_provider=llm, executor=_DummyExecutor())

        code = verifier._generate_verification_code(
            "저장소 작업이 실제로 검증됐는지 확인해줘",
            [_DummyStepResult("검증 단계", output="[validate] compile-only checks passed")],
        )

        self.assertEqual(code, "print(True)")
        self.assertEqual(len(base_client.calls), 0)
        self.assertEqual(planner_client.calls[0]["model"], "gemini-2.5-flash")

    def test_generate_verification_code_skips_non_python_text_response(self):
        planner_client = _FakeCompletionClient("(걱정) 인터넷 연결이 없어서 AI 기능이 제한돼요.")
        llm = type(
            "LLM",
            (),
            {
                "client": planner_client,
                "provider": "gemini",
                "model": "base-model",
                "planner_client": planner_client,
                "planner_provider": "gemini",
                "planner_model": "gemini-2.5-flash",
            },
        )()
        verifier = RealVerifier(llm_provider=llm, executor=_DummyExecutor())

        code = verifier._generate_verification_code(
            "검증 코드 생성",
            [_DummyStepResult("검증 단계", output="something")],
        )

        self.assertIsNone(code)

    def test_call_planner_llm_retries_after_quota_error_and_continues_code(self):
        planner_client = _SequencedCompletionClient([
            Exception("429 RESOURCE_EXHAUSTED: retry in 1s"),
            ("print('hel", "length"),
            ("lo')\nprint(True)", "stop"),
        ])
        llm = type(
            "LLM",
            (),
            {
                "client": planner_client,
                "provider": "gemini",
                "model": "base-model",
                "planner_client": planner_client,
                "planner_provider": "gemini",
                "planner_model": "gemini-2.5-flash",
            },
        )()
        verifier = RealVerifier(llm_provider=llm, executor=_DummyExecutor())

        with patch("agent.real_verifier.time.sleep", return_value=None):
            code = verifier._call_planner_llm("검증 코드 생성")

        self.assertEqual(code, "print('hello')\nprint(True)")
        self.assertEqual(len(planner_client.calls), 3)

    def test_call_planner_llm_falls_back_to_other_selected_model_after_planner_quota_exhaustion(self):
        planner_client = _SequencedCompletionClient([
            Exception("429 RESOURCE_EXHAUSTED: retry in 1s"),
            Exception("429 RESOURCE_EXHAUSTED: retry in 1s"),
            Exception("429 RESOURCE_EXHAUSTED: retry in 1s"),
        ])
        base_client = _SequencedCompletionClient([
            ("print(True)", "stop"),
        ])
        execution_client = _SequencedCompletionClient([])
        verifier = RealVerifier(
            llm_provider=_PlannerFallbackLLM(planner_client, base_client, execution_client),
            executor=_DummyExecutor(),
        )

        with patch("agent.real_verifier.time.sleep", return_value=None):
            code = verifier._call_planner_llm("검증 코드 생성")

        self.assertEqual(code, "print(True)")
        self.assertEqual(len(base_client.calls), 1)

    def test_developer_goal_prefers_validation_output_over_ocr(self):
        verifier = RealVerifier(llm_provider=None, executor=_DummyExecutor())

        result = verifier.verify(
            "VoiceCommand 저장소 전체 파악 후, 사용자 체감이 크고 회귀 위험이 낮은 개선 과제 1개를 선정하여 코드 변경 및 검증까지 완료",
            [
                _DummyStepResult(
                    "코드 수정",
                    output="changed VoiceCommand/agent/agent_planner.py",
                    content="from pathlib import Path\nPath('VoiceCommand/agent/agent_planner.py').write_text('patched', encoding='utf-8')",
                ),
                _DummyStepResult(
                    "검증 실행",
                    output="[validate] compile-only checks passed",
                    content="py -3.11 VoiceCommand\\validate_repo.py --compile-only",
                ),
            ],
        )

        self.assertTrue(result.verified)
        self.assertEqual(result.method, "developer")
        self.assertIn("검증 명령", result.summary)

    def test_developer_goal_treats_fail_output_as_failure(self):
        verifier = RealVerifier(llm_provider=None, executor=_DummyExecutor())

        result = verifier.verify(
            "VoiceCommand 저장소 전체 파악 후 코드 변경 및 검증까지 완료",
            [
                _DummyStepResult(
                    "코드 수정",
                    output="patched file",
                    content="from pathlib import Path\nPath('VoiceCommand/agent/foo.py').write_text('x', encoding='utf-8')",
                ),
                _DummyStepResult(
                    "검증 실행",
                    output="FAIL: python -m pytest returned error\nNo module named pytest",
                    content="python -m pytest tests/test_example.py",
                ),
            ],
        )

        self.assertFalse(result.verified)
        self.assertEqual(result.method, "developer")
        self.assertIn("실패 신호", result.summary)

    def test_run_verification_rejects_mutating_code(self):
        verifier = RealVerifier(llm_provider=None, executor=_DummyExecutor())

        result = verifier._run_verification(
            "import subprocess\nsubprocess.run(['py', '-3.11', 'VoiceCommand/validate_repo.py'])\nprint(True)"
        )

        self.assertIsNone(result)

    def test_developer_goal_does_not_fallback_to_ocr_success(self):
        verifier = RealVerifier(llm_provider=None, executor=_DummyExecutor())

        with patch("agent.real_verifier.ocr_screen", return_value="VoiceCommand 저장소 코드 변경 검증 완료"):
            with patch.object(
                RealVerifier,
                "_llm_verify",
                return_value=VerificationResult(
                    verified=False,
                    method="llm",
                    evidence="",
                    summary="LLM 검증 실패",
                ),
            ):
                result = verifier.verify(
                    "VoiceCommand 저장소 전체 파악 후, 사용자 체감이 크고 회귀 위험이 낮은 개선 과제 1개를 선정하여 코드 변경 및 검증까지 완료",
                    [
                        _DummyStepResult("저장소 구조 스캔", output='{"agent": {"file_count": 1}}', content="print('scan')"),
                        _DummyStepResult("검증 스크립트 확인", output="validate_repo.py lines", content="print('validate')"),
                    ],
                )

        self.assertFalse(result.verified)
        self.assertEqual(result.method, "llm")


if __name__ == "__main__":
    unittest.main()
