import unittest


from agent.planner_json_utils import extract_balanced, parse_json_array, parse_json_object


class PlannerJsonUtilsTests(unittest.TestCase):
    def test_parse_json_array_recovers_first_complete_item_from_truncated_response(self):
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

        items = parse_json_array(raw)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["step_type"], "python")
        self.assertEqual(items[0]["description_kr"], "첫 단계")

    def test_parse_json_object_strips_code_fence_before_parsing(self):
        raw = """```json
{
  "step_type": "python",
  "content": "print('ok')",
  "description_kr": "단계 설명"
}
```"""

        data = parse_json_object(raw)

        self.assertEqual(data["step_type"], "python")
        self.assertEqual(data["description_kr"], "단계 설명")

    def test_extract_balanced_ignores_brackets_inside_strings(self):
        raw = '{"message": "[] braces in string", "ok": true} trailing'

        balanced = extract_balanced(raw, "{", "}")

        self.assertEqual(balanced, '{"message": "[] braces in string", "ok": true}')


if __name__ == "__main__":
    unittest.main()
