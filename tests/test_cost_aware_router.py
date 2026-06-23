"""
Unit tests for the Cost-Aware Specialist Router (Priority 3 / Sprint 6).

Pure functions only — no network.

Run with: pytest tests/test_cost_aware_router.py -v
"""

from app.services.cost_aware_router import (
    classify_task,
    compute_complexity,
    plan_models,
    plan_sources,
    build_routing_plan,
    FRONTIER_MODEL,
    SPECIALIST_MODEL,
    SMALL_MODEL,
)


def test_classify_dimensions():
    p = classify_task("a novel first-in-class gene therapy", "gene_therapy",
                       sub_expert_id="gene_therapy_rare", signal_count=2)
    assert p["modality"] == "gene_cell"
    assert p["regulatory_risk"] == "high"
    assert p["evidence_availability"] == "low"      # 2 signals
    assert p["novelty"] == "high"                   # "novel"/"first-in-class"
    assert p["data_sensitivity"] == "low"


def test_evidence_buckets():
    assert classify_task("x", "drug", signal_count=20)["evidence_availability"] == "high"
    assert classify_task("x", "drug", signal_count=6)["evidence_availability"] == "medium"
    assert classify_task("x", "drug", signal_count=1)["evidence_availability"] == "low"


def test_complexity_ordering():
    hard = compute_complexity(classify_task("novel gene therapy", "gene_therapy",
                                            sub_expert_id="gene_therapy_rare", signal_count=1))
    easy = compute_complexity(classify_task("a digital symptom tracker app", "digital_health",
                                            sub_expert_id="digital_cds", signal_count=20))
    assert hard > easy
    assert 0.0 <= easy <= 1.0 and 0.0 <= hard <= 1.0


def test_frontier_escalation_for_complex_case():
    p = classify_task("novel gene therapy", "gene_therapy",
                      sub_expert_id="gene_therapy_rare", signal_count=1)
    m = plan_models(p, compute_complexity(p))
    assert m["escalated_to_frontier"] is True
    assert m["synthesis_model"] == FRONTIER_MODEL
    # the cheap stages stay on the small model
    assert m["classify_model"] == SMALL_MODEL
    assert m["verify_model"] == SMALL_MODEL


def test_specialist_model_for_simple_case():
    p = classify_task("a well-studied digital adherence app for diabetes", "digital_health",
                      sub_expert_id="digital_cds", signal_count=25)
    m = plan_models(p, compute_complexity(p))
    assert m["escalated_to_frontier"] is False
    assert m["synthesis_model"] == SPECIALIST_MODEL


def test_quick_triage_never_uses_frontier():
    p = classify_task("novel gene therapy", "gene_therapy",
                      sub_expert_id="gene_therapy_rare", signal_count=1,
                      output_type="quick_triage")
    m = plan_models(p, compute_complexity(p))
    assert m["escalated_to_frontier"] is False
    assert m["synthesis_model"] == SPECIALIST_MODEL
    assert p["latency_budget_s"] == 8


def test_source_plan_by_modality_and_thin_evidence():
    p = classify_task("gene therapy for a rare disease", "gene_therapy",
                      sub_expert_id="gene_therapy_rare", signal_count=1)
    sp = plan_sources(p)
    assert "Orphanet" in sp["prioritized_sources"]
    assert sp["escalate_to_slow_tiers"] is True      # thin evidence
    assert sp["max_tier"] == 3
    # full report always adds the funding/IP sweep
    assert any("SBIR" in s for s in sp["prioritized_sources"])


def test_build_routing_plan_shape_and_estimate():
    plan = build_routing_plan("novel antibiotic for MRSA", "antibiotic",
                              sub_expert_id="drug_amr", signal_count=8)
    assert set(plan) >= {"task_profile", "complexity_score", "model_plan",
                         "synthesis_model", "source_plan", "estimate"}
    assert plan["synthesis_model"] in (FRONTIER_MODEL, SPECIALIST_MODEL)
    est = plan["estimate"]
    assert est["cost_tier"] in ("premium", "standard")
    assert est["relative_cost_units"] > 0
    # frontier costs more than specialist
    if plan["model_plan"]["escalated_to_frontier"]:
        assert est["cost_tier"] == "premium"
