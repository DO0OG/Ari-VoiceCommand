import json

import pytest

from agent.agent_planner import AgentPlanner


@pytest.mark.parametrize("target", ["네이버 웨일", "새로운 업무 앱", "크롬 작업 관리", "뉴스 보기"])
def test_named_application_routes_to_launch(target):
    steps = AgentPlanner(None)._build_template_plan(f"{target} 열어줘")
    assert len(steps) == 1
    assert f"launch_app({json.dumps(target, ensure_ascii=False)})" in steps[0].content
    assert "open_url(" not in steps[0].content


@pytest.mark.parametrize("goal", ["네이버 들어가줘", "네이버 열어줘", "네이버 사이트 열어줘"])
def test_site_request_keeps_web_route(goal):
    steps = AgentPlanner(None)._build_template_plan(goal)
    assert len(steps) == 1
    assert 'open_url("https://www.naver.com")' in steps[0].content


@pytest.mark.parametrize("goal", ["네이버 웨일 실행해줘", "네이버 웨일을 열어줘"])
def test_application_request_accepts_execution_and_particle(goal):
    steps = AgentPlanner(None)._build_template_plan(goal)
    assert 'launch_app("네이버 웨일")' in steps[0].content
