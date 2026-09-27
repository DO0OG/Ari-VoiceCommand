"""Check statically imported modules before a generated script starts running."""

import ast
import importlib.util
import os
import sys
from typing import Iterable

from i18n.translator import _


_MODULE_TO_PACKAGE = {
    "PIL": "Pillow",
    "cv2": "OpenCV",
    "Crypto": "pycryptodome",
    "bs4": "BeautifulSoup",
    "sklearn": "scikit-learn",
    "yaml": "PyYAML",
}


class _RequiredImportVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: set[str] = set()
        self._optional_depth = 0
        self._type_checking_names = {"TYPE_CHECKING"}
        self._typing_modules = {"typing"}

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root_name = alias.name.split(".", 1)[0]
            if root_name == "typing":
                self._typing_modules.add(alias.asname or root_name)
            if self._optional_depth == 0:
                self.names.add(root_name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level:
            return
        root_name = (node.module or "").split(".", 1)[0]
        if root_name == "typing":
            self._type_checking_names.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name == "TYPE_CHECKING"
            )
        if root_name and self._optional_depth == 0:
            self.names.add(root_name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return  # 호출 여부를 정적으로 알 수 없으므로 실행 전 검사에서 제외한다.

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_If(self, node: ast.If) -> None:
        skip_body = self._is_type_checking(node.test) or (
            isinstance(node.test, ast.Constant) and not node.test.value
        )
        optional_body = not skip_body and self._checks_find_spec(node.test)
        if not skip_body:
            if optional_body:
                self._optional_depth += 1
            for statement in node.body:
                self.visit(statement)
            if optional_body:
                self._optional_depth -= 1
        for statement in node.orelse:
            self.visit(statement)

    @staticmethod
    def _checks_find_spec(test: ast.expr) -> bool:
        return any(
            isinstance(item, ast.Call)
            and getattr(item.func, "attr", getattr(item.func, "id", None)) == "find_spec"
            for item in ast.walk(test)
        )

    def visit_Try(self, node: ast.Try) -> None:
        optional = any(self._catches_import_error(handler.type) for handler in node.handlers)
        if optional:
            self._optional_depth += 1
        for statement in node.body:
            self.visit(statement)
        if optional:
            self._optional_depth -= 1
        for handler in node.handlers:
            self.visit(handler)
        for statement in (*node.orelse, *node.finalbody):
            self.visit(statement)

    def _is_type_checking(self, test: ast.expr) -> bool:
        if isinstance(test, ast.Name):
            return test.id in self._type_checking_names
        return (
            isinstance(test, ast.Attribute)
            and test.attr == "TYPE_CHECKING"
            and isinstance(test.value, ast.Name)
            and test.value.id in self._typing_modules
        )

    @staticmethod
    def _catches_import_error(handler_type: ast.expr | None) -> bool:
        if isinstance(handler_type, ast.Name):
            return handler_type.id in {"ImportError", "ModuleNotFoundError"}
        if isinstance(handler_type, ast.Tuple):
            return any(_RequiredImportVisitor._catches_import_error(item) for item in handler_type.elts)
        return False


def find_unavailable_imports(source: str, search_paths: Iterable[str] = ()) -> list[str]:
    """Return unavailable top-level imports, ignoring optional and local modules."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    visitor = _RequiredImportVisitor()
    visitor.visit(tree)
    local_roots = set()
    for search_path in search_paths:
        try:
            for entry in os.listdir(search_path):
                path = os.path.join(search_path, entry)
                if os.path.isfile(path) and entry.endswith(".py"):
                    local_roots.add(entry[:-3])
                elif os.path.isdir(path):
                    local_roots.add(entry)  # 일반 패키지와 네임스페이스 패키지 모두 로컬 모듈로 본다.
        except OSError:
            continue

    unavailable = []
    for name in sorted(visitor.names - local_roots - sys.stdlib_module_names):
        if name in sys.modules:
            continue
        try:
            spec = importlib.util.find_spec(name)
        except (ImportError, ValueError):
            spec = None
        if spec is None:
            unavailable.append(name)
    return unavailable


def unavailable_packages_message(module_names: Iterable[str]) -> str:
    packages = ", ".join(_MODULE_TO_PACKAGE.get(name, name) for name in sorted(set(module_names)))
    return _(
        "설치된 아리에서 사용할 수 없는 파이썬 패키지가 필요합니다: {packages}. "
        "사용할 수 있는 패키지로 바꾸어 다시 실행해 주세요.",
        packages=packages,
    )
