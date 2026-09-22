"""Release checks for the committed local decision model.

Evaluates only the files that ship in ``resources/decision``; nothing is
trained here.  Every check reports a reason and the command exits non-zero
when any of them fails, so CI blocks a release that drifted from its data,
its candidate registry or its recorded measurements.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from agent.decision.candidates import UNKNOWN, candidate_names
from .build_dataset import build_examples
from .dataset_guards import validate_gold_isolation
from .evaluate import evaluate
from .gold_data import build_gold_examples
from .split_dataset import manifest_drift
from .train import training_sha256


DATA_DIR = Path(__file__).resolve().parent
MODEL_DIR = DATA_DIR.parents[1] / "resources" / "decision"
MIN_SELECTIVE_ACCURACY = 0.99
ARTIFACTS = ("evaluation.json", "benchmark_results.json")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def check_model(model_dir: Path, rows: list[dict], snapshot_path: Path) -> list[str]:
    """The weights, labels and training hash must match what the config claims."""
    failures = []
    config = _load_json(model_dir / "config.json")
    weights_sha = hashlib.sha256((model_dir / "weights.npz").read_bytes()).hexdigest()
    if weights_sha != config.get("sha256"):
        failures.append("weights.npz SHA-256 differs from config.json")
    registry = list(candidate_names())
    if config.get("labels") != registry or registry[-1] != UNKNOWN:
        failures.append("model labels differ from the candidate registry")
    if _load_json(snapshot_path).get("candidate_labels") != registry:
        failures.append("candidate_snapshot.json differs from the candidate registry")
    augment = bool(config.get("augmentation_enabled"))
    if training_sha256(rows, augment) != config.get("training_sha256"):
        failures.append("training data hash differs from the one the model was trained on")
    return failures


def check_data(rows: list[dict], gold_rows: list[dict]) -> list[str]:
    """Recorded splits must hold and the reserved set must stay out of training."""
    failures = []
    drift = manifest_drift(rows)
    for kind in ("moved", "unrecorded", "stale"):
        if drift[kind]:
            failures.append(f"split manifest {kind}: {drift[kind][:3]}")
    try:
        validate_gold_isolation(rows, gold_rows)
    except ValueError as exc:
        failures.append(f"gold leakage: {exc}")
    return failures


def check_metrics(result: dict, minimum: float = MIN_SELECTIVE_ACCURACY) -> list[str]:
    """Direct handling must not pick a wrong or unknown label on the frozen test split."""
    failures = []
    gated = result["with_direct_policy_gate"]
    if gated["false_direct_count"]:
        failures.append(f"false direct rows: {gated['false_direct_count']}")
    if gated["unknown_false_accept_count"]:
        failures.append(f"unknown accepted rows: {gated['unknown_false_accept_count']}")
    family = result["family_with_direct_policy_gate"]["family_false_direct"]
    if family:
        failures.append(f"false direct families: {family}")
    for language, values in result["by_language"].items():
        accuracy = values["with_direct_policy_gate"]["selective_accuracy"]
        if accuracy is not None and accuracy < minimum:
            failures.append(f"{language} selective accuracy {accuracy:.4f} below {minimum}")
    return failures


def check_artifacts(result: dict, data_dir: Path) -> list[str]:
    """Committed measurements must come from the shipped model and the current test rows."""
    failures = []
    for name in ARTIFACTS:
        path = data_dir / name
        if not path.is_file():
            failures.append(f"{name} is missing")
            continue
        recorded = _load_json(path)
        if recorded.get("model_sha256") != result["model_sha256"]:
            failures.append(f"{name} was not produced by the shipped model")
        if name == "evaluation.json" and (
            recorded.get("evaluation_rows_sha256") != result["evaluation_rows_sha256"]
        ):
            failures.append("evaluation.json was produced from different test rows")
    return failures


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=MODEL_DIR)
    args = parser.parse_args(argv)

    rows, _manifest = build_examples()
    gold_rows = build_gold_examples()
    result = evaluate(args.model)
    checks = {
        "model": check_model(args.model, rows, DATA_DIR / "candidate_snapshot.json"),
        "data": check_data(rows, gold_rows),
        "metrics": check_metrics(result),
        "artifacts": check_artifacts(result, DATA_DIR),
    }
    for name, failures in checks.items():
        print(json.dumps({"check": name, "ok": not failures, "failures": failures}))
    gated = result["with_direct_policy_gate"]
    print(json.dumps({
        "model_sha256": result["model_sha256"],
        "selected_count": gated["selected_count"],
        "selective_accuracy": gated["selective_accuracy"],
        "coverage": gated["coverage"],
    }))
    return 1 if any(checks.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
