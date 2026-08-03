"""
Patient Flow Engine  (Build Spec v5, Part C — Engine 1)
=======================================================
Bottom-up epidemiology funnel: disease → treated/addressable population.

compute(disease_name, segment_gate, product_type, overrides)
  1. Load patient_flow_model from DB for this disease (or use fallback)
  2. Fill null gates (treated_segment / line_of_therapy) from segment_gate arg
  3. Walk funnel top→bottom: first absolute, each rate multiplies running total
  4. Apply persistency for chronic therapies (convert incident → prevalent on-treatment)
  5. Return PatientFlowResult with full derivation + per-step source + confidence

Reuses existing apply_population_cascade() from market_sizing_engine.py as fallback
when no patient_flow_model is seeded for the disease.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

# Gates that are intentionally handled elsewhere — skip literature extraction for these.
_SKIP_EXTRACTION_GATES = {"product_share"}  # handled by analog_engine


@dataclass
class FlowStep:
    step: str
    label: str
    rate: Optional[float]
    running_value: float
    source_id: str
    source_name: str
    confidence: str          # "high" | "medium" | "low"
    is_expert_required: bool  # True if this gate had rate=None and was filled by caller


@dataclass
class PatientFlowResult:
    disease_name: str
    product_type_hint: str
    final_population: float        # addressable/treated population
    base_metric: str               # "patients" | "sites" | "procedures" | "tests"
    steps: List[FlowStep]
    persistency_adjusted_pop: Optional[float]   # if chronic: prevalent on-treatment
    persistency_months: int
    assumptions: List[dict]        # {field, value, source_type, confidence, expert_question}
    data_source: str               # "db_seed" | "fallback_cascade"
    low_estimate: float            # −30% on low-confidence gates
    high_estimate: float           # +50% on low-confidence gates

    def to_dict(self) -> dict:
        return {
            "disease_name": self.disease_name,
            "final_population": self.final_population,
            "base_metric": self.base_metric,
            "persistency_adjusted_pop": self.persistency_adjusted_pop,
            "persistency_months": self.persistency_months,
            "low_estimate": self.low_estimate,
            "high_estimate": self.high_estimate,
            "steps": [
                {
                    "step": s.step, "label": s.label, "rate": s.rate,
                    "running_value": s.running_value, "source_id": s.source_id,
                    "source_name": s.source_name, "confidence": s.confidence,
                    "is_expert_required": s.is_expert_required,
                }
                for s in self.steps
            ],
            "assumptions": self.assumptions,
            "data_source": self.data_source,
        }


async def compute(
    disease_name: str,
    segment_gate: Optional[float],   # the "treated_segment" rate (narrows to THIS pathway)
    product_type: str = "",
    overrides: Optional[Dict[str, float]] = None,
    line_of_therapy_rate: Optional[float] = None,
    product_share_rate: Optional[float] = None,
) -> PatientFlowResult:
    """
    Compute the addressable patient/site/test population for this disease+product.

    segment_gate:         the fraction of the diagnosed population eligible for THIS
                          specific treatment pathway (the narrow-responder gate). This
                          must be set per product — it's the difference between
                          "all stroke patients" and "thrombectomy-eligible LVO".
    line_of_therapy_rate: for multi-line therapies (oncology), the fraction in the
                          relevant line. None = not applicable.
    product_share_rate:   for analog calibration. None = handled by analog_engine separately.
    """
    overrides = overrides or {}

    # 1. Try to load from DB
    pf_row = await _load_patient_flow_model(disease_name, product_type)

    if pf_row:
        # Enrich null-rate gates with literature fractions before the funnel walk
        overrides = await _enrich_null_gates(
            disease_name, pf_row.get("funnel") or [], overrides
        )
        result = _walk_db_funnel(
            pf_row, segment_gate, product_type,
            overrides, line_of_therapy_rate, product_share_rate
        )
        result.data_source = "db_seed"
    else:
        # Fallback: use existing market_sizing_engine cascade
        result = await _fallback_cascade(disease_name, product_type, segment_gate, overrides)

    return result


async def _load_patient_flow_model(disease_name: str, product_type: str) -> Optional[dict]:
    """Load the matching patient_flow_model row from DB. Returns None if not seeded."""
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            # Try exact match with product_type_hint first, then generic (NULL hint)
            row = await conn.fetchrow("""
                SELECT * FROM patient_flow_model
                WHERE LOWER(disease_name) = LOWER($1)
                  AND (product_type_hint = $2 OR product_type_hint IS NULL)
                ORDER BY (product_type_hint IS NOT NULL) DESC, id ASC
                LIMIT 1
            """, disease_name, product_type or None)
            if not row:
                # fuzzy prefix match
                row = await conn.fetchrow("""
                    SELECT * FROM patient_flow_model
                    WHERE LOWER($1) LIKE LOWER(disease_name) || '%'
                       OR LOWER(disease_name) LIKE LOWER($1) || '%'
                    ORDER BY id ASC LIMIT 1
                """, disease_name)
            if row:
                d = dict(row)
                if isinstance(d.get("funnel"), str):
                    d["funnel"] = json.loads(d["funnel"])
                return d
    except Exception as e:
        logger.warning("_load_patient_flow_model DB error: %s", e)
    return None


def _walk_db_funnel(
    pf_row: dict,
    segment_gate: Optional[float],
    product_type: str,
    overrides: dict,
    lot_rate: Optional[float],
    share_rate: Optional[float],
) -> PatientFlowResult:
    """Walk the DB funnel, filling null gates from the caller-supplied rates."""
    funnel = pf_row.get("funnel") or []
    persistency_months = pf_row.get("persistency_months") or 12

    steps: List[FlowStep] = []
    running = 0.0
    assumptions: List[dict] = []
    low_confidence_count = 0

    for gate in funnel:
        step_name = gate.get("step", "")
        gate_type = gate.get("type", "rate")
        label = gate.get("label", step_name)
        source_id = gate.get("source_id", "unknown")
        source_name = gate.get("source_id", "unknown")
        confidence = gate.get("confidence", "low")
        is_expert = False

        rate = gate.get("rate")

        # Fill null gates from caller
        if rate is None:
            if step_name == "treated_segment":
                rate = overrides.get("treated_segment", segment_gate)
                is_expert = True
                if rate is None:
                    rate = 0.20   # conservative default; flagged as low confidence
                    confidence = "low"
                    assumptions.append({
                        "field": "treated_segment_rate", "value": rate,
                        "source_type": "analyst_estimate", "confidence": "low",
                        "expert_question": "What fraction of diagnosed patients are eligible for THIS specific treatment pathway? This is the most important gate — getting it wrong changes the market 3-5x.",
                    })
            elif step_name == "line_of_therapy":
                rate = overrides.get("line_of_therapy", lot_rate or 1.0)
                is_expert = True
                if lot_rate is None:
                    assumptions.append({
                        "field": "line_of_therapy_rate", "value": rate,
                        "source_type": "analyst_estimate", "confidence": "low",
                        "expert_question": "For which line(s) of therapy is this product positioned? 1L = full eligible pool; 2L = fraction that progressed from 1L.",
                    })
            elif step_name == "product_share":
                rate = overrides.get("product_share", share_rate or 1.0)  # handled by analog_engine
                is_expert = True

        # Apply override if explicitly provided
        if step_name in overrides:
            rate = overrides[step_name]

        if gate_type == "absolute":
            running = float(overrides.get(step_name + "_value", rate or gate.get("value", 0)))
            if gate.get("value"):
                running = float(overrides.get(step_name + "_value", gate["value"]))
        else:
            running = running * float(rate or 1.0)

        if confidence == "low":
            low_confidence_count += 1

        steps.append(FlowStep(
            step=step_name, label=label, rate=rate,
            running_value=running, source_id=source_id,
            source_name=source_name, confidence=confidence,
            is_expert_required=is_expert,
        ))

    # Infer base_metric from funnel top-level step
    first_step = funnel[0].get("step", "incidence") if funnel else "incidence"
    if "site" in first_step.lower():
        base_metric = "sites"
    elif "procedure" in first_step.lower():
        base_metric = "procedures"
    elif "test" in first_step.lower():
        base_metric = "tests"
    else:
        base_metric = "patients"

    # Persistency: for chronic therapies, convert incident → prevalent on-treatment
    # prevalent_on_treatment = incident_per_yr × (persistency_months / 12)
    persistency_adj = None
    if persistency_months > 1 and base_metric == "patients":
        persistency_adj = running * (persistency_months / 12)

    # Confidence band: low-confidence gates → widen range
    low_frac = low_confidence_count / max(len(steps), 1)
    range_half = max(0.30, low_frac * 0.60)
    low_est = running * (1.0 - range_half * 0.5)
    high_est = running * (1.0 + range_half)

    return PatientFlowResult(
        disease_name=pf_row.get("disease_name", ""),
        product_type_hint=product_type,
        final_population=running,
        base_metric=base_metric,
        steps=steps,
        persistency_adjusted_pop=persistency_adj,
        persistency_months=persistency_months,
        assumptions=assumptions,
        data_source="db_seed",
        low_estimate=low_est,
        high_estimate=high_est,
    )


async def _enrich_null_gates(
    disease_name: str,
    funnel: List[dict],
    overrides: dict,
) -> dict:
    """
    For each funnel gate with rate=None that is not already overridden,
    attempt to auto-extract a fraction from literature.

    High-confidence results (≥ 0.70) are added to the overrides dict so
    _walk_db_funnel() uses them directly instead of falling back to hardcoded
    defaults. Low-confidence results (< 0.70) are queued for human review and
    NOT injected into overrides — the existing fallback logic fires instead and
    the PI sees a needs_review flag in the assumptions.

    All failures are silent (non-fatal). The engine's existing defaults remain
    the safety net.
    """
    enriched = dict(overrides)

    try:
        from app.services.funnel_fraction_extractor import extract_funnel_fraction
        from app.db.fraction_review_queue import queue_fraction_for_review
    except ImportError:
        return enriched

    for gate in funnel:
        step_name = gate.get("step", "")
        if not step_name:
            continue
        if gate.get("rate") is not None:
            continue
        if step_name in enriched:
            continue
        if step_name in _SKIP_EXTRACTION_GATES:
            continue

        try:
            lit = await extract_funnel_fraction(
                disease_name=disease_name,
                gate_name=step_name,
                gate_label=gate.get("label", step_name),
                gate_note=gate.get("note"),
            )

            if lit.fraction is not None and not lit.needs_review:
                enriched[step_name] = lit.fraction
                logger.info(
                    "Literature fraction: %s/%s = %.1f%% (conf=%.2f, %s)",
                    disease_name, step_name, lit.fraction * 100,
                    lit.confidence, lit.extraction_method,
                )
            elif lit.fraction is not None and lit.needs_review:
                # Queue but don't inject — PI review required
                await queue_fraction_for_review(lit)
                logger.info(
                    "Fraction queued for review: %s/%s = %.1f%% (conf=%.2f)",
                    disease_name, step_name, lit.fraction * 100, lit.confidence,
                )
        except Exception as e:
            logger.debug("_enrich_null_gates gate=%s error (non-fatal): %s", step_name, e)

    return enriched


async def _fallback_cascade(
    disease_name: str,
    product_type: str,
    segment_gate: Optional[float],
    overrides: dict,
) -> PatientFlowResult:
    """
    Fallback: use existing apply_population_cascade() from market_sizing_engine.
    Returns a minimal PatientFlowResult with low confidence on all gates.
    """
    try:
        from app.services.market_sizing_engine import apply_population_cascade
        # Map product_type → therapeutic_area so the cascade applies the right TA defaults
        _ta_map = {
            "biologic": "oncology", "gene_therapy": "rare_disease",
            "antibiotic": "infectious_disease", "drug_amr": "infectious_disease",
        }
        ta = _ta_map.get((product_type or "").lower(), "other")
        # apply_population_cascade(prevalent_patients, therapeutic_area, ...) → (eligible, ...)
        eligible, *_ = apply_population_cascade(
            prevalent_patients=500000,   # rough starting population; cascade narrows by TA rates
            therapeutic_area=ta,
            disease_name=disease_name,
            initial_indication_only=True,
        )
        running = float(eligible)
    except Exception as e:
        logger.warning("fallback_cascade failed: %s", e)
        running = 50000  # conservative unknown default

    # Apply segment_gate if provided
    if segment_gate is not None:
        running = running * float(segment_gate)

    low_est = running * 0.33
    high_est = running * 2.0
    assumptions = [{
        "field": "population_cascade", "value": running,
        "source_type": "llm_inference", "confidence": "low",
        "expert_question": f"What is the addressable patient population for this specific product in {disease_name}? The engine used a generic cascade — verify with a clinical expert.",
    }]

    return PatientFlowResult(
        disease_name=disease_name,
        product_type_hint=product_type,
        final_population=running,
        base_metric="patients",
        steps=[FlowStep("cascade", f"Fallback cascade for {disease_name}", None,
                         running, "llm_inference", "internal cascade", "low", True)],
        persistency_adjusted_pop=None,
        persistency_months=12,
        assumptions=assumptions,
        data_source="fallback_cascade",
        low_estimate=low_est,
        high_estimate=high_est,
    )
