import unittest
from unittest.mock import patch

import numpy as np

from scripts.decision_data.imbalance_experiments import (
    _calibration_diagnostics,
    _class_proposals,
    _folds,
    cap_training_variants,
    sample_weights,
)
from scripts.decision_data.train import fit_linear


class ImbalanceExperimentTests(unittest.TestCase):
    def test_fit_linear_rejects_non_positive_sample_weights(self):
        rows = [
            {"split": "train", "family_id": "train", "label": "get_current_time", "text": "time"},
            {"split": "calibration", "family_id": "calibration", "label": "get_current_time", "text": "time"},
        ]

        with patch("scripts.decision_data.train.validate_no_gold_rows"), patch(
            "scripts.decision_data.train.validate_family_splits"
        ), self.assertRaisesRegex(ValueError, "finite, positive"):
            fit_linear(rows, buckets=8, epochs=1, sample_weights=np.array([0.0]))

    def test_fit_linear_does_not_mutate_sample_weights(self):
        rows = [
            {"split": "train", "family_id": "train", "label": "get_current_time", "text": "time"},
            {"split": "calibration", "family_id": "calibration", "label": "get_current_time", "text": "time"},
        ]
        source_weights = np.asarray([4.0], dtype=np.float32)
        expected_weights = source_weights.copy()

        with patch("scripts.decision_data.train.validate_no_gold_rows"), patch(
            "scripts.decision_data.train.validate_family_splits"
        ):
            fit_linear(rows, buckets=8, epochs=1, sample_weights=source_weights)

        np.testing.assert_array_equal(source_weights, expected_weights)

    def test_fit_linear_rejects_weights_that_underflow_during_normalization(self):
        rows = [
            {"split": "train", "family_id": "train-a", "label": "get_current_time", "text": "time"},
            {"split": "train", "family_id": "train-b", "label": "get_current_time", "text": "clock"},
            {"split": "calibration", "family_id": "calibration", "label": "get_current_time", "text": "now"},
        ]
        weights = np.asarray([1e-300, 1e300], dtype=np.float64)

        with patch("scripts.decision_data.train.validate_no_gold_rows"), patch(
            "scripts.decision_data.train.validate_family_splits"
        ), self.assertRaisesRegex(ValueError, "cannot be normalized"):
            fit_linear(rows, buckets=8, epochs=1, sample_weights=weights)

    def test_calibration_diagnostics_reports_threshold_drops_and_errors(self):
        labels = ("get_current_time", "take_screenshot", "play_youtube")
        targets = (
            "get_current_time",
            "get_current_time",
            "get_current_time",
            "play_youtube",
        )
        rows = [
            {"family_id": f"family-{index}", "label": target, "language": "en"}
            for index, target in enumerate(targets)
        ]
        probabilities = np.asarray([
            [0.95, 0.03, 0.02],
            [0.88, 0.06, 0.06],
            [0.78, 0.11, 0.11],
            [0.95, 0.03, 0.02],
        ])

        with patch(
            "scripts.decision_data.imbalance_experiments._policy_eligibility",
            return_value=np.ones(4, dtype=bool),
        ):
            result = _calibration_diagnostics(rows, probabilities, labels, [True] * 4)

        current = result["threshold_profiles"][0]
        lower = result["threshold_profiles"][1]
        self.assertEqual((current["threshold"], current["margin"]), (0.92, 0.30))
        self.assertEqual(current["selected_rows"], 2)
        self.assertEqual(current["false_direct_rows"], 1)
        self.assertEqual(current["below_confidence_only"], 2)
        self.assertEqual(lower["selected_rows"], 3)
        self.assertEqual(lower["false_direct_rows"], 1)
        self.assertEqual(current["by_class"]["get_current_time"]["false_direct_rows"], 1)

    def test_family_weights_give_each_family_equal_total_mass(self):
        rows = [
            {"family_id": "a", "label": "time"},
            {"family_id": "a", "label": "time"},
            {"family_id": "a", "label": "time"},
            {"family_id": "b", "label": "time"},
        ]

        weights = sample_weights(rows, "family")

        self.assertAlmostEqual(float(weights[:3].sum()), float(weights[3]))
        self.assertAlmostEqual(float(weights.mean()), 1.0)

    def test_class_family_weights_give_each_class_equal_total_mass(self):
        rows = [
            {"family_id": "a", "label": "common"},
            {"family_id": "a", "label": "common"},
            {"family_id": "a", "label": "common"},
            {"family_id": "b", "label": "common"},
            {"family_id": "c", "label": "rare"},
        ]

        weights = sample_weights(rows, "class_family")

        self.assertAlmostEqual(float(weights[:4].sum()), float(weights[4]))
        self.assertAlmostEqual(float(weights.mean()), 1.0)

    def test_variant_cap_keeps_clean_rows_and_caps_each_train_family(self):
        rows = [
            {"id": f"clean-{language}", "family_id": "a", "split": "train", "language": language,
             "text": language, "is_noise": False}
            for language in ("ko", "en", "ja")
        ]
        rows += [
            {"id": f"variant-{index}", "family_id": "a", "split": "train", "language": "ko",
             "text": str(index), "is_noise": True, "noise_type": str(index)}
            for index in range(5)
        ]
        rows.append({"id": "calibration-noise", "family_id": "b", "split": "calibration",
                     "language": "en", "text": "cal", "is_noise": True})

        capped = cap_training_variants(rows, 2)
        kept_ids = {row["id"] for row in capped}
        variants = [row for row in capped if row["family_id"] == "a" and row["is_noise"]]

        self.assertTrue({"clean-ko", "clean-en", "clean-ja", "calibration-noise"} <= kept_ids)
        self.assertEqual(len(variants), 2)
        self.assertEqual(kept_ids, {row["id"] for row in cap_training_variants(rows, 2)})

    def test_calibration_fold_keeps_each_family_together(self):
        rows = [
            {"family_id": family}
            for family in ("family-a", "family-b", "family-c", "family-d", "family-e", "family-f")
            for _ in range(2)
        ]

        folds = _folds(rows, count=3)

        self.assertEqual(folds[0], folds[1])
        self.assertEqual(folds[2], folds[3])
        self.assertEqual(folds[4], folds[5])
        self.assertEqual(len(folds), len(rows))

    def test_calibration_folds_are_nonempty_when_families_cover_fold_count(self):
        rows = [{"family_id": f"family-{index}"} for index in range(5)]

        folds = _folds(rows, count=5, seed=1)

        self.assertEqual(set(folds.tolist()), set(range(5)))

    def test_per_class_proposal_disables_impossible_threshold_above_one(self):
        labels = ("get_current_time", "adjust_volume")
        rows = [{"family_id": "family-a", "label": "adjust_volume"}]
        probabilities = np.asarray([[1.0, 0.0]])
        targets = np.asarray([1])

        proposal = _class_proposals(rows, probabilities, targets, labels, [True])["get_current_time"]

        self.assertIsNone(proposal["proposed_threshold"])
        self.assertEqual(proposal["selected_rows_at_proposed_threshold"], 0)
        self.assertEqual(proposal["false_direct_at_proposed_threshold"], 0)
        self.assertEqual(proposal["proposal"], "disabled_pending_more_calibration_families")


if __name__ == "__main__":
    unittest.main()
