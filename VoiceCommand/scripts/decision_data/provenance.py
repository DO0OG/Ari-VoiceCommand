"""Hashes for the inputs that determine local decision measurements."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from core.settings_schema import DEFAULT_SETTINGS
from .gold_data import DATASET_VERSION as GOLD_DATASET_VERSION


VOICECOMMAND_ROOT = Path(__file__).resolve().parents[2]
BASELINE_MANIFEST_PATH = Path(__file__).with_name("split_manifest_baseline.json")
BASELINE_REF = "origin/137-release-quality-gate"
BASELINE_COMMIT = "ac2d4f9140a981035c46865b51dccf385d470092"
BASELINE_MANIFEST_SHA256 = "439bbad2281994370b92ab94f7153857c0726e7de37d56d1f2b00f291615fc39"
DECISION_SETTING_KEYS = (
    "local_decision_engine_enabled",
    "local_decision_backend",
    "local_decision_threshold",
    "local_decision_mode",
    "local_decision_direct_execution",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _sha256_json(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def artifact_fingerprints(model_dir: Path, data_dir: Path | None = None) -> dict[str, str]:
    data_dir = Path(data_dir) if data_dir is not None else Path(__file__).resolve().parent
    settings_template = json.loads(
        (VOICECOMMAND_ROOT / "ari_settings.template.json").read_text(encoding="utf-8")
    )
    settings = {
        "schema_defaults": {key: DEFAULT_SETTINGS[key] for key in DECISION_SETTING_KEYS},
        "template": {key: settings_template.get(key) for key in DECISION_SETTING_KEYS},
    }
    return {
        "model_sha256": sha256_file(Path(model_dir) / "weights.npz"),
        "model_config_sha256": sha256_file(Path(model_dir) / "config.json"),
        "candidate_snapshot_sha256": sha256_file(data_dir / "candidate_snapshot.json"),
        "candidate_policy_sha256": sha256_file(
            VOICECOMMAND_ROOT / "agent" / "decision" / "candidates.py"
        ),
        "parser_sha256": sha256_file(
            VOICECOMMAND_ROOT / "agent" / "decision" / "semantics.py"
        ),
        "engine_sha256": sha256_file(
            VOICECOMMAND_ROOT / "agent" / "decision" / "engine.py"
        ),
        "router_sha256": sha256_file(VOICECOMMAND_ROOT / "agent" / "llm_router.py"),
        "runtime_settings_sha256": _sha256_json(settings),
        "settings_schema_sha256": sha256_file(
            VOICECOMMAND_ROOT / "core" / "settings_schema.py"
        ),
        "split_manifest_sha256": sha256_file(data_dir / "split_manifest.json"),
        "split_baseline_manifest_sha256": sha256_file(BASELINE_MANIFEST_PATH),
        "split_baseline_commit": BASELINE_COMMIT,
        "gold_dataset_version": GOLD_DATASET_VERSION,
        "gold_dataset_sha256": sha256_file(data_dir / "gold.jsonl"),
    }
