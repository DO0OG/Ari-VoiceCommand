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

    def test_recent_summary_filters_false_positive_developer_ocr_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "episode_memory.json")
            memory = EpisodeMemory(filepath=path)
            memory.record(
                GoalEpisode(
                    goal="VoiceCommand 저장소 전체 파악 후, 사용자 체감이 크고 회귀 위험이 낮은 개선 과제 1개를 선정하여 코드 변경 및 검증까지 완료",
                    achieved=True,
                    summary_kr="화면 OCR에서 목표 관련 텍스트를 확인했습니다. (10/10)",
                )
            )
            memory.record(
                GoalEpisode(
                    goal="VoiceCommand 저장소 전체 파악 후, 사용자 체감이 크고 회귀 위험이 낮은 개선 과제 1개를 선정하여 코드 변경 및 검증까지 완료",
                    achieved=False,
                    summary_kr="저장소 분석만 수행됐고 실제 코드 변경과 검증이 확인되지 않았습니다.",
                )
            )

            summary = memory.get_recent_summary(
                goal="VoiceCommand 저장소 전체 파악 후, 사용자 체감이 크고 회귀 위험이 낮은 개선 과제 1개를 선정하여 코드 변경 및 검증까지 완료",
                limit=2,
            )

            self.assertIn("실패", summary)
            self.assertNotIn("화면 OCR", summary)
            self.assertNotIn("바탕화면", summary)

    def test_recent_summary_prefers_high_overlap_matches_over_unrelated_recent_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "episode_memory.json")
            memory = EpisodeMemory(filepath=path)
            memory.record(
                GoalEpisode(
                    goal="VoiceCommand 저장소 전체 파악 후 코드 변경 및 검증 완료",
                    achieved=False,
                    summary_kr="검증 실패",
                    timestamp="2026-04-02T03:20:00",
                )
            )
            memory.record(
                GoalEpisode(
                    goal="바탕화면에 폴더 만들기, 창 제목 수집 및 분류, markdown 보고서 생성",
                    achieved=True,
                    summary_kr="실제 경로가 확인되어 작업을 완료했습니다.",
                    timestamp="2026-04-02T03:25:00",
                )
            )

            summary = memory.get_recent_summary(
                goal="VoiceCommand 저장소 전체 파악 후 코드 변경 및 검증 완료",
                limit=1,
            )

            self.assertIn("VoiceCommand 저장소", summary)
            self.assertNotIn("바탕화면", summary)


if __name__ == "__main__":
    unittest.main()
