"""
Market Sizing Provenance Service  (Brief Priority 1)
====================================================
The market-sizing *math* already lives in `market_sizing_derivation_service`
(a per-archetype bottom-up engine that emits richly-sourced `DerivationStep`s).
What was missing is the brief's requirement: every input stored as a
**structured, typed, source-backed assumption object**, plus an explicit
conservative / base / aggressive **scenario** set, plus a **waterfall** the UI
can render with every number clickable back to its source.

This module is a *pure transform* over a `MarketSizingDerivation`:

    derivation (engine output)  ->  {
        "run":          {...},          # headline TAM/SAM/SOM + meta
        "assumptions":  [assumption],   # one per derivation step, typed
        "scenarios":    [scenario],     # conservative | base | aggressive
        "sources":      [source],       # deduped, citable
        "waterfall":    [row],          # ordered, render-ready
    }

It does no I/O, so it is deterministic and unit-testable. Persistence lives in
`app.db.market_sizing_repository`.

Assumption object schema (matches the brief exactly):
    {
      "assumption_type": "prevalence | diagnosis_rate | treatment_rate | price | penetration | geography | other",
      "value": 12345,
      "unit": "patients | USD | percent | ...",
      "source_name": "CDC | SEER | CMS | PubMed | openFDA | ...",
      "source_url": "...",
      "confidence": 0.0-1.0,
      "used_in_formula": "TAM | SAM | SOM",
      "retrieved_at": "ISO-8601",
      ...auditing extras (label, formula, explanation)
    }
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ── Scenario adoption multipliers ──────────────────────────────────────────────
# TAM (eligible pool x annual price) is a ceiling and does NOT change across
# scenarios — only the reachable share (SAM) and realistic initial penetration
# (SOM) vary with adoption assumptions. That is the economically-correct way to
# express conservative/aggressive without inventing different epidemiology.

# Clinical/therapeutic scenario narratives
SCENARIOS = {
    "conservative": {"sam_mult": 0.70, "som_mult": 0.50,
                     "narrative": "Slow clinical adoption, strong incumbent defense, "
                                  "narrow initial approved indication."},
    "base":         {"sam_mult": 1.00, "som_mult": 1.00,
                     "narrative": "Adoption in line with comparable product launches "
                                  "in this indication."},
    "aggressive":   {"sam_mult": 1.30, "som_mult": 1.60,
                     "narrative": "Fast guideline uptake, favorable payer coverage, "
                                  "limited direct competition."},
}

# Research-tool scenario narratives — no payer/label/guideline vocabulary
SCENARIOS_RESEARCH = {
    "conservative": {"sam_mult": 0.70, "som_mult": 0.50,
                     "narrative": "Slow lab adoption, strong status-quo (DIY/manual) "
                                  "inertia, narrow initial user base."},
    "base":         {"sam_mult": 1.00, "som_mult": 1.00,
                     "narrative": "Adoption in line with comparable research tool "
                                  "launches (methods paper + core-facility beachhead)."},
    "aggressive":   {"sam_mult": 1.30, "som_mult": 1.60,
                     "narrative": "Fast conference buzz and citation adoption, "
                                  "favorable NIH funding climate, few competing solutions."},
}

# Recognized authoritative source roots -> higher confidence floor.
_AUTHORITATIVE = (
    "cdc.gov", "fda.gov", "cms.gov", "seer.cancer.gov", "ncbi.nlm.nih.gov",
    "nih.gov", "who.int", "ema.europa.eu", "nice.org.uk", "census.gov",
    "ahrq.gov", "hrsa.gov", "clinicaltrials.gov",
)


# ── Assumption typing ──────────────────────────────────────────────────────────

def _classify_assumption_type(title: str, unit: str, formula: str) -> str:
    """Map a derivation step to the brief's assumption_type enum."""
    t = f"{title} {formula}".lower()
    u = (unit or "").lower()

    if u == "usd" or "price" in t or "wac" in t or "cost per" in t or "reimbursement" in t:
        # A price line, unless it's a market-total dollar figure (handled by caller).
        if "price" in t or "wac" in t or "cost per" in t or "asp" in t or "reimbursement" in t:
            return "price"
    if "diagnos" in t:
        return "diagnosis_rate"
    if "treat" in t or "eligib" in t or "line of therapy" in t or "on-therapy" in t or "addressable patients" in t:
        return "treatment_rate"
    if "penetrat" in t or "adoption" in t or "uptake" in t or "share" in t or "capture" in t:
        return "penetration"
    if "prevalen" in t or "inciden" in t or "population" in t or "patients" in u or "cases" in t:
        return "prevalence"
    if "geograph" in t or "region" in t or "u.s." in t or "country" in t or "states" in t:
        return "geography"
    return "other"


