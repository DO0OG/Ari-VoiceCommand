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
from .evaluate import build_model_card, confusion_comparison, evaluate
from .gold_data import build_gold_examples
from .provenance import (
    BASELINE_MANIFEST_SHA256,
    BASELINE_MANIFEST_PATH,
    sha256_file,
)
from .split_dataset import baseline_manifest_drift, load_manifest, manifest_drift
from .train import training_sha256


DATA_DIR = Path(__file__).resolve().parent
MODEL_DIR = DATA_DIR.parents[1] / "resources" / "decision"
MIN_SELECTIVE_ACCURACY = 0.99
MIN_DIRECT_SELECTIONS = 1
ARTIFACTS = ("evaluation.json", "benchmark_results.json", "model_card.json")


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
    if sha256_file(BASELINE_MANIFEST_PATH) != BASELINE_MANIFEST_SHA256:
        failures.append("pinned baseline split manifest SHA-256 differs")
    else:
        baseline_drift = baseline_manifest_drift(
            load_manifest(), load_manifest(BASELINE_MANIFEST_PATH)
        )
        if baseline_drift["moved"]:
            failures.append(f"baseline family split moved: {baseline_drift['moved'][:3]}")
        if baseline_drift["removed"]:
            failures.append(f"baseline families removed without migration: {baseline_drift['removed'][:3]}")
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
    if int(gated.get("selected_count") or 0) < MIN_DIRECT_SELECTIONS:
        failures.append(
            f"overall direct selection count is below the minimum of {MIN_DIRECT_SELECTIONS}"
        )
    elif gated.get("selective_accuracy") is None:
        failures.append("overall direct precision is unavailable")
    elif gated["selective_accuracy"] < minimum:
        failures.append(
            f"overall selective accuracy {gated['selective_accuracy']:.4f} below {minimum}"
        )
    languages = result.get("by_language", {})
    for language in ("ko", "en", "ja"):
        values = languages.get(language)
        if not isinstance(values, dict):
            failures.append(f"{language} metrics are missing")
            continue
        language_gate = values.get("with_direct_policy_gate")
        if not isinstance(language_gate, dict):
            failures.append(f"{language} direct metrics are missing")
            continue
        accuracy = language_gate.get("selective_accuracy")
        if int(language_gate.get("selected_count") or 0) < MIN_DIRECT_SELECTIONS:
            failures.append(
                f"{language} direct selection count is below the minimum of {MIN_DIRECT_SELECTIONS}"
            )
        elif accuracy is None:
            failures.append(f"{language} direct precision is unavailable")
        elif accuracy < minimum:
            failures.append(f"{language} selective accuracy {accuracy:.4f} below {minimum}")
    return failures


def check_artifacts(result: dict, data_dir: Path, model_dir: Path = MODEL_DIR) -> list[str]:
    """Committed measurements must match the model, data, policy, and parser inputs."""
    failures = []
    fingerprints = result["provenance"]
    for name in ARTIFACTS:
        path = data_dir / name
        if not path.is_file():
            failures.append(f"{name} is missing")
            continue
        recorded = _load_json(path)
        if recorded.get("model_sha256") != result["model_sha256"]:
            failures.append(f"{name} was not produced by the shipped model")
        if recorded.get("provenance") != fingerprints:
            failures.append(f"{name} provenance differs from the current inputs")
        if name == "evaluation.json":
            expected = dict(result)
            recorded_metrics = {key: value for key, value in recorded.items()
                                if key != "confusion_comparison"}
            if recorded_metrics != expected:
                failures.append("evaluation.json metrics differ from the current evaluation")
            comparison = recorded.get("confusion_comparison")
            previous_sha = comparison.get("previous_artifact_sha256") if isinstance(comparison, dict) else None
            if (not isinstance(previous_sha, str) or len(previous_sha) != 64
                    or any(
                        character not in "0123456789abcdef"
                        for character in previous_sha.lower()
                    )):
                failures.append("evaluation.json has no valid previous-artifact confusion comparison")
            else:
                expected_major = confusion_comparison(
                    result["overall"]["confusion_matrix"], None, previous_sha
                )["major_pairs"]
                if (
                    comparison.get("scope") != "classifier_top1"
                    or comparison.get("major_pairs") != expected_major
                ):
                    failures.append("evaluation.json major confusion pairs differ from current metrics")
                worsened = comparison.get("top_10_worsened_pairs")
                if not isinstance(worsened, list) or len(worsened) > 10:
                    failures.append("evaluation.json top 10 worsened confusion pairs are missing or invalid")
                elif any(
                    not isinstance(pair, dict)
                    or pair.get("actual") == pair.get("predicted")
                    or not all(isinstance(pair.get(key), int) for key in (
                        "current_count", "previous_count", "increase"
                    ))
                    or pair["current_count"] <= 0
                    or pair["previous_count"] < 0
                    or pair["increase"] <= 0
                    or pair["current_count"] != pair["previous_count"] + pair["increase"]
                    for pair in worsened
                ):
                    failures.append("evaluation.json has invalid worsened confusion pair counts")
        if name == "model_card.json":
            expected = build_model_card(result, model_dir, data_dir)
            if recorded != expected:
                failures.append("model_card.json differs from the current evaluation")
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
        "artifacts": check_artifacts(result, DATA_DIR, args.model),
    }
    for name, failures in checks.items():
        print(json.dumps({"check": name, "ok": not failures, "failures": failures}))
    gated = result["with_direct_policy_gate"]
    print(json.dumps({
        "model_sha256": result["model_sha256"],
        "selected_count": gated["selected_count"],
        "parser_rejected_count": result["parser_rejected_count"],
        "selective_accuracy": gated["selective_accuracy"],
        "coverage": gated["coverage"],
    }))
    return 1 if any(checks.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
