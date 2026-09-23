from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime, timezone
import copy
import io
import json
import unittest
from unittest.mock import patch

from agent.decision.candidates import DIRECT_ALLOWLIST, UNKNOWN
from scripts.decision_data import candidate_families, review_corpus
from scripts.decision_data.dataset_guards import template_signature


class ReviewCorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.release_rows, cls.safety_rows = review_corpus.build_candidate_corpora()

    def test_candidates_are_pending_multilingual_and_have_independent_tier_a_families(self):
        rows = self.release_rows + self.safety_rows
        self.assertIn(len(rows), range(1000, 2001))
        self.assertTrue(all(row["review_status"] == "pending_human_review" for row in rows))
        review_corpus.validate_corpora(self.release_rows, self.safety_rows)

        families_by_tool = {}
        for row in self.release_rows:
            if row["candidate_tool"] in DIRECT_ALLOWLIST:
                families_by_tool.setdefault(row["candidate_tool"], set()).add(row["family_id"])
        for tool in DIRECT_ALLOWLIST:
            self.assertGreaterEqual(len(families_by_tool[tool]), 50)

        for corpus_rows in (self.release_rows, self.safety_rows):
            members = {}
            for row in corpus_rows:
                members.setdefault(row["family_id"], set()).add(row["language"])
            self.assertTrue(all(languages == {"ko", "en", "ja"} for languages in members.values()))

    def test_tier_b_colloquial_and_near_tier_a_safety_coverage(self):
        tier_b = [row for row in self.release_rows if row["bucket"] == "tier_b_parser_candidate"]
        self.assertEqual({row["candidate_tool"] for row in tier_b},
                         {"get_weather", "set_timer", "cancel_timer", "launch_app"})
        self.assertTrue(all(row["expected_outcome"] == "fallback_required" for row in tier_b))
        self.assertTrue(any(row["bucket"] == "stt_candidate" for row in self.release_rows))
        self.assertGreaterEqual(len({row["family_id"] for row in self.safety_rows}), 100)
        self.assertTrue(all(row["label"] == UNKNOWN and row["expected_outcome"] == "fallback_required"
                            and row["candidate_tool"] in DIRECT_ALLOWLIST for row in self.safety_rows))
        self.assertEqual({row["bucket"] for row in self.safety_rows}, {
            "volume_meaning", "volume_negation", "time_meaning", "screen_analysis",
            "screen_share", "screen_howto", "app_side_effect", "app_diagnosis",
            "app_launch", "app_settings", "multi_intent",
        })

    def test_direct_families_do_not_reuse_numeric_or_slot_templates(self):
        for tool in DIRECT_ALLOWLIST:
            authored = candidate_families.DIRECT_FAMILIES[tool]
            self.assertGreaterEqual(len(authored), 50)
            for language in candidate_families.LANGUAGES:
                signatures = [template_signature(texts[language], language)
                              for _slug, texts, _arguments in authored]
                self.assertEqual(len(signatures), len(set(signatures)), f"{tool}/{language}")

    def test_volume_direction_regressions_keep_translations_aligned(self):
        examples = {
            "vol_29": {
                "direction": "down",
                "ko": "스피커 음량을 12퍼센트만 줄이면 돼.",
                "en": "Just reduce the speaker volume by twelve percent.",
                "ja": "スピーカー音量を12パーセントだけ下げればいい。",
            },
            "vol_32": {
                "direction": "up",
                "ko": "음성 재생이 작게 들리니 레벨을 37퍼센트 높여 줘.",
                "en": "The voice playback is quiet; raise its level by thirty-seven percent.",
                "ja": "音声再生が小さいので、レベルを37パーセント上げて。",
            },
            "vol_36": {
                "direction": "up",
                "ko": "출력 장치의 소리를 41퍼센트 더 키워 줘.",
                "en": "Turn the audio output up by forty-one percent.",
                "ja": "オーディオ出力を41パーセント高くして。",
            },
            "vol_41": {
                "direction": "down",
                "ko": "재생 볼륨을 43퍼센트 낮춰 줘.",
                "en": "Set playback volume forty-three percent lower.",
                "ja": "再生音量を43パーセント低くして。",
            },
            "vol_44": {
                "direction": "up",
                "ko": "오디오 출력을 47퍼센트 더 크게 만들어 줘.",
                "en": "Move the audio level up forty-seven percent.",
                "ja": "オーディオレベルを47パーセント大きくして。",
            },
        }
        rows_by_slug = {
            ":".join(row["id"].split(":")[2:]): row for row in self.release_rows
            if row["candidate_tool"] == "adjust_volume"
        }
        for slug, expected in examples.items():
            translations = {language: rows_by_slug[f"{slug}:{language}"]
                            for language in candidate_families.LANGUAGES}
            self.assertEqual(
                {language: row["text"] for language, row in translations.items()},
                {language: expected[language] for language in candidate_families.LANGUAGES},
            )
            self.assertEqual(
                {language: row["expected_arguments"]["direction"]
                 for language, row in translations.items()},
                {language: expected["direction"] for language in candidate_families.LANGUAGES},
            )

    def test_review_actions_record_human_and_utc_provenance(self):
        source = copy.deepcopy(self.release_rows[0])
        reviewed_at = datetime(2026, 9, 23, 3, 4, 5, tzinfo=timezone.utc)

        edited = review_corpus.review_row(
            source, action="edit", reviewer="reviewer@example.test",
            changes={"text": source["text"] + " (수정)"}, now=reviewed_at,
        )
        self.assertEqual(edited["review_status"], "pending_human_review")
        self.assertEqual(edited["review_history"][0]["reviewed_at_utc"], "2026-09-23T03:04:05Z")
        self.assertEqual(edited["review_history"][0]["changes"]["text"]["from"], source["text"])
        accepted = review_corpus.review_row(
            edited, action="accept", reviewer="reviewer@example.test", now=reviewed_at,
        )
        self.assertEqual(accepted["review_status"], "human_approved")
        self.assertEqual(accepted["review_history"][-1]["original_revision_sha256"],
                         source["source_revision"]["sha256"])
        review_corpus._validate_review_provenance(accepted)

        rejected = review_corpus.review_row(
            copy.deepcopy(self.release_rows[1]), action="reject", reviewer="reviewer@example.test",
            now=reviewed_at,
        )
        self.assertEqual(rejected["review_status"], "human_rejected")
        with self.assertRaisesRegex(ValueError, "reviewer"):
            review_corpus.review_row(source, action="accept", reviewer="  ", now=reviewed_at)

    def test_human_can_correct_one_translation_and_safety_stays_fallback_only(self):
        source = self.release_rows[0]
        corrected = review_corpus.review_row(
            copy.deepcopy(source), action="edit", reviewer="reviewer@example.test",
            changes={"label": UNKNOWN, "expected_outcome": "fallback_required"},
            now=datetime(2026, 9, 23, 3, 4, 5, tzinfo=timezone.utc),
        )
        corrected_release = [corrected if row["id"] == source["id"] else copy.deepcopy(row)
                             for row in self.release_rows]
        review_corpus.validate_corpus(corrected_release, "release_gold")
        self.assertEqual(corrected["review_status"], "pending_human_review")
        self.assertEqual(corrected["review_history"][-1]["changes"]["label"]["to"], UNKNOWN)

        safety_source = self.safety_rows[0]
        corrected_safety = review_corpus.review_row(
            copy.deepcopy(safety_source), action="edit", reviewer="reviewer@example.test",
            changes={"label": safety_source["candidate_tool"]},
            now=datetime(2026, 9, 23, 3, 4, 5, tzinfo=timezone.utc),
        )
        safety_rows = [corrected_safety if row["id"] == safety_source["id"] else copy.deepcopy(row)
                       for row in self.safety_rows]
        review_corpus.validate_corpus(safety_rows, "safety_gold")
        rejected_outcome = review_corpus.review_row(
            copy.deepcopy(safety_source), action="edit", reviewer="reviewer@example.test",
            changes={"expected_outcome": "direct_or_fallback"},
            now=datetime(2026, 9, 23, 3, 4, 5, tzinfo=timezone.utc),
        )
        safety_rows[0] = rejected_outcome
        with self.assertRaisesRegex(ValueError, "fallback cases"):
            review_corpus.validate_corpus(safety_rows, "safety_gold")

    def test_list_command_shows_only_a_bounded_review_page(self):
        output = io.StringIO()
        with patch.object(review_corpus, "_read_rows", side_effect=[self.release_rows, self.safety_rows]):
            with redirect_stdout(output):
                result = review_corpus.main(["list", "--corpus", "release_gold", "--limit", "2"])
        listing = json.loads(output.getvalue())
        self.assertEqual(result, 0)
        self.assertEqual(listing["matching_count"], len(self.release_rows))
        self.assertEqual(len(listing["rows"]), 2)
        self.assertEqual(listing["rows"][0]["id"], self.release_rows[0]["id"])

    def test_validation_rejects_stale_hash_and_historical_text_leak(self):
        corrupted = copy.deepcopy(self.release_rows)
        corrupted[0]["text"] += " altered"
        with self.assertRaisesRegex(ValueError, "revision hash"):
            review_corpus.validate_corpora(corrupted, self.safety_rows)

        candidate = self.release_rows[0]
        with self.assertRaisesRegex(ValueError, "overlaps existing"):
            review_corpus.validate_historical_isolation([candidate], [{
                "text": candidate["text"], "language": candidate["language"],
                "family_id": "historical.family", "template_id": "historical.template",
            }])

    def test_generated_candidates_do_not_leak_into_existing_splits_or_gold(self):
        review_corpus.validate_historical_isolation(self.release_rows + self.safety_rows)


if __name__ == "__main__":
    unittest.main()
