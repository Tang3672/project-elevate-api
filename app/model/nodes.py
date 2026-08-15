"""Node — the atomic unit of the market model.

Every number in a report is a node. Nodes either hold a raw_value or a formula
that references other nodes by id. Exactly one must be set.

The ``gates`` tuple holds ids of ratio nodes that multiply the resolved value.
This lets users add filters (e.g. "only labs with IACUC vivarium, ×0.6") without
touching the formula itself — the gate is additive and reversible.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

NodeMethod = Literal[
    "retrieved",      # from an executed API call; source required
    "derived",        # computed from other nodes via formula
    "modeled",        # estimated from a documented prior
    "assumed",        # no source; must surface in sensitivity
    "user_override",  # set by the user
    "user_gate",      # a filter the user added
]


@dataclass(frozen=True)
class Citation:
    publisher: str
    url: str
    retrieved_at: str
    locator: Optional[str] = None


@dataclass(frozen=True)
class Node:
    # identity
    id: str
    label: str
    unit: str                           # "labs", "USD/lab/yr", "USD", "ratio"

    # value: exactly one of raw_value or formula must be set
    raw_value: Optional[float] = None
    formula: Optional[str] = None       # e.g. "buyer_population * spend_per_unit"

    # multiplicative filters applied after the base value
    gates: tuple[str, ...] = ()         # each referenced node must resolve to (0, 1]

    # user intervention — short-circuits raw_value / formula
    override_value: Optional[float] = None
    override_rationale: Optional[str] = None

    # provenance
    method: NodeMethod = "assumed"
    source: Optional[Citation] = None
    confidence: float = 0.35
    rationale: str = ""

    # uncertainty bounds for Monte Carlo and sensitivity
    low: Optional[float] = None
    high: Optional[float] = None

    # UI affordances
    editable: bool = True
    ui_min: Optional[float] = None
    ui_max: Optional[float] = None
    ui_step: Optional[float] = None
    ui_control: Literal["number", "slider", "none"] = "number"

    def __post_init__(self) -> None:
        if (self.raw_value is None) == (self.formula is None):
            raise ValueError(
                f"Node '{self.id}': exactly one of raw_value or formula must be set "
                f"(got raw_value={self.raw_value!r}, formula={self.formula!r})"
            )
        if self.method == "retrieved" and self.source is None:
            raise ValueError(f"Node '{self.id}': method='retrieved' requires a source")

    def to_dict(self) -> dict:
        """Serialise to a plain dict for JSONB storage."""
        d: dict = {
            "id": self.id,
            "label": self.label,
            "unit": self.unit,
            "method": self.method,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "editable": self.editable,
            "gates": list(self.gates),
        }
        if self.raw_value is not None:
            d["raw_value"] = self.raw_value
        if self.formula is not None:
            d["formula"] = self.formula
        if self.override_value is not None:
            d["override_value"] = self.override_value
        if self.override_rationale is not None:
            d["override_rationale"] = self.override_rationale
        if self.source is not None:
            d["source"] = {
                "publisher": self.source.publisher,
                "url": self.source.url,
                "retrieved_at": self.source.retrieved_at,
                "locator": self.source.locator,
            }
        for k in ("low", "high", "ui_min", "ui_max", "ui_step"):
            v = getattr(self, k)
            if v is not None:
                d[k] = v
        d["ui_control"] = self.ui_control
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Node":
        source = None
        if d.get("source"):
            s = d["source"]
            source = Citation(
                publisher=s.get("publisher", ""),
                url=s.get("url", ""),
                retrieved_at=s.get("retrieved_at", ""),
                locator=s.get("locator"),
            )
        return cls(
            id=d["id"],
            label=d["label"],
            unit=d["unit"],
            raw_value=d.get("raw_value"),
            formula=d.get("formula"),
            gates=tuple(d.get("gates", [])),
            override_value=d.get("override_value"),
            override_rationale=d.get("override_rationale"),
            method=d.get("method", "assumed"),
            source=source,
            confidence=d.get("confidence", 0.35),
            rationale=d.get("rationale", ""),
            low=d.get("low"),
            high=d.get("high"),
            editable=d.get("editable", True),
            ui_min=d.get("ui_min"),
            ui_max=d.get("ui_max"),
            ui_step=d.get("ui_step"),
            ui_control=d.get("ui_control", "number"),
        )
