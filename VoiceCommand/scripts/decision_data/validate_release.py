"""커밋된 로컬 판단 모델의 배포 검사.

``resources/decision``에 포함되어 배포되는 파일만 평가하며 여기서는 학습하지
않는다. 모든 검사는 이유를 보고하고 하나라도 실패하면 0이 아닌 코드로 끝나므로,
자료·후보 등록부·기록된 측정값과 어긋난 배포는 CI에서 막힌다.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from agent.decision.candidates import DIRECT_ALLOWLIST, UNKNOWN, candidate_names
from .build_dataset import build_examples
from .dataset_guards import validate_gold_isolation
from .evaluate import (
    MIN_DEV_LANGUAGE_DIRECT_SELECTIONS,
    MIN_DEV_OVERALL_DIRECT_SELECTIONS,
    MIN_LANGUAGE_DIRECT_PRECISION,
    MIN_OVERALL_DIRECT_PRECISION,
    MIN_STRICT_RELEASE_LANGUAGE_DIRECT_SELECTIONS,
    MIN_STRICT_RELEASE_OVERALL_DIRECT_SELECTIONS,
    build_model_card,
    confusion_comparison,
    evaluate,
)
from .gold_data import build_gold_examples
from .review_corpus import LANGUAGES as REVIEW_LANGUAGES, load_review_corpora
from .provenance import (
    BASELINE_MANIFEST_SHA256,
    BASELINE_MANIFEST_PATH,
    sha256_file,
)
from .split_dataset import baseline_manifest_drift, load_manifest, manifest_drift
from .train import training_sha256


DATA_DIR = Path(__file__).resolve().parent
MODEL_DIR = DATA_DIR.parents[1] / "resources" / "decision"
# 이 이름을 가져다 쓰는 호출자를 위해 예전 전체 기준값 이름을 남긴다.
MIN_SELECTIVE_ACCURACY = MIN_OVERALL_DIRECT_PRECISION
ARTIFACTS = ("evaluation.json", "benchmark_results.json", "model_card.json")


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def check_model(model_dir: Path, rows: list[dict], snapshot_path: Path) -> list[str]:
    """가중치, 라벨, 학습 해시가 설정에 적힌 값과 일치해야 한다."""
    failures = []
    config = _load_json(model_dir / "config.json")
    weights_sha = hashlib.sha256((model_dir / "weights.npz").read_bytes()).hexdigest()
    if weights_sha != config.get("sha256"):
        failures.append("weights.npz SHA-256 differs from config.json")
    registry = list(candidate_names())
    if config.get("labels") != registry or registry[-1] != UNKNOWN:
        failures.append("model labels differ from the candidate registry")
    if _load_json(snapshot_path).get("candidate_labels") != registry:
        failures.append("candidate_snapshot.json differs from the candidate registry")
    augment = bool(config.get("augmentation_enabled"))
    if training_sha256(rows, augment) != config.get("training_sha256"):
        failures.append("training data hash differs from the one the model was trained on")
    return failures


def check_data(rows: list[dict], gold_rows: list[dict]) -> list[str]:
    """기록된 분할이 유지되고 예비 자료가 학습에 섞이지 않아야 한다."""
    failures = []
    drift = manifest_drift(rows)
    for kind in ("moved", "unrecorded", "stale"):
        if drift[kind]:
            failures.append(f"split manifest {kind}: {drift[kind][:3]}")
    if sha256_file(BASELINE_MANIFEST_PATH) != BASELINE_MANIFEST_SHA256:
        failures.append("pinned baseline split manifest SHA-256 differs")
    else:
        baseline_drift = baseline_manifest_drift(
            load_manifest(), load_manifest(BASELINE_MANIFEST_PATH)
        )
        if baseline_drift["moved"]:
            failures.append(f"baseline family split moved: {baseline_drift['moved'][:3]}")
        if baseline_drift["removed"]:
            failures.append(f"baseline families removed without migration: {baseline_drift['removed'][:3]}")
    try:
        validate_gold_isolation(rows, gold_rows)
    except ValueError as exc:
        failures.append(f"gold leakage: {exc}")
    return failures


def check_metrics(
    result: dict,
    minimum: float | None = None,
    *,
    strict_release: bool = False,
) -> list[str]:
    """정밀도 회귀와 의미 해석기가 확인한 최소 표본 수를 검사한다.

    개발 하한은 빈 검사를 막는다. 배포 하한은 배포 준비 검사를 위한 더 강한 표본
    수 기준이지만, 어느 쪽도 실제 정밀도가 99% 이상이라는 근거는 아니다. 그
    불확실성은 Wilson 구간으로 따로 공개한다.
    """
    failures = []
    gated = result["with_direct_policy_gate"]
    minimum_overall_selections = (
        MIN_STRICT_RELEASE_OVERALL_DIRECT_SELECTIONS
        if strict_release else MIN_DEV_OVERALL_DIRECT_SELECTIONS
    )
    minimum_language_selections = (
        MIN_STRICT_RELEASE_LANGUAGE_DIRECT_SELECTIONS
        if strict_release else MIN_DEV_LANGUAGE_DIRECT_SELECTIONS
    )
    minimum_overall_precision = (
        MIN_OVERALL_DIRECT_PRECISION if minimum is None else minimum
    )
    minimum_language_precision = (
        MIN_LANGUAGE_DIRECT_PRECISION if minimum is None else minimum
    )
    if gated["false_direct_count"]:
        failures.append(f"false direct rows: {gated['false_direct_count']}")
    if gated["unknown_false_accept_count"]:
        failures.append(f"unknown accepted rows: {gated['unknown_false_accept_count']}")
    family = result["family_with_direct_policy_gate"]["family_false_direct"]
    if family:
        failures.append(f"false direct families: {family}")
    if int(gated.get("selected_count") or 0) < minimum_overall_selections:
        failures.append(
            "overall direct selection count is below the minimum of "
            f"{minimum_overall_selections}"
        )
    elif gated.get("selective_accuracy") is None:
        failures.append("overall direct precision is unavailable")
    elif gated["selective_accuracy"] < minimum_overall_precision:
        failures.append(
            "overall selective accuracy "
            f"{gated['selective_accuracy']:.4f} below {minimum_overall_precision}"
        )
    languages = result.get("by_language", {})
    for language in ("ko", "en", "ja"):
        values = languages.get(language)
        if not isinstance(values, dict):
            failures.append(f"{language} metrics are missing")
            continue
        language_gate = values.get("with_direct_policy_gate")
        if not isinstance(language_gate, dict):
            failures.append(f"{language} direct metrics are missing")
            continue
        accuracy = language_gate.get("selective_accuracy")
        if int(language_gate.get("selected_count") or 0) < minimum_language_selections:
            failures.append(
                f"{language} direct selection count is below the minimum of "
                f"{minimum_language_selections}"
            )
        elif accuracy is None:
            failures.append(f"{language} direct precision is unavailable")
        elif accuracy < minimum_language_precision:
            failures.append(
                f"{language} selective accuracy {accuracy:.4f} "
                f"below {minimum_language_precision}"
            )
    return failures


def check_artifacts(result: dict, data_dir: Path, model_dir: Path = MODEL_DIR) -> list[str]:
    """커밋된 측정값은 모델, 자료, 정책, 해석기 입력과 일치해야 한다."""
    failures = []
    fingerprints = result["provenance"]
    for name in ARTIFACTS:
        path = data_dir / name
        if not path.is_file():
            failures.append(f"{name} is missing")
            continue
        recorded = _load_json(path)
        if recorded.get("model_sha256") != result["model_sha256"]:
            failures.append(f"{name} was not produced by the shipped model")
        if recorded.get("provenance") != fingerprints:
            failures.append(f"{name} provenance differs from the current inputs")
        if name == "evaluation.json":
            expected = dict(result)
            recorded_metrics = {key: value for key, value in recorded.items()
                                if key != "confusion_comparison"}
            if recorded_metrics != expected:
                failures.append("evaluation.json metrics differ from the current evaluation")
            comparison = recorded.get("confusion_comparison")
            previous_sha = comparison.get("previous_artifact_sha256") if isinstance(comparison, dict) else None
            if (not isinstance(previous_sha, str) or len(previous_sha) != 64
                    or any(
                        character not in "0123456789abcdef"
                        for character in previous_sha.lower()
                    )):
                failures.append("evaluation.json has no valid previous-artifact confusion comparison")
            else:
                expected_major = confusion_comparison(
                    result["overall"]["confusion_matrix"], None, previous_sha
                )["major_pairs"]
                if (
                    comparison.get("scope") != "classifier_top1"
                    or comparison.get("major_pairs") != expected_major
                ):
                    failures.append("evaluation.json major confusion pairs differ from current metrics")
                worsened = comparison.get("top_10_worsened_pairs")
                if not isinstance(worsened, list) or len(worsened) > 10:
                    failures.append("evaluation.json top 10 worsened confusion pairs are missing or invalid")
                elif any(
                    not isinstance(pair, dict)
                    or pair.get("actual") == pair.get("predicted")
                    or not all(isinstance(pair.get(key), int) for key in (
                        "current_count", "previous_count", "increase"
                    ))
                    or pair["current_count"] <= 0
                    or pair["previous_count"] < 0
                    or pair["increase"] <= 0
                    or pair["current_count"] != pair["previous_count"] + pair["increase"]
                    for pair in worsened
                ):
                    failures.append("evaluation.json has invalid worsened confusion pair counts")
        if name == "model_card.json":
            expected = build_model_card(result, model_dir, data_dir)
            if recorded != expected:
                failures.append("model_card.json differs from the current evaluation")
    return failures


# 승인 하한은 몇 행만 승인하고 나머지를 거절한 상태로 배포 검사를 통과하지 못하게
# 한다. 각 하한은 코퍼스를 만들 때의 행 수의 약 80%다.
MIN_APPROVED_PER_LANGUAGE = {"release_gold": 220, "safety_gold": 80}
MIN_DIRECT_APPROVED_PER_TOOL_LANGUAGE = 45


def check_review_corpora(strict_release: bool = False, loader=load_review_corpora) -> list[str]:
    """사람 검수 코퍼스를 검증한다. 배포 빌드는 대부분의 행이 검수됐는지도 확인한다."""
    try:
        release_rows, safety_rows = loader()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return [f"review corpora are invalid: {exc}"]
    if not strict_release:
        return []
    failures = []
    for name, rows in (("release_gold", release_rows), ("safety_gold", safety_rows)):
        pending = sum(row["review_status"] == "pending_human_review" for row in rows)
        if pending:
            failures.append(f"{name}: {pending} rows are pending human review")
        approved = [row for row in rows if row["review_status"] == "human_approved"]
        for language in sorted(REVIEW_LANGUAGES):
            count = sum(row["language"] == language for row in approved)
            if count < MIN_APPROVED_PER_LANGUAGE[name]:
                failures.append(
                    f"{name}: {language} has {count} approved rows, "
                    f"below the minimum of {MIN_APPROVED_PER_LANGUAGE[name]}"
                )
    # 검수된 라벨 기준으로 세므로, 행을 다른 도구로 옮기거나 대화 경로 전용으로
    # 표시한 수정은 원래 도구의 수에 들어가지 않는다.
    direct = [
        row for row in release_rows
        if row["review_status"] == "human_approved" and row["label"] in DIRECT_ALLOWLIST
        and row["expected_outcome"] != "fallback_required"
    ]
    for tool in sorted(DIRECT_ALLOWLIST):
        for language in sorted(REVIEW_LANGUAGES):
            count = sum(row["label"] == tool and row["language"] == language for row in direct)
            if count < MIN_DIRECT_APPROVED_PER_TOOL_LANGUAGE:
                failures.append(
                    f"release_gold: {tool}/{language} has {count} approved direct rows, "
                    f"below the minimum of {MIN_DIRECT_APPROVED_PER_TOOL_LANGUAGE}"
                )
    return failures


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=MODEL_DIR)
    parser.add_argument("--strict-release", action="store_true",
                        help="require the release sample floors instead of the development ones")
    args = parser.parse_args(argv)

    rows, _manifest = build_examples()
    gold_rows = build_gold_examples()
    result = evaluate(args.model)
    checks = {
        "model": check_model(args.model, rows, DATA_DIR / "candidate_snapshot.json"),
        "data": check_data(rows, gold_rows),
        "metrics": check_metrics(result, strict_release=args.strict_release),
        "artifacts": check_artifacts(result, DATA_DIR, args.model),
        "review": check_review_corpora(args.strict_release),
    }
    for name, failures in checks.items():
        print(json.dumps({"check": name, "ok": not failures, "failures": failures}))
    gated = result["with_direct_policy_gate"]
    print(json.dumps({
        "model_sha256": result["model_sha256"],
        "selected_count": gated["selected_count"],
        "parser_rejected_count": result["parser_rejected_count"],
        "selective_accuracy": gated["selective_accuracy"],
        "selective_accuracy_wilson95_lower": gated[
            "selective_accuracy_wilson95_lower"
        ],
        "coverage": gated["coverage"],
        "by_language": {
            language: {
                "selected_count": values["with_direct_policy_gate"]["selected_count"],
                "selective_accuracy": values["with_direct_policy_gate"]["selective_accuracy"],
                "selective_accuracy_wilson95_lower": values[
                    "with_direct_policy_gate"
                ]["selective_accuracy_wilson95_lower"],
            }
            for language, values in result["by_language"].items()
        },
    }))
    return 1 if any(checks.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
