"""
Market template shared types — Spec v3 Addendum Rules 4+7.

Axis, Gate, PriceTier, FunnelSpec are the four types both market templates
(life_sciences_research, engineering_hardware) compile against.  They carry
no numeric constants — values default to 0.0 in templates and are injected
from priors/ at runtime via FunnelSpec.apply_priors().
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class Axis:
    """A population-count node in a segmentation funnel.

    Templates declare axes with value=0.0; the priors/ module injects real numbers.
    """
    id:         str
    label:      str
    unit:       str       # "labs" | "sites" | "patients"
    value:      float = 0.0
    low:        float = 0.0
    high:       float = 0.0
    confidence: float = 0.5
    source:     str   = ""
    method: Literal["retrieved", "derived", "modeled", "assumed"] = "assumed"


@dataclass
class Gate:
    """A funnel multiplier applied from one Axis to the next.

    Templates declare gates with fraction=0.0; the priors/ module injects values.
    """
    id:         str
    label:      str
    fraction:   float = 0.0
    low:        float = 0.0
    high:       float = 0.0
    confidence: float = 0.5
    rationale:  str   = ""


@dataclass
class PriceTier:
    """A price segment for addressable-market leaf nodes.

    Templates declare tiers with annual_usd=0.0 and mix=0.0; priors/ injects values.
    """
    id:         str
    label:      str
    annual_usd: float = 0.0
    mix:        float = 0.0   # fraction of addressable market; tiers must sum to 1.0


@dataclass
class FunnelSpec:
    """Complete market-segmentation funnel template.

    funnel_chain: ordered list of Axis IDs (root → addressable leaf),
                  describing the tree topology.

    clinical_vocabulary_required: terms that MUST appear for this domain (e.g. "wac price" for pharma).
    clinical_vocabulary_forbidden: terms that must NOT appear for this domain.
    """
    id:                           str
    label:                        str
    segment_domain:               str           # "LIFE_SCIENCES_RESEARCH" | "ENGINEERING_HARDWARE"
    axes:                         list[Axis]
    gates:                        list[Gate]
    price_tiers:                  list[PriceTier]
    funnel_chain:                 list[str]     # ordered axis IDs root → leaf
    clinical_vocabulary_required: list[str] = field(default_factory=list)
    clinical_vocabulary_forbidden: list[str] = field(default_factory=list)

    def axis(self, axis_id: str) -> Axis:
        for a in self.axes:
            if a.id == axis_id:
                return a
        raise KeyError(f"Axis '{axis_id}' not in FunnelSpec '{self.id}'")

    def gate(self, gate_id: str) -> Gate:
        for g in self.gates:
            if g.id == gate_id:
                return g
        raise KeyError(f"Gate '{gate_id}' not in FunnelSpec '{self.id}'")

    def price_tier(self, tier_id: str) -> PriceTier:
        for t in self.price_tiers:
            if t.id == tier_id:
                return t
        raise KeyError(f"PriceTier '{tier_id}' not in FunnelSpec '{self.id}'")

    def apply_priors(self, priors: dict) -> "FunnelSpec":
        """Return a new FunnelSpec with numeric values filled from priors dict.

        priors structure:
          {
            "axes":        {axis_id: {"value", "low", "high", "confidence", "source", "method"}},
            "gates":       {gate_id: {"fraction", "low", "high", "confidence", "rationale"}},
            "price_tiers": {tier_id: {"annual_usd", "mix"}},
          }
        """
        spec = copy.deepcopy(self)
        for ax in spec.axes:
            p = priors.get("axes", {}).get(ax.id)
            if p:
                ax.value      = float(p.get("value",      0.0))
                ax.low        = float(p.get("low",        0.0))
                ax.high       = float(p.get("high",       0.0))
                ax.confidence = float(p.get("confidence", 0.5))
                ax.source     = str(p.get("source",       ""))
                ax.method     = p.get("method",           "assumed")
        for g in spec.gates:
            p = priors.get("gates", {}).get(g.id)
            if p:
                g.fraction   = float(p.get("fraction",   0.0))
                g.low        = float(p.get("low",        0.0))
                g.high       = float(p.get("high",       0.0))
                g.confidence = float(p.get("confidence", 0.5))
                g.rationale  = str(p.get("rationale",    ""))
        for t in spec.price_tiers:
            p = priors.get("price_tiers", {}).get(t.id)
            if p:
                t.annual_usd = float(p.get("annual_usd", 0.0))
                t.mix        = float(p.get("mix",        0.0))
        return spec
