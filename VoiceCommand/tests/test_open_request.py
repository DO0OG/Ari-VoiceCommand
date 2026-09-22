import json
import unittest

from agent.agent_planner import AgentPlanner


class OpenRequestRoutingTests(unittest.TestCase):
    def test_named_application_routes_to_launch(self):
        for target in ("네이버 웨일", "새로운 업무 앱", "크롬 작업 관리", "뉴스 보기"):
            with self.subTest(target=target):
                steps = AgentPlanner(None)._build_template_plan(f"{target} 열어줘")
                self.assertEqual(len(steps), 1)
                expected = f"launch_app({json.dumps(target, ensure_ascii=False)})"
                self.assertIn(expected, steps[0].content)
                self.assertNotIn("open_url(", steps[0].content)

    def test_site_request_keeps_web_route(self):
        for goal in ("네이버 들어가줘", "네이버 열어줘", "네이버 사이트 열어줘"):
            with self.subTest(goal=goal):
                steps = AgentPlanner(None)._build_template_plan(goal)
                self.assertEqual(len(steps), 1)
                self.assertIn('open_url("https://www.naver.com")', steps[0].content)

    def test_application_request_accepts_execution_and_particle(self):
        for goal in ("네이버 웨일 실행해줘", "네이버 웨일을 열어줘"):
            with self.subTest(goal=goal):
                steps = AgentPlanner(None)._build_template_plan(goal)
                self.assertIn('launch_app("네이버 웨일")', steps[0].content)


if __name__ == "__main__":
    unittest.main()
