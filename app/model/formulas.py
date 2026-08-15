"""Safe formula evaluator — whitelist-only AST, no eval().

Formulas reference other nodes by id:
    "buyer_population * spend_per_unit"
    "tam * sam_rate"

Only arithmetic operators and node references are allowed. No function calls,
no attribute access, no comprehensions. Formulas come from the generator but
are treated as untrusted — the whitelist enforces this even if the LLM drifts.
"""
from __future__ import annotations

import ast
import operator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.model.nodes import Node

_OPS = {
    ast.Add:  operator.add,
    ast.Sub:  operator.sub,
    ast.Mult: operator.mul,
    ast.Div:  operator.truediv,
    ast.USub: operator.neg,
}


def resolve(node_id: str, nodes: "dict[str, Node]", cache: dict) -> float:
    """Resolve a node to its scalar value, caching to avoid re-evaluation.

    Resolution order:
      1. override_value (user wins, gates still apply)
      2. formula (evaluated recursively)
      3. raw_value

    Gates multiply the result regardless of which path produced the base value.
    """
    if node_id in cache:
        return cache[node_id]

    n = nodes[node_id]

    if n.override_value is not None:
        val = n.override_value
    elif n.formula is not None:
        val = _eval_formula(n.formula, nodes, cache)
    else:
        val = float(n.raw_value)  # type: ignore[arg-type]

    for gid in n.gates:
        val *= resolve(gid, nodes, cache)

    cache[node_id] = val
    return val


def _eval_formula(expr: str, nodes: "dict[str, Node]", cache: dict) -> float:
    tree = ast.parse(expr, mode="eval").body
    return _eval(tree, nodes, cache)


def _eval(n: ast.expr, nodes: "dict[str, Node]", cache: dict) -> float:
    if isinstance(n, ast.Constant):
        if not isinstance(n.value, (int, float)):
            raise ValueError(f"non-numeric constant in formula: {n.value!r}")
        return float(n.value)

    if isinstance(n, ast.Name):
        if n.id not in nodes:
            raise KeyError(f"formula references unknown node '{n.id}'")
        return resolve(n.id, nodes, cache)

    if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
        left  = _eval(n.left,  nodes, cache)
        right = _eval(n.right, nodes, cache)
        return _OPS[type(n.op)](left, right)

    if isinstance(n, ast.UnaryOp) and type(n.op) in _OPS:
        return _OPS[type(n.op)](_eval(n.operand, nodes, cache))

    raise ValueError(
        f"disallowed expression node '{type(n).__name__}' — "
        "only arithmetic operators and node references are allowed"
    )


def dependencies(expr: str) -> set[str]:
    """Return the set of node ids referenced by a formula."""
    return {
        node.id
        for node in ast.walk(ast.parse(expr, mode="eval"))
        if isinstance(node, ast.Name)
    }
