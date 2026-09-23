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


# .mo 파일은 저장소에 없고 빌드 때 만들어지므로, 번역이 빠진 채 묶였는지도 확인한다.
_TRANSLATION_PROBE = "볼륨을 조절했습니다."
_TRANSLATED_LANGUAGES = ("en", "ja")


def _check_translations(locale_dir: str | Path | None) -> dict[str, bool]:
    import gettext

    if locale_dir is None:
        from i18n.translator import _LOCALE_DIR as locale_dir
    result = {}
    for language in _TRANSLATED_LANGUAGES:
        try:
            translation = gettext.translation("ari", localedir=str(locale_dir), languages=[language])
        except OSError:
            result[language] = False
            continue
        result[language] = translation.gettext(_TRANSLATION_PROBE) != _TRANSLATION_PROBE
    return result


def run_self_test(output_path: str, model_dir: str | Path | None = None,
                  locale_dir: str | Path | None = None) -> int:
    """모델 적재·체크섬·분류·의미 해석·번역이 모두 맞으면 0을 반환하고 결과를 파일로 남긴다."""
    from agent.decision.engine import LinearScorer
    from agent.decision.semantics import parse_candidate

    report: dict[str, object] = {"ok": False, "model_dir": "", "sha256": "", "predictions": [],
                                 "translations": {}, "error": ""}
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
        translations = _check_translations(locale_dir)
        report["translations"] = translations
        report["ok"] = (
            all(row["choice"] == row["expected"] and row["parsed"] for row in predictions)
            and all(translations.values())
        )
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    Path(output_path).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if report["ok"] else 1


__all__ = ["run_self_test"]
