import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent.speech_scheduler import (
    EventSpeechScheduler,
    choose_phrase,
    note_user_activity,
    read_pc_status,
)
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
        # 실제 PC 센서 값이 다른 시험의 발화 건수에 끼어들지 않게 한다.
        kwargs.setdefault("pc_status_provider", dict)
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
        # 길어진 무대화 시간이 혼잣말을 부르지 않게 꺼 둔다.
        with patch("core.config_manager.ConfigManager.get", return_value=False):
            self.assertFalse(scheduler.tick())

    def test_chitchat_waits_for_idle_and_yields_to_other_events(self):
        idle = [10 * 60]
        scheduler = self.create_scheduler(
            context_provider=lambda: {"seconds_since_last_interaction": idle[0]},
        )
        with patch("core.config_manager.ConfigManager.get", return_value=True):
            self.assertFalse(scheduler.tick())
            self.assertEqual(self.messages, [])

            idle[0] = 25 * 60
            self.guards["away"] = True
            self.assertFalse(scheduler.tick())
            self.guards["away"] = False
            scheduler.request("return")
            self.assertTrue(scheduler.tick())
            self.assertTrue(scheduler.tick())

            self.now += timedelta(hours=2)
            self.assertFalse(scheduler.tick())
            self.now += timedelta(hours=1, minutes=1)
            self.assertTrue(scheduler.tick())

        self.assertFalse(self.messages[0].startswith("("))
        self.assertTrue(self.messages[1].startswith("("))
        self.assertEqual(len(self.messages), 3)

    def test_chitchat_waits_while_user_input_is_being_answered(self):
        scheduler = self.create_scheduler(
            context_provider=lambda: {"seconds_since_last_interaction": 3600},
        )
        with patch("core.config_manager.ConfigManager.get", return_value=True):
            scheduler.note_user_activity()
            self.assertFalse(scheduler.tick())
            self.assertEqual(self.messages, [])

            self.now += timedelta(minutes=21)
            self.assertTrue(scheduler.tick())

    def test_note_user_activity_reaches_the_shared_scheduler(self):
        scheduler = self.create_scheduler()
        with patch("agent.speech_scheduler.get_speech_scheduler", return_value=scheduler):
            note_user_activity()
        self.assertEqual(scheduler._last_user_input_at, self.now)

        with patch("agent.speech_scheduler.get_speech_scheduler", return_value=None):
            note_user_activity()

    def test_pending_chitchat_is_dropped_when_user_talks_again(self):
        idle = [25 * 60]
        self.guards["away"] = True
        scheduler = self.create_scheduler(
            context_provider=lambda: {"seconds_since_last_interaction": idle[0]},
        )
        with patch("core.config_manager.ConfigManager.get", return_value=True):
            self.assertFalse(scheduler.tick())
            idle[0] = 30
            self.guards["away"] = False
            self.assertFalse(scheduler.tick())

        self.assertEqual(self.messages, [])

    def test_chitchat_is_skipped_when_setting_is_off(self):
        scheduler = self.create_scheduler(
            context_provider=lambda: {"seconds_since_last_interaction": 3600},
        )
        with patch("core.config_manager.ConfigManager.get", return_value=False):
            self.assertFalse(scheduler.tick())

        self.assertEqual(self.messages, [])

    def test_chitchat_is_off_when_setting_is_missing(self):
        scheduler = self.create_scheduler(
            context_provider=lambda: {"seconds_since_last_interaction": 3600},
        )
        with patch(
            "core.config_manager.ConfigManager.get",
            side_effect=lambda key, default=None: default,
        ):
            self.assertFalse(scheduler.tick())
        with patch(
            "core.config_manager.ConfigManager.get",
            side_effect=RuntimeError("settings unavailable"),
        ):
            self.assertFalse(scheduler.tick())

        self.assertEqual(self.messages, [])

    def test_spontaneous_talk_default_matches_settings_template(self):
        template_path = Path(__file__).resolve().parents[1] / "ari_settings.template.json"
        with template_path.open("r", encoding="utf-8") as stream:
            template = json.load(stream)

        self.assertFalse(DEFAULT_SETTINGS["spontaneous_talk_enabled"])
        self.assertEqual(
            template["spontaneous_talk_enabled"],
            DEFAULT_SETTINGS["spontaneous_talk_enabled"],
        )

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

    def pc_alert_scheduler(self):
        self.guards.clear()
        self.guards["other_window"] = True
        return self.create_scheduler(
            context_provider=lambda: {}, pc_status_provider=read_pc_status
        )

    def pc_alert_step(self, scheduler, battery, free_gib=50.0, minutes=10, settings=None):
        """가짜 센서 값으로 센서 함수를 바꾸고 시계를 옮겨 tick 을 한 번 돌린다."""
        self.now += timedelta(minutes=minutes)
        settings = {} if settings is None else settings
        sensor = None
        if battery is not None:
            sensor = SimpleNamespace(percent=battery[0], power_plugged=battery[1])
        with (
            patch("psutil.sensors_battery", return_value=sensor),
            patch(
                "psutil.disk_usage",
                return_value=SimpleNamespace(free=int(free_gib * 1024**3)),
            ),
            patch.dict(os.environ, {"SystemDrive": "C:"}),
            patch(
                "core.config_manager.ConfigManager.get",
                side_effect=lambda key, default=None: settings.get(key, default),
            ),
        ):
            return scheduler.tick()

    def test_pc_alert_fires_once_and_rearms_after_recovery(self):
        scheduler = self.pc_alert_scheduler()
        readings = [
            ((30, False), 0),   # 여유 있음
            ((19, False), 1),   # 기준 아래로 내려가 한 번 알림
            ((18, False), 1),   # 같은 상태에서는 반복하지 않음
            ((22, False), 1),   # 기준 위지만 충분히 회복하지 않음
            ((12, False), 1),   # 다시 내려가도 아직 알릴 수 있는 상태가 아님
            ((26, False), 1),   # 충분히 회복
            ((15, False), 2),   # 다시 내려가면 한 번 더 알림
            ((14, True), 2),    # 충전기를 연결하면 알리지 않음
        ]
        for battery, expected_count in readings:
            with self.subTest(battery=battery):
                self.pc_alert_step(scheduler, battery)
                self.assertEqual(len(self.messages), expected_count)
        self.assertIn("19%", self.messages[0])
        self.assertIn("15%", self.messages[1])

    def test_pc_alert_drops_stale_warning_and_handles_no_battery(self):
        scheduler = self.pc_alert_scheduler()
        self.guards["locked"] = True
        self.pc_alert_step(scheduler, (15, False))
        self.assertEqual(self.messages, [])
        self.assertEqual([item[0] for item in scheduler._pending], ["battery_low"])

        # 잠긴 사이 충전기를 연결하면 미뤄진 알림은 버려진다.
        self.pc_alert_step(scheduler, (15, True))
        self.guards["locked"] = False
        self.pc_alert_step(scheduler, (15, True))
        self.assertEqual(self.messages, [])
        self.assertEqual(scheduler._pending, [])

        # 배터리가 없는 PC는 배터리 검사만 건너뛰고 디스크 검사는 한다.
        self.pc_alert_step(scheduler, None, free_gib=5)
        self.assertEqual(len(self.messages), 1)
        self.assertIn("C 드라이브", self.messages[0])
        self.assertIn("5.0 GB", self.messages[0])
        self.pc_alert_step(scheduler, None, free_gib=4)
        self.assertEqual(len(self.messages), 1)

        # 회복한 뒤 다시 부족해지면, 대기 시간(6시간)이 지난 다음 한 번 더 알린다.
        self.pc_alert_step(scheduler, None, free_gib=20)
        self.pc_alert_step(scheduler, None, free_gib=3, minutes=7 * 60)
        self.assertEqual(len(self.messages), 2)

    def test_pc_alert_discarded_before_speaking_can_alert_again(self):
        scheduler = self.pc_alert_scheduler()
        self.guards["locked"] = True
        self.pc_alert_step(scheduler, (15, False))
        self.assertEqual(len(scheduler._pending), 1)

        # 보류 중 값이 기준과 회복 기준 사이로 올라 대기분이 버려진다.
        self.pc_alert_step(scheduler, (22, False))
        self.assertEqual(scheduler._pending, [])

        # 다시 기준 아래로 내려가면 보류가 풀린 뒤 한 번 알린다.
        self.pc_alert_step(scheduler, (15, False))
        self.guards["locked"] = False
        self.pc_alert_step(scheduler, (15, False))
        self.assertEqual(len(self.messages), 1)
        self.pc_alert_step(scheduler, (15, False))
        self.assertEqual(len(self.messages), 1)

    def test_pc_alert_skips_battery_when_power_state_unknown(self):
        scheduler = self.pc_alert_scheduler()
        self.pc_alert_step(scheduler, (10, None))
        self.assertEqual(self.messages, [])
        self.assertEqual(scheduler._pending, [])

        # 전원 상태를 알게 되면 배터리 알림을 낸다.
        self.pc_alert_step(scheduler, (10, False))
        self.assertEqual(len(self.messages), 1)

    def test_pc_alert_follows_setting_and_defaults_to_on(self):
        scheduler = self.pc_alert_scheduler()
        self.pc_alert_step(scheduler, (10, False), settings={"pc_resource_alerts_enabled": False})
        self.assertEqual(self.messages, [])

        # 설정 파일에 키가 없으면 기본값(켜짐)으로 동작한다.
        self.pc_alert_step(scheduler, (10, False))
        self.assertEqual(len(self.messages), 1)

    def test_pc_alert_check_runs_at_most_every_five_minutes(self):
        scheduler = self.pc_alert_scheduler()
        calls = []
        scheduler._pc_status_provider = lambda: calls.append(1) or {}
        for minutes in (0, 1, 2, 3, 4):
            self.pc_alert_step(scheduler, None, minutes=minutes)
        self.assertEqual(len(calls), 2)

    def test_pc_alert_default_matches_settings_template(self):
        template_path = Path(__file__).resolve().parents[1] / "ari_settings.template.json"
        with template_path.open("r", encoding="utf-8") as stream:
            template = json.load(stream)

        self.assertTrue(DEFAULT_SETTINGS["pc_resource_alerts_enabled"])
        self.assertEqual(
            template["pc_resource_alerts_enabled"],
            DEFAULT_SETTINGS["pc_resource_alerts_enabled"],
        )


if __name__ == "__main__":
    unittest.main()
