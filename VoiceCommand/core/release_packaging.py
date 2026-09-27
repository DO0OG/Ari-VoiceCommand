"""Build-time helpers for copying release dependencies without compiling them."""

import ast
import importlib.metadata
import importlib.util
import os
import re
import sys

from packaging.requirements import Requirement


_RAW_IMPORT_SKIP = {
    "tkinter", "turtle", "idlelib", "test", "lib2to3", "ensurepip", "venv",
    # 테스트 도구 전용 표준 라이브러리. 원본 복사 패키지의 테스트 코드에서만 쓴다.
    "unittest", "doctest", "pydoc",
}
# 앱 코드가 이미 컴파일해 포함하는 의존성. 원본 복사 대상에서 빼고 기존처럼 컴파일한다.
# 컴파일되는 확장 모듈의 DLL(.libs)은 Nuitka가 직접 넣으므로 원본 복사하지 않는다.
_COMPILED_DEPENDENCIES = {"numpy", "PIL", "packaging", "charset_normalizer"}


def _normalized_distribution_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def raw_packages(*module_names: str, raw_dependencies: bool = False) -> list[str]:
    """Copy packages as raw runtime files.

    raw_dependencies=True이면 선언된 서드파티 의존성 패키지도 컴파일하지 않고 원본 복사한다
    (_COMPILED_DEPENDENCIES 제외). 빌드 시간을 늘리지 않기 위한 선택이다.
    """
    args: list[str] = []
    distributions_by_import = importlib.metadata.packages_distributions()
    queue = list(module_names)
    seen: set[str] = set()
    while queue:
        module_name = queue.pop(0)
        if module_name in seen:
            continue
        seen.add(module_name)
        try:
            spec = importlib.util.find_spec(module_name)
        except (ImportError, ValueError):
            spec = None
        if spec is None or not spec.submodule_search_locations:
            print(f"• 원본 복사 패키지 생략: {module_name}")
            continue

        package_dir = list(spec.submodule_search_locations)[0]
        args.append(f"--nofollow-import-to={module_name}")
        args.append(f"--include-raw-dir={package_dir}={module_name}")

        args.extend(_sibling_library_dirs(module_name, spec.submodule_search_locations))

        args.extend(
            raw_package_imports(
                package_dir,
                module_name,
                distributions_by_import,
                raw_dependency_queue=queue if raw_dependencies else None,
            )
        )
    return list(dict.fromkeys(args))


def raw_package_imports(
    package_dir: str,
    module_name: str,
    distributions_by_import: dict[str, list[str]] | None = None,
    raw_dependency_queue: list[str] | None = None,
) -> list[str]:
    """Include imports that raw package code needs, limited to declared dependencies."""
    names: set[str] = set()
    for root, _dirs, files in os.walk(package_dir):
        for file_name in files:
            if not file_name.endswith(".py"):
                continue
            try:
                with open(os.path.join(root, file_name), encoding="utf-8") as handle:
                    tree = ast.parse(handle.read())
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names.add(node.module.split(".")[0])

    if distributions_by_import is None:
        distributions_by_import = importlib.metadata.packages_distributions()
    # import 이름과 배포 이름이 다를 수 있다(예: dateutil → python-dateutil).
    distribution_name = (distributions_by_import.get(module_name) or [module_name])[0]
    try:
        requirements = importlib.metadata.requires(distribution_name) or []
    except importlib.metadata.PackageNotFoundError:
        requirements = []

    required = set()
    for requirement in requirements:
        try:
            parsed = Requirement(requirement)
        except Exception:
            if "extra ==" in requirement:
                continue
            distribution = re.split(r"[<>=!~;\[ ]", requirement, maxsplit=1)[0].strip()
        else:
            if parsed.marker is not None and not parsed.marker.evaluate():
                continue
            distribution = parsed.name
        required.add(_normalized_distribution_name(distribution))

    required_imports = {
        name
        for name, distributions in distributions_by_import.items()
        if any(
            _normalized_distribution_name(distribution) in required
            for distribution in distributions
        )
    }
    allowed = {
        name
        for name in names
        if name in sys.stdlib_module_names
        or _normalized_distribution_name(name) in required
        or name in required_imports
    }
    args: list[str] = []
    for name in sorted(allowed - {module_name} - _RAW_IMPORT_SKIP):
        try:
            spec = importlib.util.find_spec(name)
        except (ImportError, ValueError):
            spec = None
        if spec is None:
            continue
        if (
            raw_dependency_queue is not None
            and spec.submodule_search_locations
            and name not in sys.stdlib_module_names
            and name not in _COMPILED_DEPENDENCIES
        ):
            raw_dependency_queue.append(name)
            continue
        option = "--include-package" if spec.submodule_search_locations else "--include-module"
        args.append(f"{option}={name}")
        if spec.submodule_search_locations:
            args.append(f"--include-package-data={name}")
    return args


def _sibling_library_dirs(module_name: str, package_locations) -> list[str]:
    distributions = importlib.metadata.packages_distributions().get(module_name, [])
    distribution_names = {_normalized_distribution_name(name) for name in distributions}
    args = []
    for package_dir in package_locations:
        parent_dir = os.path.dirname(package_dir)
        try:
            siblings = os.listdir(parent_dir)
        except OSError:
            continue
        for sibling in siblings:
            sibling_path = os.path.join(parent_dir, sibling)
            if not os.path.isdir(sibling_path) or not sibling.lower().endswith(".libs"):
                continue
            library_name = _normalized_distribution_name(sibling[:-5])
            if library_name in distribution_names:
                args.append(f"--include-raw-dir={sibling_path}={sibling}")
    return args
