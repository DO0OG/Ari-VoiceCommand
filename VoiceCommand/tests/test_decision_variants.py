"""Checks for deterministic Korean utterance augmentation."""

from __future__ import annotations

from pathlib import Path
import sys
import unittest

VOICECOMMAND_ROOT = Path(__file__).resolve().parents[1]
if str(VOICECOMMAND_ROOT) not in sys.path:
    sys.path.insert(0, str(VOICECOMMAND_ROOT))

from scripts.decision_data.variants import generate_variants


class DecisionVariantTests(unittest.TestCase):
    def test_output_is_deterministic_bounded_unique_and_composable(self):
        source = "크롬을 켜줘"
        first = generate_variants(source, "ko")
        second = generate_variants(source, "ko")
        self.assertEqual(first, second)
        self.assertLessEqual(len(first), 12)
        self.assertEqual(len({text for text, _ in first}), len(first))
        self.assertNotIn(source, {text for text, _ in first})
        self.assertTrue(any(kind.startswith("composed:") for _, kind in first))

        self.assertEqual(generate_variants(source, "ko", limit=3), generate_variants(source, "ko", limit=3))
        self.assertLessEqual(len(generate_variants(source, "ko", limit=3)), 3)

    def test_korean_particle_and_word_order_changes_keep_the_named_object(self):
        variants = generate_variants("크롬을 켜줘", "ko", limit=64)
        by_text = dict(variants)
        self.assertIn("particle_omission", by_text["크롬 켜줘"])
        self.assertIn("object_verb_inversion", by_text["켜줘 크롬을"])
        self.assertTrue(all(any(name in text for name in ("크롬", "크 롬", "크럼", "크론")) for text, _ in variants))
        self.assertNotIn("그거 켜줘", by_text)

        # A syllable sequence that happens to end in 을 is not enough to omit it.
        unrelated = dict(generate_variants("걸을 알려줘", "ko", limit=64))
        self.assertNotIn("걸 알려줘", unrelated)

        bare_object = dict(generate_variants("크롬 열어줘", "ko", limit=64))
        self.assertIn("object_verb_inversion", bare_object["열어줘 크롬"])
        for complex_text in ("크롬을 켜지 마", "크롬을 켜줘 그리고 볼륨을 올려줘"):
            with self.subTest(complex_text=complex_text):
                self.assertNotIn(
                    "object_verb_inversion",
                    {kind for _, kind in generate_variants(complex_text, "ko", limit=64)},
                )

    def test_transcription_errors_do_not_flip_the_action(self):
        on_variants = {text for text, _ in generate_variants("크롬을 켜줘", "ko", limit=64)}
        off_variants = {text for text, _ in generate_variants("크롬을 꺼줘", "ko", limit=64)}
        self.assertIn("크롬을 겨줘", on_variants)
        self.assertIn("크롬을 저줘", on_variants)
        self.assertNotIn("크롬을 꺼줘", on_variants)
        self.assertNotIn("크롬을 켜줘", off_variants)
        self.assertIn("크롬을 거줘", off_variants)

        transcription = (
            ("디스코드를 켜줘", "디스콜드를 켜줘"),
            ("유튜브를 열어줘", "유투브를 열어줘"),
            ("볼륨을 올려줘", "보륨을 올려줘"),
            ("스크린샷을 보여줘", "스크린셧을 보여줘"),
            ("스크린샷을 보여줘", "스크린 샷을 보여줘"),
            ("엑셀을 열어줘", "액셀을 열어줘"),
            ("유튜브를 열어줘", "유튜브를 여러줘"),
            ("크롬을 꺼줘", "크롬을 거줘"),
            ("지금 시간을 알려줘", "지금 시감을 알려줘"),
            ("화면을 보여줘", "하면을 보여줘"),
            ("크롬을 켜줘", "크론을 켜줘"),
            ("닫아줘", "다다줘"),
            ("띄워줘", "띠워줘"),
        )
        for source, expected in transcription:
            with self.subTest(source=source, expected=expected):
                output = {text for text, _ in generate_variants(source, "ko", limit=64)}
                self.assertIn(expected, output)
        on_texts = {text for text, _ in generate_variants("크롬을 켜줘", "ko", limit=64)}
        off_texts = {text for text, _ in generate_variants("크롬을 꺼줘", "ko", limit=64)}
        open_texts = {text for text, _ in generate_variants("유튜브를 열어줘", "ko", limit=64)}
        close_texts = {text for text, _ in generate_variants("유튜브를 닫아줘", "ko", limit=64)}
        self.assertNotIn("크롬을 거줘", on_texts)
        self.assertNotIn("크롬을 켜줘", off_texts)
        self.assertNotIn("유튜브를 다다줘", open_texts)
        self.assertNotIn("유튜브를 여러줘", close_texts)

    def test_request_endings_softeners_and_stutter(self):
        on = {text for text, _ in generate_variants("크롬을 켜줘", "ko", limit=64)}
        for expected in (
            "크롬을 켜봐",
            "크롬을 켜주실래요",
            "크롬을 켜주라",
            "크롬을 켜줄래",
            "미안한데 크롬을 켜줘",
            "가능하면 크롬을 켜줘",
            "어, 그거 크롬을 켜줘",
            "음, 그거 크롬을 켜줘",
            "아, 그거 크롬을 켜줘",
            "음, 음 크롬을 켜줘",
            "크 크롬을 켜줘",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, on)

        action = {text for text, _ in generate_variants("크롬을 검색해줘", "ko", limit=64)}
        for expected in ("크롬을 검색해줄래", "크롬을 검색해주라", "크롬을 검색해봐", "크롬을 검색해"):
            with self.subTest(expected=expected):
                self.assertIn(expected, action)

    def test_safe_numeric_forms_and_punctuation(self):
        variants = {text for text, _ in generate_variants("5분 타이머 설정해줘!", "ko", limit=64)}
        self.assertIn("오 분 타이머 설정해줘!", variants)
        self.assertIn("5분 타이머 설정해줘", variants)

        longer_number = {text for text, _ in generate_variants("15분 타이머 설정해줘", "ko", limit=64)}
        self.assertNotIn("1오 분 타이머 설정해줘", longer_number)
        self.assertNotIn("1삼십 분 타이머 설정해줘", longer_number)

        numeric_phrases = {text for text, _ in generate_variants("50으로 타이머를 맞춰줘", "ko", limit=64)}
        self.assertIn("오십으로 타이머를 맞춰줘", numeric_phrases)
        times = {text for text, _ in generate_variants("다섯 시에 알려줘", "ko", limit=64)}
        self.assertIn("5시에 알려줘", times)
        durations = {text for text, _ in generate_variants("삼십분 타이머를 맞춰줘", "ko", limit=64)}
        self.assertIn("30분 타이머를 맞춰줘", durations)

        for source in ("1.5분 타이머", "-5분 타이머", "1,500분 타이머"):
            with self.subTest(source=source):
                self.assertNotIn(
                    "numeric_transcription",
                    {kind for _, kind in generate_variants(source, "ko", limit=64)},
                )

    def test_generic_number_forms_preserve_duration_and_clock_values(self):
        examples = (
            ("15분 후", "십오 분 후"),
            ("20초 뒤", "이십 초 뒤"),
            ("3시간 뒤", "세 시간 뒤"),
            ("5시에", "다섯 시에"),
            ("스물세시간 뒤", "23시간 뒤"),
            ("백오십 분 뒤", "150분 뒤"),
        )
        for source, expected in examples:
            with self.subTest(source=source, expected=expected):
                self.assertIn(expected, {text for text, _ in generate_variants(source, "ko", limit=64)})

        quarter = generate_variants("5분기 보고서", "ko", limit=64)
        self.assertNotIn("numeric_transcription", {kind for _, kind in quarter})
        self.assertNotIn("오 분기 보고서", {text for text, _ in quarter})

    def test_default_limit_reserves_numeric_and_related_composition(self):
        source = "30분 뒤 알려줘"
        variants = generate_variants(source, "ko")
        self.assertLessEqual(len(variants), 12)
        self.assertTrue(any(kind == "numeric_transcription" for _, kind in variants))
        self.assertTrue(any(kind.startswith("composed:numeric_transcription+") for _, kind in variants))
        self.assertEqual(generate_variants(source, "ko", limit=1)[0][1], "numeric_transcription")

    def test_english_variants_keep_the_action_and_the_named_object(self):
        source = "Open the Chrome window"
        first = generate_variants(source, "en")
        self.assertEqual(first, generate_variants(source, "en"))
        self.assertLessEqual(len(first), 12)
        self.assertEqual(len({text for text, _ in first}), len(first))
        self.assertNotIn(source, {text for text, _ in first})

        variants = dict(generate_variants(source, "en", limit=64))
        self.assertIn("article_omission", variants["Open Chrome window"])
        self.assertIn("Please open the Chrome window", variants)
        self.assertIn("Could you open the Chrome window", variants)
        self.assertIn("Open the Chrome window please", variants)
        self.assertIn("Um, open the Chrome window", variants)
        self.assertIn("Um, um, open the Chrome window", variants)
        self.assertIn("Open the Ch- Chrome window", variants)
        self.assertIn("Open the Chrom window", variants)
        self.assertIn("open the chrome window", variants)
        for text, _ in generate_variants(source, "en", limit=64):
            with self.subTest(text=text):
                self.assertTrue(any(name in text.lower() for name in ("chrom", "crome")))

        # A request that already carries a politeness marker keeps one meaning.
        polite = dict(generate_variants("Could you please open Chrome", "en", limit=64))
        self.assertIn("Open Chrome", polite)
        self.assertIn("Can you open Chrome", polite)

    def test_english_spacing_and_number_forms_are_reversible(self):
        split = {text for text, _ in generate_variants("Take a screenshot", "en", limit=64)}
        self.assertIn("Take a screen shot", split)
        self.assertIn("Take screenshot", split)
        joined = {text for text, _ in generate_variants("Open you tube", "en", limit=64)}
        self.assertIn("Open youtube", joined)

        digits = {text for text, _ in generate_variants("Set a timer for 30 minutes", "en", limit=64)}
        self.assertIn("Set a timer for thirty minutes", digits)
        words = {text for text, _ in generate_variants("Set a timer for thirty minutes", "en", limit=64)}
        self.assertIn("Set a timer for 30 minutes", words)
        self.assertIn(
            "Set a timer for twenty-five minutes",
            {text for text, _ in generate_variants("Set a timer for 25 minutes", "en", limit=64)},
        )
        for source in ("Open 1.5 files", "Wait 1,500 minutes"):
            with self.subTest(source=source):
                self.assertNotIn(
                    "numeric_transcription",
                    {kind for _, kind in generate_variants(source, "en", limit=64)},
                )

    def test_japanese_particle_ending_and_transcription_changes(self):
        source = "Chromeを開いてください"
        first = generate_variants(source, "ja")
        self.assertEqual(first, generate_variants(source, "ja"))
        self.assertLessEqual(len(first), 12)
        self.assertEqual(len({text for text, _ in first}), len(first))
        self.assertNotIn(source, {text for text, _ in first})

        variants = dict(generate_variants(source, "ja", limit=64))
        self.assertIn("particle_omission", variants["Chrome開いてください"])
        for expected in ("Chromeを開いて", "Chromeを開いてくれる？", "Chromeを開いてよ",
                         "えっと、Chromeを開いてください", "あの、Chromeを開いてください",
                         "えっと、えっと、Chromeを開いてください", "Chromeを 開いてください"):
            with self.subTest(expected=expected):
                self.assertIn(expected, variants)
        self.assertTrue(all("開い" in text for text, _ in variants.items()))

        readings = {text for text, _ in generate_variants("クロームを開いて", "ja", limit=64)}
        self.assertIn("クロムを開いて", readings)
        self.assertIn("ク、クロームを開いて", readings)
        noisy = {text for text, _ in generate_variants("音量を上げて", "ja", limit=64)}
        self.assertIn("音料を上げて", noisy)
        self.assertNotIn("音量を下げて", noisy)

    def test_japanese_number_forms_keep_the_value_and_unit(self):
        digits = {text for text, _ in generate_variants("30分後に教えて", "ja", limit=64)}
        self.assertIn("三十分後に教えて", digits)
        kanji = {text for text, _ in generate_variants("三十分後に教えて", "ja", limit=64)}
        self.assertIn("30分後に教えて", kanji)
        hours = {text for text, _ in generate_variants("3時間後に教えて", "ja", limit=64)}
        self.assertIn("三時間後に教えて", hours)
        self.assertIn(
            "150分後に教えて",
            {text for text, _ in generate_variants("百五十分後に教えて", "ja", limit=64)},
        )

    def test_unsupported_language_and_empty_input_produce_nothing(self):
        korean = generate_variants("크롬을 켜줘", "ko")
        self.assertGreater(len(korean), 0)
        self.assertEqual(generate_variants("크롬을 켜줘", "unknown"), [])
        self.assertEqual(generate_variants("", "ko"), [])
        self.assertEqual(generate_variants("Open Chrome", ""), [])
        self.assertEqual(generate_variants("크롬을 켜줘", None), [])


if __name__ == "__main__":
    unittest.main()
