import unittest

from agent.decision.semantics import (
    SemanticParse,
    action_anchor_count,
    connector_count,
    parse_candidate,
)


class DecisionSemanticsTests(unittest.TestCase):
    def test_success_requires_all_four_signals(self):
        parsed = parse_candidate("what time is it", "get_current_time")

        self.assertTrue(parsed.valid)
        self.assertTrue(parsed.intent_confirmed)
        self.assertFalse(parsed.contradiction)
        self.assertFalse(parsed.residual_action)
        self.assertTrue(parsed.parse_success)

    def test_each_failed_signal_blocks_success(self):
        cases = (
            SemanticParse("get_current_time", "en", valid=False, intent_confirmed=True),
            SemanticParse("get_current_time", "en", valid=True, intent_confirmed=False),
            SemanticParse("get_current_time", "en", valid=True, intent_confirmed=True, contradiction=True),
            SemanticParse("get_current_time", "en", valid=True, intent_confirmed=True, residual_action=True),
        )
        for parsed in cases:
            with self.subTest(parsed=parsed):
                self.assertFalse(parsed.parse_success)

    def test_window_close_is_a_contradiction_even_for_excluded_candidate(self):
        parsed = parse_candidate("Close the Chrome window", "focus_window")

        self.assertTrue(parsed.contradiction)
        self.assertFalse(parsed.parse_success)

    def test_connector_and_action_anchors_mark_compound_request(self):
        text = "what time is it and take a screenshot"

        self.assertGreaterEqual(connector_count(text, "en"), 1)
        self.assertGreaterEqual(action_anchor_count(text, "en"), 2)
        parsed = parse_candidate(text, "get_current_time")
        self.assertTrue(parsed.residual_action)
        self.assertFalse(parsed.parse_success)

    def test_relative_volume_amount_is_optional_integer(self):
        parsed = parse_candidate("increase volume by 10%", "adjust_volume")

        self.assertTrue(parsed.parse_success)
        self.assertEqual(parsed.arguments, {"direction": "up", "amount": 10})

        cases = {
            "increase volume": {"direction": "up"},
            "Increase the volume by ten": {"direction": "up", "amount": 10},
            "볼륨 좀 줄여줘": {"direction": "down"},
            "音量を少し上げて": {"direction": "up"},
        }
        for text, arguments in cases.items():
            with self.subTest(text=text):
                parsed = parse_candidate(text, "adjust_volume")
                self.assertTrue(parsed.parse_success)
                self.assertEqual(parsed.arguments, arguments)

        for text in ("set volume to 50", "increase volume by 10.5%", "볼륨을 50으로 맞춰줘"):
            with self.subTest(text=text):
                self.assertFalse(parse_candidate(text, "adjust_volume").parse_success)

    def test_fillers_and_request_endings_do_not_block_single_commands(self):
        cases = (
            ("Um, um, what time is it now?", "get_current_time"),
            ("Sorry, capture the screen", "take_screenshot"),
            ("음, 그거 현재 시간을 알려주실래요", "get_current_time"),
            ("현재 켜진 프로그램을 알려줘", "get_running_apps"),
            ("すみませんが、画面をキャプチャしてくれない？", "take_screenshot"),
            ("現在開いているプログラムを教えてください", "get_running_apps"),
        )
        for text, candidate in cases:
            with self.subTest(text=text):
                self.assertTrue(parse_candidate(text, candidate).parse_success)

    def test_filler_words_are_not_stripped_from_inside_words(self):
        self.assertTrue(parse_candidate("음량 올려줘", "adjust_volume").parse_success)
        self.assertFalse(parse_candidate("Sorry what time works for you", "get_current_time").parse_success)

    def test_non_commands_about_allowed_tools_still_abstain(self):
        cases = (
            ("소리 너무 큰 이유가 뭐야?", "adjust_volume"),
            ("볼륨 올리지 마", "adjust_volume"),
            ("시간 좀 내줄래?", "get_current_time"),
            ("What time works for you?", "get_current_time"),
            ("What time is it in Tokyo", "get_current_time"),
            ("실행 중인 앱 다 닫아줘", "get_running_apps"),
            ("스크린샷 분석해줘", "take_screenshot"),
            ("音量を上げないで", "adjust_volume"),
        )
        for text, candidate in cases:
            with self.subTest(text=text):
                self.assertFalse(parse_candidate(text, candidate).parse_success)

    def test_mute_uses_fixed_safe_amount(self):
        parsed = parse_candidate("음소거해줘", "adjust_volume")

        self.assertTrue(parsed.parse_success)
        self.assertEqual(parsed.arguments, {"direction": "mute", "amount": 100})


if __name__ == "__main__":
    unittest.main()
