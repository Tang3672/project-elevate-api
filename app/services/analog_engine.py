"""
Analog Engine  (Build Spec v5, Part C — Engine 3)
==================================================
Infers market penetration and SOM from real-world launch analogs.

The moat here is calibrated benchmarks, not the algorithm. Analogs come from
adoption_benchmarks.json (public launch histories), not LLM guesses.

infer_analog(product_type, competitive_context)
  → AnalogResult with y1/y3/peak penetration + calibrated SOM + source citations
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Tuple

logger = logging.getLogger(__name__)

_BENCHMARKS_PATH = Path(__file__).parent.parent / "data" / "adoption_benchmarks.json"
_benchmarks_cache: Optional[List[dict]] = None


def _load_benchmarks() -> List[dict]:
    global _benchmarks_cache
    if _benchmarks_cache is None:
        try:
            _benchmarks_cache = json.loads(_BENCHMARKS_PATH.read_text())
        except Exception as e:
            logger.error("Failed to load adoption_benchmarks.json: %s", e)
            _benchmarks_cache = []
    return _benchmarks_cache


@dataclass
class AnalogResult:
    analog_class: str
    analog_label: str
    competitive_context: str
    y1_penetration: float          # share of addressable market in year 1
    y3_penetration: float
    peak_penetration: float
    years_to_peak: int
    som_fraction: float            # = y1_penetration (conservative SOM = yr-1 capture)
    som_conservative: float        # revenue × y1
    som_base: float                # revenue × y3
    som_peak: float                # revenue × peak
    source: str
    confidence: str
    note: str
    is_site_metric: bool           # True for hospital_software (penetration = fraction of sites)
    assumptions: List[dict]

    # v6 — HHI-based competitive adjustment (optional; None when HHI not available)
    hhi_score: Optional[int] = field(default=None)
    hhi_penetration_factor: Optional[float] = field(default=None)

    def to_dict(self) -> dict:
        return {
            "analog_class": self.analog_class,
            "analog_label": self.analog_label,
            "competitive_context": self.competitive_context,
            "y1_penetration": self.y1_penetration,
            "y3_penetration": self.y3_penetration,
            "peak_penetration": self.peak_penetration,
            "years_to_peak": self.years_to_peak,
            "som_fraction": self.som_fraction,
            "som_conservative": self.som_conservative,
            "som_base": self.som_base,
            "som_peak": self.som_peak,
            "source": self.source,
            "confidence": self.confidence,
            "note": self.note,
            "is_site_metric": self.is_site_metric,
            "assumptions": self.assumptions,
            "hhi_score": self.hhi_score,
            "hhi_penetration_factor": self.hhi_penetration_factor,
        }


# ─── Context inference ────────────────────────────────────────────────────────

_COMPETITIVE_CONTEXT_KEYWORDS = {
    # orphan checked BEFORE new_moa — "orphan" keyword must not match new_moa
    "orphan":  ["orphan", "rare disease", "ultra-rare", "< 200,000", "200000"],
    "new_moa": ["novel", "first-in-class", "new mechanism", "no approved", "breakthrough",
                "unmet need", "first moa"],
    "me_too":  ["me-too", "crowded", "competitor", "similar", "nth", "follow-on",
                "generic", "biosimilar"],
    "hospital_software": ["samd", "software", "digital", "ai platform", "enterprise",
                          "ehr", "epic", "site license"],
    "interventional_device": ["device", "implant", "catheter", "stent", "ablation",
                               "interventional", "surgical"],
    "companion_diagnostic": ["companion", "cdx", "biomarker test", "companion diagnostic",
                              "genomic", "molecular"],
    "antimicrobial": ["antibiotic", "antimicrobial", "amr", "resistant infection",
                      "gram-negative", "carbapenem"],
}


def _infer_competitive_context(product_type: str, context_text: str = "") -> str:
    """Best-effort infer the competitive context from product type + free text."""
    combined = (product_type + " " + context_text).lower()
    for ctx, keywords in _COMPETITIVE_CONTEXT_KEYWORDS.items():
        if any(k in combined for k in keywords):
            return ctx
    # Fallback by product_type family
    if any(t in product_type.lower() for t in ("samd", "software", "digital")):
        return "hospital_software"
    if any(t in product_type.lower() for t in ("device", "implant")):
        return "interventional_device"
    if "diagnostic" in product_type.lower():
        return "companion_diagnostic"
    return "new_moa"   # default: assume novel (conservative on penetration)


def _select_benchmark(product_type: str, competitive_context: str) -> Optional[dict]:
    benchmarks = _load_benchmarks()
    pt_lower = product_type.lower()

    # Exact context match
    for b in benchmarks:
        if b.get("competitive_context") == competitive_context:
            applies = [a.lower() for a in b.get("applies_to", [])]
            if pt_lower in applies or any(a in pt_lower for a in applies):
                return b

    # Context match without product-type filter
    for b in benchmarks:
        if b.get("competitive_context") == competitive_context:
            return b

    # Fallback: product type match, any context
    for b in benchmarks:
        applies = [a.lower() for a in b.get("applies_to", [])]
        if pt_lower in applies or any(a in pt_lower for a in applies):
            return b

    # Last resort: specialty_drug_new_moa
    return next((b for b in benchmarks if b.get("id") == "specialty_drug_new_moa"), None)


def _hhi_penetration_factor(hhi: Optional[int]) -> Tuple[float, str]:
    """
    Map a market HHI score to a multiplicative adjustment on analog penetration rates.

    Rationale
    ---------
    Analog benchmarks represent the *average* launch trajectory across all competitive
    contexts. An HHI score reveals whether this specific sub-market is more or less
    concentrated than the average analog — and concentrated markets systematically
    produce lower new-entrant penetration.

    Adjustment tiers (multiplicative, applied to y1/y3/peak):
      HHI < 1000  (fragmented)        → ×1.15  upside: no dominant incumbent
      HHI 1000–1500 (competitive)     → ×1.05  slight upside vs avg analog
      HHI 1500–2500 (moderate)        → ×0.90  mild headwind; differentiation needed
      HHI 2500–3500 (concentrated)    → ×0.78  strong headwind; dominant player present
      HHI > 3500   (highly conc.)     → ×0.65  near-monopoly; clear superiority required
      HHI = None   (no data)          → ×1.00  no adjustment

    Source
    ------
    DOJ/FTC Horizontal Merger Guidelines (2023) for concentration thresholds.
    Grabowski & Vernon (J. Law & Econ. 1992): late entrants capture 40–60% of
    pioneer share in concentrated pharmaceutical sub-markets.
    Mehta et al. (PLOS ONE 2016): 69% of pharma sub-markets by value show at
    least moderate HHI concentration; HHI correlates with new-entrant share erosion.
    """
    if hhi is None:
        return 1.0, "No HHI data available — no penetration adjustment applied."
    if hhi < 1000:
        factor = 1.15
        label = f"fragmented (HHI={hhi}<1000)"
        note = ("Fragmented market — no dominant incumbent. "
                "New entrant can capture above-average share vs analog benchmark. ×1.15.")
    elif hhi < 1500:
        factor = 1.05
        label = f"competitive (HHI={hhi} 1000–1500)"
        note = ("Competitive market — limited concentration. "
                "Slight upside vs average analog penetration. ×1.05.")
    elif hhi < 2500:
        factor = 0.90
        label = f"moderately concentrated (HHI={hhi} 1500–2500)"
        note = ("Moderately concentrated — incumbent has structural advantage. "
                "Differentiation required. Penetration adjusted ×0.90 vs analog. "
                "[DOJ/FTC: moderate concentration; Grabowski & Vernon 1992]")
    elif hhi < 3500:
        factor = 0.78
        label = f"concentrated (HHI={hhi} 2500–3500)"
        note = ("Concentrated market — dominant player controls majority of share. "
                "New entrant needs clear superiority to take meaningful penetration. "
                "Penetration adjusted ×0.78. [DOJ/FTC: highly concentrated; "
                "Mehta et al. PLOS ONE 2016]")
    else:
        factor = 0.65
        label = f"highly concentrated (HHI={hhi}>3500)"
        note = ("Near-monopoly or duopoly — extreme concentration. "
                "Very steep headwind for any new entrant without order-of-magnitude "
                "clinical superiority. Penetration adjusted ×0.65. "
                "[Grabowski & Vernon 1992: late entrant captures ~40-60% of pioneer share]")

    return factor, note


def compute(
    product_type: str,
    annual_revenue_sam: float,       # SAM revenue (full addressable before penetration)
    competitive_context: Optional[str] = None,
    context_text: str = "",          # free-text from product description (for inference)
    overrides: Optional[Dict] = None,
    hhi_score: Optional[int] = None, # market HHI from market_calibration_service
) -> AnalogResult:
    """
    Apply analog-based penetration to annual_revenue_sam to produce SOM scenarios.

    annual_revenue_sam: the monetization_engine output (SAM-level revenue, pre-penetration).
    competitive_context: optional explicit override; else inferred from product_type+context_text.
    """
    overrides = overrides or {}
    ctx = competitive_context or _infer_competitive_context(product_type, context_text)
    benchmark = _select_benchmark(product_type, ctx)

    assumptions: List[dict] = []
    is_site = False

    if benchmark is None:
        # No benchmark found: use conservative defaults
        y1, y3, peak, years_to_peak = 0.03, 0.08, 0.15, 5
        source = "analyst_estimate"
        confidence = "low"
        note = "No analog found; using conservative defaults. Verify with comps."
        label = "Default (no analog)"
        analog_class = "default"
        assumptions.append({
            "field": "analog_class", "value": "none found",
            "source_type": "analyst_estimate", "confidence": "low",
            "expert_question": "What launched products are best analogs for this product's commercial ramp? Y1/peak market share?",
        })
    else:
        analog_class = benchmark.get("id", "")
        label = benchmark.get("label", "")
        source = benchmark.get("source", "")
        confidence = benchmark.get("confidence", "low")
        note = benchmark.get("note", "")
        years_to_peak = benchmark.get("years_to_peak", 5)

        # Site-penetration metric (hospital software): keys are y1_site_penetration etc.
        if any("site_penetration" in k for k in benchmark):
            is_site = True
            y1 = benchmark.get("y1_site_penetration", 0.03)
            y3 = benchmark.get("y3_site_penetration", 0.10)
            peak = benchmark.get("peak_site_penetration", 0.30)
        else:
            y1 = benchmark.get("y1_share", 0.05)
            y3 = benchmark.get("y3_share", 0.15)
            peak = benchmark.get("peak_share", 0.25)

    # Apply overrides
    if "y1_penetration" in overrides:
        y1 = float(overrides["y1_penetration"])
        confidence = "medium"
    if "peak_penetration" in overrides:
        peak = float(overrides["peak_penetration"])

    # ── HHI-based penetration adjustment ─────────────────────────────────────
    # Applied AFTER override and BEFORE SOM calculation so it is visible in
    # the final AnalogResult and surfaced to the PI in format_for_prompt().
    hhi_factor, hhi_note = _hhi_penetration_factor(hhi_score)
    if hhi_factor != 1.0:
        y1   = min(y1   * hhi_factor, 1.0)
        y3   = min(y3   * hhi_factor, 1.0)
        peak = min(peak * hhi_factor, 1.0)
        assumptions.append({
            "field": "hhi_penetration_adjustment",
            "value": f"×{hhi_factor:.2f} (HHI={hhi_score})",
            "source_type": "market_calibration",
            "confidence": "medium",
            "expert_question": (
                f"Market HHI={hhi_score}. Does this competitive concentration "
                f"match your view of the addressable sub-segment? The HHI "
                f"adjustment reduced penetration by ×{hhi_factor:.2f}."
            ),
        })
        # Append HHI context to the note so it survives to the report
        note = note + f"\n[HHI adjustment: {hhi_note}]" if note else hhi_note

    som_conservative = annual_revenue_sam * y1
    som_base = annual_revenue_sam * y3
    som_peak = annual_revenue_sam * peak

    if confidence == "low":
        assumptions.append({
            "field": "penetration_rate", "value": f"y1={y1:.0%} peak={peak:.0%}",
            "source_type": "analog", "confidence": "low",
            "expert_question": f"Based on {label}: is {y1:.0%} year-1 penetration realistic for this product? What deals/pilots exist that calibrate the ramp?",
        })

    return AnalogResult(
        analog_class=analog_class,
        analog_label=label,
        competitive_context=ctx,
        y1_penetration=y1,
        y3_penetration=y3,
        peak_penetration=peak,
        years_to_peak=years_to_peak,
        som_fraction=y1,
        som_conservative=som_conservative,
        som_base=som_base,
        som_peak=som_peak,
        source=source,
        confidence=confidence,
        note=note,
        is_site_metric=is_site,
        assumptions=assumptions,
        hhi_score=hhi_score,
        hhi_penetration_factor=hhi_factor if hhi_factor != 1.0 else None,
    )
