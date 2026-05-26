"""에이전트 성능 벤치마크 실행기.

pytest 기본 수집 대상은 아니며 필요 시 직접 실행한다:
    py -3.11 VoiceCommand/tests/benchmark_agent.py
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass

from core.resource_manager import ResourceManager


@dataclass
class BenchmarkTask:
    category: str
    goal: str


TASKS = [
    BenchmarkTask("file", "임시 파일을 생성한다"),
    BenchmarkTask("file", "임시 파일을 읽는다"),
    BenchmarkTask("file", "임시 파일 내용을 수정한다"),
    BenchmarkTask("file", "임시 파일을 이동한다"),
    BenchmarkTask("file", "임시 파일을 삭제한다"),
    BenchmarkTask("web", "단순 정보를 검색한다"),
    BenchmarkTask("web", "복합 정보를 조사한다"),
    BenchmarkTask("web", "페이지 내용을 요약한다"),
    BenchmarkTask("system", "볼륨 상태를 확인한다"),
    BenchmarkTask("system", "앱 실행 가능성을 확인한다"),
    BenchmarkTask("system", "스크린샷 경로를 만든다"),
    BenchmarkTask("system", "시스템 정보를 확인한다"),
    BenchmarkTask("code", "작은 함수를 작성한다"),
    BenchmarkTask("code", "버그를 수정한다"),
    BenchmarkTask("code", "테스트를 추가한다"),
    BenchmarkTask("code", "문서를 생성한다"),
    BenchmarkTask("complex", "두 단계 파일 작업을 수행한다"),
    BenchmarkTask("complex", "조사 후 요약한다"),
    BenchmarkTask("complex", "상태 확인 후 보고한다"),
    BenchmarkTask("complex", "계획 실행 검증을 수행한다"),
]


def run_benchmark(orchestrator=None) -> dict:
    if orchestrator is None:
        from agent.agent_orchestrator import get_orchestrator
        orchestrator = get_orchestrator()
    results = []
    started = time.time()
    for task in TASKS:
        task_start = time.time()
        result = orchestrator.run(task.goal, timeout=30)
        results.append({
            "task": asdict(task),
            "success": bool(result.achieved),
            "duration_seconds": round(time.time() - task_start, 3),
            "iterations": result.total_iterations,
            "summary": result.summary,
        })
    success_count = sum(1 for row in results if row["success"])
    payload = {
        "task_count": len(TASKS),
        "success_rate": success_count / max(1, len(TASKS)),
        "average_duration_seconds": round(sum(row["duration_seconds"] for row in results) / max(1, len(results)), 3),
        "total_duration_seconds": round(time.time() - started, 3),
        "results": results,
    }
    path = ResourceManager.get_runtime_path("benchmark_results.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return payload


if __name__ == "__main__":
    print(json.dumps(run_benchmark(), ensure_ascii=False, indent=2))
