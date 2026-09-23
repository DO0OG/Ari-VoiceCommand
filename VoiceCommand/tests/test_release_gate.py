"""Release gate checks for the committed local decision model."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

VOICECOMMAND_ROOT = Path(__file__).resolve().parents[1]
if str(VOICECOMMAND_ROOT) not in sys.path:
    sys.path.insert(0, str(VOICECOMMAND_ROOT))

from scripts.decision_data.build_dataset import build_examples
from scripts.decision_data.gold_data import build_gold_examples
from scripts.decision_data.validate_release import (
    DATA_DIR,
    MODEL_DIR,
    check_artifacts,
    check_data,
    check_metrics,
    check_model,
)

SNAPSHOT = DATA_DIR / "candidate_snapshot.json"


def _passing_result():
    gated = {"false_direct_count": 0, "unknown_false_accept_count": 0, "selective_accuracy": 1.0}
    return {
        "with_direct_policy_gate": dict(gated),
        "family_with_direct_policy_gate": {"family_false_direct": 0},
        "by_language": {language: {"with_direct_policy_gate": dict(gated)} for language in ("ko", "en", "ja")},
    }


class ReleaseGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, _ = build_examples()

    def _model_copy(self, directory: str, **config_changes) -> Path:
        model = Path(directory) / "decision"
        shutil.copytree(MODEL_DIR, model)
        config_path = model / "config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config.update(config_changes)
        config_path.write_text(json.dumps(config), encoding="utf-8")
        return model

    def test_shipped_model_and_data_pass(self):
        self.assertEqual(check_model(MODEL_DIR, self.rows, SNAPSHOT), [])
        self.assertEqual(check_data(self.rows, build_gold_examples()), [])

    def test_weights_hash_and_label_mismatch_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            model = self._model_copy(directory, sha256="0" * 64)
            self.assertTrue(any("SHA-256" in item for item in check_model(model, self.rows, SNAPSHOT)))
        with tempfile.TemporaryDirectory() as directory:
            config = json.loads((MODEL_DIR / "config.json").read_text(encoding="utf-8"))
            model = self._model_copy(directory, labels=config["labels"][::-1])
            self.assertTrue(any("labels" in item for item in check_model(model, self.rows, SNAPSHOT)))

    def test_moved_family_fails(self):
        moved = copy.deepcopy(self.rows)
        family = moved[0]["family_id"]
        target = "test" if moved[0]["split"] != "test" else "train"
        for row in moved:
            if row["family_id"] == family:
                row["split"] = target
        failures = check_data(moved, build_gold_examples())
        self.assertTrue(any("moved" in item for item in failures))

    def test_artifact_from_another_model_fails(self):
        result = {"model_sha256": "a" * 64, "evaluation_rows_sha256": "b" * 64}
        with tempfile.TemporaryDirectory() as directory:
            for name in ("evaluation.json", "benchmark_results.json"):
                payload = {"model_sha256": "c" * 64, "evaluation_rows_sha256": "b" * 64}
                (Path(directory) / name).write_text(json.dumps(payload), encoding="utf-8")
            failures = check_artifacts(result, Path(directory))
        self.assertEqual(len(failures), 2)

    def test_false_direct_and_low_language_accuracy_fail(self):
        self.assertEqual(check_metrics(_passing_result()), [])
        result = _passing_result()
        result["with_direct_policy_gate"]["false_direct_count"] = 1
        self.assertTrue(check_metrics(result))
        result = _passing_result()
        result["family_with_direct_policy_gate"]["family_false_direct"] = 1
        self.assertTrue(check_metrics(result))
        result = _passing_result()
        result["by_language"]["ja"]["with_direct_policy_gate"]["selective_accuracy"] = 0.95
        self.assertTrue(check_metrics(result))


if __name__ == "__main__":
    unittest.main()
