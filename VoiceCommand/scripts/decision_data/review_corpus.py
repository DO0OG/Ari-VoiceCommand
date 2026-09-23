"""Pending multilingual release candidates and an auditable human review CLI."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any

from agent.decision.candidates import DIRECT_ALLOWLIST, UNKNOWN, candidate_names

try:
    from . import candidate_families as families
except ImportError:  # Direct ``python review_corpus.py`` invocation.
    import candidate_families as families


DATASET_VERSION = "decision-review-candidate-v2"
DATA_DIR = Path(__file__).resolve().parent
CORPUS_PATHS = {
    "release_gold": DATA_DIR / "release_gold.jsonl",
    "safety_gold": DATA_DIR / "safety_gold.jsonl",
}
LANGUAGES = frozenset(families.LANGUAGES)
REVIEW_STATUSES = frozenset({"pending_human_review", "human_approved", "human_rejected"})
EXPECTED_OUTCOMES = frozenset({"direct_required", "direct_or_fallback", "fallback_required"})
_CORE_FIELDS = (
    "dataset_version", "id", "family_id", "template_id", "corpus", "candidate_tool",
    "label", "expected_outcome", "expected_arguments", "text", "language", "bucket",
    "split", "evaluation_only",
)
_ROW_FIELDS = frozenset((*_CORE_FIELDS, "review_status", "source_revision", "revision_sha256", "review_history"))
_REVIEW_FIELDS = frozenset({
    "action", "reviewer", "reviewed_at_utc", "original_revision_sha256",
    "revision_before_sha256", "revision_after_sha256", "changes", "note",
})
_EDITABLE_FIELDS = frozenset({"label", "expected_outcome", "expected_arguments", "text", "bucket"})


def _canonical_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _revision(row: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes({key: row[key] for key in _CORE_FIELDS})).hexdigest()


def _new_row(*, corpus: str, row_id: str, family_id: str, candidate_tool: str,
             label: str, expected_outcome: str, expected_arguments: dict[str, Any],
             language: str, text: str, bucket: str) -> dict[str, Any]:
    row: dict[str, Any] = {
        "dataset_version": DATASET_VERSION,
        "id": row_id,
        "family_id": family_id,
        "template_id": family_id,
        "corpus": corpus,
        "candidate_tool": candidate_tool,
        "label": label,
        "expected_outcome": expected_outcome,
        "expected_arguments": expected_arguments,
        "text": text,
        "language": language,
        "bucket": bucket,
        "split": "gold",
        "evaluation_only": True,
        "review_status": "pending_human_review",
        "source_revision": {"source_id": f"{corpus}:seed:{row_id}", "sha256": ""},
        "revision_sha256": "",
        "review_history": [],
    }
    digest = _revision(row)
    row["source_revision"]["sha256"] = digest
    row["revision_sha256"] = digest
    return row


def _direct_rows() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for tool in sorted(DIRECT_ALLOWLIST):
        if len(families.DIRECT_FAMILIES[tool]) < 50:
            raise ValueError(f"Tier A tool needs 50 authored utterance families: {tool}")
        for slug, texts, arguments in families.DIRECT_FAMILIES[tool]:
            family_id = f"release.{tool}.{slug}"
            for language in families.LANGUAGES:
                result.append(_new_row(
                    corpus="release_gold", row_id=f"release:{tool}:{slug}:{language}",
                    family_id=family_id, candidate_tool=tool, label=tool,
                    expected_outcome="direct_or_fallback", expected_arguments=dict(arguments),
                    language=language, text=texts[language], bucket="direct_candidate",
                ))
    return result


def _tier_b_rows() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for candidate_tool, slug, texts, arguments in families.TIER_B:
        family_id = f"release.tier_b.{candidate_tool}.{slug}"
        for language in families.LANGUAGES:
            result.append(_new_row(
                corpus="release_gold", row_id=f"release:tier_b:{candidate_tool}:{slug}:{language}",
                family_id=family_id, candidate_tool=candidate_tool, label=candidate_tool,
                expected_outcome="fallback_required", expected_arguments=dict(arguments),
                language=language, text=texts[language], bucket="tier_b_parser_candidate",
            ))
    return result


def _colloquial_rows() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for candidate_tool, slug, texts, arguments, bucket in families.COLLOQUIAL_STT:
        family_id = f"release.{candidate_tool}.colloquial.{slug}"
        for language in families.LANGUAGES:
            result.append(_new_row(
                corpus="release_gold", row_id=f"release:colloquial:{candidate_tool}:{slug}:{language}",
                family_id=family_id, candidate_tool=candidate_tool, label=candidate_tool,
                expected_outcome="direct_or_fallback", expected_arguments=dict(arguments),
                language=language, text=texts[language], bucket=bucket,
            ))
    return result


def _safety_rows() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for slug, nearest_tool, reason, texts in families.HARD_NEGATIVES:
        family_id = f"safety.near_tier_a.{slug}"
        for language in families.LANGUAGES:
            result.append(_new_row(
                corpus="safety_gold", row_id=f"safety:{slug}:{language}",
                family_id=family_id, candidate_tool=nearest_tool, label=UNKNOWN,
                expected_outcome="fallback_required",
                expected_arguments={"nearest_direct_tool": nearest_tool, "reason": reason},
                language=language, text=texts[language], bucket=reason,
            ))
    return result


def build_candidate_corpora() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    release_rows = _direct_rows() + _tier_b_rows() + _colloquial_rows()
    safety_rows = _safety_rows()
    validate_corpora(release_rows, safety_rows)
    return release_rows, safety_rows


def _is_json_value(value: Any) -> bool:
    if value is None or isinstance(value, (str, bool, int)):
        return True
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(_is_json_value(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _is_json_value(item) for key, item in value.items())
    return False


def _validate_utc(value: Any) -> None:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("review time must be recorded in UTC")
    try:
        moment = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError("review time is invalid") from exc
    if moment.utcoffset() != timezone.utc.utcoffset(moment):
        raise ValueError("review time must be UTC")


def _validate_review_provenance(row: dict[str, Any]) -> None:
    source = row.get("source_revision")
    if not isinstance(source, dict) or set(source) != {"source_id", "sha256"}:
        raise ValueError("original source revision provenance is malformed")
    original_digest = source.get("sha256")
    if not isinstance(source.get("source_id"), str) or not source["source_id"]:
        raise ValueError("original source revision identifier is required")
    if (not isinstance(original_digest, str) or len(original_digest) != 64
            or any(character not in "0123456789abcdef" for character in original_digest)):
        raise ValueError("original source revision hash is malformed")
    if row.get("revision_sha256") != _revision(row):
        raise ValueError("current row revision hash does not match its content")
    history = row.get("review_history")
    if not isinstance(history, list):
        raise ValueError("review history must be a list")
    state = {key: row[key] for key in _CORE_FIELDS}
    for event in reversed(history):
        if not isinstance(event, dict) or set(event) != _REVIEW_FIELDS:
            raise ValueError("review audit event fields are malformed")
        if event.get("action") not in {"edit", "accept", "reject"}:
            raise ValueError("review audit action is invalid")
        if not isinstance(event.get("reviewer"), str) or not event["reviewer"].strip():
            raise ValueError("review audit event requires a human reviewer")
        _validate_utc(event.get("reviewed_at_utc"))
        if not isinstance(event.get("note"), str):
            raise ValueError("review note must be text")
        if event.get("original_revision_sha256") != original_digest:
            raise ValueError("review audit event lost original revision provenance")
        if event.get("revision_after_sha256") != _revision(state):
            raise ValueError("review audit after-hash does not match row history")
        changes = event.get("changes")
        if not isinstance(changes, dict) or set(changes) - _EDITABLE_FIELDS:
            raise ValueError("review audit changes are malformed")
        if event["action"] == "edit" and not changes:
            raise ValueError("review edit must record at least one content change")
        if event["action"] != "edit" and changes:
            raise ValueError("accept or reject event cannot change row content")
        for key, change in changes.items():
            if not isinstance(change, dict) or set(change) != {"from", "to"}:
                raise ValueError("review field change must retain before and after values")
            if state[key] != change["to"]:
                raise ValueError("review field after-value does not match the stored row")
            state[key] = change["from"]
        if event.get("revision_before_sha256") != _revision(state):
            raise ValueError("review audit before-hash does not match row history")
    if _revision(state) != original_digest:
        raise ValueError("review history cannot be traced to the original source revision")
    if history:
        last_action = history[-1]["action"]
        expected_status = {
            "edit": "pending_human_review",
            "accept": "human_approved",
            "reject": "human_rejected",
        }[last_action]
        if row.get("review_status") != expected_status:
            raise ValueError("review status does not match its latest audit event")
    elif row.get("review_status") != "pending_human_review":
        raise ValueError("a reviewed status requires a human audit event")


def _has_reviewed_field_edit(row: dict[str, Any], field: str) -> bool:
    return any(event["action"] == "edit" and field in event["changes"]
               for event in row["review_history"])


def validate_corpus(rows: list[dict[str, Any]], corpus: str) -> None:
    if corpus not in CORPUS_PATHS or not rows:
        raise ValueError("unknown or empty review corpus")
    valid_labels = set(candidate_names())
    ids: set[str] = set()
    texts: set[tuple[str, str]] = set()
    families: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != _ROW_FIELDS:
            raise ValueError("review row fields differ from the required schema")
        if row["dataset_version"] != DATASET_VERSION or row["corpus"] != corpus:
            raise ValueError("review row corpus version or source is invalid")
        if row["split"] != "gold" or row["evaluation_only"] is not True:
            raise ValueError("review candidate must stay isolated from training splits")
        if not isinstance(row["review_status"], str) or row["review_status"] not in REVIEW_STATUSES:
            raise ValueError("review status is invalid")
        if (not isinstance(row["candidate_tool"], str) or row["candidate_tool"] not in valid_labels
                or not isinstance(row["label"], str) or row["label"] not in valid_labels):
            raise ValueError("candidate tool or reviewed label is invalid")
        if not isinstance(row["expected_outcome"], str) or row["expected_outcome"] not in EXPECTED_OUTCOMES:
            raise ValueError("expected outcome is invalid")
        arguments = row["expected_arguments"]
        if not isinstance(arguments, dict) or not _is_json_value(arguments):
            raise ValueError("expected arguments must be a JSON object")
        if (not isinstance(row["language"], str) or row["language"] not in LANGUAGES
                or not isinstance(row["text"], str) or not row["text"].strip()):
            raise ValueError("candidate language or text is invalid")
        if not isinstance(row["bucket"], str) or not row["bucket"].strip():
            raise ValueError("candidate bucket is invalid")
        if (not isinstance(row["id"], str) or not row["id"]
                or not isinstance(row["family_id"], str) or not row["family_id"]
                or not isinstance(row["template_id"], str) or row["template_id"] != row["family_id"]):
            raise ValueError("family and template provenance is invalid")
        if row["id"] in ids:
            raise ValueError("review row ids are not unique")
        ids.add(row["id"])
        normalized = " ".join(row["text"].casefold().split())
        text_key = (row["language"], normalized)
        if text_key in texts:
            raise ValueError("review corpus contains duplicate normalized text")
        texts.add(text_key)
        families.setdefault(row["family_id"], []).append(row)
        _validate_review_provenance(row)
    for family_id, members in families.items():
        if len(members) != len(LANGUAGES):
            raise ValueError(f"family must contain one row per language: {family_id}")
        if {row["language"] for row in members} != LANGUAGES:
            raise ValueError(f"family language siblings are incomplete: {family_id}")
        if len({row["candidate_tool"] for row in members}) != 1:
            raise ValueError(f"family candidate intent differs across languages: {family_id}")
        if len({row["corpus"] for row in members}) != 1:
            raise ValueError(f"family is split across corpora: {family_id}")
        for field in ("label", "expected_outcome", "expected_arguments", "bucket"):
            original_values = {
                _canonical_bytes({field: row[field]})
                for row in members if not _has_reviewed_field_edit(row, field)
            }
            if len(original_values) > 1:
                raise ValueError(f"family translations disagree on {field}: {family_id}")
    if corpus == "release_gold":
        family_counts: dict[str, set[str]] = {}
        for row in rows:
            family_counts.setdefault(row["candidate_tool"], set()).add(row["family_id"])
        if any(len(family_counts.get(tool, set())) < 50 for tool in DIRECT_ALLOWLIST):
            raise ValueError("each Tier A candidate needs at least 50 independent families")
        if any(row["candidate_tool"] not in DIRECT_ALLOWLIST and row["expected_outcome"] != "fallback_required"
               for row in rows):
            raise ValueError("Tier B candidates must remain fallback-only")
    elif any(row["expected_outcome"] != "fallback_required"
             or row["candidate_tool"] not in DIRECT_ALLOWLIST
             or row["expected_arguments"].get("nearest_direct_tool") != row["candidate_tool"]
             for row in rows):
        raise ValueError("safety candidates must remain near-Tier-A fallback cases")


def _reference_rows() -> list[dict[str, Any]]:
    try:
        from .build_dataset import build_examples
        from .gold_data import build_gold_examples
    except ImportError:  # Direct ``python review_corpus.py`` invocation.
        from decision_data.build_dataset import build_examples
        from decision_data.gold_data import build_gold_examples
    rows, _manifest = build_examples(include_noise=True)
    return rows + build_gold_examples()


def _candidate_overlaps_reference(row: dict[str, Any], indexes: dict[str, set]) -> bool:
    try:
        from .dataset_guards import normalized_text, template_signature, whitespace_free_text
    except ImportError:
        from decision_data.dataset_guards import normalized_text, template_signature, whitespace_free_text
    text = normalized_text(row["text"])
    compact = whitespace_free_text(row["text"])
    family = str(row.get("family_id") or "")
    template = str(row.get("template_id") or family)
    language = row["language"]
    signature = template_signature(row["text"], language)
    return bool(
        text in indexes["text"]
        or compact in indexes["compact_text"]
        or family in indexes["families"]
        or template in indexes["templates"]
        or signature and (language, signature) in indexes["signatures"]
    )


def validate_historical_isolation(rows: list[dict[str, Any]], references: list[dict[str, Any]] | None = None) -> None:
    historical = references if references is not None else _reference_rows()
    try:
        from .dataset_guards import _gold_indexes
    except ImportError:
        from decision_data.dataset_guards import _gold_indexes
    indexes = _gold_indexes(historical)
    collisions = [row["id"] for row in rows if _candidate_overlaps_reference(row, indexes)]
    if collisions:
        raise ValueError(f"candidate corpus overlaps existing train/cal/test or Gold rows: {collisions[:5]}")


def validate_corpora(release_rows: list[dict[str, Any]], safety_rows: list[dict[str, Any]],
                     *, historical_rows: list[dict[str, Any]] | None = None) -> None:
    validate_corpus(release_rows, "release_gold")
    validate_corpus(safety_rows, "safety_gold")
    release_ids = {row["id"] for row in release_rows}
    safety_ids = {row["id"] for row in safety_rows}
    release_families = {row["family_id"] for row in release_rows}
    safety_families = {row["family_id"] for row in safety_rows}
    release_texts = {(row["language"], " ".join(row["text"].casefold().split())) for row in release_rows}
    safety_texts = {(row["language"], " ".join(row["text"].casefold().split())) for row in safety_rows}
    if release_ids & safety_ids or release_families & safety_families or release_texts & safety_texts:
        raise ValueError("release and safety corpora overlap")
    if len(release_rows) + len(safety_rows) not in range(1000, 2001):
        raise ValueError("candidate corpora must contain 1,000 to 2,000 rows")
    if historical_rows is not None:
        validate_historical_isolation(release_rows + safety_rows, historical_rows)


def _write_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=path.parent,
                                         delete=False) as handle:
            temporary = Path(handle.name)
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _read_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"review corpus is missing: {path}")
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON at {path.name}:{line_number}") from exc
    return rows


def load_review_corpora(*, validate_external: bool = True) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    release_rows = _read_rows(CORPUS_PATHS["release_gold"])
    safety_rows = _read_rows(CORPUS_PATHS["safety_gold"])
    references = _reference_rows() if validate_external else None
    validate_corpora(release_rows, safety_rows, historical_rows=references)
    return release_rows, safety_rows


def review_row(row: dict[str, Any], *, action: str, reviewer: str,
               changes: dict[str, Any] | None = None, note: str = "",
               now: datetime | None = None) -> dict[str, Any]:
    if action not in {"accept", "edit", "reject"}:
        raise ValueError("review action must be accept, edit, or reject")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError("a human reviewer name is required")
    if row.get("review_status") != "pending_human_review":
        raise ValueError("only pending candidates can be reviewed")
    changes = changes or {}
    if set(changes) - _EDITABLE_FIELDS:
        raise ValueError("review edit contains an unsupported field")
    if action == "edit" and not changes:
        raise ValueError("edit review requires at least one change")
    if action != "edit" and changes:
        raise ValueError("accept and reject do not take content edits")
    result = json.loads(json.dumps(row, ensure_ascii=False))
    before = result["revision_sha256"]
    actual_changes = {}
    for key, value in changes.items():
        if result[key] != value:
            actual_changes[key] = {"from": result[key], "to": value}
            result[key] = value
    if action == "edit" and not actual_changes:
        raise ValueError("edit does not change the candidate")
    after = _revision(result)
    result["revision_sha256"] = after
    result["review_status"] = {
        "accept": "human_approved", "edit": "pending_human_review", "reject": "human_rejected",
    }[action]
    timestamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    _validate_utc(timestamp)
    result["review_history"].append({
        "action": action,
        "reviewer": reviewer.strip(),
        "reviewed_at_utc": timestamp,
        "original_revision_sha256": result["source_revision"]["sha256"],
        "revision_before_sha256": before,
        "revision_after_sha256": after,
        "changes": actual_changes,
        "note": note,
    })
    _validate_review_provenance(result)
    return result


def review_corpus_file(corpus: str, row_id: str, *, action: str, reviewer: str,
                       changes: dict[str, Any] | None = None, note: str = "") -> dict[str, Any]:
    if corpus not in CORPUS_PATHS:
        raise ValueError("corpus must be release_gold or safety_gold")
    release_rows, safety_rows = load_review_corpora(validate_external=False)
    rows = release_rows if corpus == "release_gold" else safety_rows
    row = next((item for item in rows if item["id"] == row_id), None)
    if row is None:
        raise ValueError(f"candidate row not found: {row_id}")
    reviewed = review_row(row, action=action, reviewer=reviewer, changes=changes, note=note)
    rows[rows.index(row)] = reviewed
    validate_corpora(release_rows, safety_rows)
    validate_historical_isolation(release_rows + safety_rows)
    _write_rows(CORPUS_PATHS[corpus], rows)
    return reviewed


def _generate(*, replace_unreviewed: bool = False) -> dict[str, int]:
    existing = [path for path in CORPUS_PATHS.values() if path.exists()]
    if existing:
        if not replace_unreviewed:
            raise FileExistsError("candidate corpus files already exist; refusing to overwrite review records")
        for path in existing:
            rows = _read_rows(path)
            if any(row.get("review_status") != "pending_human_review" or row.get("review_history")
                   for row in rows):
                raise FileExistsError(f"refusing to replace reviewed candidate corpus: {path.name}")
    release_rows, safety_rows = build_candidate_corpora()
    references = _reference_rows()
    validate_corpora(release_rows, safety_rows, historical_rows=references)
    _write_rows(CORPUS_PATHS["release_gold"], release_rows)
    _write_rows(CORPUS_PATHS["safety_gold"], safety_rows)
    return {"release_gold": len(release_rows), "safety_gold": len(safety_rows),
            "total": len(release_rows) + len(safety_rows)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    generate = subparsers.add_parser("generate", help="write pending candidate files without overwriting reviewed records")
    generate.add_argument("--replace-unreviewed", action="store_true")
    subparsers.add_parser("validate", help="check candidate schema, audit trail, and corpus isolation")
    listing = subparsers.add_parser("list", help="show a bounded set of review candidates")
    listing.add_argument("--corpus", choices=tuple(CORPUS_PATHS), required=True)
    listing.add_argument("--status", choices=tuple(sorted(REVIEW_STATUSES)), default="pending_human_review")
    listing.add_argument("--limit", type=int, default=25)
    review = subparsers.add_parser("review", help="record one human review decision")
    review.add_argument("--corpus", choices=tuple(CORPUS_PATHS), required=True)
    review.add_argument("--row-id", required=True)
    review.add_argument("--action", choices=("accept", "edit", "reject"), required=True)
    review.add_argument("--reviewer", required=True)
    review.add_argument("--note", default="")
    review.add_argument("--label")
    review.add_argument("--expected-outcome", choices=tuple(sorted(EXPECTED_OUTCOMES)))
    review.add_argument("--expected-arguments", help="JSON object used to correct expected arguments")
    review.add_argument("--text")
    review.add_argument("--bucket")
    args = parser.parse_args(argv)
    if args.command == "generate":
        result = _generate(replace_unreviewed=args.replace_unreviewed)
    elif args.command == "validate":
        release_rows, safety_rows = load_review_corpora(validate_external=True)
        result = {"release_gold": len(release_rows), "safety_gold": len(safety_rows),
                  "total": len(release_rows) + len(safety_rows), "status": "valid"}
    elif args.command == "list":
        if args.limit < 1:
            parser.error("--limit must be at least 1")
        release_rows, safety_rows = load_review_corpora(validate_external=False)
        rows = release_rows if args.corpus == "release_gold" else safety_rows
        selected = [row for row in rows if row["review_status"] == args.status]
        result = {
            "corpus": args.corpus,
            "status": args.status,
            "matching_count": len(selected),
            "rows": [{key: row[key] for key in ("id", "family_id", "language", "candidate_tool",
                                                  "label", "expected_outcome", "bucket", "text")}
                     for row in selected[:args.limit]],
        }
    else:
        changes: dict[str, Any] = {field: getattr(args, field) for field in ("label", "expected_outcome", "text", "bucket")
                                   if getattr(args, field) is not None}
        if args.expected_arguments is not None:
            try:
                parsed_arguments = json.loads(args.expected_arguments)
            except json.JSONDecodeError as exc:
                parser.error(f"--expected-arguments must be valid JSON: {exc}")
            changes["expected_arguments"] = parsed_arguments
        reviewed = review_corpus_file(args.corpus, args.row_id, action=args.action,
                                      reviewer=args.reviewer, changes=changes, note=args.note)
        result = {"id": reviewed["id"], "review_status": reviewed["review_status"],
                  "reviewed_at_utc": reviewed["review_history"][-1]["reviewed_at_utc"]}
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
