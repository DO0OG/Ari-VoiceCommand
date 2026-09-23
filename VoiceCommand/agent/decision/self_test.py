"""배포 실행 파일에 묶인 판단 모델을 읽고 고정 문장으로 확인한다."""

from __future__ import annotations

import json
from pathlib import Path

_SAMPLES = (
    ("what time is it", "get_current_time"),
    ("take a screenshot", "take_screenshot"),
    ("볼륨 올려줘", "adjust_volume"),
    ("現在時刻を教えて", "get_current_time"),
    ("실행 중인 앱 목록 보여줘", "get_running_apps"),
)


def run_self_test(output_path: str, model_dir: str | Path | None = None) -> int:
    """모델 적재·체크섬·분류·의미 해석이 모두 맞으면 0을 반환하고 결과를 파일로 남긴다."""
    from agent.decision.engine import LinearScorer
    from agent.decision.semantics import parse_candidate

    report: dict[str, object] = {"ok": False, "model_dir": "", "sha256": "", "predictions": [], "error": ""}
    try:
        if model_dir is None:
            from core.resource_manager import ResourceManager

            model_dir = ResourceManager.get_bundle_path("resources/decision")
        report["model_dir"] = str(model_dir)
        scorer = LinearScorer(model_dir)
        report["sha256"] = scorer.sha256
        predictions = []
        for text, expected in _SAMPLES:
            result = scorer.predict(text)
            predictions.append({
                "text": text,
                "expected": expected,
                "choice": result.choice,
                "confidence": round(result.confidence, 4),
                "parsed": parse_candidate(text, expected).parse_success,
            })
        report["predictions"] = predictions
        report["ok"] = all(row["choice"] == row["expected"] and row["parsed"] for row in predictions)
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    Path(output_path).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if report["ok"] else 1


__all__ = ["run_self_test"]
