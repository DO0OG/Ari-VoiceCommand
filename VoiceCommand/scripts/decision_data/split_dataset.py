"""Assign dataset rows to disjoint template-family splits."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import argparse
import json
import sys
from typing import Iterable

try:
    from .dataset_guards import normalized_text, whitespace_free_text, validate_no_gold_rows
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from decision_data.dataset_guards import normalized_text, whitespace_free_text, validate_no_gold_rows


SPLITS = ("train", "calibration", "test")

# 학습 쪽이 두 배로 넓어야 보정과 시험이 각각 독립 계열을 유지할 수 있다.
SPLIT_SHARES = {"train": 2, "calibration": 1, "test": 1}

MANIFEST_PATH = Path(__file__).with_name("split_manifest.json")


def load_manifest(path: Path | None = None) -> dict[str, str]:
    """Return the recorded ``family_id -> split`` map, or an empty map."""

    location = Path(path) if path is not None else MANIFEST_PATH
    if not location.is_file():
        return {}
    payload = json.loads(location.read_text(encoding="utf-8"))
    families = payload.get("families", payload)
    if not isinstance(families, dict):
        raise ValueError("split manifest must hold a family mapping")
    recorded = {}
    for family, split in families.items():
        if not isinstance(family, str) or split not in SPLITS:
            raise ValueError(f"invalid split manifest entry: {family!r} -> {split!r}")
        recorded[family] = split
    return recorded


def dump_manifest(assignment: dict[str, str], path: Path | None = None) -> Path:
    """Write the assignment so later runs keep the same placement."""

    location = Path(path) if path is not None else MANIFEST_PATH
    payload = {
        "version": 1,
        "note": "기존 계열의 분할은 자동으로 바뀌지 않는다. 새 계열만 새로 배정한다.",
        "families": {family: assignment[family] for family in sorted(assignment)},
    }
    location.parent.mkdir(parents=True, exist_ok=True)
    location.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return location


def _least_filled(counts: Counter) -> str:
    """Pick the split that is furthest below its intended share."""

    return min(
        SPLITS,
        key=lambda split: ((counts[split] + 1) / SPLIT_SHARES[split], SPLITS.index(split)),
    )


def merge_overlapping_families(rows: list[dict]) -> list[dict]:
    parents = {row["family_id"]: row["family_id"] for row in rows}

    def root(family):
        while parents[family] != family:
            parents[family] = parents[parents[family]]
            family = parents[family]
        return family

    owners = {}
    for row in rows:
        family = row["family_id"]
        keys = (("template", row.get("template_id", family)),
                ("text", whitespace_free_text(row["text"])))
        for key in keys:
            if key in owners:
                left, right = root(family), root(owners[key])
                if left != right:
                    parents[max(left, right)] = min(left, right)
            owners[key] = family
    return [dict(row, family_id=root(row["family_id"])) for row in rows]


def families_by_label(rows: Iterable[dict]) -> dict[str, list[str]]:
    """Return the deterministically ordered family list of every label."""

    grouped: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        grouped[str(row["label"])].add(str(row["family_id"]))
    return {label: sorted(grouped[label]) for label in sorted(grouped)}


def assign_family_splits(
    rows: Iterable[dict], *, manifest: dict[str, str] | None = None
) -> dict[str, str]:
    """Return ``family_id -> split``, keeping recorded placements untouched.

    Translations, paraphrases, and noise variants sharing a family always stay
    in one split.  A family the manifest already records keeps that split even
    when its texts change, so editing existing data cannot reshuffle the
    partitions.  Only families the manifest has never seen are placed, and each
    one goes to whichever split of its label sits furthest below its share.  An
    empty manifest reproduces the earlier two-train rotation exactly.
    """

    recorded = load_manifest() if manifest is None else dict(manifest)
    assignment: dict[str, str] = {}
    for families in families_by_label(rows).values():
        counts: Counter = Counter()
        pending: list[str] = []
        for family in families:
            split = recorded.get(family)
            if split is None:
                pending.append(family)
            else:
                assignment[family] = split
                counts[split] += 1
        for family in pending:
            split = _least_filled(counts)
            assignment[family] = split
            counts[split] += 1
    return assignment


def manifest_drift(
    rows: Iterable[dict], manifest: dict[str, str] | None = None
) -> dict[str, list[str]]:
    """Report unrecorded families, unused entries, and recorded families that moved."""

    rows = [dict(row) for row in rows]
    recorded = load_manifest() if manifest is None else dict(manifest)
    placement: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        split = str(row.get("split") or "")
        if split:
            placement[str(row["family_id"])].add(split)
    families = {str(row["family_id"]) for row in rows}
    return {
        "unrecorded": sorted(families - set(recorded)),
        "stale": sorted(set(recorded) - families),
        "moved": sorted(
            family
            for family, splits in placement.items()
            if family in recorded and splits != {recorded[family]}
        ),
    }


def baseline_manifest_drift(
    current: dict[str, str] | None = None,
    baseline: dict[str, str] | None = None,
) -> dict[str, list[str]]:
    """Compare current placements with the pinned historical family mapping."""

    current = load_manifest() if current is None else dict(current)
    baseline = (
        load_manifest(Path(__file__).with_name("split_manifest_baseline.json"))
        if baseline is None else dict(baseline)
    )
    return {
        "moved": sorted(
            family for family in baseline.keys() & current.keys()
            if baseline[family] != current[family]
        ),
        "removed": sorted(baseline.keys() - current.keys()),
        "added": sorted(current.keys() - baseline.keys()),
    }


def validate_manifest(
    rows: Iterable[dict], manifest: dict[str, str] | None = None
) -> None:
    """Raise if a recorded family moved or a new family was never recorded."""

    drift = manifest_drift(rows, manifest)
    if drift["moved"]:
        raise ValueError(f"recorded family split changed: {drift['moved'][:3]}")
    if drift["unrecorded"]:
        raise ValueError(f"family missing from the split manifest: {drift['unrecorded'][:3]}")


def apply_family_splits(
    rows: Iterable[dict], *, manifest: dict[str, str] | None = None
) -> list[dict]:
    rows = [dict(row) for row in rows]
    validate_no_gold_rows(rows)
    assignment = assign_family_splits(rows, manifest=manifest)
    for row in rows:
        row["split"] = assignment[row["family_id"]]
    return rows


def validate_family_splits(rows: Iterable[dict]) -> None:
    """Raise ``ValueError`` if a family leaks or a label lacks a split."""

    rows = [dict(row) for row in rows]
    validate_no_gold_rows(rows)
    family_splits: dict[str, set[str]] = defaultdict(set)
    family_labels: dict[str, set[str]] = defaultdict(set)
    family_languages: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    labels_by_split: dict[str, set[str]] = defaultdict(set)
    normalized_text_splits: dict[str, set[str]] = defaultdict(set)
    template_splits: dict[str, set[str]] = defaultdict(set)
    compact_text_splits: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        split = str(row.get("split", ""))
        if split not in SPLITS:
            raise ValueError(f"unknown or missing split: {split!r}")
        family = str(row["family_id"])
        label = str(row["label"])
        language = str(row.get("language", ""))
        family_splits[family].add(split)
        family_labels[family].add(label)
        family_languages[family][language].add(split)
        labels_by_split[split].add(label)
        normalized = normalized_text(row["text"])
        normalized_text_splits[normalized].add(split)
        compact_text_splits[whitespace_free_text(row["text"])].add(split)
        template_splits[str(row.get("template_id") or family)].add(split)
    for kind, groups in (("template", template_splits), ("compact text", compact_text_splits)):
        if any(len(splits) != 1 for splits in groups.values()):
            raise ValueError(f"{kind} appears in multiple splits")
    leaking = sorted(family for family, splits in family_splits.items() if len(splits) != 1)
    if leaking:
        raise ValueError(f"family appears in multiple splits: {leaking[:3]}")
    mixed_labels = sorted(family for family, labels in family_labels.items() if len(labels) != 1)
    if mixed_labels:
        raise ValueError(f"family contains multiple labels: {mixed_labels[:3]}")
    mixed_languages = sorted(
        f"{family}:{language}"
        for family, languages in family_languages.items()
        for language, splits in languages.items()
        if len(splits) != 1
    )
    if mixed_languages:
        raise ValueError(f"family language appears in multiple splits: {mixed_languages[:3]}")
    duplicate_leaks = sorted(text for text, splits in normalized_text_splits.items() if len(splits) != 1)
    if duplicate_leaks:
        raise ValueError(f"normalized text appears in multiple splits: {duplicate_leaks[:3]}")
    missing = {
        label: [split for split in SPLITS if label not in labels_by_split[split]]
        for label in sorted(set().union(*labels_by_split.values()))
    }
    missing = {label: splits for label, splits in missing.items() if splits}
    if missing:
        raise ValueError(f"labels missing split coverage: {missing}")


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )


def _manifest_action(write: bool) -> int:
    try:
        from .build_dataset import build_examples
    except ImportError:
        from decision_data.build_dataset import build_examples
    rows, _ = build_examples()
    drift = manifest_drift(rows)
    if not write:
        validate_manifest(rows)
        print(json.dumps({"recorded": len(load_manifest()), "stale": drift["stale"]}))
        return 0
    dump_manifest({str(row["family_id"]): str(row["split"]) for row in rows})
    print(json.dumps({
        "recorded": len({str(row["family_id"]) for row in rows}),
        "added": len(drift["unrecorded"]),
        "removed": len(drift["stale"]),
    }))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, nargs="?")
    parser.add_argument("output", type=Path, nargs="?")
    parser.add_argument("--write-manifest", action="store_true",
                        help="record the placement of families the manifest has not seen")
    parser.add_argument("--check-manifest", action="store_true",
                        help="fail when a recorded family moved or a new family is unrecorded")
    args = parser.parse_args(argv)

    if args.write_manifest or args.check_manifest:
        return _manifest_action(args.write_manifest)

    if args.input is None or args.output is None:
        parser.error("input and output are required unless a manifest action is given")
    rows = apply_family_splits(_read_jsonl(args.input))
    validate_family_splits(rows)
    _write_jsonl(args.output, rows)
    print(json.dumps({"rows": len(rows), "families": len({r['family_id'] for r in rows})}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
