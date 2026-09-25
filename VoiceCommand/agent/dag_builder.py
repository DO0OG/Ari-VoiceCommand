"""
ActionStep 목록으로부터 실행 DAG와 병렬 그룹을 계산한다.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
import logging
import ntpath
import os
import re

_STEP_OUTPUT_REF_RE = re.compile(r"step_(\d+)_output")
_WINDOWS_PATH_RE = re.compile(r"([A-Za-z]:\\[^\\\n\"']+(?:\\[^\\\n\"']+)*)")
_SHELL_FILE_COMMAND_RE = re.compile(
    r"^\s*(?:&\s*)?(?:sudo\s+)?(?:[^\s]*[\\/])?(?P<command>"
    r"get-content|set-content|add-content|out-file|import-csv|export-csv|"
    r"remove-item|copy-item|move-item|new-item|mkdir|md|type|cat|more|cp|mv|rm|del|erase"
    r")\b(?P<args>.*)$",
    re.IGNORECASE,
)
_SHELL_ENV_VAR_RE = re.compile(
    r"%([A-Za-z_]\w*)%|\$env:([A-Za-z_]\w*)|\$\{([A-Za-z_]\w*)\}|\$([A-Za-z_]\w*)",
    re.IGNORECASE,
)
_SHELL_REDIRECTION_RE = re.compile(
    r"(?P<operator>>>?|<)\s*(?P<target>'[^']*'|\"[^\"]*\"|[^\s;]+)"
)
_SHELL_ARGUMENT_RE = re.compile(r"'[^']*'|\"[^\"]*\"|[^\s]+")
_SHELL_PATH_SWITCH_RE = re.compile(
    r"(?i)-(?:Path|LiteralPath|Destination)\s+('[^']*'|\"[^\"]*\"|[^\s]+)"
)
_URL_RE = re.compile(r"https?://([A-Za-z0-9._:-]+)")
_DESKTOP_STATE_CALL_RE = re.compile(
    r"\b(?:click_screen|click_image|move_mouse|type_text|press_keys|hotkey|"
    r"focus_window|wait_for_window|launch_app|open_path|open_url|"
    r"browser_login|run_browser_actions|run_desktop_workflow|"
    r"run_adaptive_desktop_workflow|run_resilient_desktop_workflow|"
    r"get_active_window_title|list_open_windows|get_desktop_state|"
    r"write_clipboard|read_clipboard|take_screenshot|screenshot|"
    r"is_image_visible|get_window_state)\s*\(",
    re.IGNORECASE,
)
_DESKTOP_STATE_TOKENS = (
    "pyautogui",
    "pynput",
    "win32gui",
    "win32api",
    "keyboard.",
    "mouse.",
    "pyperclip.",
    "screenshot",
    "화면",
    "창 상태",
    "창",
    "포커스",
    "클릭",
    "키보드",
    "마우스",
    "입력",
)


def _norm_file(path: str) -> str:
    return f"file:{os.path.normpath(path)}"


def _norm_relative_file(path: str) -> str | None:
    """cwd를 기준으로 실제 경로를 확인하지 않고 상대 경로를 정규화한다."""
    if not path or ntpath.isabs(path) or ntpath.splitdrive(path)[0]:
        return None
    # 이 표식은 실제 경로가 아니라 표현식/템플릿임을 나타낸다.
    if any(marker in path for marker in ("$", "%", "{", "}", "*", "?")):
        return None
    normalized = ntpath.normpath(path).replace("\\", "/")
    return f"file:{normalized}"


def _normalize_resource(resource: str) -> str:
    """명시적 상대 파일 리소스를 추론된 경로 키와 일치시킨다."""
    if not isinstance(resource, str) or not resource.startswith("file:"):
        return resource
    path = resource[len("file:") :]
    if path.startswith("envvar:") or "://" in path or ntpath.isabs(path) or ntpath.splitdrive(path)[0]:
        return resource
    normalized = _norm_relative_file(path)
    return normalized or resource


def _file_paths_overlap(first: str, second: str) -> bool:
    if not first.startswith("file:") or not second.startswith("file:"):
        return False
    first_path, second_path = first[5:], second[5:]
    if not first_path or not second_path or "://" in first_path or "://" in second_path:
        return False
    first_path = ntpath.normcase(ntpath.normpath(first_path)).replace("\\", "/")
    second_path = ntpath.normcase(ntpath.normpath(second_path)).replace("\\", "/")
    if first_path == second_path:
        return True

    def leading_parent_count(path: str) -> int:
        if ntpath.isabs(path) or ntpath.splitdrive(path)[0]:
            return 0
        count = 0
        for part in path.split("/"):
            if part != "..":
                break
            count += 1
        return count

    if leading_parent_count(first_path) != leading_parent_count(second_path):
        return False
    if first_path == "." or second_path == ".":
        descendant = second_path if first_path == "." else first_path
        return not ntpath.isabs(descendant) and not descendant.startswith("..")
    try:
        common = ntpath.normcase(
            ntpath.commonpath([first_path, second_path])
        ).replace("\\", "/")
    except ValueError:
        return False
    return common == first_path or common == second_path


def _file_dependency_conflict(
    reads: set[str],
    writes: set[str],
    other_reads: set[str],
    other_writes: set[str],
) -> bool:
    # ponytail: 스텝 쌍 안에서 리소스를 모든 조합으로 비교해 이차 시간으로 늘어난다.
    # 계획이 커지면 경로 인덱스를 도입한다.
    for write_resources, accessed_resources in (
        (writes, other_reads | other_writes),
        (other_writes, reads | writes),
    ):
        for write_resource in write_resources:
            for accessed_resource in accessed_resources:
                if _file_paths_overlap(write_resource, accessed_resource):
                    return True
    return False


def _python_call_name(expression: ast.expr) -> str | None:
    if isinstance(expression, ast.Name):
        return expression.id
    if isinstance(expression, ast.Attribute):
        parent = _python_call_name(expression.value)
        return f"{parent}.{expression.attr}" if parent else None
    return None


def _python_path_resource(expression: ast.expr) -> str | None:
    if isinstance(expression, ast.Constant) and isinstance(expression.value, str):
        return _norm_relative_file(expression.value)

    if (
        isinstance(expression, ast.Call)
        and _python_call_name(expression.func) in {"os.getenv", "os.environ.get"}
        and expression.args
        and all(keyword.arg == "default" for keyword in expression.keywords)
    ):
        name = expression.args[0]
        if isinstance(name, ast.Constant) and isinstance(name.value, str) and name.value:
            return f"file:envvar:{name.value}"

    if isinstance(expression, ast.Subscript) and _python_call_name(expression.value) == "os.environ":
        name = expression.slice
        if isinstance(name, ast.Constant) and isinstance(name.value, str) and name.value:
            return f"file:envvar:{name.value}"
    return None


def _python_path_resources(expression: ast.expr) -> set[str]:
    resource = _python_path_resource(expression)
    if not resource:
        return set()

    resources = {resource}
    if (
        isinstance(expression, ast.Call)
        and _python_call_name(expression.func) in {"os.getenv", "os.environ.get"}
    ):
        fallback = expression.args[1] if len(expression.args) > 1 else next(
            (keyword.value for keyword in expression.keywords if keyword.arg == "default"),
            None,
        )
        if fallback is not None:
            resources.update(_python_path_resources(fallback))
    return resources


def _python_file_resources(text: str) -> tuple[set[str], set[str]]:
    # ponytail: 리터럴 경로와 단순한 환경 변수 조회만 처리한다.
    # 생성 계획에서 pathlib/계산 경로 추적이 필요해지면 AST 지원을 추가한다.
    reads: set[str] = set()
    writes: set[str] = set()
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return reads, writes

    read_calls = {"os.listdir", "os.scandir", "listdir", "scandir"}
    write_calls = {
        "os.makedirs", "os.mkdir", "os.rmdir", "os.remove", "os.unlink",
        "makedirs", "mkdir", "rmdir", "remove", "unlink", "rmtree",
        "shutil.rmtree", "save_document",
    }
    copy_calls = {"shutil.copy", "shutil.copy2", "shutil.copyfile", "shutil.move"}

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = _python_call_name(node.func)

        if function in {"open", "io.open"}:
            file_argument = node.args[0] if node.args else None
            if file_argument is None:
                file_keyword = next(
                    (keyword.value for keyword in node.keywords if keyword.arg == "file"),
                    None,
                )
                file_argument = file_keyword
            if file_argument is None:
                continue
            resources = _python_path_resources(file_argument)
            if not resources:
                continue

            mode = node.args[1] if len(node.args) > 1 else None
            has_dynamic_keywords = any(keyword.arg is None for keyword in node.keywords)
            for keyword in node.keywords:
                if keyword.arg == "mode":
                    mode = keyword.value
            if mode is None and not has_dynamic_keywords:
                reads.update(resources)  # open()의 기본 모드는 읽기 모드다.
            elif isinstance(mode, ast.Constant) and isinstance(mode.value, str):
                value = mode.value.lower()
                if "r" in value or "+" in value:
                    reads.update(resources)
                if any(flag in value for flag in ("w", "a", "x", "+")):
                    writes.update(resources)
            else:
                # 동적 모드는 읽기/쓰기 여부를 알 수 없으므로 두 작업 모두로 분류해 병렬 실행을 제한한다.
                reads.update(resources)
                writes.update(resources)
            continue

        if function in copy_calls:
            source = node.args[0] if node.args else None
            destination = node.args[1] if len(node.args) > 1 else None
            for keyword in node.keywords:
                if keyword.arg in {"src", "source"} and source is None:
                    source = keyword.value
                if keyword.arg in {"dst", "destination"} and destination is None:
                    destination = keyword.value
            source_resources = _python_path_resources(source) if source else set()
            destination_resources = _python_path_resources(destination) if destination else set()
            if source_resources:
                reads.update(source_resources)
                if function == "shutil.move":
                    writes.update(source_resources)
            if destination_resources:
                writes.update(destination_resources)
            continue

        if function in (read_calls | write_calls) and node.args:
            resources = _python_path_resources(node.args[0])
            if resources:
                if function in read_calls:
                    reads.update(resources)
                if function in write_calls:
                    writes.update(resources)
    return reads, writes


def _is_outside_quotes(text: str, position: int) -> bool:
    quote: str | None = None
    escaped = False
    for char in text[:position]:
        if escaped:
            escaped = False
        elif quote == '"' and char == "\\":
            escaped = True
        elif quote:
            if char == quote:
                quote = None
        elif char in "'\"":
            quote = char
    return quote is None


def _shell_path_resource(value: str) -> str | None:
    match = _SHELL_ENV_VAR_RE.match(value)
    if not match:
        return _norm_relative_file(value)

    name = next(name for name in match.groups() if name)
    suffix = value[match.end() :].lstrip("\\/")
    if not suffix:
        return f"file:envvar:{name}"
    if any(marker in suffix for marker in ("$", "%", "{", "}")):
        return None
    suffix_resource = _norm_relative_file(suffix)
    if not suffix_resource:
        return None
    return f"file:envvar:{name}/{suffix_resource[len('file:') :]}"


def _shell_env_resources(text: str) -> tuple[set[str], set[str]]:
    # ponytail: 인식하는 명령과 단순 리디렉션만 줄 단위로 분석한다.
    # 복합 또는 여러 줄 스크립트의 의존성 보장이 필요해지면 셸 파서를 추가한다.
    reads: set[str] = set()
    writes: set[str] = set()
    read_commands = {"get-content", "import-csv", "type", "cat", "more"}
    write_commands = {
        "set-content", "add-content", "out-file", "export-csv", "remove-item",
        "new-item", "mkdir", "md", "del", "erase", "rm",
    }
    copy_commands = {"copy-item", "move-item", "cp", "mv"}

    for line in text.splitlines():
        command_match = _SHELL_FILE_COMMAND_RE.match(line)
        if command_match:
            command = command_match.group("command").lower()
            args = command_match.group("args")
            value_arg = re.search(r"\s+-Value\b", args, re.IGNORECASE)
            path_switches = list(_SHELL_PATH_SWITCH_RE.finditer(args))
            switch_values = [match.group(1) for match in path_switches]
            if path_switches and command not in copy_commands:
                tokens = switch_values
            else:
                positional_args = args
                if value_arg:
                    positional_args = positional_args[: value_arg.start()]
                switch_value_spans = [
                    match.span(1) for match in path_switches
                ]
                tokens = [
                    token.group(0)
                    for token in _SHELL_ARGUMENT_RE.finditer(positional_args)
                    if not token.group(0).startswith(("-", "/"))
                    and not any(
                        start <= token.start() < end
                        for start, end in switch_value_spans
                    )
                ]
                if path_switches:
                    tokens.extend(switch_values)
                elif command not in copy_commands:
                    tokens = tokens[:1]
                else:
                    tokens = tokens[:2]
            resources: set[str] = set()
            for token in tokens:
                value = token[1:-1] if len(token) >= 2 and token[0] == token[-1] and token[0] in "'\"" else token
                resource = _shell_path_resource(value)
                if resource:
                    resources.add(resource)
            if command in read_commands or command in copy_commands:
                reads.update(resources)
            if command in write_commands or command in copy_commands:
                writes.update(resources)

        for match in _SHELL_REDIRECTION_RE.finditer(line):
            if not _is_outside_quotes(line, match.start()):
                continue
            target = match.group("target")
            if (
                re.fullmatch(r"&\d+", target)
                and match.end("operator") == match.start("target")
            ):
                continue
            if len(target) >= 2 and target[0] == target[-1] and target[0] in "'\"":
                target = target[1:-1]
            resource = _shell_path_resource(target)
            if not resource:
                continue
            if match.group("operator") == "<":
                reads.add(resource)
            else:
                writes.add(resource)
    return reads, writes


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

    if step_type.lower() != "shell":
        python_reads, python_writes = _python_file_resources(text)
        reads.extend(python_reads)
        writes.extend(python_writes)

    if step_type.lower() == "shell":
        shell_reads, shell_writes = _shell_env_resources(text)
        reads.extend(shell_reads)
        writes.extend(shell_writes)
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
    lowered = text.lower()
    if _DESKTOP_STATE_CALL_RE.search(text) or any(
        token in lowered for token in _DESKTOP_STATE_TOKENS
    ):
        # 데스크톱 포커스, 포인터, 키보드 상태는 프로세스 전역이다.
        # 이 상태를 관찰하거나 변경하는 모든 작업을 배타적 리소스로 처리한다.
        # 그래야 두 작업이 같은 병렬 그룹에서 동시에 실행되지 않는다.
        writes.append("desktop:")
    return sorted(set(reads)), sorted(set(writes))


@dataclass
class DagNode:
    step_id: int
    depends_on: list[int]
    writes: list[str]
    reads: list[str]


def build_dag(steps: list) -> list[DagNode]:
    nodes: list[DagNode] = []
    resource_cache: dict[int, tuple[set[str], set[str]]] = {}
    for idx, step in enumerate(steps):
        depends = set(getattr(step, "depends_on", []) or [])
        refs = _STEP_OUTPUT_REF_RE.findall((getattr(step, "content", "") or "") + (getattr(step, "condition", "") or ""))
        depends.update(int(ref) for ref in refs)
        inferred_reads, inferred_writes = extract_resources(
            getattr(step, "content", "") or "",
            getattr(step, "step_type", "python"),
        )
        curr_reads = {
            _normalize_resource(resource)
            for resource in (set(getattr(step, "reads", []) or []) | set(inferred_reads))
        }
        curr_writes = {
            _normalize_resource(resource)
            for resource in (set(getattr(step, "writes", []) or []) | set(inferred_writes))
        }
        resource_cache[step.step_id] = (curr_reads, curr_writes)
        for prev in steps[:idx]:
            prev_reads, prev_writes = resource_cache[prev.step_id]
            shared_desktop = "desktop:" in (curr_reads | curr_writes) and "desktop:" in (prev_reads | prev_writes)
            if (
                shared_desktop
                or (curr_reads & prev_writes)
                or (curr_writes & prev_writes)
                or (curr_writes & prev_reads)
                or _file_dependency_conflict(
                    curr_reads,
                    curr_writes,
                    prev_reads,
                    prev_writes,
                )
            ):
                depends.add(prev.step_id)
        nodes.append(
            DagNode(
                step.step_id,
                sorted(depends),
                sorted(curr_writes),
                sorted(curr_reads),
            )
        )
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
    logging.basicConfig(level=logging.DEBUG)
    logging.debug("dag_builder ready")