def _classify_formula_role(title: str, atype: str) -> str:
    """Which aggregate (TAM/SAM/SOM) the assumption contributes to."""
    t = title.lower()
    if "som" in t or "initial" in t or "year 1" in t or "first-year" in t or "launch year" in t:
        return "SOM"
    if "sam" in t or "serviceable" in t or "reachable" in t or "approved segment" in t:
        return "SAM"
    if atype == "penetration":
        # First-year/initial penetration -> SOM; steady-state reachable share -> SAM.
        return "SOM" if ("initial" in t or "year 1" in t or "launch" in t) else "SAM"
    # Population/diagnosis/treatment/price all build the addressable ceiling.
    return "TAM"


def _confidence_for(source_url: str, data_source: str, assumptions: list[str]) -> float:
    """
    Heuristic confidence: authoritative sourced data is trusted most; modeled or
    assumed values least. Deterministic so the score is reproducible.
    """
    url = (source_url or "").lower()
    ds = (data_source or "").lower()
    modeled = any(k in ds for k in ("assumption", "model", "estimate", "derived", "proxy")) \
        or len(assumptions or []) >= 2

    if any(root in url for root in _AUTHORITATIVE):
        base = 0.90
    elif url.startswith("http"):
        base = 0.75
    else:
        base = 0.55
    if modeled:
        base -= 0.20
    return round(max(0.30, min(0.95, base)), 2)


def _fmt_usd(v: float) -> str:
    if v >= 1e9:  return f"${v/1e9:.1f}B"
    if v >= 1e6:  return f"${v/1e6:.0f}M"
    if v >= 1e4:  return f"${v/1e3:.0f}K"
    return f"${v:,.0f}"


# ── Main transform ─────────────────────────────────────────────────────────────

