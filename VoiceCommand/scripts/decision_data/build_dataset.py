"""Build the deterministic multilingual Phase 0 seed dataset."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import argparse
import json
import re
import sys

try:
    from .generate_candidates import build_snapshot
    from . import seed_data
    from .dataset_guards import (
        families_overlapping_gold,
        normalized_text,
        whitespace_free_text,
        validate_gold_isolation,
    )
    from .split_dataset import apply_family_splits, merge_overlapping_families, validate_family_splits
    from .expanded_data import expanded_families
    from .gold_data import build_gold_examples
    from .variants import generate_variants
except ImportError:  # Direct ``python build_dataset.py`` invocation.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from decision_data.generate_candidates import build_snapshot
    from decision_data import seed_data
    from decision_data.dataset_guards import (
        families_overlapping_gold,
        normalized_text,
        whitespace_free_text,
        validate_gold_isolation,
    )
    from decision_data.split_dataset import apply_family_splits, merge_overlapping_families, validate_family_splits
    from decision_data.expanded_data import expanded_families
    from decision_data.gold_data import build_gold_examples
    from decision_data.variants import generate_variants


DATASET_VERSION = "decision-dataset-v2"
GENERATOR_SEED = 131
LANGUAGES = ("ko", "en", "ja")
CATEGORY_NAMES = (
    "normal",
    "conversational",
    "short",
    "polite",
    "alias",
    "slang",
    "spacing_noise",
    "stt_noise",
    "entity_replacement",
    "hard_negative",
    "multi_intent",
    "unknown_complex",
    "conversation",
    "knowledge_question",
)


def _category(bucket: str) -> str:
    if bucket in CATEGORY_NAMES:
        return bucket
    if bucket.startswith("hard_negative"):
        return "hard_negative"
    return {
        "single_action": "normal",
        "compound": "multi_intent",
        "ambiguous": "unknown_complex",
        "knowledge": "knowledge_question",
    }.get(bucket, bucket)


def _variant_category(kind: str) -> str:
    parts = kind.split("+")
    if any("spacing" in part for part in parts):
        return "spacing_noise"
    if any(
        marker in part
        for part in parts
        for marker in ("transcription", "stutter", "numeric", "typo", "punctuation", "phonetic", "case", "pause")
    ):
        return "stt_noise"
    return "conversational"


def _source_family_ids(family: dict) -> list[str]:
    values = family.get("source_family_ids") or (family["family_id"],)
    if isinstance(values, str):
        values = (values,)
    return sorted({str(value) for value in values if value})


def _merge_row_provenance(previous: dict, incoming: dict) -> dict:
    preferred = incoming if (incoming["is_noise"], incoming["augmentation"]) < (
        previous["is_noise"], previous["augmentation"]
    ) else previous
    merged = dict(preferred)
    merged["source_family_ids"] = sorted(
        set(previous.get("source_family_ids", ())) | set(incoming.get("source_family_ids", ()))
    )
    merged["category_tags"] = sorted(
        set(previous.get("category_tags", (previous["bucket"],)))
        | set(incoming.get("category_tags", (incoming["bucket"],)))
    )
    source_texts = set(previous.get("source_texts", ())) | set(incoming.get("source_texts", ()))
    source_texts.update(
        text for text in (previous.get("source_text"), incoming.get("source_text")) if text
    )
    if source_texts:
        merged["source_texts"] = sorted(source_texts)
    return merged


def _noise_variants(text: str, language: str, ordinal: int) -> list[tuple[str, str]]:
    """Create conservative STT-like variants without dropping meaning."""

    variants: list[tuple[str, str]] = []

    if language == "ko":
        # Spacing loss is common in Korean STT and is deliberately kept within
        # the same family as its clean transcription.
        compact = re.sub(r"\s+", "", text)
        if compact != text:
            variants.append((compact, "spacing_loss"))
        # Common Korean app-name transcriptions occur in otherwise English or
        # Korean speech; they remain within the same family as the clean text.
        for source, target in (("크롬", "Chrome"), ("디스코드", "디코"), ("메모장", "메모 장")):
            if source in text:
                variants.append((text.replace(source, target, 1), "app_transcription"))
        if "알려줘" in text:
            variants.append((text.replace("알려줘", "알려 줘", 1), "spacing_pause"))
        return variants
    if language == "en":
        replacements = (
            ("weather", "wether"),
            ("search", "serach"),
            ("open", "opne"),
            ("file", "flie"),
            ("read", "reed"),
            ("calendar", "calender"),
            ("screenshot", "screen shot"),
        )
        for source, target in replacements:
            if source in text.lower():
                variants.append((re.sub(source, target, text, count=1, flags=re.IGNORECASE), "word_substitution"))
                break
        words = text.split()
        if not variants and words:
            # Mutate one character inside a content word.  Never remove a
            # complete trailing word: that changes the command semantics.
            candidate_index = max(range(len(words)), key=lambda index: len(words[index]))
            word = words[candidate_index]
            if len(word) >= 5:
                middle = len(word) // 2
                mutated = word[:middle] + word[middle + 1 :]
                changed = list(words)
                changed[candidate_index] = mutated
                variants.append((" ".join(changed), "phonetic_typo"))
            else:
                variants.append((text.lower(), "case_variation"))
        # Numeric transcription is useful for timer/schedule commands and does
        # not alter the action or the quantity.
        numeric = text
        for source, target in {
            "five": "5",
            "ten": "10",
            "one": "1",
            "twenty": "20",
            "thirty": "30",
            "three": "3",
        }.items():
            numeric = re.sub(rf"\b{source}\b", target, numeric, flags=re.IGNORECASE)
        if numeric != text:
            variants.append((numeric, "numeric_transcription"))
        return variants
    # Japanese STT commonly inserts a pause or drops a polite ending.  Both
    # variants retain enough content to be useful without inventing intent.
    if text.endswith("して"):
        variants.append((text[:-2] + "し て", "pause_insertion"))
        return variants
    if text.endswith("ください"):
        variants.append((text[:-4], "politeness_drop"))
        return variants
    variants.append((text + "ね", "sentence_particle"))
    # Japanese transcription of common English application names.
    for source, target in (("Chrome", "クローム"), ("Discord", "ディスコード")):
        if source in text:
            variants.append((text.replace(source, target, 1), "app_transcription"))
    return variants


def build_examples(include_noise: bool = True) -> tuple[list[dict], dict]:
    """Return examples and a manifest without touching the filesystem."""

    snapshot = build_snapshot()
    candidates = set(snapshot["candidate_labels"])
    families = seed_data.seed_families() + expanded_families()
    ignored_labels = sorted({f["label"] for f in families} - candidates)
    families = [family for family in families if family["label"] in candidates]

    template_labels = defaultdict(set)
    for family in families:
        template_labels[str(family.get("template_id") or family["family_id"])].add(family["label"])
    conflicting_templates = sorted(
        template for template, labels in template_labels.items() if len(labels) > 1
    )
    if conflicting_templates:
        raise ValueError(f"conflicting clean template labels: {conflicting_templates[:3]}")

    base_rows: list[dict] = []
    for family in families:
        source_family_ids = _source_family_ids(family)
        bucket = _category(str(family["bucket"]))
        for language in LANGUAGES:
            text = family["texts"][language]
            row = {
                "text": text,
                "label": family["label"],
                "language": language,
                "bucket": bucket,
                "category_tags": [bucket],
                "family_id": family["family_id"],
                "template_id": family.get("template_id", family["family_id"]),
                "source_family_ids": source_family_ids,
                "is_noise": False,
                "noise_type": None,
                "augmentation": False,
            }
            if "hard_negative_pair" in family:
                row["hard_negative_pair"] = family["hard_negative_pair"]
            base_rows.append(row)
            if include_noise:
                for noisy, noise_type in _noise_variants(text, language, len(base_rows)):
                    if noisy == text:
                        continue
                    category = _variant_category(noise_type)
                    base_rows.append(dict(
                        row,
                        text=noisy,
                        bucket=category,
                        category_tags=[category],
                        is_noise=True,
                        noise_type=noise_type,
                        source_text=text,
                    ))
                for noisy, kind in generate_variants(text, language, seed=GENERATOR_SEED):
                    category = _variant_category(kind)
                    base_rows.append(dict(row, text=noisy, is_noise=True, noise_type=kind,
                                          bucket=category, category_tags=[category],
                                          augmentation=True, source_text=text))

    clean_labels = defaultdict(set)
    for row in base_rows:
        if not row["is_noise"]:
            clean_labels[whitespace_free_text(row["text"])].add(row["label"])
    noisy_labels = defaultdict(set)
    for row in base_rows:
        if row["is_noise"]:
            noisy_labels[whitespace_free_text(row["text"])].add(row["label"])
    safe_rows = []
    discarded_conflicting_variants = 0
    for row in base_rows:
        key = whitespace_free_text(row["text"])
        if len(clean_labels[key]) > 1:
            raise ValueError(f"conflicting source labels: {row['text']!r}")
        if row["is_noise"]:
            conflicts_with_clean = bool(clean_labels[key] - {row["label"]})
            conflicts_with_noise = not clean_labels[key] and len(noisy_labels[key]) > 1
            if conflicts_with_clean or conflicts_with_noise:
                discarded_conflicting_variants += 1
                continue
        safe_rows.append(row)
    base_rows = merge_overlapping_families(safe_rows)
    gold = build_gold_examples()
    excluded = families_overlapping_gold(base_rows, gold)
    base_rows = [row for row in base_rows if row["family_id"] not in excluded]
    unique = {}
    for row in base_rows:
        key = (row["language"], normalized_text(row["text"]))
        previous = unique.get(key)
        if previous is None:
            unique[key] = row
        else:
            unique[key] = _merge_row_provenance(previous, row)

    rows = apply_family_splits(unique.values())
    for index, row in enumerate(rows):
        row["id"] = f"{row['family_id']}:{row['language']}:{'noise' if row['is_noise'] else 'clean'}:{index:05d}"
        row["dataset_version"] = DATASET_VERSION
    validate_family_splits(rows)
    validate_gold_isolation(rows, gold)

    split_counts = Counter(row["split"] for row in rows)
    manifest = {
        "dataset_version": DATASET_VERSION,
        "languages": list(LANGUAGES),
        "candidate_labels": snapshot["candidate_labels"],
        "unsupported_schema_tools": snapshot["unsupported_schema_tools"],
        "stale_mapping_tools": snapshot["stale_mapping_tools"],
        "seed_family_count": len(families),
        "family_count": len({row["family_id"] for row in rows}),
        "row_count": len(rows),
        "split_counts": dict(sorted(split_counts.items())),
        "label_counts": dict(sorted(Counter(row["label"] for row in rows).items())),
        "bucket_counts": dict(sorted(
            Counter(category for row in rows for category in row.get("category_tags", (row["bucket"],))).items()
        )),
        "noise_enabled": include_noise,
        "generator_seed": GENERATOR_SEED,
        "language_counts": dict(sorted(Counter(row["language"] for row in rows).items())),
        "excluded_reserved_families": sorted(excluded),
        "excluded_reserved_family_count": len(excluded),
        "discarded_conflicting_variants": discarded_conflicting_variants,
        "ignored_seed_labels": ignored_labels,
        "split_unit": "family_id (translations, slots, paraphrases, and noise stay together)",
    }
    return rows, manifest


def write_dataset(output: str | Path, include_noise: bool = True) -> dict:
    """Write JSONL examples plus a sibling manifest and return the manifest."""

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows, manifest = build_examples(include_noise=include_noise)
    output_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    manifest_path = output_path.with_suffix(output_path.suffix + ".manifest.json")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("decision_dataset.jsonl"))
    parser.add_argument("--no-noise", action="store_true", help="omit deterministic STT variants")
    args = parser.parse_args(argv)
    manifest = write_dataset(args.output, include_noise=not args.no_noise)
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
