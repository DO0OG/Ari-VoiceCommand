"""Measure cold load, warm latency and RSS in a fresh CPU-only process."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import time

import psutil


def benchmark(model_dir: Path, iterations: int = 1000) -> dict:
    """Include runtime import overhead in additional RSS; never poll in background."""
    process = psutil.Process()
    baseline_rss = process.memory_info().rss
    started = time.perf_counter()
    import numpy as np
    from agent.decision.engine import LinearScorer

    imported = time.perf_counter()
    scorer = LinearScorer(model_dir)
    loaded = time.perf_counter()
    texts = ("현재 시간을 알려줘", "Open the browser please", "今の天気を教えて")
    scorer.predict(texts[0])
    cold_ms = (time.perf_counter() - started) * 1000
    for i in range(30):
        scorer.predict(texts[i % len(texts)])
    cpu_started = time.process_time()
    latencies = []
    for i in range(iterations):
        start = time.perf_counter()
        scorer.predict(texts[i % len(texts)])
        latencies.append((time.perf_counter() - start) * 1000)
    cpu_ms = (time.process_time() - cpu_started) * 1000
    memory = process.memory_info()
    return {
        "python": platform.python_version(), "platform": platform.platform(),
        "processor": platform.processor(), "iterations": iterations,
        "import_ms": (imported - started) * 1000, "load_ms": (loaded - imported) * 1000,
        "cold_first_prediction_ms": cold_ms,
        "warm_ms": dict(zip(("p50", "p95", "p99"), map(float, np.percentile(latencies, [50, 95, 99])))),
        "cpu_ms": cpu_ms, "baseline_rss_bytes": baseline_rss,
        "steady_rss_bytes": memory.rss, "additional_steady_rss_bytes": memory.rss - baseline_rss,
        "peak_rss_bytes": getattr(memory, "peak_wset", None),
        "resource_bytes": sum(path.stat().st_size for path in model_dir.iterdir() if path.is_file()),
        "gpu_used": False,
        "rss_scope": "Fresh process: baseline after psutil, before NumPy and runtime import; OS peak if available",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, default=Path("resources/decision"))
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--output", type=Path, default=Path("scripts/decision_data/benchmark_results.json"))
    args = parser.parse_args(argv)
    if args.iterations < 1:
        parser.error("iterations must be positive")
    result = benchmark(args.model, args.iterations)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
