import os
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from agent.episode_memory import EpisodeMemory, GoalEpisode


class EpisodeMemoryTests(unittest.TestCase):
    def test_recent_summary_prefers_matching_goal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "episode_memory.json")
            memory = EpisodeMemory(filepath=path)
            memory.record(GoalEpisode(goal="메모장에 메모 저장", achieved=True, summary_kr="저장 성공", policy_summary="desktop=adaptive"))
            memory.record(GoalEpisode(goal="브라우저 로그인 후 다운로드", achieved=False, summary_kr="다운로드 실패", failure_kind="timeout", policy_summary="browser=learned_only"))

            summary = memory.get_recent_summary(goal="브라우저 다운로드", limit=2)

            self.assertIn("브라우저 로그인 후 다운로드", summary)
            self.assertIn("failure=timeout", summary)

    def test_goal_guidance_wraps_recent_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "episode_memory.json")
            memory = EpisodeMemory(filepath=path)
            memory.record(GoalEpisode(goal="report overwrite", achieved=False, summary_kr="복구 필요", failure_kind="overwrite"))

            guidance = memory.get_goal_guidance(goal="report overwrite", limit=1)

            self.assertIn("최근 유사 목표 에피소드", guidance)
            self.assertIn("report overwrite", guidance)


if __name__ == "__main__":
    unittest.main()
