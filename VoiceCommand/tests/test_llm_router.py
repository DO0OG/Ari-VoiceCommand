import unittest

from agent.llm_router import LLMRouter


class LLMRouterTests(unittest.TestCase):
    def setUp(self):
        self.router = LLMRouter()

    def test_english_code_keyword_routes_to_code_agent(self):
        self.assertEqual(self.router.route("Please refactor this python test").task_type, "code_gen")

    def test_japanese_plan_keyword_routes_to_planner(self):
        self.assertEqual(self.router.route("自動化の計画を作って").task_type, "complex_plan")

    def test_english_long_keyword_routes_to_analysis(self):
        self.assertEqual(self.router.route("Can you compare these options?").task_type, "long_analysis")


if __name__ == "__main__":
    unittest.main()
