"""
Market Sizing Orchestrator  (Build Spec v6, Parts 1-4)
=======================================================
9-step pipeline (steps 1-5 unchanged, steps 6-9 new in v6):
  1. patient_flow_engine      → addressable population + base_metric
  2. indication_sequence      → initial vs expansion fraction
  3. monetization_engine      → annual revenue (SAM level, pre-penetration)
  4. analog_engine            → y1/y3/peak penetration → SOM scenarios
  5. confidence_engine        → ranges + verify-with-expert + honesty_statement
  6. monte_carlo_engine       → P10/P50/P90 distribution + tornado analysis
  7. regulatory_pathways      → time-to-market + reimbursement risk
  8. expert_router_v2 (MoE)  → weighted expert activations + consensus
  9. heuristics               → market-sizing corrections with citations

Steps 6-9 are additive and isolated: failure in any step is logged and
the result falls back gracefully; existing engine outputs are unaffected.

Returns OrchestratedResult with all fields the spec requires.
The model narrates this output — it must NOT re-compute these figures.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict

from app.services.patient_flow_engine import PatientFlowResult
from app.services.monetization_engine import MonetizationResult
from app.services.analog_engine import AnalogResult
from app.services.confidence_engine import ConfidenceResult

logger = logging.getLogger(__name__)


@dataclass
class OrchestratedResult:
    disease_name: str
    product_type: str

    # Engine 1 – patient flow
    patient_flow: PatientFlowResult

    # Engine 2 – indication sequence
    initial_indication_fraction: float
    expansion_path: List[dict]
    initial_population: float      # patient_flow.final_population × initial_fraction

    # Engine 3 – monetization
    monetization: MonetizationResult
    sam_revenue_usd: float         # annual revenue at SAM (initial label)

    # Engine 4 – analog
    analog: AnalogResult
    som_conservative_usd: float
    som_base_usd: float
    som_peak_usd: float

    # Engine 5 – confidence
    confidence: ConfidenceResult

    # ── v6 additions (all optional; default=None to keep existing tests green) ──

    # Engine 6 – Monte Carlo distribution
    monte_carlo: Optional[object] = field(default=None)  # SizingDistribution | None

    # Engine 7 – Regulatory pathway
    regulatory_pathway: Optional[object] = field(default=None)  # RegulatoryPathway | None
    pathway_was_inferred: bool = field(default=False)
    time_to_market_months: Optional[float] = field(default=None)

    # Engine 8 – MoE expert activations
    expert_activations: Optional[List] = field(default=None)  # List[ExpertActivation] | None
    expert_consensus: Optional[object] = field(default=None)  # ExpertConsensus | None

    # Engine 9 – Heuristics
    fired_heuristics: Optional[List] = field(default=None)  # List[FiredHeuristic] | None

    def to_dict(self) -> dict:
        d: Dict = {
            "disease_name": self.disease_name,
            "product_type": self.product_type,
            "patient_flow": self.patient_flow.to_dict(),
            "initial_indication_fraction": self.initial_indication_fraction,
            "expansion_path": self.expansion_path,
            "initial_population": self.initial_population,
            "monetization": self.monetization.to_dict(),
            "sam_revenue_usd": self.sam_revenue_usd,
            "analog": self.analog.to_dict(),
            "som_conservative_usd": self.som_conservative_usd,
            "som_base_usd": self.som_base_usd,
            "som_peak_usd": self.som_peak_usd,
            "confidence": self.confidence.to_dict(),
        }
        # v6 optional fields — only included when populated
        if self.monte_carlo is not None:
            d["monte_carlo"] = self.monte_carlo.to_dict()
        if self.regulatory_pathway is not None:
            d["regulatory_pathway"] = self.regulatory_pathway.to_dict()
            d["pathway_was_inferred"] = self.pathway_was_inferred
            d["time_to_market_months"] = self.time_to_market_months
        if self.expert_consensus is not None:
            d["expert_consensus"] = self.expert_consensus.to_dict()
        if self.fired_heuristics:
            d["fired_heuristics"] = [h.to_dict() for h in self.fired_heuristics]
        return d

    def format_for_prompt(self) -> str:
        """
        Produces the authoritative block injected into the Claude prompt.
        The model must narrate these figures — it must not recompute them.
        """
        c = self.confidence
        m = self.monetization
        a = self.analog

        def _fm(v: float) -> str:
            if v >= 1e9:
                return f"${v/1e9:.1f}B"
            if v >= 1e6:
                return f"${v/1e6:.0f}M"
            return f"${v:,.0f}"

        lines = [
            "=== PROFESSIONAL MARKET SIZING — AUTHORITATIVE (DO NOT RECOMPUTE) ===",
            f"Disease:       {self.disease_name}",
            f"Product type:  {self.product_type}",
            f"Revenue model: {m.revenue_model} | Base unit: {m.base_unit}",
            "",
            f"ADDRESSABLE POPULATION: {self.initial_population:,.0f} {m.base_unit}",
            f"  (initial indication — {self.initial_indication_fraction:.0%} of eligible)",
            f"  Low / High range: {self.patient_flow.low_estimate:,.0f} – {self.patient_flow.high_estimate:,.0f}",
            "",
            f"NET PRICE (per {m.base_unit[:-1]}):  {_fm(m.net_price_usd)}",
            f"  Source: {m.price_source} | Confidence: {m.price_confidence}",
            f"  {m.price_note}",
            "",
            f"SAM REVENUE:   {_fm(self.sam_revenue_usd)} / yr",
            f"  Range:       {_fm(self.patient_flow.low_estimate * m.net_price_usd)} – {_fm(self.patient_flow.high_estimate * m.net_price_usd)}",
            "",
            f"SOM (year 1):  {_fm(self.som_conservative_usd)}  [{a.y1_penetration:.0%} penetration]",
            f"SOM (year 3):  {_fm(self.som_base_usd)}  [{a.y3_penetration:.0%} penetration]",
            f"SOM (peak):    {_fm(self.som_peak_usd)}  [{a.peak_penetration:.0%} penetration, ~{a.years_to_peak}yr]",
            f"  Analog:      {a.analog_label}",
            f"  Source:      {a.source}",
            *(
                [f"  HHI adj:     ×{a.hhi_penetration_factor:.2f} (market HHI={a.hhi_score} — "
                 f"{'fragmented' if a.hhi_score < 1000 else 'competitive' if a.hhi_score < 1500 else 'moderate' if a.hhi_score < 2500 else 'concentrated' if a.hhi_score < 3500 else 'highly conc.'})"]
                if a.hhi_penetration_factor is not None and a.hhi_score is not None else []
            ),
            "",
            f"OVERALL CONFIDENCE:  {c.overall_confidence.upper()} ({c.confidence_score:.0%})",
            f"REVENUE RANGE:       {_fm(c.low_bound_usd)} – {_fm(c.high_bound_usd)}",
            "",
        ]

        if self.expansion_path:
            lines.append("LABEL EXPANSION PATH (contingent on initial approval):")
            for step in self.expansion_path:
                lines.append(f"  • {step.get('label', step.get('indication', 'next indication'))}: "
                             f"+{step.get('fraction', 0):.0%} of initial")
            lines.append("")

        if c.verify_with_expert:
            lines.append("TOP QUESTIONS TO VALIDATE WITH EXPERT:")
            for i, q in enumerate(c.verify_with_expert[:3], 1):
                lines.append(f"  {i}. [{q.impact.upper()} IMPACT] {q.question}")
            lines.append("")

        # ── v6: Monte Carlo distribution ─────────────────────────────────────
        mc = self.monte_carlo
        if mc is not None:
            try:
                lines.append("MONTE CARLO DISTRIBUTION (10,000 simulations — DO NOT RECOMPUTE):")
                p10 = _fm(mc.p10)
                p50 = _fm(mc.p50)
                p90 = _fm(mc.p90)
                lines.append(f"  P10 (pessimistic): {p10}")
                lines.append(f"  P50 (median):      {p50}")
                lines.append(f"  P90 (optimistic):  {p90}")
                if mc.tornado:
                    top3 = mc.tornado[:3]
                    lines.append("  Top drivers (tornado):")
                    for t in top3:
                        lines.append(
                            f"    • {t.gate_label}: {_fm(t.p50_at_gate_p10)} – {_fm(t.p50_at_gate_p90)} "
                            f"(swing {_fm(t.swing_usd)})"
                        )
                lines.append("")
            except Exception:
                pass  # MC block is optional; never crash format_for_prompt

        # ── v6: Regulatory pathway ────────────────────────────────────────────
        rp = self.regulatory_pathway
        if rp is not None:
            try:
                from app.services.regulatory_pathways import time_to_market_summary
                lines.append("REGULATORY & REIMBURSEMENT PATHWAY:")
                lines.append(f"  {time_to_market_summary(rp)}")
                if rp.pathway_was_inferred:
                    lines.append(f"  ⚠  Pathway inferred: {rp.inference_basis}")
                if rp.clarifying_question:
                    lines.append(f"  → Clarifying question: {rp.clarifying_question}")
                reimb = rp.reimbursement
                lines.append(f"  Reimbursement risk: {reimb.risk_level.upper()}")
                if reimb.risk_note:
                    lines.append(f"  {reimb.risk_note}")
                lines.append("")
            except Exception:
                pass

        # ── v6: Expert consensus & disagreement ───────────────────────────────
        ec = self.expert_consensus
        if ec is not None:
            try:
                if ec.has_disagreement:
                    lines.append("EXPERT CONSENSUS — DISAGREEMENT FLAGGED:")
                    lines.append(f"  {ec.disagreement_note}")
                else:
                    lines.append("EXPERT CONSENSUS:")
                    lines.append(
                        f"  SAM adj ×{ec.consensus_sam_multiplier:.2f}, "
                        f"SOM adj ×{ec.consensus_som_multiplier:.2f} "
                        f"({len(ec.activated_experts)} expert lenses)"
                    )
                lines.append("")
            except Exception:
                pass

        # ── v6: Heuristics ───────────────────────────────────────────────────
        fired = self.fired_heuristics
        if fired:
            try:
                lines.append(f"HEURISTIC ADJUSTMENTS APPLIED ({len(fired)}):")
                for h in fired:
                    adj_parts = []
                    if h.sam_adjustment != 1.0:
                        adj_parts.append(f"SAM ×{h.sam_adjustment:.2f}")
                    if h.som_adjustment != 1.0:
                        adj_parts.append(f"SOM ×{h.som_adjustment:.2f}")
                    adj_str = ", ".join(adj_parts) if adj_parts else "informational"
                    lines.append(f"  • {h.rule_name} [{h.confidence}] — {adj_str}")
                    lines.append(f"    Trigger: {h.trigger}")
                    lines.append(f"    {h.note[:180]}{'…' if len(h.note) > 180 else ''}")
                lines.append("")
            except Exception:
                pass

        lines.append(c.honesty_statement)
        lines.append("=== END MARKET SIZING ===")

        return "\n".join(lines)


async def run(
    disease_name: str,
    product_type: str,
    segment_gate: Optional[float] = None,
    net_price_usd: Optional[float] = None,
    competitive_context: Optional[str] = None,
    context_text: str = "",
    overrides: Optional[Dict] = None,
    line_of_therapy_rate: Optional[float] = None,
) -> OrchestratedResult:
    """
    Execute the full 5-engine pipeline for one disease + product.
    Returns OrchestratedResult; call .format_for_prompt() to get the LLM block.
    """
    from app.services import patient_flow_engine, monetization_engine, analog_engine, confidence_engine

    overrides = overrides or {}

    # ── Step 1: Patient flow ─────────────────────────────────────────────────
    pf_result = await patient_flow_engine.compute(
        disease_name=disease_name,
        segment_gate=segment_gate,
        product_type=product_type,
        overrides=overrides,
        line_of_therapy_rate=line_of_therapy_rate,
    )
    logger.info("patient_flow done: pop=%.0f, metric=%s, source=%s",
                pf_result.final_population, pf_result.base_metric, pf_result.data_source)

    # ── Step 2: Indication sequence ──────────────────────────────────────────
    init_frac, expansion_path = await _load_indication_sequence(disease_name, product_type)
    # C-09: None means DB error — use full disease population but make it visible
    if init_frac is None:
        logger.warning("[C-09] indication_sequence not found for '%s' / '%s' — no fraction applied",
                       disease_name, product_type)
        initial_population = pf_result.final_population
        init_frac = 1.0  # for downstream use in expansion_path
    else:
        initial_population = pf_result.final_population * init_frac

    # ── Step 3: Monetization ─────────────────────────────────────────────────
    mon_result = await monetization_engine.compute(
        product_type=product_type,
        disease_name=disease_name,
        population=initial_population,
        population_base_metric=pf_result.base_metric,
        net_price_usd=net_price_usd or overrides.get("net_price_usd"),
        persistency_months=pf_result.persistency_months,
        overrides=overrides,
    )
    sam_revenue = mon_result.annual_revenue_usd
    logger.info("monetization done: model=%s, revenue=%s",
                mon_result.revenue_model, _fmt(sam_revenue))

    # ── Step 3b: Market HHI (feeds step 4 penetration) ──────────────────────
    _hhi_score: Optional[int] = None
    try:
        from app.services.market_calibration_service import get_hhi_for_indication
        _hhi_score = get_hhi_for_indication(disease_name, product_type)
        if _hhi_score is not None:
            logger.info("hhi done: score=%d for disease=%s", _hhi_score, disease_name)
    except Exception as e:
        logger.warning("get_hhi_for_indication failed (non-fatal): %s", e)

    # ── Step 4: Analog penetration ───────────────────────────────────────────
    analog_result = analog_engine.compute(
        product_type=product_type,
        annual_revenue_sam=sam_revenue,
        competitive_context=competitive_context,
        context_text=context_text,
        overrides=overrides,
        hhi_score=_hhi_score,
    )
    logger.info("analog done: class=%s, y1=%.0f%%", analog_result.analog_class,
                analog_result.y1_penetration * 100)

    # ── Step 5: Confidence ───────────────────────────────────────────────────
    conf_result = confidence_engine.compute(
        annual_revenue_sam=sam_revenue,
        low_revenue=mon_result.low_revenue_usd * analog_result.y1_penetration,
        high_revenue=mon_result.high_revenue_usd * analog_result.peak_penetration,
        patient_flow_assumptions=pf_result.assumptions,
        monetization_assumptions=mon_result.assumptions,
        analog_assumptions=analog_result.assumptions,
        disease_name=disease_name,
        product_type=product_type,
    )

    # ── Step 6: Monte Carlo simulation ──────────────────────────────────────
    mc_result = None
    try:
        from app.services.monte_carlo_engine import simulate_from_patient_flow
        mc_result = simulate_from_patient_flow(
            patient_flow_result=pf_result,
            net_price_usd=mon_result.net_price_usd,
            revenue_model=mon_result.revenue_model,
            monetization_unit=mon_result.base_unit,
        )
        logger.info("monte_carlo done: P50=%s, P10=%s, P90=%s",
                    _fmt(mc_result.p50), _fmt(mc_result.p10), _fmt(mc_result.p90))
    except Exception as e:
        logger.warning("monte_carlo_engine failed (non-fatal): %s", e)

    # ── Step 7: Regulatory pathway ───────────────────────────────────────────
    rp_result = None
    pathway_inferred = False
    ttm_months = None
    try:
        from app.services.regulatory_pathways import select_regulatory_pathway
        rp_result = select_regulatory_pathway(
            product_type=product_type,
            idea_text=context_text,
        )
        pathway_inferred = rp_result.pathway_was_inferred
        ttm_months = rp_result.time_to_first_revenue_months
        logger.info("regulatory_pathway done: %s, TTM=%.0f mo, inferred=%s",
                    rp_result.pathway_name, ttm_months, pathway_inferred)
    except Exception as e:
        logger.warning("regulatory_pathways failed (non-fatal): %s", e)

    # ── Step 8: MoE expert routing ───────────────────────────────────────────
    expert_acts = None
    expert_cons = None
    try:
        from app.services.expert_router_v2 import route_to_experts, reconcile
        tier1 = _product_type_to_tier1(product_type)
        expert_acts = await route_to_experts(
            idea=context_text or disease_name,
            tier1_category=tier1,
        )
        expert_cons = reconcile(expert_acts)
        logger.info("moe done: %d experts, disagreement=%s, SAM_adj=%.2f, SOM_adj=%.2f",
                    len(expert_acts), expert_cons.has_disagreement,
                    expert_cons.consensus_sam_multiplier,
                    expert_cons.consensus_som_multiplier)
    except Exception as e:
        logger.warning("expert_router_v2 MoE failed (non-fatal): %s", e)

    # ── Step 9: Heuristics ───────────────────────────────────────────────────
    heuristics_fired = None
    try:
        from app.services.expert_router_v2 import apply_heuristics
        heuristics_fired = apply_heuristics(
            idea_text=context_text or disease_name,
            product_type=product_type,
            activations=expert_acts,
        )
        if heuristics_fired:
            logger.info("heuristics fired: %s",
                        [h.rule_name for h in heuristics_fired])
    except Exception as e:
        logger.warning("apply_heuristics failed (non-fatal): %s", e)

    return OrchestratedResult(
        disease_name=disease_name,
        product_type=product_type,
        patient_flow=pf_result,
        initial_indication_fraction=init_frac,
        expansion_path=expansion_path,
        initial_population=initial_population,
        monetization=mon_result,
        sam_revenue_usd=sam_revenue,
        analog=analog_result,
        som_conservative_usd=analog_result.som_conservative,
        som_base_usd=analog_result.som_base,
        som_peak_usd=analog_result.som_peak,
        confidence=conf_result,
        # v6 additions
        monte_carlo=mc_result,
        regulatory_pathway=rp_result,
        pathway_was_inferred=pathway_inferred,
        time_to_market_months=ttm_months,
        expert_activations=expert_acts,
        expert_consensus=expert_cons,
        fired_heuristics=heuristics_fired,
    )


async def _load_indication_sequence(
    disease_name: str, product_type: str
) -> tuple[float, List[dict]]:
    """Load indication_sequence from DB; fallback to (1.0, []) if not seeded."""
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT initial_fraction, expansion_path
                FROM indication_sequence
                WHERE LOWER(disease_name) = LOWER($1)
                  AND (product_type_hint = $2 OR product_type_hint IS NULL)
                ORDER BY (product_type_hint IS NOT NULL) DESC, id ASC
                LIMIT 1
            """, disease_name, product_type or None)
            if row:
                frac = float(row["initial_fraction"] or 1.0)
                exp = row["expansion_path"]
                if isinstance(exp, str):
                    exp = json.loads(exp)
                return frac, exp or []
    except Exception as e:
        logger.warning("[C-09] _load_indication_sequence DB error for '%s': %s", disease_name, e)
    return None, []  # C-09: None signals DB miss — caller must not assume 1.0


def _fmt(v: float) -> str:
    if v >= 1e9:
        return f"${v/1e9:.1f}B"
    if v >= 1e6:
        return f"${v/1e6:.1f}M"
    if v >= 1e3:
        return f"${v/1e3:.0f}K"
    return f"${v:,.0f}"


def _product_type_to_tier1(product_type: str) -> str:
    """Map OrchestratedResult.product_type to expert_router_v2 tier1 category."""
    pt = (product_type or "").lower()
    _map = {
        "drug_small_molecule": "drug_small_molecule",
        "biologic": "biologic",
        "gene_therapy": "gene_cell_therapy",
        "gene_cell_therapy": "gene_cell_therapy",
        "medical_device": "medical_device",
        "device": "medical_device",
        "diagnostic": "diagnostic",
        "digital_health": "digital_health",
        "software": "digital_health",
        "samd": "digital_health",
        "vaccine_immunotherapy": "vaccine_immunotherapy",
        "vaccine": "vaccine_immunotherapy",
        "other_platform": "other_platform",
        "antibiotic": "drug_small_molecule",
        "drug_amr": "drug_small_molecule",
        "drug_oncology": "biologic",
    }
    return _map.get(pt, "drug_small_molecule")
