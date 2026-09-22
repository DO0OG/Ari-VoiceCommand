from __future__ import annotations

from functools import lru_cache
import re
import unicodedata


def normalize_text(text: object, *, remove_whitespace: bool = False) -> str:
    value = unicodedata.normalize("NFKC", str(text or "")).casefold()
    if remove_whitespace:
        return "".join(value.split())
    return " ".join(value.split())


def normalized_text(text: object) -> str:
    return normalize_text(text)


def whitespace_free_text(text: object) -> str:
    return normalize_text(text, remove_whitespace=True)


def row_template_id(row: dict) -> str:
    return str(row.get("template_id") or row.get("family_id") or "")


def _row_family_ids(row: dict) -> set[str]:
    values = row.get("source_family_ids", ())
    if isinstance(values, str):
        values = (values,)
    return {str(value) for value in values if value}


def _has_gold_metadata(row: dict) -> bool:
    split = str(row.get("split") or "").casefold()
    version = str(row.get("dataset_version") or "").casefold()
    family = str(row.get("family_id") or "").casefold()
    template = row_template_id(row).casefold()
    return bool(
        split in {"gold", "evaluation_only"}
        or row.get("evaluation_only") is True
        or row.get("is_gold") is True
        or row.get("review_status")
        or row.get("gold_source")
        or version.startswith("decision-gold-")
        or str(row.get("id") or "").casefold().startswith(("gold:", "gold-", "gold_", "gold/"))
        or family.startswith("gold.")
        or template.startswith("gold.")
        or any(value.casefold().startswith("gold.") for value in _row_family_ids(row))
    )


def _gold_rows() -> list[dict]:
    try:
        from .gold_data import build_gold_examples
    except ImportError:
        from decision_data.gold_data import build_gold_examples
    return build_gold_examples()


@lru_cache(maxsize=1)
def _slot_values() -> dict[str, tuple[str, ...]]:
    try:
        from . import expanded_data
    except ImportError:
        from decision_data import expanded_data
    slots = {}
    for name in ("SLOT_OPTIONS",):
        for slot, variants in getattr(expanded_data, name, {}).items():
            slots[slot] = tuple(
                normalized
                for triplet in variants
                for normalized in (normalize_text(triplet[index]) for index in range(3))
                if normalized
            )
    return slots


_ENGLISH_NUMBERS = (
    "zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    "thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
    "thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred"
)
_KOREAN_NUMBERS = "영|공|일|이|삼|사|오|육|칠|팔|구|십|백|천|하나|둘|셋|넷|한|두|세|네|다섯|여섯|일곱|여덟|아홉|열|스물|서른"
_JAPANESE_NUMBERS = "零|〇|一|二|三|四|五|六|七|八|九|十|百|千|二十|三十"


def template_signature(text: object, language: str = "") -> str:
    """Return a language-local template fingerprint with entity slots normalized."""
    value = re.sub(r"[-‐‑–—]", " ", normalized_text(text))
    value = re.sub(r"\d+(?:[.,]\d+)?", "<number>", value)
    value = re.sub(
        rf"\b(?:{_ENGLISH_NUMBERS})(?:[- ](?:{_ENGLISH_NUMBERS}))*\b(?=\s*(?:minutes?|seconds?|hours?|days?|weeks?|months?))",
        "<number>",
        value,
    )
    value = re.sub(rf"(?:{_KOREAN_NUMBERS})+(?=\s*(?:분|초|시간|일|주|개월))", "<number>", value)
    value = re.sub(rf"(?:{_JAPANESE_NUMBERS})+(?=\s*(?:分|秒|時間|日|週|か月))", "<number>", value)
    value = re.sub(r"<number>\s+(分|秒|時間|日|週|か月)", r"<number>\1", value)
    for slot, variants in _slot_values().items():
        for variant in sorted(set(variants), key=len, reverse=True):
            if variant:
                value = value.replace(variant, f"<{slot}>")
    return " ".join(value.split())


def _gold_indexes(gold_rows: list[dict]) -> dict[str, set]:
    indexes = {
        "text": set(),
        "compact_text": set(),
        "families": set(),
        "templates": set(),
        "source_families": set(),
        "signatures": set(),
    }
    for row in gold_rows:
        text = normalized_text(row.get("text", ""))
        compact = whitespace_free_text(row.get("text", ""))
        family = str(row.get("family_id") or "")
        template = row_template_id(row)
        language = str(row.get("language") or "")
        if text:
            indexes["text"].add(text)
        if compact:
            indexes["compact_text"].add(compact)
        if family:
            indexes["families"].add(family)
        if template:
            indexes["templates"].add(template)
        indexes["source_families"].update(_row_family_ids(row))
        signature = template_signature(row.get("text", ""), language)
        if signature:
            indexes["signatures"].add((language, signature))
    return indexes


def row_overlaps_gold(row: dict, indexes: dict[str, set]) -> bool:
    text = normalized_text(row.get("text", ""))
    compact = whitespace_free_text(row.get("text", ""))
    family = str(row.get("family_id") or "")
    template = row_template_id(row)
    language = str(row.get("language") or "")
    source_families = _row_family_ids(row)
    signature = template_signature(row.get("text", ""), language)
    return bool(
        _has_gold_metadata(row)
        or text and text in indexes["text"]
        or compact and compact in indexes["compact_text"]
        or family and family in indexes["families"]
        or template and template in indexes["templates"]
        or source_families & (indexes["families"] | indexes["source_families"])
        or signature and (language, signature) in indexes["signatures"]
    )


def families_overlapping_gold(rows: list[dict], gold_rows: list[dict]) -> set[str]:
    indexes = _gold_indexes(gold_rows)
    return {
        str(row.get("family_id") or "")
        for row in rows
        if row_overlaps_gold(row, indexes)
    } - {""}


def validate_no_gold_rows(rows: list[dict], gold_rows: list[dict] | None = None) -> None:
    indexes = _gold_indexes(gold_rows if gold_rows is not None else _gold_rows())
    invalid = [
        str(row.get("id") or index)
        for index, row in enumerate(rows)
        if row_overlaps_gold(row, indexes)
    ]
    if invalid:
        raise ValueError(f"gold rows or reserved families are not allowed in training input: {invalid[:3]}")


def validate_gold_isolation(rows: list[dict], gold_rows: list[dict]) -> None:
    validate_no_gold_rows(rows, gold_rows)
