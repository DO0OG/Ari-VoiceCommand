import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.agent_planner import AgentPlanner
from tests.support import DummyLLMProvider


class AgentPlannerParsingTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
