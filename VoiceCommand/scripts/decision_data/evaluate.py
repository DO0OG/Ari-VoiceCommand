"""Held-out classification, calibration, and selective routing measurements."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np

from agent.decision.engine import LinearScorer, UNKNOWN
from agent.decision.candidates import DIRECT_ALLOWLIST, is_direct_allowed
from agent.decision.semantics import is_multi_intent, parse_candidate
from core.settings_schema import DEFAULT_SETTINGS
from .build_dataset import build_examples
from .gold_data import build_gold_examples
from .provenance import (
    BASELINE_COMMIT,
    BASELINE_MANIFEST_SHA256,
    BASELINE_REF,
    artifact_fingerprints,
    sha256_file,
)


# These sample floors are regression and non-vacuity checks. The reported
# Wilson bounds describe uncertainty separately; the floors do not establish
# a 99% precision claim.
MIN_DEV_OVERALL_DIRECT_SELECTIONS = 50
MIN_DEV_LANGUAGE_DIRECT_SELECTIONS = 10
MIN_STRICT_RELEASE_OVERALL_DIRECT_SELECTIONS = 100
MIN_STRICT_RELEASE_LANGUAGE_DIRECT_SELECTIONS = 30
MIN_OVERALL_DIRECT_PRECISION = 0.995
MIN_LANGUAGE_DIRECT_PRECISION = 0.99
WILSON_95_Z = 1.959963984540054


def wilson_lower_bound_95(successes: int, trials: int) -> float | None:
    """Return the two-sided 95% Wilson lower bound, or None for no trials."""
    if trials < 0 or successes < 0 or successes > trials:
        raise ValueError("successes and trials must satisfy 0 <= successes <= trials")
    if trials == 0:
        return None
    z_squared = WILSON_95_Z**2
    proportion = successes / trials
    denominator = 1 + z_squared / trials
    center = proportion + z_squared / (2 * trials)
    margin = WILSON_95_Z * math.sqrt(
        proportion * (1 - proportion) / trials
        + z_squared / (4 * trials**2)
    )
    return max(0.0, min(1.0, (center - margin) / denominator))


def metrics(probabilities, targets, labels, threshold=0.92, eligible=None) -> dict:
    """Compute multiclass Brier/ECE and selection with unknown abstention."""
    probabilities = np.asarray(probabilities, dtype=float)
    targets = np.asarray(targets, dtype=int)
    if not len(targets):
        return {
            "count": 0, "accuracy": None, "selected_count": 0, "coverage": 0.0,
            "selective_accuracy": None, "selective_accuracy_wilson95_lower": None,
            "false_direct_count": 0, "unknown_false_accept_count": 0,
        }
    predicted = probabilities.argmax(axis=1)
    confidence = probabilities.max(axis=1)
    correct = predicted == targets
    sorted_probs = np.sort(probabilities, axis=1)
    selected = ((confidence >= threshold)
                & (sorted_probs[:, -1] - sorted_probs[:, -2] >= 0.30)
                & (predicted != labels.index(UNKNOWN)))
    if eligible is not None:
        selected &= np.asarray(eligible, dtype=bool)
    reliability = []
    ece = 0.0
    for index in range(10):
        mask = (confidence >= index / 10) & (
            confidence <= 1 if index == 9 else confidence < (index + 1) / 10)
        count = int(mask.sum())
        accuracy = float(correct[mask].mean()) if count else None
        mean_confidence = float(confidence[mask].mean()) if count else None
        if count:
            ece += count / len(targets) * abs(accuracy - mean_confidence)
        reliability.append({"lower": index / 10, "upper": (index + 1) / 10,
                            "count": count, "accuracy": accuracy, "confidence": mean_confidence})
    one_hot = np.eye(len(labels))[targets]
    confusion = np.zeros((len(labels), len(labels)), dtype=int)
    np.add.at(confusion, (targets, predicted), 1)
    selected_count = int(selected.sum())
    selected_correct = int(correct[selected].sum())
    return {
        "count": len(targets), "accuracy": float(correct.mean()),
        "selected_count": selected_count, "coverage": float(selected.mean()),
        "selective_accuracy": selected_correct / selected_count if selected_count else None,
        "selective_accuracy_wilson95_lower": wilson_lower_bound_95(
            selected_correct, selected_count
        ),
        "false_direct_count": int((selected & ~correct).sum()),
        "unknown_false_accept_count": int((selected & (targets == labels.index(UNKNOWN))).sum()),
        "ece": float(ece), "brier": float(np.square(probabilities - one_hot).sum(axis=1).mean()),
        "reliability_bins": reliability,
        "confusion_matrix": {label: {labels[j]: int(n) for j, n in enumerate(confusion[i]) if n}
                             for i, label in enumerate(labels)},
    }


def _selection(probabilities, targets, labels, threshold, eligible=None):
    """Return the per-row correct and selected masks the gates agree on."""
    predicted = probabilities.argmax(axis=1)
    confidence = probabilities.max(axis=1)
    sorted_probs = np.sort(probabilities, axis=1)
    selected = ((confidence >= threshold)
                & (sorted_probs[:, -1] - sorted_probs[:, -2] >= 0.30)
                & (predicted != labels.index(UNKNOWN)))
    if eligible is not None:
        selected &= np.asarray(eligible, dtype=bool)
    return predicted == targets, selected


def parser_confirmed_eligibility(rows, predictions, eligible):
    """Require the semantic parser to confirm each policy-eligible prediction."""

    return [
        allowed and parse_candidate(row["text"], prediction.choice).parse_success
        for row, prediction, allowed in zip(rows, predictions, eligible)
    ]


def family_metrics(rows, probabilities, targets, labels, threshold=0.92, eligible=None) -> dict:
    """Score each template family once so large variant groups cannot dominate.

    A family expands into dozens or hundreds of rows through spacing, noise and
    number variants.  Averaging over rows therefore reports how well the model
    handles the families that happened to generate the most variants, not how
    well it generalizes to a phrasing it has never seen.  Every family gets one
    vote here regardless of how many rows it produced.
    """
    probabilities = np.asarray(probabilities, dtype=float)
    targets = np.asarray(targets, dtype=int)
    if not len(targets):
        return {"family_count": 0, "family_top1_accuracy": None, "family_coverage": 0.0,
                "family_selective_accuracy": None, "family_false_direct": 0}
    correct, selected = _selection(probabilities, targets, labels, threshold, eligible)
    grouped: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        grouped.setdefault(str(row.get("family_id") or ""), []).append(index)
    accuracies, selective, false_direct, covered = [], [], 0, 0
    for indexes in grouped.values():
        member = np.array(indexes, dtype=int)
        accuracies.append(float(correct[member].mean()))
        chosen = selected[member]
        if chosen.any():
            covered += 1
            selective.append(float(correct[member][chosen].mean()))
            false_direct += int((chosen & ~correct[member]).any())
    return {
        "family_count": len(grouped),
        "family_top1_accuracy": float(np.mean(accuracies)),
        "family_coverage": covered / len(grouped),
        "family_selective_accuracy": float(np.mean(selective)) if selective else None,
        "family_false_direct": false_direct,
    }


def macro_metrics(rows, probabilities, targets, labels, threshold=0.92, eligible=None) -> dict:
    """Average per label and per language so rare classes keep their weight."""
    probabilities = np.asarray(probabilities, dtype=float)
    targets = np.asarray(targets, dtype=int)
    if not len(targets):
        return {"accuracy_by_label": None, "accuracy_by_language": None,
                "direct_precision": None}
    correct, selected = _selection(probabilities, targets, labels, threshold, eligible)

    def grouped_mean(keys, mask=None):
        scores = []
        for key in sorted(set(keys)):
            member = np.array([value == key for value in keys])
            if mask is not None:
                member = member & mask
            if member.any():
                scores.append(float(correct[member].mean()))
        return float(np.mean(scores)) if scores else None

    return {
        "accuracy_by_label": grouped_mean([labels[index] for index in targets]),
        "accuracy_by_language": grouped_mean([str(row.get("language") or "") for row in rows]),
        "direct_precision": grouped_mean(
            [labels[index] for index in probabilities.argmax(axis=1)], selected
        ),
    }


def confusion_comparison(current: dict, previous: dict | None, previous_sha256: str | None) -> dict:
    """Summarize top classifier errors and increases over the prior artifact."""

    def pairs(matrix):
        result = {}
        if not isinstance(matrix, dict):
            return result
        for actual, predicted_counts in matrix.items():
            if not isinstance(predicted_counts, dict):
                continue
            for predicted, count in predicted_counts.items():
                if actual != predicted and isinstance(count, int) and count > 0:
                    result[(str(actual), str(predicted))] = count
        return result

    current_pairs = pairs(current)
    prior_overall = previous.get("overall", {}) if isinstance(previous, dict) else {}
    previous_pairs = pairs(prior_overall.get("confusion_matrix", {}))
    major = sorted(current_pairs.items(), key=lambda item: (-item[1], item[0]))[:10]
    worsened = []
    for pair, current_count in current_pairs.items():
        previous_count = previous_pairs.get(pair, 0)
        if current_count > previous_count:
            worsened.append({
                "actual": pair[0], "predicted": pair[1],
                "current_count": current_count, "previous_count": previous_count,
                "increase": current_count - previous_count,
            })
    worsened.sort(key=lambda row: (-row["increase"], -row["current_count"], row["actual"], row["predicted"]))
    return {
        "scope": "classifier_top1",
        "previous_artifact_sha256": previous_sha256,
        "major_pairs": [
            {"actual": pair[0], "predicted": pair[1], "count": count}
            for pair, count in major
        ],
        "top_10_worsened_pairs": worsened[:10],
    }


def build_model_card(result: dict, model_dir: Path, data_dir: Path) -> dict:
    config = json.loads((Path(model_dir) / "config.json").read_text(encoding="utf-8"))
    gold_rows = build_gold_examples()
    review_status = sorted({str(row.get("review_status", "unspecified")) for row in gold_rows})
    gated = result["with_direct_policy_gate"]
    benchmark_path = Path(data_dir) / "benchmark_results.json"
    benchmark = (
        json.loads(benchmark_path.read_text(encoding="utf-8"))
        if benchmark_path.is_file() else {}
    )
    warm_ms = benchmark.get("warm_ms") or {}
    return {
        "model_name": "local_command_classifier",
        "model_version": config.get("version", 1),
        "model_sha256": result["model_sha256"],
        "task": "classify short Korean, English, and Japanese command requests",
        "supported_languages": sorted(result["by_language"]),
        "architecture": "hashed character n-gram linear classifier",
        "intended_use": "development evaluation and conservative local command selection",
        "direct_eligible_tools": sorted(DIRECT_ALLOWLIST),
        "runtime_policy_default": {
            "mode": DEFAULT_SETTINGS["local_decision_mode"],
            "direct_execution": DEFAULT_SETTINGS["local_decision_direct_execution"],
        },
        "training": {
            "dataset_version": config.get("dataset_version"),
            "training_sha256": config.get("training_sha256"),
            "augmentation_enabled": bool(config.get("augmentation_enabled")),
        },
        "evaluation": {
            "partition": "held_out_test",
            "row_count": result["overall"]["count"],
            "top1_accuracy": result["overall"]["accuracy"],
            "parser_confirmed_selected_count": gated["selected_count"],
            "parser_confirmed_precision": gated["selective_accuracy"],
            "parser_confirmed_precision_wilson95_lower": gated[
                "selective_accuracy_wilson95_lower"
            ],
            "false_direct_count": gated["false_direct_count"],
            "by_language": {
                language: {
                    "selected_count": values["with_direct_policy_gate"]["selected_count"],
                    "selective_accuracy": values["with_direct_policy_gate"]["selective_accuracy"],
                    "selective_accuracy_wilson95_lower": values[
                        "with_direct_policy_gate"
                    ]["selective_accuracy_wilson95_lower"],
                    "false_direct_count": values["with_direct_policy_gate"]["false_direct_count"],
                }
                for language, values in result["by_language"].items()
            },
            "precision_evidence": {
                "sample_floors": {
                    "development": {
                        "overall": MIN_DEV_OVERALL_DIRECT_SELECTIONS,
                        "per_language": MIN_DEV_LANGUAGE_DIRECT_SELECTIONS,
                    },
                    "strict_release": {
                        "overall": MIN_STRICT_RELEASE_OVERALL_DIRECT_SELECTIONS,
                        "per_language": MIN_STRICT_RELEASE_LANGUAGE_DIRECT_SELECTIONS,
                    },
                },
                "observed_parser_confirmed_selection_counts": {
                    "overall": gated["selected_count"],
                    "by_language": {
                        language: values["with_direct_policy_gate"]["selected_count"]
                        for language, values in result["by_language"].items()
                    },
                },
                "wilson95_lower_bounds": {
                    "overall": gated["selective_accuracy_wilson95_lower"],
                    "by_language": {
                        language: values["with_direct_policy_gate"][
                            "selective_accuracy_wilson95_lower"
                        ]
                        for language, values in result["by_language"].items()
                    },
                },
                "interpretation": (
                    "Sample floors guard against vacuous regression results; they do not "
                    "establish 99% precision. With zero errors, at least 381 samples are "
                    "needed for a two-sided 95% Wilson lower bound of 0.99."
                ),
            },
            "commands_dispatched": 0,
        },
        "resource_usage": {
            "model_resource_bytes": benchmark.get("resource_bytes"),
            "additional_steady_rss_bytes": benchmark.get("additional_steady_rss_bytes"),
            "warm_p95_ms": warm_ms.get("p95"),
            "gpu_used": benchmark.get("gpu_used"),
        },
        "review": {
            "gold_rows": len(gold_rows),
            "gold_status": review_status,
            "release_approval": "pending_human_review",
            "safety_corpus": "not_separated",
        },
        "limitations": [
            "The evaluation set is generated and does not represent microphone acceptance.",
            "The held-out measurements do not establish release readiness.",
            "The evaluator checks parser confirmation but does not dispatch commands.",
        ],
        "provenance": result["provenance"],
        "split_baseline": {
            "ref": BASELINE_REF,
            "commit": BASELINE_COMMIT,
            "manifest_sha256": BASELINE_MANIFEST_SHA256,
            "snapshot_sha256": sha256_file(Path(data_dir) / "split_manifest_baseline.json"),
        },
    }


def evaluate(model_dir: Path, threshold=0.92, *, gold=False) -> dict:
    rows, manifest = build_examples()
    if gold:
        from .gold_data import build_gold_examples
        from .dataset_guards import validate_gold_isolation

        test = build_gold_examples()
        validate_gold_isolation(rows, test)
        manifest = {
            "dataset_version": "decision-gold-v1",
            "row_count": len(test),
            "family_count": len({row["family_id"] for row in test}),
            "evaluation_only": True,
            "review_status": sorted({row["review_status"] for row in test}),
        }
    else:
        test = [row for row in rows if row["split"] == "test"]
    scorer = LinearScorer(model_dir)
    predictions = [scorer.predict(row["text"]) for row in test]
    probabilities = np.array([list(result.probabilities.values()) for result in predictions])
    targets = np.array([scorer.labels.index(row["label"]) for row in test])
    labels = list(scorer.labels)
    result = {"dataset": manifest, "threshold": threshold, "margin": 0.30,
              "overall": metrics(probabilities, targets, labels, threshold)}
    result["evaluation_rows_sha256"] = hashlib.sha256(
        json.dumps(test, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    result["by_language"] = {}
    for language in ("ko", "en", "ja"):
        mask = np.array([row["language"] == language for row in test])
        result["by_language"][language] = metrics(
            probabilities[mask], targets[mask], labels, threshold
        )
    buckets = ["hard_negative" if row["bucket"].startswith("hard_negative") else row["bucket"]
               for row in test]
    result["by_bucket"] = {}
    for bucket in sorted(set(buckets)):
        mask = np.array([value == bucket for value in buckets])
        result["by_bucket"][bucket] = metrics(probabilities[mask], targets[mask], labels, threshold)
    for kind in (False, True):
        mask = np.array([row["is_noise"] == kind for row in test])
        result["by_bucket"]["noise" if kind else "clean"] = metrics(
            probabilities[mask], targets[mask], labels, threshold)
    eligible = [not is_multi_intent(row["text"]) for row in test]
    result["with_existing_rule_gate"] = metrics(probabilities, targets, labels, threshold, eligible)
    direct_eligible = [
        rule_pass and is_direct_allowed(prediction.choice, "fast")
        for rule_pass, prediction in zip(eligible, predictions)
    ]
    parser_eligible = parser_confirmed_eligibility(test, predictions, direct_eligible)
    candidate_gate_selected = _selection(
        probabilities, targets, labels, threshold, direct_eligible
    )[1]
    parser_gate_selected = _selection(
        probabilities, targets, labels, threshold, parser_eligible
    )[1]
    result["parser_rejected_count"] = int((candidate_gate_selected & ~parser_gate_selected).sum())
    result["with_candidate_policy_gate"] = metrics(
        probabilities, targets, labels, threshold, direct_eligible
    )
    for language in ("ko", "en", "ja"):
        mask = np.array([row["language"] == language for row in test])
        result["by_language"][language]["with_candidate_policy_gate"] = metrics(
            probabilities[mask], targets[mask], labels, threshold,
            np.asarray(direct_eligible, dtype=bool)[mask],
        )
        result["by_language"][language]["with_direct_policy_gate"] = metrics(
            probabilities[mask], targets[mask], labels, threshold,
            np.asarray(parser_eligible, dtype=bool)[mask],
        )
    result["with_direct_policy_gate"] = metrics(
        probabilities, targets, labels, threshold, parser_eligible)
    # 계열 하나가 수백 행으로 늘어나므로 행 평균과 별개로 계열 한 표 기준을 함께 낸다.
    result["family"] = family_metrics(test, probabilities, targets, labels, threshold)
    result["family_with_direct_policy_gate"] = family_metrics(
        test, probabilities, targets, labels, threshold, parser_eligible)
    result["family_with_candidate_policy_gate"] = family_metrics(
        test, probabilities, targets, labels, threshold, direct_eligible)
    result["macro"] = macro_metrics(test, probabilities, targets, labels, threshold)
    result["macro_with_direct_policy_gate"] = macro_metrics(
        test, probabilities, targets, labels, threshold, parser_eligible)
    result["macro_with_candidate_policy_gate"] = macro_metrics(
        test, probabilities, targets, labels, threshold, direct_eligible)
    result["direct_executions"] = 0
    result["provenance"] = artifact_fingerprints(model_dir)
    result["model_sha256"] = result["provenance"]["model_sha256"]
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=Path("resources/decision"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--compare-with", type=Path,
                        help="prior evaluation artifact used for confusion-pair comparison")
    parser.add_argument("--gold", action="store_true", help="evaluate the reserved partition")
    args = parser.parse_args(argv)
    if args.output is None:
        filename = "gold_evaluation.json" if args.gold else "evaluation.json"
        args.output = Path("scripts/decision_data") / filename
    comparison_path = args.compare_with or args.output
    previous = None
    previous_sha256 = None
    if comparison_path.is_file():
        previous_bytes = comparison_path.read_bytes()
        previous_sha256 = hashlib.sha256(previous_bytes).hexdigest()
        try:
            previous = json.loads(previous_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            previous = None
    result = evaluate(args.model, gold=args.gold)
    result["confusion_comparison"] = confusion_comparison(
        result["overall"]["confusion_matrix"], previous, previous_sha256
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if not args.gold and args.output.resolve() == Path("scripts/decision_data/evaluation.json").resolve():
        card = build_model_card(result, args.model, args.output.parent)
        (args.output.parent / "model_card.json").write_text(
            json.dumps(card, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import pyplot as plt

    bins = [row for row in result["overall"]["reliability_bins"] if row["count"]]
    figure, axis = plt.subplots(figsize=(5, 5))
    axis.plot([0, 1], [0, 1], "--", color="gray", label="Perfect calibration")
    axis.plot([row["confidence"] for row in bins], [row["accuracy"] for row in bins], "o-")
    axis.set(xlim=(0, 1), ylim=(0, 1), xlabel="Mean confidence", ylabel="Accuracy",
             title="Reserved reliability (10 bins)" if args.gold else "Held-out reliability (10 bins)")
    axis.legend()
    figure.tight_layout()
    figure.savefig(args.output.with_suffix(".png"), dpi=150)
    plt.close(figure)
    print(json.dumps({key: result["overall"][key] for key in (
        "count", "accuracy", "selective_accuracy", "coverage", "ece", "brier", "false_direct_count")}))
    print(json.dumps({language: value["accuracy"] for language, value in result["by_language"].items()}))
    print(json.dumps(result["family_with_direct_policy_gate"]))
    print(json.dumps(result["macro_with_direct_policy_gate"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
