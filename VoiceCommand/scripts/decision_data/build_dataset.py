"""Build the deterministic multilingual Phase 0 seed dataset."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import argparse
import json
import re
import sys

try:
    from .generate_candidates import build_snapshot
    from .seed_data import seed_families
    from .split_dataset import apply_family_splits, validate_family_splits
except ImportError:  # Direct ``python build_dataset.py`` invocation.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from decision_data.generate_candidates import build_snapshot
    from decision_data.seed_data import seed_families
    from decision_data.split_dataset import apply_family_splits, validate_family_splits


DATASET_VERSION = "decision-seed-v2"
LANGUAGES = ("ko", "en", "ja")


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
    families = seed_families()
    ignored_labels = sorted({f["label"] for f in families} - candidates)
    families = [family for family in families if family["label"] in candidates]

    base_rows: list[dict] = []
    for family in families:
        for language in LANGUAGES:
            text = family["texts"][language]
            base_rows.append({
                "text": text,
                "label": family["label"],
                "language": language,
                "bucket": family["bucket"],
                "family_id": family["family_id"],
                "is_noise": False,
                "noise_type": None,
            })
            if include_noise:
                for noisy, noise_type in _noise_variants(text, language, len(base_rows)):
                    if noisy == text:
                        continue
                    base_rows.append({
                        "text": noisy,
                        "label": family["label"],
                        "language": language,
                        "bucket": family["bucket"],
                        "family_id": family["family_id"],
                        "is_noise": True,
                        "noise_type": noise_type,
                    })

    rows = apply_family_splits(base_rows)
    for index, row in enumerate(rows):
        row["id"] = f"{row['family_id']}:{row['language']}:{'noise' if row['is_noise'] else 'clean'}:{index:05d}"
        row["dataset_version"] = DATASET_VERSION
    validate_family_splits(rows)

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
        "bucket_counts": dict(sorted(Counter(row["bucket"] for row in rows).items())),
        "noise_enabled": include_noise,
        "ignored_seed_labels": ignored_labels,
        "split_unit": "family_id (translations, paraphrases, and noise stay together)",
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
