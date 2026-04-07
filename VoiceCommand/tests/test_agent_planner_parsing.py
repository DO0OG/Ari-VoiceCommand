import os
import sys
import types
import unittest
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.agent_planner import AgentPlanner
from tests.support import DummyLLMProvider


class _FakePlannerCompletionClient:
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


class _RoleFallbackProvider:
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


class AgentPlannerParsingTests(unittest.TestCase):
    def test_strategy_memory_helpers_return_context_and_failure_hints(self):
        planner = AgentPlanner(DummyLLMProvider())
        fake_module = types.ModuleType("agent.strategy_memory")

        class _FakeStrategyMemory:
            def get_relevant_context(self, goal):
                return f"context:{goal}"

            def recent_failures(self, goal):
                return [f"{goal}-실패1", f"{goal}-실패2"]

        fake_module.get_strategy_memory = lambda: _FakeStrategyMemory()

        with patch.dict(sys.modules, {"agent.strategy_memory": fake_module}):
            self.assertEqual(planner._get_strategy_context("목표"), "context:목표")
            self.assertEqual(planner._get_failure_hints("목표"), "- 목표-실패1\n- 목표-실패2")

    def test_memory_helpers_fail_closed_when_optional_modules_raise(self):
        planner = AgentPlanner(DummyLLMProvider())
        strategy_module = types.ModuleType("agent.strategy_memory")
        episode_module = types.ModuleType("agent.episode_memory")

        def _raise_strategy():
            raise RuntimeError("strategy unavailable")

        def _raise_episode():
            raise RuntimeError("episode unavailable")

        strategy_module.get_strategy_memory = _raise_strategy
        episode_module.get_episode_memory = _raise_episode

        with patch.dict(
            sys.modules,
            {
                "agent.strategy_memory": strategy_module,
                "agent.episode_memory": episode_module,
            },
        ):
            self.assertEqual(planner._get_strategy_context("목표"), "")
            self.assertEqual(planner._get_failure_hints("목표"), "")
            self.assertEqual(planner._get_episode_failure_patterns("목표"), "")

    def test_parse_array_recovers_first_complete_item_from_truncated_response(self):
        planner = AgentPlanner(DummyLLMProvider())
        raw = """```json
[
  {
    "step_type": "python",
    "content": "print('ok')",
    "description_kr": "첫 단계"
  },
  {
    "step_type": "python",
    "content": "print('next')",
    "description_"""

        items = planner._parse_array(raw)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["step_type"], "python")
        self.assertEqual(items[0]["description_kr"], "첫 단계")

    def test_parse_object_recovers_truncated_object_when_complete_brace_exists(self):
        planner = AgentPlanner(DummyLLMProvider())
        raw = """```json
{
  "step_type": "python",
  "content": "print('ok')",
  "description_kr": "단계 설명"
}
```"""

        data = planner._parse_object(raw)

        self.assertEqual(data["step_type"], "python")
        self.assertEqual(data["description_kr"], "단계 설명")

    def test_repository_goal_skips_template_and_does_not_infer_documents_folder(self):
        planner = AgentPlanner(DummyLLMProvider())
        goal = (
            "이 저장소를 먼저 전체 파악한 뒤 VoiceCommand/agent, VoiceCommand/core, VoiceCommand/ui, "
            "VoiceCommand/plugins, VoiceCommand/tests, docs 범위에서 사용자 체감이 크고 회귀 위험이 낮은 "
            "개선 과제 1개를 스스로 선정해 실제 코드 변경까지 진행하고, 필요하면 테스트와 문서도 함께 수정한 뒤, "
            "py -3.11 VoiceCommand/validate_repo.py 또는 --compile-only와 영향받는 테스트를 직접 실행하고, "
            "실패하면 원인을 분석해 한 번 더 고친 다음, 마지막에 수정한 파일·실행한 검증 명령·실제 결과·남은 리스크만 간결하게 보고해줘."
        )

        profile = planner._profile_goal(goal)

        self.assertTrue(planner.is_developer_goal(goal))
        self.assertEqual(profile.source_path, "")
        self.assertEqual(planner._build_template_plan(goal), [])

    def test_short_voicecommand_repository_goal_is_treated_as_developer_work(self):
        planner = AgentPlanner(DummyLLMProvider())
        goal = "VoiceCommand 저장소 전체 파악 후, 사용자 체감이 크고 회귀 위험이 낮은 개선 과제 1개를 선정하여 코드 변경 및 검증까지 완료"

        self.assertTrue(planner.is_developer_goal(goal))
        self.assertEqual(planner._build_template_plan(goal), [])

    def test_decompose_repository_goal_uses_bootstrap_plan_when_llm_response_is_truncated(self):
        provider = DummyLLMProvider()
        provider.planner_model = "dummy"
        provider.planner_client = None
        provider.planner_provider = "openai"
        planner = AgentPlanner(provider)
        goal = (
            "VoiceCommand/agent, VoiceCommand/core, VoiceCommand/ui, VoiceCommand/plugins, "
            "VoiceCommand/tests, docs 범위를 분석하여 회귀 위험은 낮지만 사용자 경험 개선이 큰 작업을 찾아서 직접 구현하고 검증까지 완료"
        )
        raw = """```json
[
  {
    "step_type": "python",
    "content": "import os\\n\\ntarget_dirs = [\\n    'VoiceCommand/"""

        with patch.object(planner, "_call_llm", return_value=raw):
            steps = planner.decompose(goal, {})

        self.assertEqual(len(steps), 3)
        self.assertEqual(steps[0].description_kr, "저장소 구조 스캔")
        self.assertTrue(all(step.step_type == "python" for step in steps))
        self.assertEqual(steps[2].description_kr, "관련 테스트 목록 수집")
        self.assertIn("module_dir", steps[0].content)
        self.assertIn("repo_root", steps[0].content)
        self.assertNotIn(".\\VoiceCommand\\", steps[1].content)

    def test_decompose_repository_goal_retries_with_compact_followup_prompt(self):
        provider = DummyLLMProvider()
        provider.planner_model = "dummy"
        provider.planner_client = None
        provider.planner_provider = "openai"
        planner = AgentPlanner(provider)
        goal = (
            "요청하신 6단계(탐색-선정-수정-검증-재수정-보고)를 자율적으로 수행합니다. 저장소 구조를 먼저 파악하고, "
            "VoiceCommand/{agent,core,ui,plugins,tests}와 docs 범위에서 회귀 위험 낮으면서 사용자 체감 큰 1개 과제를 골라 "
            "실제 코드 수정부터 테스트·문서까지 일괄 처리한 뒤 validate_repo.py와 영향 테스트를 실행합니다."
        )
        context = {
            "step_0_output": '{"agent":{"file_count":2,"samples":["agent_planner.py","llm_provider.py"]},"ui":{"file_count":1,"samples":["settings_dialog.py"]}}',
            "step_1_output": 'parser.add_argument("--compile-only", action="store_true")',
            "step_2_output": '["test_llm_provider.py","test_agent_planner_parsing.py"]',
            "이전_시도": "탐색만 수행되어 실제 코드 변경과 검증이 확인되지 않았습니다.",
        }
        truncated = """```json
[
  {
    "step_type": "python",
    "content": "import os\\n\\nmodule_dir = os.path."""
        retry = """```json
[
  {
    "step_type": "python",
    "content": "from pathlib import Path\\nPath('VoiceCommand/agent/agent_planner.py').write_text('patched', encoding='utf-8')",
    "description_kr": "후보 파일 수정",
    "expected_output": "changed file",
    "condition": "",
    "on_failure": "abort"
  },
  {
    "step_type": "shell",
    "content": "py -3.11 VoiceCommand\\\\validate_repo.py --compile-only; py -3.11 -m unittest VoiceCommand.tests.test_agent_planner_parsing",
    "description_kr": "검증 실행",
    "expected_output": "validation output",
    "condition": "",
    "on_failure": "abort"
  }
]"""

        with patch.object(planner, "_call_llm", side_effect=[truncated, retry]):
            steps = planner.decompose(goal, context)

        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0].description_kr, "후보 파일 수정")
        self.assertEqual(steps[1].step_type, "shell")

    def test_decompose_repository_goal_does_not_fallback_to_synthetic_edit_after_retry_failure(self):
        provider = DummyLLMProvider()
        provider.planner_model = "dummy"
        provider.planner_client = None
        provider.planner_provider = "openai"
        planner = AgentPlanner(provider)
        goal = "VoiceCommand 저장소 전체 파악 후 코드 변경 및 검증까지 완료"
        context = {
            "step_0_output": '{"agent":{"file_count":2}}',
            "step_1_output": "--compile-only",
        }
        truncated = """```json
[
  {
    "step_type": "python",
    "content": "import os\\npath = os.path."""

        with patch.object(planner, "_call_llm", side_effect=[truncated, truncated]):
            steps = planner.decompose(goal, context)

        self.assertEqual(steps, [])

    def test_call_llm_retries_after_rate_limit_and_continues_truncated_json(self):
        provider = DummyLLMProvider()
        provider.planner_model = "dummy"
        provider.planner_provider = "openai"
        provider.planner_client = _FakePlannerCompletionClient([
            Exception("429 RESOURCE_EXHAUSTED: retry in 1s"),
            ('[{"step_type":"python","content":"print(1)"', "length"),
            (',"description_kr":"단계 1"}]', "stop"),
        ])
        provider.client = provider.planner_client
        planner = AgentPlanner(provider)

        with patch("agent.agent_planner.time.sleep", return_value=None):
            raw = planner._call_llm("JSON only")

        self.assertIn('"description_kr":"단계 1"', raw)
        self.assertEqual(len(provider.planner_client.calls), 3)
        self.assertEqual(
            provider.planner_client.calls[1].get("response_format"),
            {"type": "json_object"},
        )

    def test_call_llm_falls_back_to_other_selected_model_after_planner_quota_exhaustion(self):
        planner_client = _FakePlannerCompletionClient([
            Exception("429 RESOURCE_EXHAUSTED: retry in 1s"),
            Exception("429 RESOURCE_EXHAUSTED: retry in 1s"),
            Exception("429 RESOURCE_EXHAUSTED: retry in 1s"),
        ])
        base_client = _FakePlannerCompletionClient([
            ('[{"step_type":"python","content":"print(1)","description_kr":"base fallback"}]', "stop"),
        ])
        execution_client = _FakePlannerCompletionClient([])
        planner = AgentPlanner(_RoleFallbackProvider(planner_client, base_client, execution_client))

        with patch("agent.agent_planner.time.sleep", return_value=None):
            raw = planner._call_llm("JSON only", role_hint="planner")

        self.assertIn('"description_kr":"base fallback"', raw)
        self.assertEqual(len(base_client.calls), 1)

    def test_call_llm_adds_json_response_format_for_groq(self):
        provider = DummyLLMProvider()
        provider.planner_model = "dummy"
        provider.planner_provider = "groq"
        provider.planner_client = _FakePlannerCompletionClient([
            ('[{"step_type":"python","content":"print(1)","description_kr":"groq"}]', "stop"),
        ])
        provider.client = provider.planner_client
        planner = AgentPlanner(provider)

        raw = planner._call_llm("JSON only")

        self.assertIn('"description_kr":"groq"', raw)
        self.assertEqual(
            provider.planner_client.calls[0].get("response_format"),
            {"type": "json_object"},
        )

    def test_call_llm_skips_json_response_format_for_ollama(self):
        provider = DummyLLMProvider()
        provider.planner_model = "dummy"
        provider.planner_provider = "ollama"
        provider.planner_client = _FakePlannerCompletionClient([
            ('[{"step_type":"python","content":"print(1)","description_kr":"ollama"}]', "stop"),
        ])
        provider.client = provider.planner_client
        planner = AgentPlanner(provider)

        raw = planner._call_llm("JSON only")

        self.assertIn('"description_kr":"ollama"', raw)
        self.assertNotIn("response_format", provider.planner_client.calls[0])

    def test_decompose_repository_goal_rejects_disallowed_repo_root_env_plan(self):
        provider = DummyLLMProvider()
        provider.planner_model = "dummy"
        provider.planner_client = None
        provider.planner_provider = "openai"
        planner = AgentPlanner(provider)
        goal = "VoiceCommand 저장소 전체 파악 후 코드 변경 및 검증까지 완료"
        raw = """[
  {
    "step_type": "python",
    "content": "import os\\nrepo_root = os.environ['repo_root']\\nprint(repo_root)",
    "description_kr": "잘못된 계획"
  }
]"""

        with patch.object(planner, "_call_llm", return_value=raw):
            steps = planner.decompose(goal, {})

        self.assertEqual(len(steps), 3)
        self.assertEqual(steps[0].description_kr, "저장소 구조 스캔")

    def test_developer_scope_helper_rejects_market_and_voicecommand_docs_paths(self):
        planner = AgentPlanner(DummyLLMProvider())
        goal = (
            "VoiceCommand/agent, VoiceCommand/core, VoiceCommand/ui, VoiceCommand/plugins, "
            "VoiceCommand/tests, docs 범위에서 코드 변경 및 검증까지 완료"
        )

        self.assertFalse(planner.is_allowed_developer_path("market/ari_integration/ui/settings_dialog_patch.py", goal=goal))
        self.assertFalse(planner.is_allowed_developer_path("VoiceCommand/docs/README.md", goal=goal))
        self.assertTrue(planner.is_allowed_developer_path("VoiceCommand/agent/agent_planner.py", goal=goal))
        self.assertTrue(planner.is_allowed_developer_path("docs/README.md", goal=goal))

    def test_decompose_repository_goal_rejects_py_compile_only_retry_plan(self):
        provider = DummyLLMProvider()
        provider.planner_model = "dummy"
        provider.planner_client = None
        provider.planner_provider = "openai"
        planner = AgentPlanner(provider)
        goal = (
            "VoiceCommand/agent, VoiceCommand/core, VoiceCommand/ui, VoiceCommand/plugins, "
            "VoiceCommand/tests, docs 범위를 분석한 뒤 validate_repo.py와 영향받는 테스트를 직접 실행해 검증까지 완료"
        )
        context = {
            "step_0_output": '{"agent":{"file_count":2,"samples":["agent_planner.py","llm_provider.py"]},"docs":{"file_count":1,"samples":["README.md"]}}',
            "step_1_output": "validate_repo_path=D:/Git/Ari-VoiceCommand/VoiceCommand/validate_repo.py",
            "step_2_output": '["test_llm_provider.py","test_agent_planner_parsing.py"]',
        }
        invalid = """[
  {
    "step_type": "python",
    "content": "from pathlib import Path\\nPath('VoiceCommand/agent/foo.py').write_text('patched', encoding='utf-8')",
    "description_kr": "파일 수정"
  },
  {
    "step_type": "shell",
    "content": "py -3.11 -m py_compile VoiceCommand/agent/foo.py",
    "description_kr": "컴파일 검증"
  }
]"""

        with patch.object(planner, "_call_llm", side_effect=[invalid, invalid]):
            steps = planner.decompose(goal, context)

        self.assertEqual(steps, [])


if __name__ == "__main__":
    unittest.main()
