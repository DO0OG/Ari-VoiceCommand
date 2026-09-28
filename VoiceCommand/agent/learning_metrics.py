"""학습 컴포넌트 기여도 계측."""
from __future__ import annotations

import json
import logging
import math
import os
import random
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Callable

logger = logging.getLogger(__name__)


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
    holdout: bool = False
    trial_success_with: int = 0
    trial_total_with: int = 0
    trial_success_holdout: int = 0
    trial_total_holdout: int = 0

    @property
    def success_rate_with(self) -> float:
        return self.trial_success_with / max(self.trial_total_with, 1)

    @property
    def success_rate_without(self) -> float:
        return self.trial_success_holdout / max(self.trial_total_holdout, 1)

    @property
    def lift(self) -> float:
        if not self.trial_total_with or not self.trial_total_holdout:
            return 0.0
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

    HOLDOUT_RATE = 0.1
    WINDOW_DAYS = 60

    def __init__(
        self,
        filepath: str | None = None,
        random_func: Callable[[], float] | None = None,
    ):
        self.filepath = filepath or _get_metrics_file()
        self._random = random_func or random.random
        self._lock = threading.RLock()
        self._metrics: dict[str, ComponentMetrics] = {}
        self._daily_components: dict[str, dict[str, dict[str, int | bool]]] = {}
        self._daily_counters: dict[str, dict[str, int]] = {}
        self._load()

    def record(
        self,
        name: str,
        activated: bool,
        success: bool,
        holdout: bool = False,
        eligible: bool | None = None,
    ) -> None:
        key = str(name or "").strip()
        if not key:
            return
        if eligible is None:
            eligible = bool(activated or holdout)
        holdout = bool(holdout and eligible and not activated)
        with self._lock:
            metrics = self._metrics.setdefault(key, ComponentMetrics(name=key))
            metrics.holdout = holdout
            if activated:
                metrics.activated_count += 1
                metrics.total_with += 1
                if success:
                    metrics.success_with += 1
            else:
                metrics.total_without += 1
                if success:
                    metrics.success_without += 1
            daily_metrics = self._get_daily_component_metrics(self._today_key(), key)
            daily_metrics["holdout"] = holdout
            if activated:
                daily_metrics["activated_count"] += 1
                daily_metrics["total_with"] += 1
                if success:
                    daily_metrics["success_with"] += 1
            else:
                daily_metrics["total_without"] += 1
                if success:
                    daily_metrics["success_without"] += 1
            if eligible and holdout:
                metrics.trial_total_holdout += 1
                daily_metrics["trial_total_holdout"] += 1
                if success:
                    metrics.trial_success_holdout += 1
                    daily_metrics["trial_success_holdout"] += 1
            elif eligible:
                metrics.trial_total_with += 1
                daily_metrics["trial_total_with"] += 1
                if success:
                    metrics.trial_success_with += 1
                    daily_metrics["trial_success_with"] += 1
            self._prune_daily_locked()
            self._save_locked()

    def record_llm_call(self, component: str, estimated_tokens: int) -> None:
        key = str(component or "").strip()
        tokens = max(int(estimated_tokens or 0), 0)
        if not key or tokens <= 0:
            return
        with self._lock:
            daily_key = self._today_key()
            counters = self._daily_counters.setdefault(daily_key, {})
            counters["estimated_tokens"] = counters.get("estimated_tokens", 0) + tokens
            token_key = f"estimated_tokens:{key}"
            counters[token_key] = counters.get(token_key, 0) + tokens
            self._prune_daily_locked()
            self._save_locked()

    def record_counter(self, name: str, count: int = 1) -> None:
        key = str(name or "").strip()
        amount = int(count or 0)
        if not key or amount == 0:
            return
        with self._lock:
            counters = self._daily_counters.setdefault(self._today_key(), {})
            counters[key] = counters.get(key, 0) + amount
            self._prune_daily_locked()
            self._save_locked()

    def get_component(self, name: str) -> ComponentMetrics:
        with self._lock:
            metrics = self._metrics.get(name)
            if metrics is None:
                return ComponentMetrics(name=name)
            return ComponentMetrics(**asdict(metrics))

    def should_activate(
        self,
        component_name: str,
        min_samples: int = 10,
        *,
        eligible: bool = True,
        trials: dict[str, dict[str, bool]] | None = None,
    ) -> bool:
        """해당 컴포넌트를 이번 실행에서 활성화할지 여부를 반환한다."""
        key = str(component_name or "").strip()
        if not key or not eligible:
            return False
        if trials is not None:
            previous = trials.get(key)
            if previous and previous.get("eligible"):
                return not previous.get("holdout", False)
        with self._lock:
            state = self._component_state_locked(key, min_samples)
        if state["state"] == "disabled":
            active = self._random() < self.HOLDOUT_RATE
            holdout = not active
        else:
            holdout = self._random() < self.HOLDOUT_RATE
            active = not holdout
        if trials is not None:
            trials[key] = {"eligible": True, "holdout": holdout}
        if not active:
            logger.info(
                "[LearningMetrics] %s 무작위 대조군으로 이번 실행에서 비활성화",
                key,
            )
        return active

    def get_component_diagnostics(self, min_samples: int = 10) -> list[dict]:
        with self._lock:
            names = set(self._DEFAULT_COMPONENTS) | set(self._metrics)
            for daily in self._daily_components.values():
                names.update(daily)
            return [
                self._component_state_locked(name, min_samples)
                for name in sorted(names)
            ]

    def _component_state_locked(self, name: str, min_samples: int) -> dict:
        trial_total_with = 0
        trial_success_with = 0
        trial_total_holdout = 0
        trial_success_holdout = 0
        for day in self._recent_day_keys(self.WINDOW_DAYS):
            daily = self._daily_components.get(day, {}).get(name, {})
            trial_total_with += int(daily.get("trial_total_with", 0))
            trial_success_with += int(daily.get("trial_success_with", 0))
            trial_total_holdout += int(daily.get("trial_total_holdout", 0))
            trial_success_holdout += int(daily.get("trial_success_holdout", 0))
        state = "pending"
        upper = 1.0
        if trial_total_with >= min_samples and trial_total_holdout >= min_samples:
            _, with_upper = self._wilson_interval(
                trial_success_with, trial_total_with
            )
            holdout_lower, _ = self._wilson_interval(
                trial_success_holdout, trial_total_holdout
            )
            upper = with_upper - holdout_lower
            state = "disabled" if upper < 0 else "active"
        return {
            "name": name,
            "state": state,
            "applied_samples": trial_total_with,
            "holdout_samples": trial_total_holdout,
            "lift_upper": upper,
        }

    @staticmethod
    def _wilson_interval(successes: int, total: int) -> tuple[float, float]:
        if total <= 0:
            return 0.0, 1.0
        z = 1.96
        rate = successes / total
        z_squared = z * z
        denominator = 1 + z_squared / total
        center = (rate + z_squared / (2 * total)) / denominator
        margin = z * math.sqrt(
            rate * (1 - rate) / total + z_squared / (4 * total * total)
        ) / denominator
        return max(0.0, center - margin), min(1.0, center + margin)

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

    def get_summary(self, days: int = 7) -> dict:
        with self._lock:
            keys = self._recent_day_keys(days)
            component_rows = []
            component_names = set(self._metrics.keys())
            for daily in self._daily_components.values():
                component_names.update(daily.keys())
            for name in sorted(component_names):
                activated_count = 0
                success_with = 0
                total_with = 0
                for key in keys:
                    metrics = self._daily_components.get(key, {}).get(name, {})
                    activated_count += int(metrics.get("activated_count", 0))
                    success_with += int(metrics.get("success_with", 0))
                    total_with += int(metrics.get("total_with", 0))
                if activated_count <= 0 and total_with <= 0:
                    continue
                component_rows.append(
                    {
                        "name": name,
                        "activated_count": activated_count,
                        "success_rate": round(success_with / total_with, 4) if total_with else 0.0,
                    }
                )
            component_rows.sort(
                key=lambda item: (item["activated_count"], item["name"]),
                reverse=True,
            )
            estimated_tokens = 0
            new_skills_created = 0
            python_compiled_skills = 0
            for key in keys:
                counters = self._daily_counters.get(key, {})
                estimated_tokens += int(counters.get("estimated_tokens", 0))
                new_skills_created += int(counters.get("new_skills_created", 0))
                python_compiled_skills += int(counters.get("python_compiled_skills", 0))
            return {
                "days": max(int(days or 0), 0),
                "components": component_rows,
                "estimated_tokens": estimated_tokens,
                "new_skills_created": new_skills_created,
                "python_compiled_skills": python_compiled_skills,
            }

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
            raw_daily_components = payload.get("daily_components", {}) if isinstance(payload, dict) else {}
            raw_daily_counters = payload.get("daily_counters", {}) if isinstance(payload, dict) else {}
            if isinstance(raw_items, list):
                raw_items = {item.get("name", ""): item for item in raw_items if isinstance(item, dict)}
            for name, item in dict(raw_items or {}).items():
                if not isinstance(item, dict):
                    continue
                item.setdefault("name", str(name or item.get("name", "")))
                component_values = {
                    field: item.get(field, 0 if field != "name" else item["name"])
                    for field in ComponentMetrics.__dataclass_fields__
                }
                component_values["holdout"] = bool(item.get("holdout", False))
                self._metrics[item["name"]] = ComponentMetrics(**component_values)
            self._daily_components = {}
            for day, items in dict(raw_daily_components or {}).items():
                if not isinstance(items, dict):
                    continue
                daily_items = {}
                for name, values in dict(items or {}).items():
                    if not isinstance(values, dict):
                        continue
                    daily_items[str(name)] = {
                        "activated_count": int(values.get("activated_count", 0)),
                        "success_with": int(values.get("success_with", 0)),
                        "total_with": int(values.get("total_with", 0)),
                        "success_without": int(values.get("success_without", 0)),
                        "total_without": int(values.get("total_without", 0)),
                        "holdout": bool(values.get("holdout", False)),
                        "trial_success_with": int(
                            values.get("trial_success_with", 0)
                        ),
                        "trial_total_with": int(
                            values.get("trial_total_with", 0)
                        ),
                        "trial_success_holdout": int(
                            values.get("trial_success_holdout", 0)
                        ),
                        "trial_total_holdout": int(
                            values.get("trial_total_holdout", 0)
                        ),
                    }
                self._daily_components[str(day)] = daily_items
            self._daily_counters = {
                str(day): {
                    str(name): int(value)
                    for name, value in dict(items or {}).items()
                    if isinstance(value, int)
                }
                for day, items in dict(raw_daily_counters or {}).items()
                if isinstance(items, dict)
            }
        except Exception as exc:
            logging.warning("[LearningMetrics] 로드 실패: %s", exc)
        finally:
            for name in self._DEFAULT_COMPONENTS:
                self._metrics.setdefault(name, ComponentMetrics(name=name))
            self._prune_daily_locked()

    def _save_locked(self) -> None:
        try:
            parent = os.path.dirname(self.filepath)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with open(self.filepath, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "components": {name: asdict(metrics) for name, metrics in self._metrics.items()},
                        "daily_components": self._daily_components,
                        "daily_counters": self._daily_counters,
                    },
                    handle,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception as exc:
            logging.warning("[LearningMetrics] 저장 실패: %s", exc)

    def _today_key(self) -> str:
        return datetime.now().date().isoformat()

    def _recent_day_keys(self, days: int) -> list[str]:
        safe_days = max(int(days or 0), 0)
        if safe_days <= 0:
            return []
        today = datetime.now().date()
        return [
            (today - timedelta(days=offset)).isoformat()
            for offset in range(safe_days)
        ]

    def _get_daily_component_metrics(
        self,
        day: str,
        name: str,
    ) -> dict[str, int | bool]:
        daily_components = self._daily_components.setdefault(day, {})
        return daily_components.setdefault(
            name,
            {
                "activated_count": 0,
                "success_with": 0,
                "total_with": 0,
                "success_without": 0,
                "total_without": 0,
                "holdout": False,
                "trial_success_with": 0,
                "trial_total_with": 0,
                "trial_success_holdout": 0,
                "trial_total_holdout": 0,
            },
        )

    def _prune_daily_locked(self, max_days: int = 90) -> None:
        cutoff = datetime.now().date() - timedelta(days=max(int(max_days or 0), 1))
        valid_keys = set()
        for key in set(self._daily_components.keys()) | set(self._daily_counters.keys()):
            try:
                parsed = datetime.fromisoformat(key).date()
            except ValueError:
                continue
            if parsed >= cutoff:
                valid_keys.add(key)
        self._daily_components = {
            key: value for key, value in self._daily_components.items() if key in valid_keys
        }
        self._daily_counters = {
            key: value for key, value in self._daily_counters.items() if key in valid_keys
        }


_metrics: LearningMetrics | None = None
_metrics_lock = threading.Lock()


def get_learning_metrics() -> LearningMetrics:
    global _metrics
    if _metrics is None:
        with _metrics_lock:
            if _metrics is None:
                _metrics = LearningMetrics()
    return _metrics
