"""
Confidence Engine  (Build Spec v5, Part C — Engine 4 / Honesty Layer)
======================================================================
Collects all assumptions from engines 1-3, scores each by source quality,
runs a sensitivity pass to assign impact, and generates:
  - verify_with_expert[] sorted by (confidence × impact) priority
  - honesty_statement: what we know, what we estimated, what we don't know
  - overall_confidence: "high" | "medium" | "low"
  - confidence_range: (low_bound, high_bound) on total revenue

Source quality ladder (descending):
  expert_verified   → 1.0
  public_dataset    → 0.85
  literature        → 0.70
  analog            → 0.55
  analyst_estimate  → 0.35
  llm_inference     → 0.10
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict

logger = logging.getLogger(__name__)

_SOURCE_QUALITY: Dict[str, float] = {
    "expert_verified":  1.00,
    "public_dataset":   0.85,
    "literature":       0.70,
    "analog":           0.55,
    "analyst_estimate": 0.35,
    "llm_inference":    0.10,
}

_IMPACT_WEIGHT = {"high": 1.0, "medium": 0.5, "low": 0.2}


@dataclass
class ExpertQuestion:
    field_name: str
    question: str
    source_type: str
    confidence: str
    impact: str
    priority_score: float    # higher = ask first (low_quality × high_impact)


@dataclass
class ConfidenceResult:
    overall_confidence: str          # "high" | "medium" | "low"
    confidence_score: float          # 0–1 composite
    low_bound_usd: float
    high_bound_usd: float
    verify_with_expert: List[ExpertQuestion]   # sorted highest priority first
    honesty_statement: str
    llm_inference_count: int
    total_assumptions: int
    weakest_assumptions: List[str]   # field names of llm_inference gates

    def to_dict(self) -> dict:
        return {
            "overall_confidence": self.overall_confidence,
            "confidence_score": round(self.confidence_score, 3),
            "low_bound_usd": self.low_bound_usd,
            "high_bound_usd": self.high_bound_usd,
            "verify_with_expert": [
                {
                    "field": q.field_name,
                    "question": q.question,
                    "source_type": q.source_type,
                    "confidence": q.confidence,
                    "impact": q.impact,
                    "priority_score": round(q.priority_score, 3),
                }
                for q in self.verify_with_expert
            ],
            "honesty_statement": self.honesty_statement,
            "llm_inference_count": self.llm_inference_count,
            "total_assumptions": self.total_assumptions,
            "weakest_assumptions": self.weakest_assumptions,
        }


def _assign_impact(assumption: dict, all_assumptions: List[dict]) -> str:
    """
    Rough sensitivity: gates that set population (absolute counts or broad rates)
    are "high" impact; everything else is "medium" or "low".
    """
    field = (assumption.get("field") or "").lower()
    if any(k in field for k in ("segment", "treated", "incidence", "prevalence", "diagnosed",
                                 "eligible", "population", "site_count", "total_sites")):
        return "high"
    if any(k in field for k in ("price", "adoption", "penetration", "line_of_therapy",
                                 "persistency", "analog")):
        return "medium"
    return "low"


def compute(
    annual_revenue_sam: float,
    low_revenue: float,
    high_revenue: float,
    patient_flow_assumptions: List[dict],
    monetization_assumptions: List[dict],
    analog_assumptions: List[dict],
    disease_name: str = "",
    product_type: str = "",
) -> ConfidenceResult:
    """
    Aggregate all assumptions, score, and build the honesty layer.

    Inputs: assumptions lists from patient_flow_engine, monetization_engine,
    analog_engine — each item is {field, value, source_type, confidence, expert_question}.
    """
    all_assumptions = (
        patient_flow_assumptions
        + monetization_assumptions
        + analog_assumptions
    )

    if not all_assumptions:
        return _empty_result(annual_revenue_sam, low_revenue, high_revenue)

    scored: List[ExpertQuestion] = []
    quality_scores: List[float] = []
    llm_count = 0
    weakest: List[str] = []

    for a in all_assumptions:
        src_type = a.get("source_type", "llm_inference")
        conf = a.get("confidence", "low")
        quality = _SOURCE_QUALITY.get(src_type, 0.10)
        impact = _assign_impact(a, all_assumptions)
        impact_w = _IMPACT_WEIGHT.get(impact, 0.2)

        # Priority: low quality × high impact = ask first
        priority = (1.0 - quality) * impact_w

        question = a.get("expert_question")
        if question:
            scored.append(ExpertQuestion(
                field_name=a.get("field", "unknown"),
                question=question,
                source_type=src_type,
                confidence=conf,
                impact=impact,
                priority_score=priority,
            ))

        quality_scores.append(quality)

        if src_type == "llm_inference":
            llm_count += 1
            weakest.append(a.get("field", "unknown"))

    # Overall confidence = weighted mean quality across all assumptions
    if quality_scores:
        composite = sum(quality_scores) / len(quality_scores)
    else:
        composite = 0.50

    if composite >= 0.70:
        overall = "high"
    elif composite >= 0.45:
        overall = "medium"
    else:
        overall = "low"

    # Sort by priority descending
    scored.sort(key=lambda q: q.priority_score, reverse=True)

    # Quality-adjusted confidence band on SAM level.
    # Width scales with uncertainty: low-quality inputs → wider band.
    # Asymmetric toward upside because markets usually run larger than models predict.
    # min 0.30 (even for high-confidence inputs), max 0.45 (heavy LLM-inference).
    llm_frac = llm_count / max(len(all_assumptions), 1)
    range_frac = max(0.30, min(0.45, llm_frac * 0.80 + (1.0 - composite) * 0.25))
    cal_low = max(0.0, annual_revenue_sam * (1.0 - range_frac))
    cal_high = annual_revenue_sam * (1.0 + range_frac * 1.30)

    # Honesty statement
    honesty = _build_honesty_statement(
        disease_name, product_type, overall, composite,
        llm_count, len(all_assumptions), weakest, cal_low, cal_high,
    )

    return ConfidenceResult(
        overall_confidence=overall,
        confidence_score=composite,
        low_bound_usd=cal_low,
        high_bound_usd=cal_high,
        verify_with_expert=scored,
        honesty_statement=honesty,
        llm_inference_count=llm_count,
        total_assumptions=len(all_assumptions),
        weakest_assumptions=weakest[:5],
    )


def _build_honesty_statement(
    disease_name: str,
    product_type: str,
    overall: str,
    score: float,
    llm_count: int,
    total: int,
    weakest: List[str],
    low_rev: float,
    high_rev: float,
) -> str:
    def _fmt_m(v: float) -> str:
        if v >= 1e9:
            return f"${v/1e9:.1f}B"
        if v >= 1e6:
            return f"${v/1e6:.1f}M"
        return f"${v:,.0f}"

    lines = [
        f"**Market size confidence: {overall.upper()} ({score:.0%} composite quality)**",
        "",
        f"Estimated revenue range: {_fmt_m(low_rev)} – {_fmt_m(high_rev)} annually.",
        "",
    ]

    if llm_count == 0:
        lines.append(
            "All assumptions are grounded in public datasets, peer-reviewed literature, "
            "or published commercial analogs — no LLM-inferred figures."
        )
    else:
        pct = llm_count / max(total, 1)
        lines.append(
            f"{llm_count} of {total} assumptions ({pct:.0%}) were estimated by AI inference "
            f"because no public data was found."
        )
        if weakest:
            fields = ", ".join(f"`{w}`" for w in weakest[:3])
            lines.append(
                f"The highest-uncertainty gates are: {fields}. "
                "These are the numbers most likely to change 2-5x after expert validation."
            )

    lines += [
        "",
        "**What this model does NOT do:** We do not invent market figures. "
        "The engine walks a structured funnel from epidemiology through treatment eligibility "
        "to adoption — every step cites its source. Figures labeled 'analyst estimate' or "
        "'AI inference' must be validated by a domain expert before use in investor materials.",
    ]

    if overall == "low":
        lines += [
            "",
            "⚠️  LOW CONFIDENCE: This market is poorly characterized in public data or the "
            "addressable segment is highly product-specific. Use these figures only as a "
            "directional range and prioritize expert validation before committing resources.",
        ]

    return "\n".join(lines)


def _empty_result(sam: float, low: float, high: float) -> ConfidenceResult:
    return ConfidenceResult(
        overall_confidence="low",
        confidence_score=0.10,
        low_bound_usd=low * 0.3,
        high_bound_usd=high * 2.0,
        verify_with_expert=[],
        honesty_statement=(
            "No assumptions were tracked during this sizing run. "
            "All figures should be treated as directional only."
        ),
        llm_inference_count=0,
        total_assumptions=0,
        weakest_assumptions=[],
    )
