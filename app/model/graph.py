"""Dependency graph utilities for the market model.

Build the directed graph of which nodes depend on which, detect cycles,
and compute the affected set (topological order) after an edit.
"""
from __future__ import annotations

from collections import defaultdict, deque
from typing import TYPE_CHECKING

from app.model.formulas import dependencies

if TYPE_CHECKING:
    from app.model.nodes import Node


def build_edges(nodes: "dict[str, Node]") -> dict[str, set[str]]:
    """Return a map of node_id → set of node_ids that depend on it.

    Raises KeyError if any formula or gate references a node not in the dict.
    """
    dependents: dict[str, set[str]] = defaultdict(set)
    for nid, n in nodes.items():
        deps: set[str] = set(n.gates)
        if n.formula:
            deps |= dependencies(n.formula)
        for d in deps:
            if d not in nodes:
                raise KeyError(
                    f"Node '{nid}' depends on '{d}' which is not in the model"
                )
            dependents[d].add(nid)
    return dict(dependents)


def affected(start: str, dependents: "dict[str, set[str]]") -> list[str]:
    """All node ids downstream of `start`, in topological order.

    The returned list includes `start` itself and every node that (transitively)
    depends on it. Order is guaranteed safe for sequential recomputation.
    """
    seen: set[str] = {start}
    q: deque[str] = deque([start])
    while q:
        cur = q.popleft()
        for dep in dependents.get(cur, ()):
            if dep not in seen:
                seen.add(dep)
                q.append(dep)
    return _topo_order(seen, dependents)


def _topo_order(node_ids: set[str], dependents: "dict[str, set[str]]") -> list[str]:
    """Topological sort of `node_ids` with respect to the dependency graph."""
    in_edges: dict[str, set[str]] = {nid: set() for nid in node_ids}
    for nid in node_ids:
        for dep in dependents.get(nid, ()):
            if dep in node_ids:
                in_edges[dep].add(nid)

    queue: deque[str] = deque(n for n, ins in in_edges.items() if not ins)
    order: list[str] = []
    while queue:
        cur = queue.popleft()
        order.append(cur)
        for dep in dependents.get(cur, ()):
            if dep in node_ids:
                in_edges[dep].discard(cur)
                if not in_edges[dep]:
                    queue.append(dep)
    return order


def assert_acyclic(nodes: "dict[str, Node]") -> None:
    """Raise ValueError if the node graph contains a cycle.

    Run at model construction — a cycle means the generator produced a broken
    model and the MarketModel.__post_init__ will surface it immediately.
    """
    try:
        deps = build_edges(nodes)
    except KeyError as e:
        raise ValueError(str(e)) from e

    visited: set[str] = set()
    stack:   set[str] = set()

    def dfs(nid: str) -> None:
        visited.add(nid)
        stack.add(nid)
        for dep in deps.get(nid, ()):
            if dep not in visited:
                dfs(dep)
            elif dep in stack:
                raise ValueError(
                    f"Cycle detected in market model: '{nid}' → '{dep}'"
                )
        stack.discard(nid)

    for nid in nodes:
        if nid not in visited:
            dfs(nid)
