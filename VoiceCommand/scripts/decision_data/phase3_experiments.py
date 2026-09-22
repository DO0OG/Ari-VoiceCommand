"""Offline comparison of low-cost text feature groups."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import unicodedata
import zlib

import numpy as np

from agent.decision.candidates import is_direct_allowed
from agent.decision.engine import LinearScorer, candidate_names, hash_features, softmax
from agent.llm_router import get_llm_router
from .evaluate import metrics
from .train import fit_temperature
from .dataset_guards import validate_gold_isolation
from .gold_data import build_gold_examples
from .split_dataset import validate_family_splits


SEED = 131
EPOCHS = 160
CHAR_BUCKETS = 8192
WORD_BUCKETS = 4096
THRESHOLD = 0.92
MARGIN = 0.30
FEATURE_GROUPS = ("word_unigram_bigram", "numeric_duration", "sentence_command")

_WORDS = re.compile(r"[^\W_]+", re.UNICODE)
_EN_NUMBER = re.compile(
    r"zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
    r"thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred"
)
_EN_NUMBER_WORDS = frozenset(_EN_NUMBER.pattern.split("|"))
_EN_NUMBER_SEQUENCE = rf"(?:{_EN_NUMBER.pattern})(?:[\s-]+(?:{_EN_NUMBER.pattern}))*"
_KO_NUMBER = re.compile(
    r"^(?:영|공|일|이|삼|사|오|육|칠|팔|구|십|백|천|하나|둘|셋|넷|한|두|세|네|"
    r"다섯|여섯|일곱|여덟|아홉|열|스물|서른|마흔|쉰|예순|일흔|여든|아흔)+"
    r"(?:분|초|시간|시|일|주|개월)?$"
)
_JA_NUMBER = re.compile(r"[零〇一二三四五六七八九十百千]+(?:分|秒|時間|日|週|か月)?")
_KO_NUMBER_WORDS = "영공일이삼사오육칠팔구십백천하나둘셋넷한두세네다섯여섯일곱여덟아홉열스물서른마흔쉰예순일흔여든아흔"
_EN_DURATION = re.compile(
    rf"(?<!\w)(?:\d+(?:[.,]\d+)?|{_EN_NUMBER_SEQUENCE})\s*-?\s*"
    r"(?:seconds?|minutes?|hours?|days?|weeks?|months?)\b", re.IGNORECASE,
)
_KO_DURATION = re.compile(rf"(?:\d+(?:[.,]\d+)?|[{_KO_NUMBER_WORDS}]+)\s*(?:분|초|시간)")
_JA_DURATION = re.compile(r"(?:\d+(?:[.,]\d+)?|[零〇一二三四五六七八九十百千]+)\s*(?:分|秒|時間|週間|週|か月)")
_QUESTION_KO = re.compile(r"(?:까|나요|니|어때|뭐야)[?.。？!]*$")
_QUESTION_EN = re.compile(r"^(?:what|when|where|who|why|how|can|could|do|does|is|are|would)\b")
_COMMAND_KO = re.compile(r"(?:해줘|해 주세요|해주세요|해봐|해 봐|줘|주세요|틀어|켜|열어|보여줘|알려줘)[.!?。？]*$")
_COMMAND_EN = re.compile(
    r"^(?:please\s+)?(?:open|launch|set|cancel|close|show|tell|play|focus|read|find|"
    r"search|write|take|capture|save|check|increase|lower|stop|switch|bring)\b"
)
_COMMAND_JA = re.compile(r"(?:して|ください|しろ|くれ|お願い|頼む)[。？!?]*$")


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def _normalized_sparse(counts: Counter[int]) -> tuple[np.ndarray, np.ndarray]:
    indices = np.fromiter(counts, dtype=np.intp)
    values = np.fromiter(counts.values(), dtype=np.float32)
    norm = np.linalg.norm(values)
    if norm:
        values /= norm
    return indices, values


def _word_features(text: str, start: int = CHAR_BUCKETS) -> tuple[np.ndarray, np.ndarray]:
    words = _WORDS.findall(_normalize(text))
    counts: Counter[int] = Counter()
    for token in [*(f"u:{word}" for word in words), *(
        f"b:{left}\x1f{right}" for left, right in zip(words, words[1:])
    )]:
        counts[start + zlib.crc32(token.encode("utf-8")) % WORD_BUCKETS] += 1
    return _normalized_sparse(counts)


def _numeric_features(text: str, start: int) -> tuple[np.ndarray, np.ndarray]:
    normalized = _normalize(text)
    tokens = _WORDS.findall(normalized)
    has_duration = bool(
        _EN_DURATION.search(normalized)
        or _KO_DURATION.search(normalized)
        or _JA_DURATION.search(normalized)
    )
    has_number = bool(re.search(r"\d", normalized)) or has_duration or any(
        token in _EN_NUMBER_WORDS
        or _KO_NUMBER.fullmatch(token)
        or _JA_NUMBER.fullmatch(token)
        for token in tokens
    )
    active = [start + index for index, enabled in enumerate((has_number, has_duration)) if enabled]
    values = np.ones(len(active), dtype=np.float32)
    if len(values):
        values /= np.linalg.norm(values)
    return np.asarray(active, dtype=np.intp), values


def _sentence_command_features(text: str, start: int) -> tuple[np.ndarray, np.ndarray]:
    normalized = _normalize(text)
    words = _WORDS.findall(normalized)
    features: list[int] = [start + (0 if len(words) <= 4 else 1 if len(words) <= 9 else 2)]
    question = (
        "?" in normalized
        or "？" in normalized
        or bool(_QUESTION_KO.search(normalized))
        or bool(_QUESTION_EN.search(normalized))
        or normalized.endswith("か")
    )
    command = bool(
        _COMMAND_KO.search(normalized)
        or _COMMAND_EN.search(normalized)
        or _COMMAND_JA.search(normalized)
    )
    if question:
        features.append(start + 3)
    if command:
        features.append(start + 4)
    values = np.ones(len(features), dtype=np.float32)
    values /= np.linalg.norm(values)
    return np.asarray(features, dtype=np.intp), values


def extract_features(
    text: str, groups: tuple[str, ...] = (), buckets: int = CHAR_BUCKETS
) -> tuple[np.ndarray, np.ndarray]:
    """Use the existing character hash plus selected offline feature blocks."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    unknown = set(groups) - set(FEATURE_GROUPS)
    if unknown:
        raise ValueError(f"unknown feature groups: {sorted(unknown)}")
    indices, values = hash_features(text, buckets)
    all_indices = [indices]
    all_values = [values]
    next_offset = buckets
    for group in FEATURE_GROUPS:
        if group not in groups:
            continue
        if group == "word_unigram_bigram":
            group_indices, group_values = _word_features(text, next_offset)
            next_offset += WORD_BUCKETS
        elif group == "numeric_duration":
            group_indices, group_values = _numeric_features(text, next_offset)
            next_offset += 2
        else:
            group_indices, group_values = _sentence_command_features(text, next_offset)
            next_offset += 5
        all_indices.append(group_indices)
        all_values.append(group_values)
    return np.concatenate(all_indices), np.concatenate(all_values)


