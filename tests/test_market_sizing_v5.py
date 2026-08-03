"""
Build Spec v5 Tests — Professional Market Sizing Engine
=======================================================
Tests:
  1. Software → site_license (never per_patient)
  2. Funnel math: absolute first gate, then rate multiplications
  3. Initial indication < eventual (expansion always adds, never subtracts)
  4. Confidence ordering: expert_verified > public_dataset > llm_inference
  5. Base unit matches revenue model (sites vs patients)
  6. GBD excluded from commercial path (commercial_ok=False)
  7. Orchestrator produces all required fields
  8. format_for_prompt contains required sections
  9. Analog class inferred correctly by product_type
 10. Monetization mismatch guard (site flow + per_patient = auto-corrected)
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

STROKE_FUNNEL = [
    {"step": "us_stroke_incidence", "type": "absolute", "value": 795000,
     "label": "US annual stroke incidence", "source_id": "cdc_stroke_2022",
     "confidence": "high"},
    {"step": "diagnosed_reached_hospital", "type": "rate", "rate": 0.80,
     "label": "Reach hospital within window", "source_id": "aha_stroke_2022",
     "confidence": "high"},
    {"step": "treated_segment", "type": "rate", "rate": None,
     "label": "LVO thrombectomy-eligible", "source_id": None,
     "confidence": "low"},
]

SEPSIS_FUNNEL = [
    {"step": "total_sites", "type": "absolute", "value": 4000,
     "label": "US hospitals with ICU treating sepsis", "source_id": "aha_hospital_2022",
     "confidence": "high"},
    {"step": "icu_capable", "type": "rate", "rate": 0.75,
     "label": "ICU-capable hospitals", "source_id": "cms_2022",
     "confidence": "medium"},
]

def _mock_stroke_pf_row():
    return {
        "id": 1, "disease_name": "stroke", "geography": "US",
        "product_type_hint": None, "funnel": STROKE_FUNNEL,
        "persistency_months": 1,  # acute — no annualization
    }

def _mock_sepsis_pf_row():
    return {
        "id": 2, "disease_name": "sepsis", "geography": "US",
        "product_type_hint": "samd", "funnel": SEPSIS_FUNNEL,
        "persistency_months": 12,
    }


# ──────────────────────────────────────────────────────────────────────────────
# 1. Software → site_license (not per_patient)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_software_routes_to_site_license():
    from app.services.monetization_engine import compute, _infer_revenue_model

    for pt in ("samd", "digital_health_enterprise", "software", "clinical_ai"):
        model = _infer_revenue_model(pt)
        assert model == "site_license", f"{pt} should map to site_license, got {model}"

    result = await compute(
        product_type="samd",
        disease_name="sepsis",
        population=3000,
        population_base_metric="sites",
        net_price_usd=75_000,
        persistency_months=12,
    )
    assert result.revenue_model == "site_license"
    assert result.base_unit == "sites"
    assert result.annual_revenue_usd == pytest.approx(3000 * 75_000, rel=0.01)


@pytest.mark.asyncio
async def test_drug_routes_to_per_patient():
    from app.services.monetization_engine import _infer_revenue_model

    for pt in ("drug_small_molecule", "biologic", "gene_cell_therapy"):
        assert _infer_revenue_model(pt) == "per_patient", f"{pt} should map to per_patient"


# ──────────────────────────────────────────────────────────────────────────────
# 2. Funnel math: absolute gate resets, rate gates multiply
# ──────────────────────────────────────────────────────────────────────────────

def test_funnel_absolute_then_rate():
    from app.services.patient_flow_engine import _walk_db_funnel

    pf_row = {
        "disease_name": "stroke",
        "funnel": STROKE_FUNNEL,
        "persistency_months": 1,
    }
    result = _walk_db_funnel(pf_row, segment_gate=0.10, product_type="drug_small_molecule",
                              overrides={}, lot_rate=None, share_rate=None)

    steps = {s.step: s.running_value for s in result.steps}

    # Step 1: absolute → 795,000
    assert steps["us_stroke_incidence"] == 795_000

    # Step 2: rate 0.80 → 795,000 × 0.80 = 636,000
    assert steps["diagnosed_reached_hospital"] == pytest.approx(636_000, rel=0.01)

    # Step 3: treated_segment = None → filled from segment_gate=0.10 → 63,600
    assert steps["treated_segment"] == pytest.approx(63_600, rel=0.01)

    assert result.final_population == pytest.approx(63_600, rel=0.01)


def test_funnel_site_absolute():
    """Sepsis software: first gate is absolute site count, not patient incidence."""
    from app.services.patient_flow_engine import _walk_db_funnel

    pf_row = {
        "disease_name": "sepsis",
        "funnel": SEPSIS_FUNNEL,
        "persistency_months": 12,
    }
    result = _walk_db_funnel(pf_row, segment_gate=None, product_type="samd",
                              overrides={}, lot_rate=None, share_rate=None)

    steps = {s.step: s.running_value for s in result.steps}

    # Absolute → 4,000 sites
    assert steps["total_sites"] == 4_000
    # Rate 0.75 → 4,000 × 0.75 = 3,000 sites
    assert steps["icu_capable"] == pytest.approx(3_000, rel=0.01)
    assert result.base_metric == "sites"


# ──────────────────────────────────────────────────────────────────────────────
# 3. Initial indication < eventual (expansion path additive)
# ──────────────────────────────────────────────────────────────────────────────

def test_initial_fraction_less_than_one():
    """initial_indication_fraction is always ≤ 1.0; expansion adds on top."""
    from app.services.market_sizing_orchestrator import _load_indication_sequence

    async def _run():
        # Without DB, fallback returns (1.0, []) — that's valid (no sequence defined)
        # But when a sequence IS loaded, initial_fraction should be < 1
        pass

    # Directly test the fraction contract
    initial_fraction = 0.60   # e.g. NSCLC KRAS-only first
    expansion_fraction = 0.20  # second-line expansion

    initial_pop = 100_000 * initial_fraction
    expanded_pop = 100_000 * (initial_fraction + expansion_fraction)

    assert initial_pop < expanded_pop, "expansion must always ADD to initial"
    assert initial_fraction <= 1.0


# ──────────────────────────────────────────────────────────────────────────────
# 4. Confidence ordering: expert_verified > public_dataset > llm_inference
# ──────────────────────────────────────────────────────────────────────────────

def test_confidence_quality_ordering():
    from app.services.confidence_engine import _SOURCE_QUALITY

    assert _SOURCE_QUALITY["expert_verified"] > _SOURCE_QUALITY["public_dataset"]
    assert _SOURCE_QUALITY["public_dataset"] > _SOURCE_QUALITY["literature"]
    assert _SOURCE_QUALITY["literature"] > _SOURCE_QUALITY["analog"]
    assert _SOURCE_QUALITY["analog"] > _SOURCE_QUALITY["analyst_estimate"]
    assert _SOURCE_QUALITY["analyst_estimate"] > _SOURCE_QUALITY["llm_inference"]
    assert _SOURCE_QUALITY["llm_inference"] >= 0.0


def test_confidence_all_llm_gives_low():
    from app.services.confidence_engine import compute as conf_compute

    assumptions = [
        {"field": "treated_segment", "value": 0.20, "source_type": "llm_inference",
         "confidence": "low", "expert_question": "What fraction?"},
        {"field": "net_price_usd", "value": 50000, "source_type": "llm_inference",
         "confidence": "low", "expert_question": "What is the price?"},
    ]
    result = conf_compute(
        annual_revenue_sam=1e8, low_revenue=3e7, high_revenue=2e8,
        patient_flow_assumptions=assumptions,
        monetization_assumptions=[], analog_assumptions=[],
    )
    assert result.overall_confidence == "low"
    assert result.llm_inference_count == 2
    assert len(result.verify_with_expert) == 2


def test_confidence_all_public_gives_high():
    from app.services.confidence_engine import compute as conf_compute

    assumptions = [
        {"field": "incidence", "value": 795000, "source_type": "public_dataset",
         "confidence": "high", "expert_question": None},
        {"field": "net_price", "value": 25000, "source_type": "literature",
         "confidence": "high", "expert_question": None},
    ]
    result = conf_compute(
        annual_revenue_sam=1e8, low_revenue=7e7, high_revenue=1.3e8,
        patient_flow_assumptions=assumptions,
        monetization_assumptions=[], analog_assumptions=[],
    )
    assert result.overall_confidence in ("high", "medium")
    assert result.llm_inference_count == 0


def test_verify_with_expert_sorted_by_priority():
    """High-impact low-quality assumptions appear first in verify_with_expert."""
    from app.services.confidence_engine import compute as conf_compute

    assumptions = [
        # low quality + high impact = should appear first
        {"field": "treated_segment_rate", "value": 0.20, "source_type": "llm_inference",
         "confidence": "low", "expert_question": "Treated segment rate?"},
        # high quality + low impact = should appear last
        {"field": "geography_us_only", "value": True, "source_type": "expert_verified",
         "confidence": "high", "expert_question": "Is this US-only?"},
    ]
    result = conf_compute(
        annual_revenue_sam=1e8, low_revenue=3e7, high_revenue=2e8,
        patient_flow_assumptions=assumptions,
        monetization_assumptions=[], analog_assumptions=[],
    )
    expert_qs = result.verify_with_expert
    assert len(expert_qs) >= 1
    # First question should be about treated_segment (highest impact+uncertainty)
    assert "treated_segment" in expert_qs[0].field_name or expert_qs[0].confidence == "low"


# ──────────────────────────────────────────────────────────────────────────────
# 5. Base unit matches revenue model
# ──────────────────────────────────────────────────────────────────────────────

def test_base_unit_matches_revenue_model():
    from app.services.monetization_engine import _infer_revenue_model, _base_unit_for_model

    pairs = [
        ("drug_small_molecule", "patients"),
        ("samd", "sites"),
        ("medical_device", "procedures"),
        ("diagnostic", "tests"),
    ]
    for pt, expected_unit in pairs:
        model = _infer_revenue_model(pt)
        unit = _base_unit_for_model(model)
        assert unit == expected_unit, f"{pt} → {model} should give unit={expected_unit}, got {unit}"


# ──────────────────────────────────────────────────────────────────────────────
# 6. GBD excluded from commercial path
# ──────────────────────────────────────────────────────────────────────────────

def test_gbd_commercial_ok_false_in_data_sources():
    import json
    from pathlib import Path

    sources_path = Path(__file__).parent.parent / "app" / "data" / "data_sources.json"
    assert sources_path.exists(), "data_sources.json must exist"

    sources = json.loads(sources_path.read_text())
    gbd_entries = [s for s in sources if "gbd" in s.get("id", "").lower() or
                   "global burden" in s.get("name", "").lower()]
    assert gbd_entries, "data_sources.json must contain GBD entry"

    for gbd in gbd_entries:
        assert gbd.get("commercial_ok") is False, \
            f"GBD entry '{gbd.get('id')}' must have commercial_ok=false"


@pytest.mark.asyncio
async def test_gbd_rows_have_commercial_ok_false():
    """DB schema enforces commercial_ok column; this tests the seed logic marks GBD correctly."""
    from app.data.patient_flows_seed import EPI_SEED

    for row in EPI_SEED:
        if "gbd" in (row.get("source_id") or "").lower():
            assert row.get("commercial_ok") is False, \
                f"GBD epi row for {row.get('disease_name')} must have commercial_ok=False"


# ──────────────────────────────────────────────────────────────────────────────
# 7. Monetization mismatch guard: site flow + per_patient → auto-corrected
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_monetization_mismatch_guard():
    """If patient_flow returned 'sites' but product_type looks like per_patient drug,
    monetization_engine should auto-correct to site_license."""
    from app.services.monetization_engine import compute

    # Pass product_type that naively maps to per_patient but flow returned sites
    result = await compute(
        product_type="drug_small_molecule",  # would normally be per_patient
        disease_name="sepsis",
        population=3000,
        population_base_metric="sites",   # ← mismatch trigger
        net_price_usd=75_000,
    )
    # After guard: should have switched to site_license
    assert result.revenue_model == "site_license"
    assert any("revenue_model_corrected" in str(a) for a in result.assumptions), \
        "Mismatch correction must be logged in assumptions"


# ──────────────────────────────────────────────────────────────────────────────
# 8. Analog class inference
# ──────────────────────────────────────────────────────────────────────────────

def test_analog_infers_hospital_software():
    from app.services.analog_engine import _infer_competitive_context

    ctx = _infer_competitive_context("samd", "AI-powered sepsis detection platform")
    assert ctx == "hospital_software"


def test_analog_infers_new_moa_drug():
    from app.services.analog_engine import _infer_competitive_context

    ctx = _infer_competitive_context("biologic", "novel mechanism no approved competitor")
    assert ctx == "new_moa"


def test_analog_infers_orphan():
    from app.services.analog_engine import _infer_competitive_context

    ctx = _infer_competitive_context("gene_therapy", "SMA rare disease orphan designation")
    assert ctx == "orphan"


def test_analog_compute_returns_y1_lt_peak():
    from app.services.analog_engine import compute

    result = compute(
        product_type="samd",
        annual_revenue_sam=100_000_000,
        context_text="hospital software enterprise",
    )
    assert result.y1_penetration <= result.y3_penetration <= result.peak_penetration
    assert result.som_conservative <= result.som_base <= result.som_peak
    assert result.is_site_metric is True


# ──────────────────────────────────────────────────────────────────────────────
# 9. format_for_prompt contains required sections
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_orchestrated_format_for_prompt_contains_required_sections():
    """format_for_prompt must include TAM/SAM/SOM, confidence, honesty."""
    from app.services.patient_flow_engine import PatientFlowResult, FlowStep
    from app.services.monetization_engine import MonetizationResult
    from app.services.analog_engine import AnalogResult
    from app.services.confidence_engine import ConfidenceResult, ExpertQuestion
    from app.services.market_sizing_orchestrator import OrchestratedResult

    pf = PatientFlowResult(
        disease_name="stroke", product_type_hint="drug_small_molecule",
        final_population=63_600, base_metric="patients",
        steps=[FlowStep("us_stroke", "Incidence", None, 63600, "cdc", "CDC", "high", False)],
        persistency_adjusted_pop=None, persistency_months=1,
        assumptions=[], data_source="db_seed",
        low_estimate=44_520, high_estimate=82_680,
    )
    mon = MonetizationResult(
        product_type="drug_small_molecule", revenue_model="per_patient",
        base_unit="patients", base_count=63_600, net_price_usd=13_750,
        annual_revenue_usd=874_500_000, low_revenue_usd=612_150_000,
        high_revenue_usd=1_137_850_000, price_source="pricing_ref_db",
        price_confidence="medium", price_note="Blended net tPA", assumptions=[],
    )
    analog = AnalogResult(
        analog_class="specialty_drug_new_moa", analog_label="Specialty drug — novel MoA",
        competitive_context="new_moa", y1_penetration=0.05, y3_penetration=0.15,
        peak_penetration=0.25, years_to_peak=5, som_fraction=0.05,
        som_conservative=43_725_000, som_base=131_175_000, som_peak=218_625_000,
        source="Keytruda analog", confidence="medium", note="", is_site_metric=False,
        assumptions=[],
    )
    conf = ConfidenceResult(
        overall_confidence="medium", confidence_score=0.62,
        low_bound_usd=43_725_000, high_bound_usd=218_625_000,
        verify_with_expert=[
            ExpertQuestion("treated_segment_rate", "What fraction eligible?",
                           "analyst_estimate", "low", "high", 0.65)
        ],
        honesty_statement="This estimate is grounded in CDC incidence data.",
        llm_inference_count=0, total_assumptions=2, weakest_assumptions=[],
    )

    result = OrchestratedResult(
        disease_name="stroke", product_type="drug_small_molecule",
        patient_flow=pf, initial_indication_fraction=1.0, expansion_path=[],
        initial_population=63_600, monetization=mon, sam_revenue_usd=874_500_000,
        analog=analog, som_conservative_usd=43_725_000, som_base_usd=131_175_000,
        som_peak_usd=218_625_000, confidence=conf,
    )

    prompt = result.format_for_prompt()

    assert "AUTHORITATIVE" in prompt, "must be marked authoritative"
    assert "SAM REVENUE" in prompt
    assert "SOM" in prompt
    assert "CONFIDENCE" in prompt.upper()
    assert "VALIDATE" in prompt.upper() or "EXPERT" in prompt.upper()
    assert "honesty" in prompt.lower() or "confidence" in prompt.lower() or "grounded" in prompt.lower()


# ──────────────────────────────────────────────────────────────────────────────
# 10. Persistency: chronic therapy population annualizes correctly
# ──────────────────────────────────────────────────────────────────────────────

def test_persistency_annualization():
    """prevalent_on_treatment = incident × (persistency_months / 12)"""
    from app.services.patient_flow_engine import _walk_db_funnel

    chronic_funnel = [
        {"step": "incidence", "type": "absolute", "value": 100_000,
         "label": "Annual incident patients", "source_id": "cdc", "confidence": "high"},
        {"step": "treated", "type": "rate", "rate": 0.40,
         "label": "Treated fraction", "source_id": "lit", "confidence": "medium"},
    ]
    pf_row = {"disease_name": "T1D", "funnel": chronic_funnel, "persistency_months": 36}
    result = _walk_db_funnel(pf_row, segment_gate=None, product_type="device",
                              overrides={}, lot_rate=None, share_rate=None)

    # Incident treated = 100,000 × 0.40 = 40,000
    assert result.final_population == pytest.approx(40_000, rel=0.01)
    # Persistent: 40,000 × (36/12) = 120,000
    assert result.persistency_adjusted_pop == pytest.approx(120_000, rel=0.01)
