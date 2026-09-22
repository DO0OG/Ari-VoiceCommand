from __future__ import annotations

from pathlib import Path
import sys
import unittest

import numpy as np

VOICECOMMAND_ROOT = Path(__file__).resolve().parents[1]
if str(VOICECOMMAND_ROOT) not in sys.path:
    sys.path.insert(0, str(VOICECOMMAND_ROOT))

from agent.decision.engine import candidate_names, hash_features
from scripts.decision_data.phase3_experiments import (
    FEATURE_GROUPS,
    _feature_width,
    _score_subset,
    extract_features,
    run_experiments,
)


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

    def test_presence_features_have_positive_and_negative_signals(self):
        examples = {
            "url_presence": ("https://example.com/help", "웹 주소 없음"),
            "file_path_presence": (r"C:\Users\Ari\report.json", "파일 이름만 말해줘"),
            "app_alias": ("디코 켜줘", "음악을 틀어줘"),
            "entity_signal": ("서울 날씨 알려줘", "무엇을 할지 모르겠어"),
        }
        for group, (positive, negative) in examples.items():
            with self.subTest(group=group, value="positive"):
                indices, values = extract_features(positive, (group,))
                self.assertEqual(set(indices[indices >= 8192]), {8192})
                self.assertEqual(len(indices), len(values))
            with self.subTest(group=group, value="negative"):
                indices, values = extract_features(negative, (group,))
                self.assertEqual(len(indices[indices >= 8192]), 0)
                self.assertEqual(len(indices), len(values))

        for path in ("/tmp/config", "~/Documents"):
            with self.subTest(group="file_path_presence", value=path):
                indices, _ = extract_features(path, ("file_path_presence",))
                self.assertEqual(set(indices[indices >= 8192]), {8192})
        indices, _ = extract_features("https://example.com/help", ("file_path_presence",))
        self.assertEqual(len(indices[indices >= 8192]), 0)

    def test_presence_feature_offsets_follow_existing_blocks(self):
        groups = ("numeric_duration", "url_presence", "entity_signal")
        indices, values = extract_features(
            "30분 뒤 https://example.com 서울", groups
        )
        self.assertEqual(set(indices[indices >= 8192]), {8192, 8193, 8194, 8195})
        self.assertEqual(_feature_width(groups, 8192), 8196)
        self.assertEqual(len(indices), len(values))

    def test_policy_gate_excludes_forbidden_prediction_and_counts_allowed_error(self):
        labels = list(candidate_names())
        probabilities = np.full((2, len(labels)), 0.0001, dtype=float)
        probabilities[0, labels.index("get_current_time")] = 0.99
        probabilities[1, labels.index("delete_file")] = 0.99
        probabilities /= probabilities.sum(axis=1, keepdims=True)
        rows = [
            {"label": "get_weather", "language": "ko"},
            {"label": "delete_file", "language": "ko"},
        ]

        result = _score_subset(rows, probabilities, np.asarray([True, True]))

        self.assertEqual(result["gates"]["confidence"]["selected_count"], 2)
        self.assertEqual(result["gates"]["confidence"]["false_direct_count"], 1)
        self.assertEqual(result["gates"]["policy"]["selected_count"], 1)
        self.assertEqual(result["gates"]["policy"]["false_direct_count"], 1)

    def test_group_validation_rejects_unknown_and_duplicate_groups(self):
        for groups in (("missing",), ("url_presence", "url_presence")):
            with self.subTest(groups=groups):
                with self.assertRaises(ValueError):
                    run_experiments(
                        Path("missing-rows.jsonl"),
                        Path("missing-baseline"),
                        Path("missing-output.json"),
                        feature_groups=groups,
                    )


if __name__ == "__main__":
    unittest.main()