def _feature_width(groups: tuple[str, ...], buckets: int) -> int:
    return buckets + sum(
        WORD_BUCKETS if group == "word_unigram_bigram" else 2 if group == "numeric_duration" else 5
        for group in FEATURE_GROUPS if group in groups
    )


def _logits(weights: np.ndarray, bias: np.ndarray, text: str, groups: tuple[str, ...]) -> np.ndarray:
    indices, values = extract_features(text, groups)
    return (weights[:, indices] * values).sum(axis=1) + bias


def _fit(rows: list[dict], groups: tuple[str, ...]) -> tuple[np.ndarray, np.ndarray, float]:
    labels = candidate_names()
    train = [row for row in rows if row["split"] == "train"]
    calibration = [row for row in rows if row["split"] == "calibration" and not row.get("augmentation", False)]
    if not train or not calibration:
        raise ValueError("train and clean calibration partitions must not be empty")
    width = _feature_width(groups, CHAR_BUCKETS)
    train_features = [extract_features(row["text"], groups) for row in train]
    targets = np.asarray([labels.index(row["label"]) for row in train], dtype=np.intp)
    weights = np.zeros((len(labels), width), dtype=np.float32)
    bias = np.zeros(len(labels), dtype=np.float32)
    rng = np.random.default_rng(SEED)
    for epoch in range(EPOCHS):
        rate = 0.3 / (1.0 + epoch / 80.0)
        weights *= 0.999
        for index in rng.permutation(len(train)):
            indices, values = train_features[index]
            logits = (weights[:, indices] * values).sum(axis=1) + bias
            error = softmax(logits).astype(np.float32)
            error[targets[index]] -= 1
            weights[:, indices] -= rate * error[:, None] * values
            bias -= rate * error
    calibration_logits = np.asarray([
        _logits(weights, bias, row["text"], groups) for row in calibration
    ])
    temperature = fit_temperature(
        calibration_logits,
        np.asarray([labels.index(row["label"]) for row in calibration], dtype=np.intp),
    )
    return weights, bias, temperature


