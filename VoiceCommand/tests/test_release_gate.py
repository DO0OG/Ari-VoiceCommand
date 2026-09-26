"""커밋된 로컬 판단 모델의 배포 검사 테스트."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import re
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
    check_review_corpora,
)

SNAPSHOT = DATA_DIR / "candidate_snapshot.json"


def _passing_result():
    gated = {
        "selected_count": 50,
        "false_direct_count": 0,
        "unknown_false_accept_count": 0,
        "selective_accuracy": 0.995,
    }
    language_gate = dict(gated, selected_count=10, selective_accuracy=0.99)
    return {
        "with_direct_policy_gate": dict(gated),
        "family_with_direct_policy_gate": {"family_false_direct": 0},
        "by_language": {
            language: {"with_direct_policy_gate": dict(language_gate)}
            for language in ("ko", "en", "ja")
        },
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

    def test_release_build_requires_bulk_review_approval(self):
        from scripts.decision_data.review_corpus import load_review_corpora

        release, safety = load_review_corpora(validate_external=False)

        def reviewed(rows, rejected=lambda index, row: False):
            return [
                {**row, "review_status": "human_rejected" if rejected(index, row) else "human_approved"}
                for index, row in enumerate(rows)
            ]

        approved = lambda: (reviewed(release), reviewed(safety))  # noqa: E731
        self.assertEqual(check_review_corpora(True, loader=approved), [])

        # 배포된 코퍼스는 검수를 마쳤으므로 대기 상태는 테스트 안에서 되돌려 만든다.
        waiting = [{**row, "review_status": "pending_human_review"} for row in release]
        pending = lambda: (waiting, reviewed(safety))  # noqa: E731
        self.assertEqual(check_review_corpora(False, loader=pending), [])
        failures = check_review_corpora(True, loader=pending)
        self.assertTrue(any("release_gold: 825 rows are pending" in item for item in failures))

        # 언어마다 몇 행만 승인하고 나머지를 거절하면 통과하면 안 된다.
        few = lambda: (reviewed(release, lambda index, row: index >= 30),  # noqa: E731
                       reviewed(safety, lambda index, row: index >= 30))
        failures = check_review_corpora(True, loader=few)
        self.assertTrue(any("safety_gold: ja has" in item for item in failures))
        self.assertTrue(any("take_screenshot/ja has 0 approved direct rows" in item for item in failures))

        volume_ko = [index for index, row in enumerate(release)
                     if row["label"] == "adjust_volume" and row["language"] == "ko"
                     and row["bucket"] == "direct_candidate"][:12]
        one_short = lambda: (reviewed(release, lambda index, row: index in volume_ko),  # noqa: E731
                             reviewed(safety))
        self.assertEqual(
            check_review_corpora(True, loader=one_short),
            ["release_gold: adjust_volume/ko has 44 approved direct rows, below the minimum of 45"],
        )

        def broken():
            raise ValueError("review row fields differ from the required schema")

        self.assertEqual(len(check_review_corpora(False, loader=broken)), 1)
        # 배포된 코퍼스는 검수를 마쳐 개발 검사와 배포 검사를 모두 통과한다.
        self.assertEqual(check_review_corpora(False), [])
        self.assertEqual(check_review_corpora(True), [])

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
        result = {
            "model_sha256": "a" * 64,
            "provenance": {"candidate_policy_sha256": "a" * 64},
            "evaluation_rows_sha256": "b" * 64,
        }
        with tempfile.TemporaryDirectory() as directory:
            for name in ("evaluation.json", "benchmark_results.json"):
                payload = {
                    "model_sha256": "c" * 64,
                    "provenance": {"candidate_policy_sha256": "d" * 64},
                    "evaluation_rows_sha256": "b" * 64,
                }
                (Path(directory) / name).write_text(json.dumps(payload), encoding="utf-8")
            failures = check_artifacts(result, Path(directory))
        self.assertTrue(any("not produced by the shipped model" in item for item in failures))
        self.assertTrue(any("provenance differs" in item for item in failures))

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

    def test_development_sample_and_precision_floors_pass_at_boundary(self):
        self.assertEqual(check_metrics(_passing_result()), [])

        result = _passing_result()
        result["with_direct_policy_gate"]["selected_count"] = 49
        self.assertTrue(any("minimum of 50" in item for item in check_metrics(result)))

        result = _passing_result()
        result["by_language"]["ja"]["with_direct_policy_gate"]["selected_count"] = 9
        self.assertTrue(any("ja direct selection" in item for item in check_metrics(result)))

        result = _passing_result()
        result["with_direct_policy_gate"]["selective_accuracy"] = 0.994
        self.assertTrue(any("overall selective accuracy" in item for item in check_metrics(result)))

        result = _passing_result()
        result["by_language"]["ja"]["with_direct_policy_gate"]["selective_accuracy"] = 0.989
        self.assertTrue(any("ja selective accuracy" in item for item in check_metrics(result)))

    def test_strict_release_sample_floors_are_separate_from_dev_floors(self):
        result = _passing_result()
        result["with_direct_policy_gate"]["selected_count"] = 100
        for values in result["by_language"].values():
            values["with_direct_policy_gate"]["selected_count"] = 30
        self.assertEqual(check_metrics(result, strict_release=True), [])

        result["with_direct_policy_gate"]["selected_count"] = 99
        failures = check_metrics(result, strict_release=True)
        self.assertTrue(any("minimum of 100" in item for item in failures))

        result["with_direct_policy_gate"]["selected_count"] = 100
        result["by_language"]["ja"]["with_direct_policy_gate"]["selected_count"] = 29
        failures = check_metrics(result, strict_release=True)
        self.assertTrue(any("ja direct selection" in item and "minimum of 30" in item for item in failures))

    def test_current_fixed_split_sample_counts_do_not_meet_strict_floors(self):
        result = _passing_result()
        result["with_direct_policy_gate"]["selected_count"] = 51
        for language, count in (("ko", 21), ("en", 17), ("ja", 13)):
            result["by_language"][language]["with_direct_policy_gate"]["selected_count"] = count
        failures = check_metrics(result, strict_release=True)
        self.assertTrue(any("minimum of 100" in item for item in failures))
        for language in ("ko", "en", "ja"):
            self.assertTrue(any(language in item and "minimum of 30" in item for item in failures))

    def test_release_build_bundles_decision_runtime(self):
        # build_exe.py는 import하면 바로 빌드하므로 소스 텍스트로 확인한다.
        source = (VOICECOMMAND_ROOT / "build_exe.py").read_text(encoding="utf-8")
        self.assertFalse('"--nofollow-import-to=numpy"' in source, "numpy must ship with the EXE")
        for data_dir in re.findall(r'"--include-data-dir=([^=]+)=', source):
            self.assertTrue((VOICECOMMAND_ROOT / data_dir).is_dir(), data_dir)


if __name__ == "__main__":
    unittest.main()
