"""extract_model — adapter from existing report JSON to MarketModel.

Phase 1 of the migration spec: wrap, don't rewrite. The generator already
produces the five step values; this function extracts them into a proper
node graph without touching the generator itself.

The extraction is deterministic: for the same report JSON, it always produces
the same model. The __post_init__ assertion on MarketModel will raise if the
existing TAM/SAM are inconsistent — surfacing the dual-writer bug cleanly.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from app.model.market_model import MarketModel, _new_id, _utcnow
from app.model.nodes import Node


def extract_model(report_json: dict, report_id: str) -> MarketModel:
    """Build a v1 MarketModel from the generator's market section.

    Reads from report_json["market_sizing_derivation"]["nodes"] if present
    (research-tool buyer model), falling back to the legacy step table.
    """
    derivation = report_json.get("market_sizing_derivation") or {}
    flat = derivation.get("nodes") if isinstance(derivation, dict) else None

    if flat and isinstance(flat, dict) and "pop_lo" in flat:
        return extract_model_from_flat(flat, report_id, version=1)

    # Fallback: extract from market_sizing step table
    mkt = report_json.get("market_sizing") or {}
    steps = mkt.get("steps") or []
    tam_usd = float(mkt.get("total_addressable_market_usd") or 0)
    sam_usd = float(mkt.get("serviceable_market_usd") or 0)

    pop_val   = float(steps[0]["value"]) if len(steps) > 0 and steps[0].get("value") else 1.0
    spend_val = float(steps[1]["value"]) if len(steps) > 1 and steps[1].get("value") else 1.0
    sam_rate  = (sam_usd / tam_usd) if tam_usd > 0 else 0.40
    som_usd   = float(report_json.get("commercialization_scores", {}).get("som_usd") or 0)
    som_rate  = (som_usd / sam_usd) if sam_usd > 0 else 0.165

    nodes = _standard_nodes(pop_val, spend_val, sam_rate, som_rate)
    return MarketModel(
        id=_new_id(),
        report_id=report_id,
        version=1,
        parent_version=None,
        nodes=nodes,
        created_at=_utcnow(),
        created_by="engine",
        change_note="Extracted from generator output (step table)",
    )


def extract_model_from_flat(flat: dict, report_id: str, version: int = 1) -> MarketModel:
    """Build a MarketModel from the existing flat lo/hi dict (legacy storage).

    Used both for reading old rows from the DB and for the fallback in the
    generator pipeline before full node-graph generation is live.
    """
    pop_lo  = float(flat.get("pop_lo",  3_000))
    pop_hi  = float(flat.get("pop_hi",  8_000))
    sp_lo   = float(flat.get("sp_lo",   1_000))
    sp_hi   = float(flat.get("sp_hi",   5_000))
    sam_lo  = float(flat.get("sam_lo",  0.35))
    sam_hi  = float(flat.get("sam_hi",  0.65))
    som_lo  = float(flat.get("som_lo",  0.08))
    som_hi  = float(flat.get("som_hi",  0.25))

    pop_mid  = (pop_lo + pop_hi)   / 2
    sp_mid   = (sp_lo  + sp_hi)    / 2
    sam_rate = (sam_lo + sam_hi)   / 2
    som_rate = (som_lo + som_hi)   / 2

    nodes = _standard_nodes(pop_mid, sp_mid, sam_rate, som_rate,
                             pop_low=pop_lo, pop_high=pop_hi,
                             sp_low=sp_lo,   sp_high=sp_hi,
                             sam_low=sam_lo, sam_high=sam_hi,
                             som_low=som_lo, som_high=som_hi)

    return MarketModel(
        id=flat.get("model_id") or _new_id(),
        report_id=report_id,
        version=version,
        parent_version=None,
        nodes=nodes,
        created_at=flat.get("created_at") or _utcnow(),
        created_by=flat.get("created_by") or "engine",
        change_note=flat.get("change_note") or "Converted from legacy flat store",
    )


def _standard_nodes(
    pop: float,
    spend: float,
    sam_rate: float,
    som_rate: float,
    pop_low: Optional[float] = None,
    pop_high: Optional[float] = None,
    sp_low: Optional[float] = None,
    sp_high: Optional[float] = None,
    sam_low: Optional[float] = None,
    sam_high: Optional[float] = None,
    som_low: Optional[float] = None,
    som_high: Optional[float] = None,
) -> dict[str, Node]:
    """Build the standard 7-node buyer model: 4 editable inputs + 3 derived outputs."""
    return {
        "buyer_population": Node(
            id="buyer_population",
            label="Eligible buyer population",
            unit="labs",
            raw_value=pop,
            method="assumed",
            confidence=0.70,
            low=pop_low,
            high=pop_high,
            ui_control="slider",
            ui_min=100,
            ui_max=200_000,
            ui_step=100,
            rationale="Derived from NIH/NSF/USDA award data or PI intake estimate.",
        ),
        "spend_per_unit": Node(
            id="spend_per_unit",
            label="Annualised spend per lab",
            unit="USD/lab/yr",
            raw_value=spend,
            method="assumed",
            confidence=0.35,
            low=sp_low,
            high=sp_high,
            ui_control="number",
            ui_min=0,
            ui_max=500_000,
            ui_step=50,
            rationale="PI intake band or comparable product benchmark.",
        ),
        "tam": Node(
            id="tam",
            label="Total Addressable Market",
            unit="USD",
            formula="buyer_population * spend_per_unit",
            method="derived",
            editable=False,
            ui_control="none",
        ),
        "sam_rate": Node(
            id="sam_rate",
            label="Reachable penetration rate",
            unit="ratio",
            raw_value=max(0.0, min(1.0, sam_rate)),
            method="assumed",
            confidence=0.40,
            low=sam_low,
            high=sam_high,
            ui_control="slider",
            ui_min=0.0,
            ui_max=1.0,
            ui_step=0.01,
            rationale="Fraction of TAM reachable given channel, geography, and budget cycle.",
        ),
        "sam": Node(
            id="sam",
            label="Serviceable Addressable Market",
            unit="USD",
            formula="tam * sam_rate",
            method="derived",
            editable=False,
            ui_control="none",
        ),
        "som_rate": Node(
            id="som_rate",
            label="5-year penetration rate",
            unit="ratio",
            raw_value=max(0.0, min(1.0, som_rate)),
            method="assumed",
            confidence=0.30,
            low=som_low,
            high=som_high,
            ui_control="slider",
            ui_min=0.0,
            ui_max=1.0,
            ui_step=0.005,
            rationale="Conservative 5-yr capture rate given competitive alternatives.",
        ),
        "som": Node(
            id="som",
            label="Serviceable Obtainable Market (5-yr)",
            unit="USD",
            formula="sam * som_rate",
            method="derived",
            editable=False,
            ui_control="none",
        ),
    }
