import unittest
import numpy as np

from agent.decision.engine import UNKNOWN, softmax
from scripts.decision_data.evaluate import metrics
from scripts.decision_data.train import fit_temperature


class DecisionMetricsTests(unittest.TestCase):
    def test_known_calibration_and_abstention_metrics(self):
        labels = ["example", UNKNOWN]
        result = metrics([[0.95, 0.05], [0.05, 0.95], [0.6, 0.4]], [0, 1, 1], labels)
        self.assertAlmostEqual(result["accuracy"], 2 / 3)
        self.assertAlmostEqual(result["coverage"], 1 / 3)
        self.assertEqual(result["selective_accuracy"], 1)
        self.assertAlmostEqual(result["ece"], (0.05 + 0.05 + 0.6) / 3)
        self.assertAlmostEqual(result["brier"], (0.005 + 0.005 + 0.72) / 3)
        self.assertEqual(result["confusion_matrix"][UNKNOWN], {"example": 1, UNKNOWN: 1})

    def test_confident_wrong_selection_and_empty_selection_are_reported(self):
        labels = ["example", UNKNOWN]
        result = metrics([[0.99, 0.01]], [1], labels)
        self.assertEqual(result["false_direct_count"], 1)
        self.assertEqual(result["unknown_false_accept_count"], 1)
        gated = metrics([[0.99, 0.01]], [1], labels, eligible=[False])
        self.assertIsNone(gated["selective_accuracy"])
        self.assertEqual(gated["coverage"], 0)

    def test_temperature_fit_reduces_calibration_loss_and_normalizes(self):
        logits = np.array([[10, 0], [10, 0], [0, 10], [0, 10]], dtype=float)
        targets = np.array([0, 1, 1, 0])
        temperature = fit_temperature(logits, targets)
        calibrated = softmax(logits, temperature)
        np.testing.assert_allclose(calibrated.sum(axis=1), np.ones(4))
        self.assertGreater(temperature, 1)
        old_loss = -np.log(softmax(logits)[np.arange(4), targets]).mean()
        new_loss = -np.log(calibrated[np.arange(4), targets]).mean()
        self.assertLess(new_loss, old_loss)


if __name__ == "__main__":
    unittest.main()