def _row_hash(rows: list[dict]) -> str:
    payload = json.dumps(rows, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _read_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _validate_snapshot(rows: list[dict], split_map_path: Path | None) -> dict:
    validate_gold_isolation(rows, build_gold_examples())
    validate_family_splits(rows)
    family_splits: dict[str, str] = {}
    for row in rows:
        family = str(row["family_id"])
        split = str(row["split"])
        if family in family_splits and family_splits[family] != split:
            raise ValueError(f"family has multiple splits: {family}")
        family_splits[family] = split
    if split_map_path:
        supplied = json.loads(split_map_path.read_text(encoding="utf-8"))
        if supplied["family_splits"] != family_splits:
            raise ValueError("split map does not match rows")
        if supplied["row_count"] != len(rows) or supplied["family_count"] != len(family_splits):
            raise ValueError("split map counts do not match rows")
    return {
        "row_count": len(rows),
        "family_count": len(family_splits),
        "rows_sha256": _row_hash(rows),
        "family_splits_sha256": hashlib.sha256(
            json.dumps(family_splits, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }


def _nll(probabilities: np.ndarray, targets: np.ndarray) -> float:
    return float(-np.log(probabilities[np.arange(len(targets)), targets].clip(1e-15)).mean())


def _rule_gate(rows: list[dict]) -> np.ndarray:
    router = get_llm_router()
    return np.asarray([
        router.route(row["text"]).task_type == "simple_chat" for row in rows
    ], dtype=bool)


def _score_subset(rows: list[dict], probabilities: np.ndarray, rule_gate: np.ndarray) -> dict:
    labels = candidate_names()
    targets = np.asarray([labels.index(row["label"]) for row in rows], dtype=np.intp)
    predictions = probabilities.argmax(axis=1)
    eligible_class = np.asarray([
        is_direct_allowed(labels[index], "fast") for index in predictions
    ], dtype=bool)
    confidence_metrics = metrics(probabilities, targets, labels, THRESHOLD)
    rule_metrics = metrics(probabilities, targets, labels, THRESHOLD, rule_gate)
    policy_metrics = metrics(probabilities, targets, labels, THRESHOLD, rule_gate & eligible_class)
    gates = {
        "confidence": confidence_metrics,
        "rule": rule_metrics,
        "policy": policy_metrics,
    }
    return {
        "count": len(rows),
        "accuracy": confidence_metrics.get("accuracy"),
        "ece": confidence_metrics.get("ece"),
        "nll": _nll(probabilities, targets) if len(targets) else None,
        "gates": {
            name: {
                "selected_count": value.get("selected_count", 0),
                "coverage": value.get("coverage", 0.0),
                "selective_accuracy": value.get("selective_accuracy"),
                "false_direct_count": value.get("false_direct_count", 0),
            }
            for name, value in gates.items()
        },
    }


def _score(
    rows: list[dict], logits: np.ndarray, temperature: float, *, rule_gate: np.ndarray
) -> dict:
    probabilities = softmax(logits, temperature)
    result = _score_subset(rows, probabilities, rule_gate)
    result["temperature"] = temperature
    result["by_language"] = {}
    for language in ("ko", "en", "ja"):
        mask = np.asarray([row["language"] == language for row in rows], dtype=bool)
        result["by_language"][language] = _score_subset(
            [row for row, keep in zip(rows, mask) if keep],
            probabilities[mask],
            rule_gate[mask],
        )
    return result


def _calibration_eligible(candidate: dict, baseline: dict) -> bool:
    candidate_all = candidate["calibrated"]
    baseline_all = baseline["calibrated"]
    candidate_policy = candidate_all["gates"]["policy"]
    baseline_policy = baseline_all["gates"]["policy"]
    return (
        candidate_all["accuracy"] >= baseline_all["accuracy"]
        and candidate_all["ece"] <= baseline_all["ece"]
        and candidate_all["nll"] <= baseline_all["nll"]
        and candidate_policy["false_direct_count"] == 0
        and candidate_policy["coverage"] >= baseline_policy["coverage"]
        and (
            candidate_all["accuracy"] > baseline_all["accuracy"]
            or candidate_all["ece"] < baseline_all["ece"]
            or candidate_all["nll"] < baseline_all["nll"]
            or candidate_policy["coverage"] > baseline_policy["coverage"]
        )
    )


def run_experiments(
    rows_path: Path,
    baseline_dir: Path,
    output_path: Path,
    *,
    split_map_path: Path | None = None,
    baseline_evaluation_path: Path | None = None,
) -> dict:
    rows = _read_rows(rows_path)
    if split_map_path:
        supplied_map = json.loads(split_map_path.read_text(encoding="utf-8"))
        actual_file_hash = hashlib.sha256(rows_path.read_bytes()).hexdigest()
        if supplied_map.get("rows_sha256") != actual_file_hash:
            raise ValueError("split map row hash does not match input file")
    snapshot = _validate_snapshot(rows, split_map_path)
    labels = candidate_names()
    train = [row for row in rows if row["split"] == "train"]
    calibration = [row for row in rows if row["split"] == "calibration" and not row.get("augmentation", False)]
    test = [row for row in rows if row["split"] == "test"]
    training_rows = train + calibration
    scorer = LinearScorer(baseline_dir)
    config = json.loads((baseline_dir / "config.json").read_text(encoding="utf-8"))
    if (
        scorer.buckets != CHAR_BUCKETS
        or config.get("epochs") != EPOCHS
        or config.get("augmentation_enabled") is not True
    ):
        raise ValueError("baseline settings do not match the frozen experiment protocol")
    training_hash = _row_hash(training_rows)
    if config.get("training_sha256") != training_hash:
        raise ValueError("baseline training rows do not match the frozen snapshot")
    heldout_hash = _row_hash(test)
    if baseline_evaluation_path:
        baseline_eval = json.loads(baseline_evaluation_path.read_text(encoding="utf-8"))
        if baseline_eval.get("evaluation_rows_sha256") != heldout_hash:
            raise ValueError("baseline held-out rows do not match the frozen snapshot")

    calibration_rule = _rule_gate(calibration)
    test_rule = _rule_gate(test)
    baseline_calibration_logits = np.asarray([
        _logits(scorer.weights, scorer.bias, row["text"], ()) for row in calibration
    ])
    baseline_test_logits = np.asarray([
        _logits(scorer.weights, scorer.bias, row["text"], ()) for row in test
    ])
    baseline_temperature = scorer.temperature
    recalculated_temperature = fit_temperature(
        baseline_calibration_logits,
        np.asarray([labels.index(row["label"]) for row in calibration], dtype=np.intp),
    )
    if not np.isclose(recalculated_temperature, baseline_temperature, rtol=0, atol=1e-12):
        raise ValueError("saved baseline temperature does not match the frozen calibration rows")

    trials: dict[str, dict] = {
        "baseline": {
            "groups": [],
            "calibration": {
                "uncalibrated": _score(calibration, baseline_calibration_logits, 1.0, rule_gate=calibration_rule),
                "calibrated": _score(calibration, baseline_calibration_logits, baseline_temperature, rule_gate=calibration_rule),
            },
        }
    }
    fit_results: dict[str, tuple[np.ndarray, np.ndarray, float]] = {}
    for group in FEATURE_GROUPS:
        fit = _fit(rows, (group,))
        fit_results[group] = fit
        weights, bias, temperature = fit
        calibration_logits = np.asarray([
            _logits(weights, bias, row["text"], (group,)) for row in calibration
        ])
        trials[group] = {
            "groups": [group],
            "calibration": {
                "uncalibrated": _score(calibration, calibration_logits, 1.0, rule_gate=calibration_rule),
                "calibrated": _score(calibration, calibration_logits, temperature, rule_gate=calibration_rule),
            },
        }

    eligible = [name for name in FEATURE_GROUPS if _calibration_eligible(trials[name]["calibration"], trials["baseline"]["calibration"])]
    selected = min(
        eligible,
        key=lambda name: (
            -trials[name]["calibration"]["calibrated"]["gates"]["policy"]["coverage"],
            trials[name]["calibration"]["calibrated"]["ece"],
            trials[name]["calibration"]["calibrated"]["nll"],
            FEATURE_GROUPS.index(name),
        ),
    ) if eligible else None

    final_test: dict[str, dict] = {
        "baseline": {
            "uncalibrated": _score(test, baseline_test_logits, 1.0, rule_gate=test_rule),
            "calibrated": _score(test, baseline_test_logits, baseline_temperature, rule_gate=test_rule),
        }
    }
    if selected:
        weights, bias, temperature = fit_results[selected]
        test_logits = np.asarray([_logits(weights, bias, row["text"], (selected,)) for row in test])
        final_test[selected] = {
            "uncalibrated": _score(test, test_logits, 1.0, rule_gate=test_rule),
            "calibrated": _score(test, test_logits, temperature, rule_gate=test_rule),
        }

    result = {
        "protocol": {
            "rows_path": str(rows_path),
            "baseline_path": str(baseline_dir),
            "baseline_training_sha256": training_hash,
            "heldout_rows_sha256": heldout_hash,
            "seed": SEED,
            "epochs": EPOCHS,
            "char_buckets": CHAR_BUCKETS,
            "word_buckets": WORD_BUCKETS,
            "threshold": THRESHOLD,
            "margin": MARGIN,
            "snapshot": snapshot,
            "split_counts": {
                split: sum(row["split"] == split for row in rows)
                for split in ("train", "calibration", "test")
            },
            "family_counts": {
                split: len({row["family_id"] for row in rows if row["split"] == split})
                for split in ("train", "calibration", "test")
            },
            "selection_rule": (
                "Calibration only: candidate must not regress accuracy, ECE, or NLL; "
                "must have zero policy-gated false directs and no lower policy-gated coverage. "
                "Among eligible candidates, maximize policy-gated coverage, then minimize ECE, NLL, and fixed group order."
            ),
            "heldout_rule": "Evaluate baseline and the calibration-selected candidate once; never use heldout labels for selection.",
            "temperature_rule": "Fit one global temperature by calibration NLL only; threshold and margin stay fixed.",
        },
        "calibration_trials": trials,
        "calibration_eligible_groups": eligible,
        "selected_group": selected,
        "heldout": final_test,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=Path, required=True)
    parser.add_argument("--split-map", type=Path)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--baseline-evaluation", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = run_experiments(
        args.rows,
        args.baseline,
        args.output,
        split_map_path=args.split_map,
        baseline_evaluation_path=args.baseline_evaluation,
    )
    print(json.dumps({
        "selected_group": result["selected_group"],
        "calibration_eligible_groups": result["calibration_eligible_groups"],
        "heldout": {
            key: value["calibrated"]["gates"]["policy"]
            for key, value in result["heldout"].items()
        },
        "output": str(args.output),
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
