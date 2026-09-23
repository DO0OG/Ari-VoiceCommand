"""Unit checks for the Phase 0 dataset contract."""

from __future__ import annotations

from collections import defaultdict
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
import unicodedata
from unittest.mock import patch

# ``pytest`` loads tests/conftest.py, while direct unittest discovery does not.
VOICECOMMAND_ROOT = Path(__file__).resolve().parents[1]
if str(VOICECOMMAND_ROOT) not in sys.path:
    sys.path.insert(0, str(VOICECOMMAND_ROOT))

from scripts.decision_data.build_dataset import build_examples
from scripts.decision_data.generate_candidates import UNKNOWN_LABEL, build_snapshot
from scripts.decision_data.seed_data import HARD_NEGATIVE_FAMILIES
from scripts.decision_data.split_dataset import (
    SPLITS,
    assign_family_splits,
    baseline_manifest_drift,
    load_manifest,
    manifest_drift,
    validate_manifest,
    validate_family_splits,
)
from scripts.decision_data.evaluate import confusion_comparison
from scripts.decision_data.validate_release import check_metrics
from scripts.decision_data import provenance
from agent.decision.candidates import candidate_names as registry_candidate_names


class DecisionDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows, cls.manifest = build_examples()

    def test_candidate_snapshot_is_registry_derived_and_unknown_is_last(self):
        snapshot = build_snapshot()
        self.assertEqual(snapshot["candidate_labels"][-1], UNKNOWN_LABEL)
        self.assertEqual(tuple(snapshot["candidate_labels"]), registry_candidate_names())
        self.assertEqual(snapshot["source"]["candidate_registry"], "agent.decision.candidates.REGISTRY")
        self.assertEqual(snapshot["unsupported_schema_tools"], [])
        for name in ("adjust_volume", "mcp_call", "play_youtube", "shutdown_computer"):
            self.assertIn(name, snapshot["candidate_labels"])
        self.assertEqual(len(snapshot["core_tool_schemas"]), len(snapshot["core_tool_names"]))

    def test_seed_has_every_candidate_in_every_split_and_language(self):
        candidates = set(self.manifest["candidate_labels"])
        labels_by_split = {split: {row["label"] for row in self.rows if row["split"] == split} for split in SPLITS}
        for split in SPLITS:
            self.assertEqual(labels_by_split[split], candidates)

        languages_by_family = defaultdict(set)
        splits_by_family_language = defaultdict(set)
        for row in self.rows:
            key = (row["family_id"], row["language"])
            languages_by_family[row["family_id"]].add(row["language"])
            splits_by_family_language[key].add(row["split"])
        self.assertTrue(all(languages == {"ko", "en", "ja"} for languages in languages_by_family.values()))
        self.assertTrue(all(len(splits) == 1 for splits in splits_by_family_language.values()))

    def test_family_and_normalized_text_splits_are_disjoint(self):
        validate_family_splits(self.rows)
        family_splits = defaultdict(set)
        normalized_splits = defaultdict(set)
        for row in self.rows:
            family_splits[row["family_id"]].add(row["split"])
            normalized = " ".join(unicodedata.normalize("NFKC", row["text"]).casefold().split())
            normalized_splits[normalized].add(row["split"])
        self.assertTrue(all(len(splits) == 1 for splits in family_splits.values()))
        self.assertTrue(all(len(splits) == 1 for splits in normalized_splits.values()))

    def test_manifest_records_every_family_and_matches_the_built_split(self):
        recorded = load_manifest()
        families = {row["family_id"] for row in self.rows}
        self.assertTrue(recorded, "split manifest must be committed")
        self.assertEqual(set(recorded), families)
        for row in self.rows:
            self.assertEqual(row["split"], recorded[row["family_id"]])
        validate_manifest(self.rows)
        self.assertEqual(manifest_drift(self.rows), {"unrecorded": [], "stale": [], "moved": []})

    def test_new_family_is_placed_without_moving_recorded_families(self):
        recorded = load_manifest()
        label = self.rows[0]["label"]
        added = [{"label": label, "family_id": "zzz.unrecorded.family.01"}]
        assignment = assign_family_splits(
            [{"label": row["label"], "family_id": row["family_id"]} for row in self.rows] + added
        )
        moved = [
            family for family, split in recorded.items()
            if assignment.get(family) != split
        ]
        self.assertEqual(moved, [])
        self.assertIn(assignment["zzz.unrecorded.family.01"], SPLITS)

    def test_empty_manifest_reproduces_the_recorded_placement(self):
        # 기록이 없을 때의 배정 규칙이 현재 기록과 같아야 재현이 가능하다.
        assignment = assign_family_splits(
            [{"label": row["label"], "family_id": row["family_id"]} for row in self.rows],
            manifest={},
        )
        self.assertEqual(assignment, load_manifest())

    def test_manifest_validator_rejects_a_moved_or_unrecorded_family(self):
        moved = copy.deepcopy(self.rows)
        for row in moved:
            if row["family_id"] == self.rows[0]["family_id"]:
                row["split"] = "test" if row["split"] != "test" else "train"
        with self.assertRaises(ValueError):
            validate_manifest(moved)

        unrecorded = copy.deepcopy(self.rows)
        unrecorded[0]["family_id"] = "zzz.unrecorded.family.02"
        with self.assertRaises(ValueError):
            validate_manifest(unrecorded)

    def test_baseline_comparison_rejects_moved_families_and_allows_additions(self):
        baseline = load_manifest()
        current = dict(baseline)
        family = next(iter(current))
        current[family] = "test" if current[family] != "test" else "train"
        current["new.family"] = "calibration"
        drift = baseline_manifest_drift(current, baseline)
        self.assertEqual(drift["moved"], [family])
        self.assertEqual(drift["added"], ["new.family"])

    def test_current_split_manifest_matches_the_pinned_baseline(self):
        drift = baseline_manifest_drift()
        self.assertEqual(drift["moved"], [])
        self.assertEqual(drift["removed"], [])

    def test_release_metrics_reject_empty_overall_and_language_samples(self):
        empty_gate = {
            "selected_count": 0,
            "selective_accuracy": None,
            "false_direct_count": 0,
            "unknown_false_accept_count": 0,
        }
        result = {
            "with_direct_policy_gate": empty_gate,
            "family_with_direct_policy_gate": {"family_false_direct": 0},
            "by_language": {
                language: {"with_direct_policy_gate": dict(empty_gate)}
                for language in ("ko", "en", "ja")
            },
        }
        failures = check_metrics(result)
        self.assertEqual(len(failures), 4)
        self.assertTrue(any("overall direct selection" in failure for failure in failures))
        for language in ("ko", "en", "ja"):
            self.assertTrue(any(f"{language} direct selection" in failure for failure in failures))

    def test_release_metrics_require_all_supported_languages(self):
        gate = {
            "selected_count": 1,
            "selective_accuracy": 1.0,
            "false_direct_count": 0,
            "unknown_false_accept_count": 0,
        }
        result = {
            "with_direct_policy_gate": dict(gate),
            "family_with_direct_policy_gate": {"family_false_direct": 0},
            "by_language": {
                language: {"with_direct_policy_gate": dict(gate)}
                for language in ("ko", "en", "ja")
            },
        }
        del result["by_language"]["ja"]
        self.assertIn("ja metrics are missing", check_metrics(result))

    def test_candidate_policy_fingerprint_changes_when_policy_fixture_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir = root / "data"
            model_dir = root / "model"
            policy_path = root / "agent" / "decision" / "candidates.py"
            for path in (
                root / "agent" / "decision" / "semantics.py",
                root / "agent" / "decision" / "engine.py",
                root / "agent" / "llm_router.py",
                root / "core" / "settings_schema.py",
                data_dir / "candidate_snapshot.json",
                data_dir / "split_manifest.json",
                data_dir / "gold.jsonl",
                model_dir / "weights.npz",
                model_dir / "config.json",
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("fixture", encoding="utf-8")
            policy_path.parent.mkdir(parents=True, exist_ok=True)
            policy_path.write_text("policy v1", encoding="utf-8")
            baseline_path = data_dir / "split_manifest_baseline.json"
            baseline_path.write_text("baseline", encoding="utf-8")
            template = {
                key: provenance.DEFAULT_SETTINGS[key]
                for key in provenance.DECISION_SETTING_KEYS
            }
            (root / "ari_settings.template.json").write_text(
                json.dumps(template), encoding="utf-8"
            )
            with patch.object(provenance, "VOICECOMMAND_ROOT", root), patch.object(
                provenance, "BASELINE_MANIFEST_PATH", baseline_path
            ):
                before = provenance.artifact_fingerprints(model_dir, data_dir)
                policy_path.write_text("policy v2", encoding="utf-8")
                after = provenance.artifact_fingerprints(model_dir, data_dir)
        self.assertNotEqual(before["candidate_policy_sha256"], after["candidate_policy_sha256"])
        self.assertEqual(before["engine_sha256"], after["engine_sha256"])
        self.assertEqual(before["router_sha256"], after["router_sha256"])

    def test_confusion_comparison_reports_major_and_worsened_pairs(self):
        current = {
            "get_weather": {"get_weather": 30, "get_current_time": 5},
            "set_timer": {"set_timer": 40, "cancel_timer": 4},
            "launch_app": {"close_app": 7},
        }
        previous = {
            "overall": {
                "confusion_matrix": {
                    "get_weather": {"get_current_time": 2},
                    "set_timer": {"cancel_timer": 1},
                }
            }
        }
        comparison = confusion_comparison(current, previous, "a" * 64)
        self.assertEqual(comparison["previous_artifact_sha256"], "a" * 64)
        self.assertEqual(
            comparison["major_pairs"],
            [
                {"actual": "launch_app", "predicted": "close_app", "count": 7},
                {"actual": "get_weather", "predicted": "get_current_time", "count": 5},
                {"actual": "set_timer", "predicted": "cancel_timer", "count": 4},
            ],
        )
        self.assertEqual(
            [(row["actual"], row["predicted"], row["increase"])
             for row in comparison["top_10_worsened_pairs"]],
            [
                ("launch_app", "close_app", 7),
                ("get_weather", "get_current_time", 3),
                ("set_timer", "cancel_timer", 3),
            ],
        )

    def test_validator_rejects_unknown_split_and_cross_split_duplicate(self):
        unknown = copy.deepcopy(self.rows)
        unknown[0]["split"] = "validation"
        with self.assertRaises(ValueError):
            validate_family_splits(unknown)

        duplicate = copy.deepcopy(self.rows)
        duplicate[0]["text"] = duplicate[1]["text"]
        duplicate[1]["split"] = "test" if duplicate[0]["split"] != "test" else "train"
        with self.assertRaises(ValueError):
            validate_family_splits(duplicate)

    def test_hard_negative_golden_labels(self):
        expected = {
            "크롬을 열어서 검색해줘": UNKNOWN_LABEL,
            "파일에서 TODO를 찾아서 보여줘": "search_in_files",
            "파일 내용을 그대로 읽어줘": "read_file",
            "기존 파일의 오타를 고쳐서 저장해줘": "edit_file",
            "새 문서를 만들어서 내용을 써줘": "write_file",
            "화면을 분석하지 말고 캡처 파일만 저장해줘": "take_screenshot",
            "클립보드 내용을 읽지 말고 이 문장을 복사해줘": "set_clipboard",
            "복사된 클립보드 내용을 확인해줘": "get_clipboard",
            "타이머가 아니라 내일 작업을 예약해줘": "schedule_task",
            "작업 예약 말고 5분 타이머를 맞춰줘": "set_timer",
            "터미널 명령이 아니라 여러 단계 작업을 맡겨줘": UNKNOWN_LABEL,
            "에이전트 말고 이 터미널 명령만 실행해줘": "execute_shell_command",
            "검색하지 말고 지금 날씨만 알려줘": "get_weather",
        }
        labels_by_text = {
            row["text"]: row["label"]
            for row in self.rows
            if not row["is_noise"] and row["language"] == "ko"
        }
        for text, label in expected.items():
            self.assertEqual(labels_by_text[text], label)

        # Keep this golden list in sync with the hand-written seed itself: all
        # hard-negative records must use a supported candidate or abstain.
        candidate_labels = set(self.manifest["candidate_labels"])
        self.assertTrue(all(label in candidate_labels for label, _, _ in HARD_NEGATIVE_FAMILIES))

    def test_slot_variants_share_a_family_and_noise_preserves_content(self):
        launch_families = {
            row["family_id"]
            for row in self.rows
            if row["language"] == "en" and row["text"] in {"Open Chrome", "Launch Discord"}
        }
        close_families = {
            row["family_id"]
            for row in self.rows
            if row["language"] == "en" and row["text"] in {"Close Chrome", "Quit Discord"}
        }
        # 병합 후 대표 이름은 바뀔 수 있으므로 이름이 아니라 불변식을 확인한다.
        # 앱 이름만 바뀐 문장은 한 family 안에 머물러야 학습과 평가가 갈리지 않는다.
        self.assertEqual(len(launch_families), 1)
        self.assertEqual(len(close_families), 1)
        self.assertNotEqual(launch_families, close_families)
        noise_types = {row["noise_type"] for row in self.rows if row["is_noise"]}
        self.assertIn("numeric_transcription", noise_types)
        self.assertIn("app_transcription", noise_types)
        self.assertIn("phonetic_typo", noise_types)
        self.assertNotIn("trailing_word_drop", noise_types)


if __name__ == "__main__":
    unittest.main()
