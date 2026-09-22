from __future__ import annotations

from pathlib import Path
import sys
import unittest

import numpy as np

VOICECOMMAND_ROOT = Path(__file__).resolve().parents[1]
if str(VOICECOMMAND_ROOT) not in sys.path:
    sys.path.insert(0, str(VOICECOMMAND_ROOT))

from agent.decision.engine import hash_features
from scripts.decision_data.phase3_experiments import FEATURE_GROUPS, extract_features


class Phase3FeatureTests(unittest.TestCase):
    def test_character_baseline_matches_runtime_hash(self):
        text = "크롬을 열어줘"
        expected_indices, expected_values = hash_features(text)
        actual_indices, actual_values = extract_features(text)
        np.testing.assert_array_equal(actual_indices, expected_indices)
        np.testing.assert_array_equal(actual_values, expected_values)

    def test_feature_groups_are_deterministic(self):
        text = "삼십 분 뒤에 알림을 설정해줘"
        for group in FEATURE_GROUPS:
            with self.subTest(group=group):
                first = extract_features(text, (group,))
                second = extract_features(text, (group,))
                np.testing.assert_array_equal(first[0], second[0])
                np.testing.assert_array_equal(first[1], second[1])

    def test_number_word_and_duration_signals_cover_three_languages(self):
        examples = ("삼십분 뒤에", "in thirty minutes", "30分後に", "三十分後に")
        for text in examples:
            with self.subTest(text=text):
                indices, values = extract_features(text, ("numeric_duration",))
                active = indices[indices >= 8192]
                self.assertEqual(set(active), {8192, 8193})
                self.assertTrue(np.isfinite(values).all())

    def test_korean_duration_units_require_a_number(self):
        for text in ("분석 결과", "초안 작성", "시간표 확인", "일부분만 보여줘"):
            with self.subTest(text=text):
                indices, _ = extract_features(text, ("numeric_duration",))
                self.assertEqual(len(indices[indices >= 8192]), 0)


if __name__ == "__main__":
    unittest.main()
