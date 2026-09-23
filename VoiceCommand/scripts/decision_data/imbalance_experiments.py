"""Compare family/class balancing and per-family variant caps on calibration data."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from agent.decision.candidates import DIRECT_ALLOWLIST, is_direct_allowed
from agent.decision.engine import LinearScorer, candidate_names, hash_features, softmax
from agent.decision.semantics import parse_candidate
from agent.llm_router import get_llm_router
from .build_dataset import build_examples
from .evaluate import family_metrics, macro_metrics, metrics
from .train import fit_linear, fit_temperature, training_sha256


THRESHOLD = 0.92
MARGIN = 0.30
EPOCHS = 160
CAPS = (4, 8)
_LANGUAGES = ("ko", "en", "ja")
THRESHOLD_DIAGNOSTICS = (
    (0.92, 0.30),
    (0.85, 0.25),
    (0.80, 0.20),
    (0.70, 0.20),
    (0.60, 0.15),
)
_SOURCE_ROOT = Path(__file__).resolve().parents[2]
_POLICY_SOURCES = (
    "agent/decision/candidates.py",
    "agent/decision/engine.py",
    "agent/decision/semantics.py",
    "agent/llm_router.py",
)
PROFILES = (
    "baseline",
    "family_weighted",
    "class_family_weighted",
    *(f"augmentation_cap_{cap}" for cap in CAPS),
)


def cap_training_variants(rows: list[dict], limit: int | None) -> list[dict]:
    """Keep every clean train row and at most ``limit`` noise variants per family."""
    if limit is None:
        return list(rows)
    if limit < 0:
        raise ValueError("variant limit must be non-negative")

    kept_ids = {
        id(row) for row in rows
        if row.get("split") != "train" or not (row.get("is_noise") or row.get("augmentation"))
    }
    variants: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        if row.get("split") == "train" and (row.get("is_noise") or row.get("augmentation")):
            family = str(row.get("family_id") or "")
            language = str(row.get("language") or "")
            variants[family][language].append(row)

    language_order = (*_LANGUAGES, "")
    for by_language in variants.values():
        for values in by_language.values():
            values.sort(key=lambda row: (str(row.get("noise_type") or ""), str(row.get("id") or ""), row["text"]))
        selected = 0
        while selected < limit:
            added = False
            for language in language_order:
                values = by_language.get(language)
                if values:
                    kept_ids.add(id(values.pop(0)))
                    selected += 1
                    added = True
                    if selected == limit:
                        break
            if not added:
                break
    return [row for row in rows if id(row) in kept_ids]


def sample_weights(rows: list[dict], scheme: str) -> np.ndarray:
    """Return mean-one row weights for family or class-within-family balance."""
    if scheme not in {"family", "class_family"}:
        raise ValueError(f"unknown weighting scheme: {scheme}")
    family_counts = Counter(str(row.get("family_id") or "") for row in rows)
    if not rows or "" in family_counts:
        raise ValueError("weighted rows must have family_id values")

    family_labels: dict[str, str] = {}
    for row in rows:
        family = str(row["family_id"])
        label = str(row["label"])
        previous = family_labels.setdefault(family, label)
        if previous != label:
            raise ValueError(f"family has multiple labels: {family}")

    families_per_label = Counter(family_labels.values())
    values = np.asarray([
        1.0 / family_counts[str(row["family_id"])]
        / (families_per_label[str(row["label"])] if scheme == "class_family" else 1)
        for row in rows
    ], dtype=np.float32)
    values /= values.mean()
    return values


def _folds(rows: list[dict], count: int = 5, seed: int = 131) -> np.ndarray:
    family_ids = {str(row.get("family_id") or "") for row in rows}
    if count < 2 or len(family_ids) < count or "" in family_ids:
        raise ValueError("calibration needs at least one family per fold")
    ordered_families = sorted(
        family_ids,
        key=lambda family: hashlib.sha256(f"{seed}:{family}".encode("utf-8")).digest(),
    )
    family_fold = {
        family: index % count for index, family in enumerate(ordered_families)
    }
    return np.asarray([family_fold[str(row["family_id"])] for row in rows], dtype=np.intp)


def out_of_fold_probabilities(
    rows: list[dict], logits: np.ndarray, labels: tuple[str, ...], *, folds: int = 5
) -> tuple[np.ndarray, dict[str, float]]:
    """Fit temperature on other calibration families, then score each held-out fold."""
    targets = np.asarray([labels.index(row["label"]) for row in rows], dtype=np.intp)
    assignments = _folds(rows, folds)
    probabilities = np.empty_like(logits, dtype=np.float64)
    temperatures: dict[str, float] = {}
    for fold in range(folds):
        dev = assignments == fold
        temperature_rows = ~dev
        temperature = fit_temperature(logits[temperature_rows], targets[temperature_rows])
        probabilities[dev] = softmax(logits[dev], temperature)
        temperatures[str(fold)] = temperature
    return probabilities, temperatures


def _logits(weights: np.ndarray, bias: np.ndarray, rows: list[dict], buckets: int) -> np.ndarray:
    result = []
    for row in rows:
        indices, values = hash_features(row["text"], buckets)
        result.append((weights[:, indices] * values).sum(axis=1) + bias)
    return np.asarray(result, dtype=np.float64)


def _policy_eligibility(rows: list[dict], probabilities: np.ndarray, labels: tuple[str, ...], simple_gate) -> np.ndarray:
    eligible = []
    for index, row in enumerate(rows):
        label = labels[int(probabilities[index].argmax())]
        if not simple_gate[index] or not is_direct_allowed(label, "fast"):
            eligible.append(False)
            continue
        eligible.append(parse_candidate(row["text"], label).parse_success)
    return np.asarray(eligible, dtype=bool)


def _class_proposals(rows, probabilities, targets, labels, eligibility) -> dict:
    predictions = probabilities.argmax(axis=1)
    confidence = probabilities.max(axis=1)
    ordered = np.sort(probabilities, axis=1)
    margin = ordered[:, -1] - ordered[:, -2]
    result = {}
    for label in sorted(DIRECT_ALLOWLIST):
        predicted = np.asarray([labels[index] == label for index in predictions])
        valid = predicted & eligibility & (margin >= MARGIN)
        selected = valid & (confidence >= THRESHOLD)
        wrong = selected & (predictions != targets)
        wrong_confidence = float(confidence[wrong].max()) if wrong.any() else None
        proposal_threshold = max(
            THRESHOLD,
            float(np.nextafter(wrong_confidence, math.inf)) if wrong_confidence is not None else THRESHOLD,
        )
        if proposal_threshold > 1.0:
            proposal_threshold = None
        proposed = (
            valid & (confidence >= proposal_threshold)
            if proposal_threshold is not None else np.zeros_like(valid)
        )
        selected_families = {str(row["family_id"]) for row, keep in zip(rows, proposed) if keep}
        false_families = {
            str(rows[index]["family_id"])
            for index in np.flatnonzero(proposed & (predictions != targets))
        }
        result[label] = {
            "predicted_rows": int(predicted.sum()),
            "selected_rows_at_global_threshold": int(selected.sum()),
            "false_direct_at_global_threshold": int(wrong.sum()),
            "selected_families_at_proposed_threshold": len(selected_families),
            "selected_rows_at_proposed_threshold": int(proposed.sum()),
            "false_direct_at_proposed_threshold": int((proposed & (predictions != targets)).sum()),
            "false_direct_families_at_proposed_threshold": len(false_families),
            "proposed_threshold": proposal_threshold,
            "proposal": (
                "candidate" if len(selected_families) >= 5 and not false_families
                else "disabled_pending_more_calibration_families"
            ),
        }
    return result


def _calibration_diagnostics(rows, probabilities, labels, simple_gate, eligibility=None) -> dict:
    """Report calibration-only direct selection by fixed threshold and margin pairs."""
    probabilities = np.asarray(probabilities, dtype=np.float64)
    targets = np.asarray([labels.index(row["label"]) for row in rows], dtype=np.intp)
    predictions = probabilities.argmax(axis=1)
    confidence = probabilities.max(axis=1)
    ordered = np.sort(probabilities, axis=1)
    margins = ordered[:, -1] - ordered[:, -2]
    correct = predictions == targets
    allowed = np.asarray([
        is_direct_allowed(labels[index], "fast") for index in predictions
    ], dtype=bool)
    simple_gate = np.asarray(simple_gate, dtype=bool)
    eligible = (
        _policy_eligibility(rows, probabilities, labels, simple_gate)
        if eligibility is None else np.asarray(eligibility, dtype=bool)
    )
    router_rejected = allowed & ~simple_gate
    parser_rejected = allowed & simple_gate & ~eligible

    confidence_buckets = []
    for lower, upper, name in (
        (0.0, 0.60, "below_0_60"),
        (0.60, 0.70, "0_60_to_0_70"),
        (0.70, 0.80, "0_70_to_0_80"),
        (0.80, 0.85, "0_80_to_0_85"),
        (0.85, 0.92, "0_85_to_0_92"),
        (0.92, 1.01, "at_least_0_92"),
    ):
        selected = eligible & (confidence >= lower) & (confidence < upper)
        confidence_buckets.append({
            "bucket": name,
            "rows": int(selected.sum()),
            "correct": int((selected & correct).sum()),
            "wrong": int((selected & ~correct).sum()),
        })

    profiles = []
    for threshold, minimum_margin in THRESHOLD_DIAGNOSTICS:
        confident = confidence >= threshold
        enough_margin = margins >= minimum_margin
        selected = eligible & confident & enough_margin
        false = selected & ~correct
        class_results = {}
        for label in sorted(DIRECT_ALLOWLIST):
            predicted_class = np.asarray([labels[index] == label for index in predictions])
            class_selected = selected & predicted_class
            class_false = class_selected & ~correct
            class_results[label] = {
                "selected_rows": int(class_selected.sum()),
                "selected_families": len({
                    str(rows[index]["family_id"])
                    for index in np.flatnonzero(class_selected)
                }),
                "false_direct_rows": int(class_false.sum()),
                "false_direct_families": len({
                    str(rows[index]["family_id"])
                    for index in np.flatnonzero(class_false)
                }),
            }
        profiles.append({
            "threshold": threshold,
            "margin": minimum_margin,
            "eligible_rows": int(eligible.sum()),
            "selected_rows": int(selected.sum()),
            "selected_families": len({
                str(rows[index]["family_id"])
                for index in np.flatnonzero(selected)
            }),
            "false_direct_rows": int(false.sum()),
            "false_direct_families": len({
                str(rows[index]["family_id"])
                for index in np.flatnonzero(false)
            }),
            "below_confidence_only": int((eligible & ~confident & enough_margin).sum()),
            "below_margin_only": int((eligible & confident & ~enough_margin).sum()),
            "below_both": int((eligible & ~confident & ~enough_margin).sum()),
            "by_class": class_results,
        })

    return {
        "predicted_allowlisted_rows": int(allowed.sum()),
        "simple_gate_rejected_rows": int(router_rejected.sum()),
        "parser_rejected_rows": int(parser_rejected.sum()),
        "parser_eligible_rows": int(eligible.sum()),
        "confidence_buckets": confidence_buckets,
        "threshold_profiles": profiles,
    }


def _score_trial(rows, probabilities, labels, simple_gate) -> dict:
    targets = np.asarray([labels.index(row["label"]) for row in rows], dtype=np.intp)
    eligibility = _policy_eligibility(rows, probabilities, labels, simple_gate)
    return {
        "overall": metrics(probabilities, targets, labels, THRESHOLD),
        "nll": float(-np.log(probabilities[np.arange(len(targets)), targets].clip(1e-15)).mean()),
        "direct_policy": metrics(probabilities, targets, labels, THRESHOLD, eligibility),
        "family": family_metrics(rows, probabilities, targets, labels, THRESHOLD, eligibility),
        "macro": macro_metrics(rows, probabilities, targets, labels, THRESHOLD, eligibility),
        "per_class_policy_proposal": _class_proposals(
            rows, probabilities, targets, labels, eligibility
        ),
        "calibration_diagnostics": _calibration_diagnostics(
            rows, probabilities, labels, simple_gate, eligibility
        ),
    }


def _candidate_improves(candidate: dict, baseline: dict) -> bool:
    current = candidate["score"]
    base = baseline["score"]
    current_direct = current["direct_policy"]
    base_direct = base["direct_policy"]
    current_family = current["family"]
    base_family = base["family"]
    current_macro = current["macro"]
    base_macro = base["macro"]
    return bool(
        current["overall"]["accuracy"] >= base["overall"]["accuracy"]
        and current_family["family_top1_accuracy"] >= base_family["family_top1_accuracy"]
        and current_macro["accuracy_by_label"] >= base_macro["accuracy_by_label"]
        and current_macro["accuracy_by_language"] >= base_macro["accuracy_by_language"]
        and current["overall"]["ece"] <= base["overall"]["ece"]
        and current["nll"] <= base["nll"]
        and current_direct["false_direct_count"] == 0
        and current_family["family_false_direct"] == 0
        and current_direct["selected_count"] >= base_direct["selected_count"]
        and (
            current_family["family_top1_accuracy"] > base_family["family_top1_accuracy"]
            or current_macro["accuracy_by_label"] > base_macro["accuracy_by_label"]
            or current_direct["selected_count"] > base_direct["selected_count"]
        )
    )


def run_experiments(
    output_path: Path, *, model_dir: Path | None = None, epochs_override: int | None = None,
    profiles: tuple[str, ...] | None = None,
) -> dict:
    rows, manifest = build_examples()
    train_rows = [row for row in rows if row["split"] == "train"]
    calibration = [
        row for row in rows
        if row["split"] == "calibration" and not row.get("augmentation", False)
    ]
    if not train_rows or not calibration:
        raise ValueError("train and calibration partitions must not be empty")

    labels = candidate_names()
    model_dir = model_dir or Path(__file__).resolve().parents[2] / "resources" / "decision"
    existing = LinearScorer(model_dir)
    config = json.loads((model_dir / "config.json").read_text(encoding="utf-8"))
    configured_epochs = int(config["epochs"])
    epochs = configured_epochs if epochs_override is None else epochs_override
    if not 1 <= epochs <= configured_epochs:
        raise ValueError(f"epochs must be between 1 and {configured_epochs}")
    training_hash = training_sha256(rows, augment=True)
    manifest_path = Path(__file__).with_name("split_manifest.json")
    simple_gate_router = get_llm_router()
    simple_gate = np.asarray([
        simple_gate_router.route(row["text"]).task_type == "simple_chat" for row in calibration
    ], dtype=bool)
    existing_logits = _logits(existing.weights, existing.bias, calibration, existing.buckets)
    existing_probabilities, existing_temperatures = out_of_fold_probabilities(
        calibration, existing_logits, labels
    )

    trials = {}
    configurations = [
        ("baseline", None, None),
        ("family_weighted", "family", None),
        ("class_family_weighted", "class_family", None),
        *((f"augmentation_cap_{cap}", None, cap) for cap in CAPS),
    ]
    profiles_to_run = PROFILES if profiles is None else profiles
    if "baseline" not in profiles_to_run or set(profiles_to_run) - set(PROFILES):
        raise ValueError("profiles must include baseline and contain only known trials")
    if len(set(profiles_to_run)) != len(profiles_to_run):
        raise ValueError("profiles must not contain duplicates")
    baseline_weights = baseline_bias = None
    for name, weighting, cap in configurations:
        if name not in profiles_to_run:
            continue
        selected_rows = cap_training_variants(rows, cap)
        selected_train = [row for row in selected_rows if row["split"] == "train"]
        weights = sample_weights(selected_train, weighting) if weighting else None
        model_weights, bias, _ = fit_linear(
            selected_rows,
            buckets=existing.buckets,
            epochs=epochs,
            augment=True,
            sample_weights=weights,
        )
        if name == "baseline":
            baseline_weights, baseline_bias = model_weights, bias
        logits = _logits(model_weights, bias, calibration, existing.buckets)
        probabilities, temperatures = out_of_fold_probabilities(calibration, logits, labels)
        trials[name] = {
            "training_rows": len(selected_train),
            "training_families": len({row["family_id"] for row in selected_train}),
            "training_rows_sha256": hashlib.sha256(
                json.dumps(selected_train, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "temperature_by_calibration_fold": temperatures,
            "score": _score_trial(calibration, probabilities, labels, simple_gate),
        }

    trials["baseline"]["reproduces_current_model"] = bool(
        np.array_equal(baseline_weights, existing.weights)
        and np.array_equal(baseline_bias, existing.bias)
    ) if epochs == configured_epochs else None
    eligible = [
        name for name in trials
        if name != "baseline" and _candidate_improves(trials[name], trials["baseline"])
    ]
    selected = min(
        eligible,
        key=lambda name: (
            -trials[name]["score"]["direct_policy"]["selected_count"],
            -trials[name]["score"]["family"]["family_top1_accuracy"],
            trials[name]["score"]["overall"]["ece"],
            name,
        ),
    ) if eligible else None

    result = {
        "protocol": {
            "training_partition": "train",
            "selection_partition": "family-held-out calibration folds",
            "commands_dispatched": 0,
            "gold_used_for_selection": False,
            "test_used_for_selection": False,
            "review_corpora_used": False,
            "train_row_count": len(train_rows),
            "train_family_count": len({row["family_id"] for row in train_rows}),
            "training_sha256": training_hash,
            "baseline_training_sha256": config.get("training_sha256"),
            "baseline_training_sha256_matches": training_hash == config.get("training_sha256"),
            "split_manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            "calibration_row_count": len(calibration),
            "calibration_family_count": len({row["family_id"] for row in calibration}),
            "calibration_rows_sha256": hashlib.sha256(
                json.dumps(calibration, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "dataset_version": manifest["dataset_version"],
            "policy_source_sha256": {
                source: hashlib.sha256((_SOURCE_ROOT / source).read_bytes()).hexdigest()
                for source in _POLICY_SOURCES
            },
            "epochs": epochs,
            "configured_training_epochs": configured_epochs,
            "screening_only": epochs != configured_epochs,
            "threshold": THRESHOLD,
            "margin": MARGIN,
            "augmentation_caps": list(CAPS),
            "profiles_run": list(profiles_to_run),
            "selection_rule": (
                "No regression in row accuracy, family top-1 accuracy, label-macro accuracy, "
                "language-macro accuracy, ECE, or NLL; zero direct false-directs and family "
                "false-directs; no reduction in direct selections; and strict improvement in "
                "family top-1 accuracy, label-macro accuracy, or direct selections."
            ),
            "threshold_proposal_note": (
                "Per-class thresholds are calibration candidates only and require a frozen human-reviewed release gate."
            ),
        },
        "existing_model_calibration": {
            "model_sha256": config.get("sha256"),
            "temperature_by_calibration_fold": existing_temperatures,
            "score": _score_trial(calibration, existing_probabilities, labels, simple_gate),
        },
        "trials": trials,
        "eligible_candidates": eligible,
        "selected_candidate": selected,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--epochs", type=int)
    parser.add_argument("--profiles", nargs="+", choices=PROFILES)
    args = parser.parse_args(argv)
    output_path = args.output.resolve()
    repo_root = Path(__file__).resolve().parents[3]
    if output_path.is_relative_to(repo_root):
        parser.error("write the experiment artifact outside the repository")
    result = run_experiments(
        output_path,
        model_dir=args.model_dir,
        epochs_override=args.epochs,
        profiles=tuple(args.profiles) if args.profiles else None,
    )
    print(json.dumps({
        "selected_candidate": result["selected_candidate"],
        "eligible_candidates": result["eligible_candidates"],
        "output": str(output_path),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
