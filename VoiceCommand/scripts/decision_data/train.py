"""Offline NumPy softmax training; calibration never uses the test partition."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from agent.decision.engine import candidate_names, hash_features, softmax
from .build_dataset import DATASET_VERSION, build_examples
from .generate_candidates import write_snapshot
from .split_dataset import validate_family_splits


def fit_temperature(logits: np.ndarray, targets: np.ndarray) -> float:
    """Choose a positive scalar by calibration negative log likelihood."""
    if not len(targets):
        raise ValueError("Calibration partition must not be empty")
    temperatures = np.unique(np.append(np.geomspace(0.05, 20.0, 241), 1.0))
    losses = [
        -np.log(softmax(logits, float(t))[np.arange(len(targets)), targets].clip(1e-15)).mean()
        for t in temperatures
    ]
    return float(temperatures[int(np.argmin(losses))])


def fit_linear(rows: list[dict], *, buckets: int = 8192, epochs: int = 160):
    """Fit on train families only, then calibrate on separate families."""
    validate_family_splits(rows)
    labels = candidate_names()
    train = [row for row in rows if row["split"] == "train"]
    calibration = [row for row in rows if row["split"] == "calibration"]
    features = [hash_features(row["text"], buckets) for row in train]
    targets = np.array([labels.index(row["label"]) for row in train])
    weights = np.zeros((len(labels), buckets), dtype=np.float32)
    bias = np.zeros(len(labels), dtype=np.float32)
    rng = np.random.default_rng(131)
    for epoch in range(epochs):
        rate = 0.3 / (1.0 + epoch / 80.0)
        weights *= 0.999
        for row in rng.permutation(len(train)):
            indices, values = features[row]
            logits = (weights[:, indices] * values).sum(axis=1) + bias
            error = softmax(logits).astype(np.float32)
            error[targets[row]] -= 1
            weights[:, indices] -= rate * error[:, None] * values
            bias -= rate * error
    logits = []
    for row in calibration:
        indices, values = hash_features(row["text"], buckets)
        logits.append((weights[:, indices] * values).sum(axis=1) + bias)
    temperature = fit_temperature(
        np.asarray(logits), np.array([labels.index(row["label"]) for row in calibration])
    )
    return weights, bias, temperature


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("resources/decision"))
    parser.add_argument("--epochs", type=int, default=160)
    parser.add_argument("--buckets", type=int, default=8192)
    args = parser.parse_args(argv)
    if args.epochs < 1 or not 1 <= args.buckets <= 65536:
        parser.error("epochs must be positive and buckets between 1 and 65536")
    rows, manifest = build_examples()
    weights, bias, temperature = fit_linear(rows, buckets=args.buckets, epochs=args.epochs)
    args.output.mkdir(parents=True, exist_ok=True)
    weights_path = args.output / "weights.npz"
    np.savez_compressed(weights_path, weights=weights, bias=bias)
    training_rows = [row for row in rows if row["split"] != "test"]
    config = {
        "version": 1, "labels": list(candidate_names()), "buckets": args.buckets,
        "temperature": temperature, "dataset_version": DATASET_VERSION,
        "calibration_version": "temperature-nll-v1",
        "training_sha256": hashlib.sha256(
            json.dumps(training_rows, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest(),
        "sha256": hashlib.sha256(weights_path.read_bytes()).hexdigest(), "epochs": args.epochs,
    }
    (args.output / "config.json").write_text(
        json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    write_snapshot(Path(__file__).with_name("candidate_snapshot.json"))
    print(json.dumps({"temperature": temperature, "weights_bytes": weights_path.stat().st_size,
                      "rows": manifest["split_counts"], "labels": len(config["labels"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
