"""Alternate deterministic splits that expose split-specific results.

The release decision uses one frozen split recorded in ``split_manifest.json``.
A model can still look good on that single arrangement by accident, so this
script rebuilds the partitions under a few fixed seeds, trains a model on each,
and reports how far the selective numbers move.  It never replaces the frozen
evaluation; it only says whether the frozen result is representative.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
import random

import numpy as np

from agent.decision.candidates import is_direct_allowed
from agent.decision.engine import candidate_names, hash_features, softmax
from agent.llm_router import get_llm_router
from .build_dataset import build_examples
from .evaluate import family_metrics, metrics
from .split_dataset import _least_filled, families_by_label
from .train import fit_linear


DEFAULT_SEEDS = (131, 271, 911)


def seeded_assignment(rows: list[dict], seed: int) -> dict[str, str]:
    """Place every family again from a shuffled order under a fixed seed."""
    # 재현 가능한 대체 분할을 만들기 위한 것이며 보안 용도가 아니다.
    rng = random.Random(seed)  # nosec B311
    assignment: dict[str, str] = {}
    for families in families_by_label(rows).values():
        order = list(families)
        rng.shuffle(order)
        counts: Counter = Counter()
        for family in order:
            split = _least_filled(counts)
            assignment[family] = split
            counts[split] += 1
    return assignment


def _probabilities(rows, weights, bias, temperature, buckets):
    logits = []
    for row in rows:
        indices, values = hash_features(row["text"], buckets)
        logits.append((weights[:, indices] * values).sum(axis=1) + bias)
    return softmax(np.asarray(logits), temperature)


def evaluate_split(rows: list[dict], seed: int, *, epochs: int, buckets: int) -> dict:
    """Train on one alternate split and report its selective numbers."""
    assignment = seeded_assignment(rows, seed)
    placed = [dict(row, split=assignment[row["family_id"]]) for row in rows]
    weights, bias, temperature = fit_linear(
        placed, buckets=buckets, epochs=epochs, augment=True
    )
    test = [row for row in placed if row["split"] == "test"]
    labels = list(candidate_names())
    probabilities = _probabilities(test, weights, bias, temperature, buckets)
    targets = np.array([labels.index(row["label"]) for row in test])
    eligible = [
        get_llm_router().route(row["text"]).task_type == "simple_chat"
        and is_direct_allowed(labels[int(index)], "fast")
        for row, index in zip(test, probabilities.argmax(axis=1))
    ]
    gated = metrics(probabilities, targets, labels, eligible=eligible)
    families = family_metrics(test, probabilities, targets, labels, eligible=eligible)
    return {
        "seed": seed,
        "split_counts": dict(sorted(Counter(row["split"] for row in placed).items())),
        "temperature": temperature,
        "accuracy": gated["accuracy"],
        "coverage": gated["coverage"],
        "selective_accuracy": gated["selective_accuracy"],
        "false_direct": gated["false_direct_count"],
        "family_selective_accuracy": families["family_selective_accuracy"],
        "family_false_direct": families["family_false_direct"],
    }


def summarize(reports: list[dict]) -> dict:
    """Reduce the per-seed reports to the values a release review looks at."""
    selective = [r["selective_accuracy"] for r in reports if r["selective_accuracy"] is not None]
    return {
        "selective_accuracy_mean": float(np.mean(selective)) if selective else None,
        "selective_accuracy_min": float(np.min(selective)) if selective else None,
        "false_direct_max": max((r["false_direct"] for r in reports), default=0),
        "family_false_direct_max": max((r["family_false_direct"] for r in reports), default=0),
        "coverage_mean": float(np.mean([r["coverage"] for r in reports])) if reports else None,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, nargs="+", default=list(DEFAULT_SEEDS))
    parser.add_argument("--epochs", type=int, default=160)
    parser.add_argument("--buckets", type=int, default=8192)
    parser.add_argument("--output", type=Path,
                        default=Path("scripts/decision_data/robustness.json"))
    args = parser.parse_args(argv)
    if args.epochs < 1 or not 1 <= args.buckets <= 65536:
        parser.error("epochs must be positive and buckets between 1 and 65536")

    rows, manifest = build_examples()
    reports = []
    for seed in args.seeds:
        report = evaluate_split(rows, seed, epochs=args.epochs, buckets=args.buckets)
        reports.append(report)
        print(json.dumps(report))
    payload = {
        "dataset_version": manifest["dataset_version"],
        "frozen_split_counts": manifest["split_counts"],
        "seeds": list(args.seeds),
        "splits": reports,
        "summary": summarize(reports),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload["summary"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
