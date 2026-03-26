from __future__ import annotations

"""
ActionStep 목록으로부터 실행 DAG와 병렬 그룹을 계산한다.
"""

from dataclasses import dataclass
import os
import re

_STEP_OUTPUT_REF_RE = re.compile(r"step_(\d+)_output")
_WINDOWS_PATH_RE = re.compile(r"([A-Za-z]:\\[^\\\n\"']+(?:\\[^\\\n\"']+)*)")
_URL_RE = re.compile(r"https?://([A-Za-z0-9._:-]+)")


def _norm_file(path: str) -> str:
    return f"file:{os.path.normpath(path)}"


def extract_resources(step_content: str, step_type: str) -> tuple[list[str], list[str]]:
    text = step_content or ""
    if step_type == "think" or not text.strip():
        return [], []
    reads: list[str] = []
    writes: list[str] = []
    for path in _WINDOWS_PATH_RE.findall(text):
        if any(token in text for token in ("open(", '"r"', "'r'", '"rb"', "'rb'", "web_fetch", "requests.get")):
            reads.append(_norm_file(path))
        if any(token in text for token in ("makedirs", "save_document", '"w"', "'w'", '"a"', "'a'", "os.remove", "shutil.copy", "shutil.move", "rmtree")):
            writes.append(_norm_file(path))
    for domain in _URL_RE.findall(text):
        reads.append(f"net:{domain.lower()}")
    if "taskkill" in text.lower():
        writes.append("proc:taskkill")
    if "pyperclip.copy" in text or "write_clipboard" in text:
        writes.append("clipboard:")
    if "read_clipboard" in text or "pyperclip.paste" in text:
        reads.append("clipboard:")
    if "reg add" in text.lower():
        writes.append("reg:unknown")
    return sorted(set(reads)), sorted(set(writes))


@dataclass
class DagNode:
    step_id: int
    depends_on: list[int]
    writes: list[str]
    reads: list[str]


def build_dag(steps: list) -> list[DagNode]:
    nodes: list[DagNode] = []
    for idx, step in enumerate(steps):
        depends = set(getattr(step, "depends_on", []) or [])
        refs = _STEP_OUTPUT_REF_RE.findall((getattr(step, "content", "") or "") + (getattr(step, "condition", "") or ""))
        depends.update(int(ref) for ref in refs)
        for prev in steps[:idx]:
            prev_reads = set(getattr(prev, "reads", []) or [])
            prev_writes = set(getattr(prev, "writes", []) or [])
            curr_reads = set(getattr(step, "reads", []) or [])
            curr_writes = set(getattr(step, "writes", []) or [])
            if (curr_reads & prev_writes) or (curr_writes & prev_writes) or (curr_writes & prev_reads):
                depends.add(prev.step_id)
        nodes.append(DagNode(step.step_id, sorted(depends), list(getattr(step, "writes", []) or []), list(getattr(step, "reads", []) or [])))
    return nodes


def assign_parallel_groups(dag: list[DagNode]) -> dict[int, int]:
    remaining = {node.step_id: set(node.depends_on) for node in dag}
    groups: dict[int, int] = {}
    group_no = 0
    while remaining:
        ready = sorted(step_id for step_id, deps in remaining.items() if not deps)
        if not ready:
            for offset, step_id in enumerate(sorted(remaining)):
                groups[step_id] = group_no + offset
            break
        for step_id in ready:
            groups[step_id] = group_no
            remaining.pop(step_id, None)
        for deps in remaining.values():
            deps.difference_update(ready)
        group_no += 1
    return groups


def annotate_steps(steps: list, dag: list[DagNode], groups: dict[int, int]) -> list:
    node_map = {node.step_id: node for node in dag}
    for step in steps:
        node = node_map.get(step.step_id)
        if not node:
            continue
        step.depends_on = list(node.depends_on)
        step.reads = list(node.reads)
        step.writes = list(node.writes)
        step.parallel_group = int(groups.get(step.step_id, -1))
    return steps


if __name__ == "__main__":
    print("dag_builder ready")
