"""Safe condition evaluation helpers for execution steps."""

from __future__ import annotations

import ast
from typing import Any

_SAFE_AST_CALLS = {
    "len": len,
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
}

_SAFE_AST_METHODS = {
    dict: {"get"},
}

_COMPARE_OPERATORS = {
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
    ast.Is: lambda a, b: a is b,
    ast.IsNot: lambda a, b: a is not b,
}

_UNARY_OPERATORS = {
    ast.Not: lambda value: not value,
}


def evaluate_condition(condition: str, context: dict[str, str]) -> bool:
    parsed = ast.parse(condition, mode="eval")
    return bool(_evaluate_condition_node(parsed, {"step_outputs": context}))


def _evaluate_condition_node(node: ast.AST, scope: dict[str, Any]) -> Any:
    if isinstance(node, ast.Expression):
        return _evaluate_condition_node(node.body, scope)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in scope:
            return scope[node.id]
        raise ValueError(f"허용되지 않은 이름: {node.id}")
    if isinstance(node, ast.BoolOp):
        values = [bool(_evaluate_condition_node(value, scope)) for value in node.values]
        if isinstance(node.op, ast.And):
            return all(values)
        if isinstance(node.op, ast.Or):
            return any(values)
        raise ValueError("허용되지 않은 BoolOp")
    if isinstance(node, ast.UnaryOp):
        operator = _UNARY_OPERATORS.get(type(node.op))
        if operator is None:
            raise ValueError("허용되지 않은 UnaryOp")
        return operator(_evaluate_condition_node(node.operand, scope))
    if isinstance(node, ast.Compare):
        left = _evaluate_condition_node(node.left, scope)
        for operator_node, comparator in zip(node.ops, node.comparators):
            right = _evaluate_condition_node(comparator, scope)
            operator = _COMPARE_OPERATORS.get(type(operator_node))
            if operator is None or not operator(left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.Subscript):
        target = _evaluate_condition_node(node.value, scope)
        key = _evaluate_condition_node(node.slice, scope)
        return target[key]
    if isinstance(node, ast.Call):
        return _evaluate_condition_call(node, scope)
    if isinstance(node, (ast.List, ast.Tuple)):
        return [_evaluate_condition_node(item, scope) for item in node.elts]
    raise ValueError(f"지원하지 않는 조건식 노드: {type(node).__name__}")


def _evaluate_condition_call(node: ast.Call, scope: dict[str, Any]) -> Any:
    if isinstance(node.func, ast.Name):
        func = _SAFE_AST_CALLS.get(node.func.id)
        if func is None:
            raise ValueError(f"허용되지 않은 함수: {node.func.id}")
        args = [_evaluate_condition_node(arg, scope) for arg in node.args]
        return func(*args)
    if isinstance(node.func, ast.Attribute):
        owner = _evaluate_condition_node(node.func.value, scope)
        allowed_methods = _SAFE_AST_METHODS.get(type(owner), set())
        if node.func.attr not in allowed_methods:
            raise ValueError(f"허용되지 않은 메서드: {node.func.attr}")
        args = [_evaluate_condition_node(arg, scope) for arg in node.args]
        return getattr(owner, node.func.attr)(*args)
    raise ValueError("지원하지 않는 호출식")
