import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from agent.speech_scheduler import EventSpeechScheduler, choose_phrase
from core.mood_state import MoodState
from core.settings_schema import DEFAULT_SETTINGS


class SpeechSchedulerTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 29, 12, 0)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.messages = []
        self.guards = {"other_window": True}
        self.scheduler_index = 0

    def create_scheduler(self, **kwargs):
        self.scheduler_index += 1
        return EventSpeechScheduler(
            self.messages.append,
            guard_state=lambda: self.guards,
            state_path=os.path.join(
                self.directory.name,
                f"speech-{self.scheduler_index}.json",
            ),
            clock=lambda: self.now,
            **kwargs,
        )

    def test_each_guard_defers_until_clear(self):
        for name in (
            "locked",
            "away",
            "quiet",
            "fullscreen",
            "game",
            "tts",
            "agent",
        ):
            with self.subTest(guard=name):
                self.messages.clear()
                self.guards.clear()
                self.guards["other_window"] = True
                self.guards[name] = True
                scheduler = self.create_scheduler()
                scheduler.request("return")
                self.assertFalse(scheduler.tick())
                self.assertEqual(self.messages, [])

                self.guards[name] = False
                self.assertTrue(scheduler.tick())
                self.assertEqual(len(self.messages), 1)

    def test_agent_result_waits_for_another_window(self):
        self.guards["other_window"] = False
        scheduler = self.create_scheduler()
        scheduler.request("agent_done", summary="완료")

        self.assertFalse(scheduler.tick())
        self.assertEqual(self.messages, [])
        self.guards["other_window"] = True
        self.assertTrue(scheduler.tick())
        self.assertIn("완료", self.messages[0])

    def test_maintenance_result_waits_until_user_returns(self):
        self.guards["away"] = True
        scheduler = self.create_scheduler()
        scheduler.request("maintenance_result", summary="정리 완료")

        self.assertFalse(scheduler.tick())
        self.assertEqual(self.messages, [])
        self.guards["away"] = False
        self.assertTrue(scheduler.tick())
        self.assertIn("정리 완료", self.messages[0])

    def test_event_cooldown_and_daily_speech_cap(self):
        scheduler = self.create_scheduler()
        scheduler.request("return")
        self.assertTrue(scheduler.tick())

        self.now += timedelta(minutes=10)
        scheduler.request("return")
        self.assertFalse(scheduler.tick())
        self.now += timedelta(minutes=20)
        self.assertTrue(scheduler.tick())

        scheduler.request("long_use")
        self.assertTrue(scheduler.tick())
        scheduler.request("late_night")
        self.assertFalse(scheduler.tick())
        self.assertEqual(scheduler._daily_count, 3)

        self.now += timedelta(days=1)
        self.assertTrue(scheduler.tick())
        self.assertEqual(scheduler._daily_count, 1)

    def test_long_use_is_once_per_day(self):
        scheduler = self.create_scheduler()
        scheduler.request("long_use")
        self.assertTrue(scheduler.tick())
        scheduler.request("long_use")
        self.assertFalse(scheduler.tick())

        self.now += timedelta(days=1)
        self.assertTrue(scheduler.tick())

    def test_context_metrics_queue_daily_speech_events(self):
        scheduler = self.create_scheduler(
            context_provider=lambda: {
                "continuous_use_minutes": 180,
                "recent_praise_count": 3,
            },
        )

        self.assertTrue(scheduler.tick())
        self.assertTrue(scheduler.tick())
        self.assertEqual(scheduler._daily_count, 2)
        self.assertEqual(
            set(scheduler._last_delivered),
            {"long_use", "praise_streak"},
        )

        self.now = datetime(2026, 9, 29, 2, 0)
        late_scheduler = self.create_scheduler(
            context_provider=lambda: {"continuous_use_minutes": 60},
        )
        self.assertTrue(late_scheduler.tick())
        self.assertEqual(len(self.messages), 3)
        self.assertIn("late_night", late_scheduler._last_delivered)

    def test_ignored_speech_reduces_frequency_and_mood(self):
        last_interaction = [self.now]
        mood_path = os.path.join(self.directory.name, "mood.json")
        mood = MoodState(
            path=mood_path,
            clock=lambda: self.now.timestamp(),
        )

        def context():
            elapsed = (self.now - last_interaction[0]).total_seconds()
            return {"seconds_since_last_interaction": elapsed}

        scheduler = self.create_scheduler(
            context_provider=context,
            mood_provider=lambda: mood,
        )
        scheduler.request("return")
        self.assertTrue(scheduler.tick())
        self.now += timedelta(seconds=121)
        scheduler.tick()
        self.assertEqual(scheduler._ignored_streak, 1)
        self.assertEqual(scheduler._daily_limit(), 2)
        self.assertLess(mood.values(self.now.timestamp())[0], 0)

        self.now += timedelta(minutes=40)
        scheduler.request("return")
        self.assertFalse(scheduler.tick())

    def test_phrase_pool_selects_language_and_mood(self):
        source = {
            "good": ("좋음 첫 문구||좋음 둘째 문구",),
            "calm": ("평온 첫 문구||평온 둘째 문구",),
            "down": ("가라앉음 첫 문구||가라앉음 둘째 문구",),
        }
        translations = {
            "ko": {
                source["good"][0]: "좋은 문구||반가운 문구",
                source["calm"][0]: "차분한 문구||평온한 문구",
                source["down"][0]: "천천히 해요||괜찮아요",
            },
            "en": {
                source["good"][0]: "Glad you're back||Welcome back",
                source["calm"][0]: "Let's continue||Where to next?",
                source["down"][0]: "Take it slowly||It's okay to rest",
            },
            "ja": {
                source["good"][0]: "おかえりなさい||戻ってきてうれしいです",
                source["calm"][0]: "続きをしましょう||次はどこからですか？",
                source["down"][0]: "ゆっくりで大丈夫||少し休みましょう",
            },
        }

        class Mood:
            def __init__(self, valence):
                self.valence = valence

            def values(self):
                return self.valence, 0.0

        expected = {
            ("ko", 0.5): {"좋은 문구", "반가운 문구"},
            ("en", 0.0): {"Let's continue", "Where to next?"},
            ("ja", -0.5): {"ゆっくりで大丈夫", "少し休みましょう"},
        }
        for (language, valence), phrases in expected.items():
            with self.subTest(language=language, valence=valence):
                result = choose_phrase(
                    source,
                    Mood(valence),
                    translator=translations[language].get,
                )
                self.assertIn(result, phrases)

    def test_fixed_response_persona_override(self):
        from commands.ai_fast_path import FastPathMixin

        settings = {
            "fixed_responses": {
                "adjust_volume": {
                    "calm": ["볼륨을 조정했어요.", "완료했습니다."],
                },
            },
        }
        with (
            patch(
                "core.config_manager.ConfigManager.get",
                side_effect=lambda key, default=None: settings.get(key, default),
            ),
            patch("core.mood_state.get_mood_state", return_value=None),
            patch("commands.ai_fast_path._", side_effect=lambda value: value),
        ):
            response = FastPathMixin()._fast_response("adjust_volume", None)

        self.assertIn(response, {"볼륨을 조정했어요.", "완료했습니다."})

    def test_weekly_default_matches_settings_template(self):
        template_path = Path(__file__).resolve().parents[1] / "ari_settings.template.json"
        with template_path.open("r", encoding="utf-8") as stream:
            template = json.load(stream)

        self.assertTrue(DEFAULT_SETTINGS["weekly_report_enabled"])
        self.assertEqual(
            template["weekly_report_enabled"],
            DEFAULT_SETTINGS["weekly_report_enabled"],
        )
        self.assertEqual(template["fixed_responses"], {})


if __name__ == "__main__":
    unittest.main()
