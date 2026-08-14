"""MarketModel — immutable, versioned, self-validating market model.

Every edit returns a new version with a parent pointer. This gives undo,
side-by-side comparison, an audit trail, and a stable hash for PDF stamping —
all for free from the immutability invariant.

The __post_init__ assertions mean SAM > TAM is impossible to construct, not
something a post-hoc verifier catches afterward (spec v8 Part A fix).
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Literal, Optional

from app.model.formulas import resolve, dependencies
from app.model.graph import assert_acyclic, build_edges
from app.model.nodes import Node


def _new_id() -> str:
    return f"mm_{uuid.uuid4().hex[:16]}"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class MarketModel:
    id: str
    report_id: str
    version: int
    parent_version: Optional[int]
    nodes: dict[str, Node]          # node_id → Node (must use frozenset for true immutability,
                                    # but dict is fine here — we never mutate, always replace)
    created_at: str
    created_by: Literal["engine", "user"]
    change_note: str = ""

    # ── computed accessors ────────────────────────────────────────────────────

    def value(self, node_id: str) -> float:
        """Resolve a single node to its scalar value."""
        return resolve(node_id, self.nodes, {})

    def values(self) -> dict[str, float]:
        """Resolve all nodes, returning a flat dict of node_id → float."""
        cache: dict[str, float] = {}
        for nid in self.nodes:
            resolve(nid, self.nodes, cache)
        return cache

    def formatted(self) -> dict[str, str]:
        """Format all resolved values using the node's unit as a hint."""
        vals = self.values()
        result: dict[str, str] = {}
        for nid, n in self.nodes.items():
            v = vals[nid]
            u = n.unit.lower()
            if u in ("labs", "sites", "units"):
                result[nid] = f"{v:,.0f} {n.unit}"
            elif "usd/lab/yr" in u or "usd/yr" in u:
                result[nid] = _fmt_usd(v) + "/yr"
            elif "usd" in u or u == "":
                result[nid] = _fmt_usd(v)
            elif "ratio" in u or u == "%":
                result[nid] = f"{v * 100:.1f}%"
            elif "lab" in u or "site" in u or "unit" in u:
                result[nid] = f"{v:,.0f}"
            else:
                result[nid] = f"{v:,.2f}"
        return result

    def model_hash(self) -> str:
        """SHA-256 of the canonical node JSON, for PDF stamping and version integrity."""
        canonical = json.dumps(
            {nid: n.to_dict() for nid, n in sorted(self.nodes.items())},
            sort_keys=True, separators=(",", ":"),
        )
        return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()[:24]

    # ── construction-time invariants ──────────────────────────────────────────

    def __post_init__(self) -> None:
        assert_acyclic(self.nodes)
        v = self.values()
        if "sam" in v and "tam" in v:
            if v["sam"] > v["tam"] + 1e-6:
                raise AssertionError(
                    f"SAM ({v['sam']:,.0f}) cannot exceed TAM ({v['tam']:,.0f}) — "
                    "adjust sam_rate or buyer_population"
                )
        if "som" in v and "sam" in v:
            if v["som"] > v["sam"] + 1e-6:
                raise AssertionError(
                    f"SOM ({v['som']:,.0f}) cannot exceed SAM ({v['sam']:,.0f}) — "
                    "adjust som_rate"
                )

    # ── mutation — always returns a NEW version ───────────────────────────────

    def with_override(
        self,
        node_id: str,
        value: float,
        rationale: str,
        user_id: str,
    ) -> "MarketModel":
        """Return a new MarketModel with node_id overridden to value.

        The __post_init__ of the new model enforces SAM ≤ TAM and SOM ≤ SAM.
        If the override would violate those invariants, AssertionError is raised
        before the new version is created — the original model is unchanged.
        """
        n = self.nodes[node_id]
        if not n.editable:
            raise PermissionError(f"Node '{node_id}' is not editable")
        new_nodes = dict(self.nodes)
        new_nodes[node_id] = replace(
            n,
            override_value=float(value),
            override_rationale=rationale,
            method="user_override",
        )
        return MarketModel(
            id=_new_id(),
            report_id=self.report_id,
            version=self.version + 1,
            parent_version=self.version,
            nodes=new_nodes,
            created_at=_utcnow(),
            created_by="user",
            change_note=f"{node_id} → {value}  ({rationale[:60]})",
        )

    def with_gate(self, target_id: str, gate: Node) -> "MarketModel":
        """Return a new model with a multiplicative gate appended to target_id."""
        if gate.unit.lower() not in ("ratio", "%", ""):
            raise ValueError(
                f"Gate node '{gate.id}' must have unit 'ratio', not '{gate.unit}'"
            )
        new_nodes = dict(self.nodes)
        new_nodes[gate.id] = gate
        t = new_nodes[target_id]
        new_nodes[target_id] = replace(t, gates=t.gates + (gate.id,))
        return MarketModel(
            id=_new_id(),
            report_id=self.report_id,
            version=self.version + 1,
            parent_version=self.version,
            nodes=new_nodes,
            created_at=_utcnow(),
            created_by="user",
            change_note=f"gate '{gate.id}' on '{target_id}'",
        )

    def without_gate(self, gate_id: str) -> "MarketModel":
        """Return a new model with gate_id removed from every target."""
        new_nodes = dict(self.nodes)
        for nid, n in self.nodes.items():
            if gate_id in n.gates:
                new_nodes[nid] = replace(n, gates=tuple(g for g in n.gates if g != gate_id))
        if gate_id in new_nodes:
            del new_nodes[gate_id]
        return replace(
            self,
            id=_new_id(),
            version=self.version + 1,
            parent_version=self.version,
            nodes=new_nodes,
            created_at=_utcnow(),
            created_by="user",
            change_note=f"removed gate '{gate_id}'",
        )

    def reset_node(self, node_id: str) -> "MarketModel":
        """Return a new model with node_id's override cleared."""
        n = self.nodes[node_id]
        new_nodes = dict(self.nodes)
        new_nodes[node_id] = replace(n, override_value=None, override_rationale=None,
                                     method="assumed")
        return replace(
            self,
            id=_new_id(),
            version=self.version + 1,
            parent_version=self.version,
            nodes=new_nodes,
            created_at=_utcnow(),
            created_by="user",
            change_note=f"reset '{node_id}' to engine default",
        )

    # ── serialisation ─────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "report_id": self.report_id,
            "version": self.version,
            "parent_version": self.parent_version,
            "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
            "created_at": self.created_at,
            "created_by": self.created_by,
            "change_note": self.change_note,
            "model_hash": self.model_hash(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "MarketModel":
        from app.model.nodes import Node
        nodes = {nid: Node.from_dict(nd) for nid, nd in d["nodes"].items()}
        return cls(
            id=d["id"],
            report_id=d["report_id"],
            version=d["version"],
            parent_version=d.get("parent_version"),
            nodes=nodes,
            created_at=d["created_at"],
            created_by=d.get("created_by", "engine"),
            change_note=d.get("change_note", ""),
        )

    # ── diff helper ───────────────────────────────────────────────────────────

    def diff(self, other: "MarketModel") -> dict[str, dict]:
        """Return {node_id: {from, to, pct}} for nodes whose value changed."""
        old_v = self.values()
        new_v = other.values()
        result: dict[str, dict] = {}
        for nid in old_v:
            ov, nv = old_v[nid], new_v.get(nid, old_v[nid])
            if abs(ov - nv) > 1e-9:
                denom = abs(ov) if abs(ov) > 1e-9 else 1.0
                result[nid] = {
                    "from": ov,
                    "to": nv,
                    "pct": round((nv - ov) / denom * 100, 1),
                }
        return result


def _fmt_usd(v: float) -> str:
    if v >= 1e9:  return f"${v / 1e9:.1f}B"
    if v >= 1e6:  return f"${v / 1e6:.1f}M"
    if v >= 1e3:  return f"${v / 1e3:,.0f}K"
    return f"${v:,.0f}"
