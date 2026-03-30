"""플래너 성능 피드백 루프."""
from __future__ import annotations

import json
import logging
import os
from typing import List


class PlannerFeedbackLoop:
    def __init__(self):
        try:
            from core.resource_manager import ResourceManager
            self.file_path = ResourceManager.get_writable_path("planner_stats.json")
        except Exception:
            self.file_path = os.path.join(os.path.dirname(__file__), "planner_stats.json")
        self.stats = self._load()

    def _load(self):
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}
        except Exception as e:
            logging.warning(f"[PlannerFeedback] 로드 실패: {e}")
            return {}

    def _save(self):
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(self.stats, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logging.warning(f"[PlannerFeedback] 저장 실패: {e}")

    def record(self, steps: List, success: bool, duration_ms: int):
        for step in steps or []:
            key = getattr(step, "step_type", "unknown")
            bucket = self.stats.setdefault(key, {"success": 0, "fail": 0, "durations": []})
            if success:
                bucket["success"] += 1
            else:
                bucket["fail"] += 1
            bucket["durations"] = (bucket["durations"] + [int(duration_ms)])[-20:]
        self._save()

    def get_hints(self, goal: str, tags: List[str]) -> str:
        lines = []
        for key, bucket in self.stats.items():
            total = bucket.get("success", 0) + bucket.get("fail", 0)
            if total <= 0:
                continue
            success_rate = bucket.get("success", 0) / total
            if success_rate >= 0.7:
                lines.append(f"{key} 단계 성공률 {success_rate * 100:.0f}%")
            elif bucket.get("fail", 0) >= 2:
                lines.append(f"{key} 단계 실패 빈도 높음, 대안 접근 권장")
        if not lines:
            return ""
        return "[플래너 힌트]\n" + "\n".join(f"- {line}" for line in lines[:4])


_feedback_loop: PlannerFeedbackLoop | None = None


def get_planner_feedback_loop() -> PlannerFeedbackLoop:
    global _feedback_loop
    if _feedback_loop is None:
        _feedback_loop = PlannerFeedbackLoop()
    return _feedback_loop
