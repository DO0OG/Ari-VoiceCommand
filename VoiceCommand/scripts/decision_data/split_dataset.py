"""Assign dataset rows to disjoint template-family splits."""

from __future__ import annotations

from collections import defaultdict
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


def assign_family_splits(rows: Iterable[dict]) -> dict[str, str]:
    """Return ``family_id -> split`` with every label in every split.

    Families are ordered deterministically within each label.  Translations,
    paraphrases, and noise variants sharing a family therefore always stay in
    one split.  The seed supplies at least three families per label, and the
    fallback branch keeps the invariant useful for small custom datasets.
    """

    by_label: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        label = str(row["label"])
        family = str(row["family_id"])
        by_label[label].add(family)

    assignment: dict[str, str] = {}
    for label in sorted(by_label):
        families = sorted(by_label[label])
        count = len(families)
        if count == 1:
            pattern = ["train"]
        elif count == 2:
            pattern = ["train", "test"]
        elif count == 3:
            pattern = list(SPLITS)
        else:
            # Two train families provide a less fragile training baseline while
            # calibration and test each retain independent templates.
            pattern = ["train", "train", "calibration", "test"]
        for index, family in enumerate(families):
            assignment[family] = pattern[index % len(pattern)]
    return assignment


def apply_family_splits(rows: Iterable[dict]) -> list[dict]:
    rows = [dict(row) for row in rows]
    validate_no_gold_rows(rows)
    assignment = assign_family_splits(rows)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    rows = apply_family_splits(_read_jsonl(args.input))
    validate_family_splits(rows)
    _write_jsonl(args.output, rows)
    print(json.dumps({"rows": len(rows), "families": len({r['family_id'] for r in rows})}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