def build_provenance(deriv, *, geography: str = "United States") -> dict:
    """
    Turn a MarketSizingDerivation into the structured provenance bundle.
    `deriv` is duck-typed (MarketSizingDerivation) so this stays import-light.
    """
    retrieved_at = datetime.utcnow().isoformat()

    assumptions: list[dict] = []
    waterfall: list[dict] = []
    sources_seen: dict[tuple, dict] = {}

    for step in getattr(deriv, "steps", []) or []:
        title = getattr(step, "title", "") or ""
        unit = getattr(step, "unit", "") or ""
        formula = getattr(step, "formula", "") or ""
        value = getattr(step, "value", None)
        src_name = getattr(step, "data_source", "") or getattr(step, "source_paper", "") or "Derivation model"
        src_url = getattr(step, "source_url", "") or ""
        step_assumptions = getattr(step, "assumptions", []) or []

        atype = _classify_assumption_type(title, unit, formula)
        role = _classify_formula_role(title, atype)
        confidence = _confidence_for(src_url, getattr(step, "data_source", ""), step_assumptions)

        assumption = {
            "assumption_type": atype,
            "value": value,
            "unit": unit or "ratio",
            "source_name": src_name,
            "source_url": src_url or None,
            "confidence": confidence,
            "used_in_formula": role,
            "retrieved_at": retrieved_at,
            # auditing extras (not in the minimal schema, useful for the UI)
            "label": title,
            "formula": formula,
            "explanation": getattr(step, "explanation", "") or "",
        }
        assumptions.append(assumption)

        waterfall.append({
            "step": getattr(step, "step_num", len(waterfall) + 1),
            "label": title,
            "value": value,
            "unit": unit,
            "source_name": src_name,
            "source_url": src_url or None,
            "confidence": confidence,
            "used_in_formula": role,
        })

        if src_name:
            key = (src_name.lower(), (src_url or "").lower())
            if key not in sources_seen:
                sources_seen[key] = {
                    "source_name": src_name,
                    "source_url": src_url or None,
                    "citation": title,
                }

    # Fold in any primary citations the engine declared.
    for cit in getattr(deriv, "primary_citations", []) or []:
        name = cit.get("source") or cit.get("name") or cit.get("title") or "Citation"
        url = cit.get("url") or cit.get("source_url") or ""
        key = (name.lower(), url.lower())
        if key not in sources_seen:
            sources_seen[key] = {"source_name": name, "source_url": url or None,
                                 "citation": cit.get("title", "")}

    tam = float(getattr(deriv, "us_tam_usd", 0) or 0)
    sam = float(getattr(deriv, "us_sam_usd", 0) or 0)
    som = float(getattr(deriv, "us_som_usd", 0) or 0)

    archetype = getattr(deriv, "archetype", "") or ""
    scenarios = build_scenarios(tam, sam, som, archetype=archetype)

    # Append the three aggregate roll-up rows to the waterfall for the UI.
    for label, val, role in (("Total Addressable Market (TAM)", tam, "TAM"),
                             ("Serviceable Available Market (SAM)", sam, "SAM"),
                             ("Serviceable Obtainable Market (SOM)", som, "SOM")):
        waterfall.append({
            "step": len(waterfall) + 1,
            "label": label,
            "value": val,
            "unit": "USD",
            "source_name": "Bottom-up derivation",
            "source_url": None,
            "confidence": None,
            "used_in_formula": role,
            "is_aggregate": True,
        })

    return {
        "run": {
            "idea": getattr(deriv, "idea", ""),
            "archetype": getattr(deriv, "archetype", ""),
            "archetype_label": getattr(deriv, "archetype_label", ""),
            "formula_name": getattr(deriv, "formula_name", ""),
            "formula_overview": getattr(deriv, "formula_overview", ""),
            "geography": geography,
            "tam_usd": tam,
            "sam_usd": sam,
            "som_usd": som,
            "tam_fmt": getattr(deriv, "tam_fmt", _fmt_usd(tam)),
            "sam_fmt": getattr(deriv, "sam_fmt", _fmt_usd(sam)),
            "som_fmt": getattr(deriv, "som_fmt", _fmt_usd(som)),
            "confidence_note": getattr(deriv, "confidence_note", ""),
            "key_assumptions": getattr(deriv, "key_assumptions", []) or [],
            "assumption_count": len(assumptions),
            "retrieved_at": retrieved_at,
        },
        "assumptions": assumptions,
        "scenarios": scenarios,
        "sources": list(sources_seen.values()),
        "waterfall": waterfall,
    }


def build_scenarios(tam: float, sam: float, som: float, *, archetype: str = "") -> list[dict]:
    """Conservative / base / aggressive, clamped so SOM <= SAM <= TAM."""
    _is_research = archetype.startswith(("research_tool", "research_infrastructure"))
    scenario_set = SCENARIOS_RESEARCH if _is_research else SCENARIOS
    out: list[dict] = []
    for name, cfg in scenario_set.items():
        s_sam = min(sam * cfg["sam_mult"], tam)
        s_som = min(som * cfg["som_mult"], s_sam)
        out.append({
            "scenario": name,
            "tam_usd": round(tam),
            "sam_usd": round(s_sam),
            "som_usd": round(s_som),
            "tam_fmt": _fmt_usd(tam),
            "sam_fmt": _fmt_usd(s_sam),
            "som_fmt": _fmt_usd(s_som),
            "sam_multiplier": cfg["sam_mult"],
            "som_multiplier": cfg["som_mult"],
            "narrative": cfg["narrative"],
        })
    return out
