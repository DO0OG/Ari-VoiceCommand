import json
import shutil
import tempfile
import unittest
from pathlib import Path

from agent.decision.self_test import run_self_test
from scripts.compile_po import compile_po

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "resources" / "decision"


def _compiled_locales(directory: str) -> Path:
    locales = Path(directory) / "locales"
    for language in ("ko", "en", "ja"):
        target = locales / language / "LC_MESSAGES"
        target.mkdir(parents=True)
        source = ROOT / "i18n" / "locales" / language / "LC_MESSAGES" / "ari.po"
        compile_po(str(source), str(target / "ari.mo"))
    return locales


class DecisionSelfTestTests(unittest.TestCase):
    def test_bundled_model_passes_and_reports_checksum(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"

            self.assertEqual(run_self_test(str(output), MODEL_DIR, _compiled_locales(directory)), 0)
            report = json.loads(output.read_text(encoding="utf-8"))

        config = json.loads((MODEL_DIR / "config.json").read_text(encoding="utf-8"))
        self.assertTrue(report["ok"])
        self.assertEqual(report["sha256"], config["sha256"])
        self.assertTrue(all(row["choice"] == row["expected"] for row in report["predictions"]))
        self.assertEqual(report["translations"], {"en": True, "ja": True})

    def test_missing_compiled_translations_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            # compile_po 실행 전의 깨끗한 checkout처럼 .po 원본만 둔다.
            self.assertEqual(run_self_test(str(output), MODEL_DIR, Path(directory) / "empty"), 1)
            report = json.loads(output.read_text(encoding="utf-8"))

        self.assertFalse(report["ok"])
        self.assertEqual(report["translations"], {"en": False, "ja": False})

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
