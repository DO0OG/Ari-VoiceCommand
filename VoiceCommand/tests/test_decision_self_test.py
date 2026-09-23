import json
import shutil
import tempfile
import unittest
from pathlib import Path

from agent.decision.self_test import run_self_test

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "resources" / "decision"


class DecisionSelfTestTests(unittest.TestCase):
    def test_bundled_model_passes_and_reports_checksum(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"

            self.assertEqual(run_self_test(str(output), MODEL_DIR), 0)
            report = json.loads(output.read_text(encoding="utf-8"))

        config = json.loads((MODEL_DIR / "config.json").read_text(encoding="utf-8"))
        self.assertTrue(report["ok"])
        self.assertEqual(report["sha256"], config["sha256"])
        self.assertTrue(all(row["choice"] == row["expected"] for row in report["predictions"]))

    def test_corrupt_weights_fail_with_error(self):
        with tempfile.TemporaryDirectory() as directory:
            model = Path(directory) / "decision"
            shutil.copytree(MODEL_DIR, model)
            weights = model / "weights.npz"
            weights.write_bytes(weights.read_bytes() + b"corrupt")
            output = Path(directory) / "report.json"

            self.assertEqual(run_self_test(str(output), model), 1)
            report = json.loads(output.read_text(encoding="utf-8"))

        self.assertFalse(report["ok"])
        self.assertIn("Checksum mismatch", report["error"])


if __name__ == "__main__":
    unittest.main()
