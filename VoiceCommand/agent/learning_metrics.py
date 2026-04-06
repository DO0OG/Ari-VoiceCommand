"""학습 컴포넌트 기여도 계측."""
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass


def _get_metrics_file() -> str:
    try:
        from core.resource_manager import ResourceManager
        return ResourceManager.get_writable_path("learning_metrics.json")
    except Exception:
        return os.path.join(os.path.dirname(__file__), "learning_metrics.json")


@dataclass
class ComponentMetrics:
    name: str
    activated_count: int = 0
    success_with: int = 0
    success_without: int = 0
    total_with: int = 0
    total_without: int = 0

    @property
    def success_rate_with(self) -> float:
        return self.success_with / max(self.total_with, 1)

    @property
    def success_rate_without(self) -> float:
        return self.success_without / max(self.total_without, 1)

    @property
    def lift(self) -> float:
        return self.success_rate_with - self.success_rate_without


class LearningMetrics:
    _DEFAULT_COMPONENTS = (
        "GoalPredictor",
        "StrategyMemory",
        "EpisodeMemory",
        "FewShot",
        "PlannerFeedback",
        "SkillLibrary",
        "ReflectionEngine",
    )

    def __init__(self, filepath: str | None = None):
        self.filepath = filepath or _get_metrics_file()
        self._lock = threading.RLock()
        self._metrics: dict[str, ComponentMetrics] = {}
        self._load()

    def record(self, name: str, activated: bool, success: bool) -> None:
        key = str(name or "").strip()
        if not key:
            return
        with self._lock:
            metrics = self._metrics.setdefault(key, ComponentMetrics(name=key))
            if activated:
                metrics.activated_count += 1
                metrics.total_with += 1
                if success:
                    metrics.success_with += 1
            else:
                metrics.total_without += 1
                if success:
                    metrics.success_without += 1
            self._save_locked()

    def get_component(self, name: str) -> ComponentMetrics:
        with self._lock:
            metrics = self._metrics.get(name)
            if metrics is None:
                return ComponentMetrics(name=name)
            return ComponentMetrics(**asdict(metrics))

    def get_report_lines(self, limit: int = 3) -> list[str]:
        with self._lock:
            ranked = []
            for metrics in self._metrics.values():
                total = metrics.total_with + metrics.total_without
                if total <= 0 or metrics.activated_count <= 0:
                    continue
                ranked.append(
                    (
                        abs(metrics.lift),
                        metrics.activated_count,
                        metrics.name,
                        self._format_component_line(metrics),
                    )
                )
            ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
            return [line for _, _, _, line in ranked[:limit]]

    def _format_component_line(self, metrics: ComponentMetrics) -> str:
        with_rate = int(round(metrics.success_rate_with * 100))
        without_rate = int(round(metrics.success_rate_without * 100))
        lift = metrics.lift * 100
        return (
            f"{metrics.name} {metrics.activated_count}회 활성 "
            f"(활성 {with_rate}% / 비활성 {without_rate}% / lift {lift:+.0f}%p)"
        )

    def _load(self) -> None:
        if not os.path.exists(self.filepath):
            for name in self._DEFAULT_COMPONENTS:
                self._metrics.setdefault(name, ComponentMetrics(name=name))
            return
        try:
            with open(self.filepath, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            raw_items = payload.get("components", payload) if isinstance(payload, dict) else {}
            if isinstance(raw_items, list):
                raw_items = {item.get("name", ""): item for item in raw_items if isinstance(item, dict)}
            for name, item in dict(raw_items or {}).items():
                if not isinstance(item, dict):
                    continue
                item.setdefault("name", str(name or item.get("name", "")))
                self._metrics[item["name"]] = ComponentMetrics(**{
                    field: item.get(field, 0 if field != "name" else item["name"])
                    for field in ComponentMetrics.__dataclass_fields__
                })
        except Exception as exc:
            logging.warning("[LearningMetrics] 로드 실패: %s", exc)
        finally:
            for name in self._DEFAULT_COMPONENTS:
                self._metrics.setdefault(name, ComponentMetrics(name=name))

    def _save_locked(self) -> None:
        try:
            parent = os.path.dirname(self.filepath)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(self.filepath, "w", encoding="utf-8") as handle:
                json.dump(
                    {"components": {name: asdict(metrics) for name, metrics in self._metrics.items()}},
                    handle,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception as exc:
            logging.warning("[LearningMetrics] 저장 실패: %s", exc)


_metrics: LearningMetrics | None = None
_metrics_lock = threading.Lock()


def get_learning_metrics() -> LearningMetrics:
    global _metrics
    if _metrics is None:
        with _metrics_lock:
            if _metrics is None:
                _metrics = LearningMetrics()
    return _metrics
