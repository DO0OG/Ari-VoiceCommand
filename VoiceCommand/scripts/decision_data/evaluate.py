"""Held-out classification, calibration, and selective routing measurements."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from agent.decision.engine import LinearScorer, UNKNOWN
from agent.decision.candidates import is_direct_allowed
from agent.llm_router import get_llm_router
from .build_dataset import build_examples


def metrics(probabilities, targets, labels, threshold=0.92, eligible=None) -> dict:
    """Compute multiclass Brier/ECE and selection with unknown abstention."""
    probabilities = np.asarray(probabilities, dtype=float)
    targets = np.asarray(targets, dtype=int)
    if not len(targets):
        return {"count": 0, "accuracy": None, "coverage": 0.0, "selective_accuracy": None}
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
    return {
        "count": len(targets), "accuracy": float(correct.mean()),
        "selected_count": int(selected.sum()), "coverage": float(selected.mean()),
        "selective_accuracy": float(correct[selected].mean()) if selected.any() else None,
        "false_direct_count": int((selected & ~correct).sum()),
        "unknown_false_accept_count": int((selected & (targets == labels.index(UNKNOWN))).sum()),
        "ece": float(ece), "brier": float(np.square(probabilities - one_hot).sum(axis=1).mean()),
        "reliability_bins": reliability,
        "confusion_matrix": {label: {labels[j]: int(n) for j, n in enumerate(confusion[i]) if n}
                             for i, label in enumerate(labels)},
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
    eligible = [get_llm_router().route(row["text"]).task_type == "simple_chat" for row in test]
    result["with_existing_rule_gate"] = metrics(probabilities, targets, labels, threshold, eligible)
    direct_eligible = [
        rule_pass and is_direct_allowed(prediction.choice, "fast")
        for rule_pass, prediction in zip(eligible, predictions)
    ]
    for language in ("ko", "en", "ja"):
        mask = np.array([row["language"] == language for row in test])
        result["by_language"][language]["with_direct_policy_gate"] = metrics(
            probabilities[mask], targets[mask], labels, threshold,
            np.asarray(direct_eligible, dtype=bool)[mask],
        )
    result["with_direct_policy_gate"] = metrics(
        probabilities, targets, labels, threshold, direct_eligible)
    result["direct_executions"] = 0
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=Path("resources/decision"))
    parser.add_argument("--output", type=Path)
    parser.add_argument("--gold", action="store_true", help="evaluate the reserved partition")
    args = parser.parse_args(argv)
    if args.output is None:
        filename = "gold_evaluation.json" if args.gold else "evaluation.json"
        args.output = Path("scripts/decision_data") / filename
    result = evaluate(args.model, gold=args.gold)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
