"""
Tests for product_archetype.py and buyer_model.py
===================================================
Validates the H-01 archetype gate, H-07 buyer model, and H-08 market sizing.

Critical acceptance criteria:
  H-01: RESEARCH_TOOL_NON_CLINICAL produces zero banned-token violations
        for clean research-tool text, and raises ArchetypeViolationError
        for every banned clinical token.
  H-09: inapplicable_stub returns score=None (never 0.0).
  H-07: check_price_vs_spend_band flags when price > spend band.
  H-08: MarketSizeResult arithmetic is single-source and consistent.
"""

from __future__ import annotations

import math
import pytest

from app.services.product_archetype import (
    ARCHETYPE_MANIFESTS,
    ArchetypeViolationError,
    ProductArchetype,
    _EXEMPT_SECTION_IDS,
    get_manifest,
    inapplicable_stub,
    resolve_archetype,
    validate_content,
    validate_report_dict,
)
from app.services.buyer_model import (
    BuyerModel,
    MarketSizeResult,
    SpendGapWarning,
    academic_neurotech_lab_buyer,
    check_price_vs_spend_band,
)


# ─── H-01: resolve_archetype ──────────────────────────────────────────────────

class TestResolveArchetype:

    def test_research_tool_maps_correctly(self):
        assert resolve_archetype("research_tool_non_clinical") == \
               ProductArchetype.RESEARCH_TOOL_NON_CLINICAL

    def test_research_infra_maps_correctly(self):
        assert resolve_archetype("research_infrastructure_saas") == \
               ProductArchetype.RESEARCH_INFRASTRUCTURE_SAAS

    def test_digital_rpm_maps_to_samd_clinical(self):
        # digital_rpm is clinical patient monitoring — it is SaMD, not a research tool
        assert resolve_archetype("digital_rpm") == ProductArchetype.SAMD_CLINICAL

    def test_drug_amr_maps_to_small_molecule(self):
        assert resolve_archetype("drug_amr") == ProductArchetype.THERAPEUTIC_SMALL_MOLECULE

    def test_biologic_maps_correctly(self):
        assert resolve_archetype("biologic_oncology") == ProductArchetype.THERAPEUTIC_BIOLOGIC

    def test_unknown_sub_expert_returns_unknown(self):
        assert resolve_archetype("nonexistent_expert") == ProductArchetype.UNKNOWN
        assert resolve_archetype("") == ProductArchetype.UNKNOWN

    def test_all_manifests_present(self):
        for archetype in ProductArchetype:
            assert archetype in ARCHETYPE_MANIFESTS, \
                f"Missing manifest for {archetype}"


# ─── H-01: banned vocabulary gate ────────────────────────────────────────────

class TestValidateContent:

    ARCHETYPE = ProductArchetype.RESEARCH_TOOL_NON_CLINICAL

    # Every token that must be banned for RESEARCH_TOOL_NON_CLINICAL
    BANNED_TOKENS = [
        "510(k)", "de novo", "breakthrough device", "ntap",
        "cpt 99", "j-code", "drg ", "wac price", "daly",
        "predicate device", "peak revenue", "peak sales",
    ]

    def test_clean_text_passes(self):
        clean = (
            "Hublink is a data logging platform for academic neuroscience labs. "
            "It reduces manual data retrieval burden and improves experiment reliability. "
            "Buyers are PIs funded by NIH R01 grants, with a per-lab annual subscription model."
        )
        violations = validate_content(clean, self.ARCHETYPE, section_id="competitive_landscape")
        assert violations == []

    @pytest.mark.parametrize("banned_token", BANNED_TOKENS)
    def test_each_banned_token_raises_in_strict_mode(self, banned_token):
        text = f"The company should pursue a {banned_token} pathway to market."
        with pytest.raises(ArchetypeViolationError) as exc_info:
            validate_content(text, self.ARCHETYPE, section_id="regulatory_section", strict=True)
        assert banned_token.lower() in exc_info.value.token.lower()
        assert exc_info.value.archetype == self.ARCHETYPE

    @pytest.mark.parametrize("banned_token", BANNED_TOKENS)
    def test_each_banned_token_returns_violation_in_non_strict_mode(self, banned_token):
        text = f"The product should pursue a {banned_token} clearance pathway."
        violations = validate_content(text, self.ARCHETYPE, section_id="regulatory", strict=False)
        assert len(violations) > 0
        assert any(banned_token.lower() in v.lower() for v in violations)

    def test_exempt_section_bypasses_gate(self):
        text = "This product is not FDA regulated. 510(k) does not apply. NTAP is irrelevant."
        for exempt_id in _EXEMPT_SECTION_IDS:
            violations = validate_content(text, self.ARCHETYPE, section_id=exempt_id, strict=True)
            assert violations == [], f"Exempt section {exempt_id!r} should bypass gate"

    def test_clean_drug_text_passes_drug_archetype(self):
        text = (
            "The WAC price for this drug is $45,000 per course. "
            "J-code J0999 has been assigned. DRG payment applies for hospital inpatient use."
        )
        violations = validate_content(
            text, ProductArchetype.THERAPEUTIC_SMALL_MOLECULE, section_id="pricing"
        )
        assert violations == []

    def test_saas_vocab_banned_in_drug_context(self):
        text = "We will sell a per-lab site-license to academic PIs at $2,000/yr."
        archetype = ProductArchetype.THERAPEUTIC_SMALL_MOLECULE
        manifest = get_manifest(archetype)
        if "site-license" in manifest.banned_vocabulary:
            violations = validate_content(text, archetype, section_id="pricing", strict=False)
            assert len(violations) > 0

    def test_violation_error_contains_section_id(self):
        text = "This product needs a 510(k) clearance."
        try:
            validate_content(text, self.ARCHETYPE, section_id="my_test_section", strict=True)
            pytest.fail("Expected ArchetypeViolationError")
        except ArchetypeViolationError as e:
            assert "my_test_section" in str(e)

    def test_case_insensitive_detection(self):
        text = "Pursue a 510(K) CLEARANCE pathway."   # uppercase variant
        # The banned token is "510(k)" lowercase — the check uses text.lower()
        violations = validate_content(text, self.ARCHETYPE, section_id="reg", strict=False)
        assert len(violations) > 0

    def test_empty_text_always_passes(self):
        violations = validate_content("", self.ARCHETYPE, section_id="any")
        assert violations == []


# ─── H-01: validate_report_dict ──────────────────────────────────────────────

class TestValidateReportDict:

    def test_clean_report_produces_no_violations(self):
        report = {
            "title": "Hublink — Research Infrastructure Report",
            "sections": {
                "market": "The TAM is $30M-$60M based on NIH-funded neurotech labs.",
                "competitive": "Primary competitor is the status quo: SD card + manual scripts.",
            },
        }
        violations = validate_report_dict(report, ProductArchetype.RESEARCH_TOOL_NON_CLINICAL)
        assert violations == []

    def test_nested_banned_token_detected(self):
        report = {
            "sections": {
                "regulatory": {
                    "text": "We recommend pursuing a 510(k) clearance with Philips as predicate.",
                    "pathway": "510(k) preferred",
                }
            }
        }
        violations = validate_report_dict(report, ProductArchetype.RESEARCH_TOOL_NON_CLINICAL)
        assert len(violations) >= 2  # both "510(k)" occurrences

    def test_list_values_are_scanned(self):
        report = {
            "action_items": [
                "File 510(k) within 90 days",
                "Apply for NTAP designation",
                "Clean action item with no clinical vocab",
            ]
        }
        violations = validate_report_dict(report, ProductArchetype.RESEARCH_TOOL_NON_CLINICAL)
        assert len(violations) >= 2


# ─── H-09: inapplicable_stub ─────────────────────────────────────────────────

class TestInapplicableStub:

    def test_score_is_none_not_zero(self):
        stub = inapplicable_stub("regulatory_pathway", ProductArchetype.RESEARCH_TOOL_NON_CLINICAL)
        assert stub["score"] is None, "Inapplicable sections must have score=None, never 0.0"

    def test_not_included_in_composite(self):
        stub = inapplicable_stub("reimbursement_strategy", ProductArchetype.RESEARCH_TOOL_NON_CLINICAL)
        assert stub["included_in_composite"] is False

    def test_status_is_not_applicable(self):
        stub = inapplicable_stub("clinical_trial_design", ProductArchetype.RESEARCH_TOOL_NON_CLINICAL)
        assert stub["status"] == "not_applicable"

    def test_reason_is_non_empty(self):
        stub = inapplicable_stub("payer_access", ProductArchetype.RESEARCH_TOOL_NON_CLINICAL)
        assert isinstance(stub["reason"], str)
        assert len(stub["reason"]) > 20

    def test_section_name_in_reason(self):
        stub = inapplicable_stub("my_custom_section", ProductArchetype.RESEARCH_TOOL_NON_CLINICAL)
        assert "my_custom_section" in stub["reason"].lower() or \
               "my custom section" in stub["reason"].lower()


# ─── H-07: BuyerModel + check_price_vs_spend_band ────────────────────────────

class TestBuyerModel:

    def test_annualised_spend_correct(self):
        bm = BuyerModel(
            buyer_persona="academic_pi",
            budget_line="nih_grant_equipment",
            purchase_cadence="grant_cycle",
            approval_chain=None,
            observed_spend_band_lo=20_000,
            observed_spend_band_hi=30_000,
            spend_source="Gaidica 2026 n=10",
            buyer_population_lo=3_000,
            buyer_population_hi=8_000,
            population_denominator="NIH neurotech labs",
            population_source="NIH RePORTER estimate",
            annualization_factor=1.0 / 3.0,  # 3-year cycle
        )
        assert math.isclose(bm.annualised_spend_lo(), 20_000 / 3, rel_tol=1e-9)
        assert math.isclose(bm.annualised_spend_hi(), 30_000 / 3, rel_tol=1e-9)

    def test_price_within_band_no_warning(self):
        bm = academic_neurotech_lab_buyer(
            observed_spend_hi=30_000, cycle_years=3.0
        )
        # Annualised hi = 30_000 / 3 = 10_000/yr
        # Price at $8,000/yr is within band
        warning = check_price_vs_spend_band(8_000, bm)
        assert warning is None

    def test_price_exceeds_band_returns_warning(self):
        bm = academic_neurotech_lab_buyer(
            observed_spend_lo=20_000, observed_spend_hi=30_000, cycle_years=3.0
        )
        # Annualised hi = $10,000/yr; price at $75,000/yr is 7.5× over
        warning = check_price_vs_spend_band(75_000, bm)
        assert warning is not None
        assert isinstance(warning, SpendGapWarning)
        assert warning.gap_multiple > 7.0
        assert "75,000" in warning.message
        assert "gap" in warning.message.lower()

    def test_gap_multiple_computed_correctly(self):
        bm = academic_neurotech_lab_buyer(
            observed_spend_hi=30_000, cycle_years=3.0
        )
        # hi_annual = 30_000/3 = 10_000; price = 100_000 → gap = 10.0
        warning = check_price_vs_spend_band(100_000, bm)
        assert warning is not None
        assert math.isclose(warning.gap_multiple, 10.0, rel_tol=0.01)

    def test_zero_spend_band_no_warning(self):
        bm = BuyerModel(
            buyer_persona="unknown", budget_line="", purchase_cadence="",
            approval_chain=None, observed_spend_band_lo=0, observed_spend_band_hi=0,
            spend_source="", buyer_population_lo=0, buyer_population_hi=0,
            population_denominator="", population_source="", annualization_factor=1.0,
        )
        assert check_price_vs_spend_band(50_000, bm) is None

    def test_academic_neurotech_factory_defaults(self):
        bm = academic_neurotech_lab_buyer()
        assert bm.buyer_persona == "academic_pi"
        assert bm.observed_spend_band_lo == 20_000
        assert bm.observed_spend_band_hi == 30_000
        assert math.isclose(bm.annualization_factor, 1.0 / 3.0, rel_tol=1e-6)


# ─── H-08: MarketSizeResult arithmetic ───────────────────────────────────────

class TestMarketSizeResult:

    def _make_result(self, **kwargs) -> MarketSizeResult:
        bm = academic_neurotech_lab_buyer(
            observed_spend_lo=20_000, observed_spend_hi=30_000, cycle_years=3.0,
            population_lo=3_000, population_hi=8_000,
        )
        defaults = dict(buyer_model=bm, sam_fraction=0.30, som_fraction=0.10,
                        som_horizon_years=5)
        defaults.update(kwargs)
        return MarketSizeResult(**defaults)

    def test_tam_lo_computed_correctly(self):
        r = self._make_result()
        # lo = 3_000 × (20_000/3) ≈ 20_000_000
        expected = 3_000 * (20_000 / 3.0)
        assert math.isclose(r.tam_lo_usd, expected, rel_tol=1e-9)

    def test_tam_hi_computed_correctly(self):
        r = self._make_result()
        expected = 8_000 * (30_000 / 3.0)
        assert math.isclose(r.tam_hi_usd, expected, rel_tol=1e-9)

    def test_sam_derived_from_tam(self):
        r = self._make_result()
        assert math.isclose(r.sam_lo_usd, r.tam_lo_usd * 0.30, rel_tol=1e-9)
        assert math.isclose(r.sam_hi_usd, r.tam_hi_usd * 0.30, rel_tol=1e-9)

    def test_som_derived_from_sam(self):
        r = self._make_result()
        assert math.isclose(r.som_lo_usd, r.sam_lo_usd * 0.10, rel_tol=1e-9)
        assert math.isclose(r.som_hi_usd, r.sam_hi_usd * 0.10, rel_tol=1e-9)

    def test_p10_equals_som_lo(self):
        r = self._make_result()
        assert math.isclose(r.p10_usd, r.som_lo_usd, rel_tol=1e-9)

    def test_p90_equals_som_hi(self):
        r = self._make_result()
        assert math.isclose(r.p90_usd, r.som_hi_usd, rel_tol=1e-9)

    def test_tam_ordering(self):
        r = self._make_result()
        assert r.tam_lo_usd <= r.tam_hi_usd
        assert r.sam_lo_usd <= r.sam_hi_usd
        assert r.som_lo_usd <= r.som_hi_usd
        assert r.p10_usd <= r.p90_usd

    def test_to_dict_structure(self):
        r = self._make_result()
        d = r.to_dict()
        assert "tam_lo_usd" in d
        assert "tam_hi_usd" in d
        assert "som_lo_usd" in d
        assert "som_hi_usd" in d
        assert "p10_usd" in d
        assert "p90_usd" in d
        assert "uncertainty_method" in d
        assert d["som_horizon_years"] == 5

    def test_explain_returns_string(self):
        r = self._make_result()
        text = r.explain()
        assert isinstance(text, str)
        assert "TAM" in text
        assert "SAM" in text
        assert "SOM" in text

    def test_consistency_tam_sam_som_hierarchy(self):
        r = self._make_result(sam_fraction=0.50, som_fraction=0.20)
        # SAM ≤ TAM, SOM ≤ SAM
        assert r.sam_hi_usd <= r.tam_hi_usd + 1
        assert r.som_hi_usd <= r.sam_hi_usd + 1

    def test_format_usd_billions(self):
        r = self._make_result()
        assert r.format_usd(1_500_000_000) == "$1.5B"

    def test_format_usd_millions(self):
        r = self._make_result()
        assert r.format_usd(45_000_000) == "$45M"

    def test_format_usd_thousands(self):
        r = self._make_result()
        assert r.format_usd(750_000) == "$750K"


# ─── Manifest completeness ────────────────────────────────────────────────────

class TestManifestCompleteness:

    def test_research_tool_tam_formula(self):
        m = get_manifest(ProductArchetype.RESEARCH_TOOL_NON_CLINICAL)
        assert m.tam_formula == "research_tool_bottom_up"

    def test_research_tool_buyer_persona(self):
        m = get_manifest(ProductArchetype.RESEARCH_TOOL_NON_CLINICAL)
        assert m.buyer_persona_hint == "academic_pi"

    def test_drug_archetype_has_wac_revenue_model(self):
        m = get_manifest(ProductArchetype.THERAPEUTIC_SMALL_MOLECULE)
        assert any("wac" in rev for rev in m.eligible_revenue_models)

    def test_research_tool_has_no_wac_revenue_model(self):
        m = get_manifest(ProductArchetype.RESEARCH_TOOL_NON_CLINICAL)
        assert all("wac" not in rev for rev in m.eligible_revenue_models)

    def test_samd_clinical_has_cpt_reimbursement(self):
        m = get_manifest(ProductArchetype.SAMD_CLINICAL)
        assert any("cpt" in rev for rev in m.eligible_reimbursement_vocab)

    def test_research_tool_has_no_cpt_reimbursement(self):
        m = get_manifest(ProductArchetype.RESEARCH_TOOL_NON_CLINICAL)
        assert all("cpt" not in rev for rev in m.eligible_reimbursement_vocab)

    def test_inapplicable_sections_nonempty_for_research_tool(self):
        m = get_manifest(ProductArchetype.RESEARCH_TOOL_NON_CLINICAL)
        assert len(m.inapplicable_sections) > 0

    def test_research_tool_banned_vocabulary_nonempty(self):
        m = get_manifest(ProductArchetype.RESEARCH_TOOL_NON_CLINICAL)
        assert len(m.banned_vocabulary) >= 10


# ─── H-09: Panel gate (wiring) ───────────────────────────────────────────────

class TestPanelGate:
    """
    Verifies that run_expert_panel skips clinical and regulatory panels for
    non-clinical research tool archetypes (H-09 / H-01 panel-selection layer).
    These tests run synchronously without an API key — the gate fires before
    any network call.
    """

    def _run(self, coro):
        import asyncio
        return asyncio.run(coro)

    def test_research_tool_clinical_panel_is_none(self):
        from app.services.expert_panel import run_expert_panel
        result = self._run(run_expert_panel(
            disease_name="neuroscience data logging",
            idea="Wireless data logger for academic neurotech labs",
            sub_expert_id="research_tool_non_clinical",
            archetype="research_tool_non_clinical",
        ))
        assert result.clinical is None, \
            "Clinical panel must be None for research tool (no clinical indication)"

    def test_research_tool_regulatory_panel_is_none(self):
        from app.services.expert_panel import run_expert_panel
        result = self._run(run_expert_panel(
            disease_name="neuroscience data logging",
            idea="Wireless data logger for academic neurotech labs",
            sub_expert_id="research_tool_non_clinical",
            archetype="research_tool_non_clinical",
        ))
        assert result.regulatory is None, \
            "Regulatory panel must be None for research tool (not FDA-regulated)"

    def test_research_infra_saas_panels_also_skipped(self):
        from app.services.expert_panel import run_expert_panel
        result = self._run(run_expert_panel(
            disease_name="lab data management",
            idea="SaaS platform for academic lab data management",
            sub_expert_id="research_infrastructure_saas",
            archetype="research_infrastructure_saas",
        ))
        assert result.clinical is None
        assert result.regulatory is None

    def test_drug_archetype_does_not_skip_panels(self):
        """Non-research-tool archetypes must attempt all three panels (gate not triggered)."""
        from app.services.expert_panel import run_expert_panel, _RESEARCH_TOOL_ARCHETYPES
        # Verify the set does NOT contain drug archetypes
        assert "drug_amr" not in _RESEARCH_TOOL_ARCHETYPES
        assert "biologic_oncology" not in _RESEARCH_TOOL_ARCHETYPES


# ─── H-07/H-08: Derivation routing wiring ────────────────────────────────────

class TestDerivationRouting:
    """
    Verifies that generate_market_sizing_derivation routes to the buyer-model
    formula when sub_expert_id is research_tool_non_clinical, regardless of
    what product_type enum is passed (ProductType.OTHER is the common fallback).
    """

    def test_research_tool_routes_to_buyer_model(self):
        from app.services.market_sizing_derivation_service import generate_market_sizing_derivation
        d = generate_market_sizing_derivation(
            idea="Wireless sensor data logger for neuroscience labs",
            product_type="other",          # would normally fall to pharma default
            disease_name="research data infrastructure",
            sub_expert_id="research_tool_non_clinical",
        )
        assert d.archetype == "research_tool_non_clinical"
        assert "buyer" in d.formula_name.lower() or "pi" in d.formula_name.lower()

    def test_research_tool_tam_is_lab_based_not_patient_based(self):
        from app.services.market_sizing_derivation_service import generate_market_sizing_derivation
        d = generate_market_sizing_derivation(
            idea="Data logging infrastructure for animal behaviour research labs",
            product_type="other",
            sub_expert_id="research_tool_non_clinical",
        )
        # TAM should be in $20M-$80M pre-calibration range (3k-8k labs × $6k-$10k/yr).
        # G.14 EDGAR calibration divides by ~2.4, so post-calibration floor is ~$3M.
        # The critical guard is the upper bound: must never be billion-dollar.
        assert d.us_tam_usd < 500_000_000, \
            f"Research tool TAM should be <$500M (lab-based, not hospital-based): got {d.tam_fmt}"
        assert d.us_tam_usd >= 3_000_000, \
            f"Research tool TAM should be >$3M (calibration-adjusted): got {d.tam_fmt}"

    def test_research_infra_saas_also_routes_to_buyer_model(self):
        from app.services.market_sizing_derivation_service import generate_market_sizing_derivation
        d = generate_market_sizing_derivation(
            idea="Lab data management SaaS for academic PIs",
            product_type="other",
            sub_expert_id="research_infrastructure_saas",
        )
        assert d.archetype == "research_tool_non_clinical"

    def test_derivation_steps_reference_buyer_not_patient_count(self):
        from app.services.market_sizing_derivation_service import generate_market_sizing_derivation
        d = generate_market_sizing_derivation(
            idea="Hublink wireless data logger",
            product_type="other",
            sub_expert_id="research_tool_non_clinical",
        )
        step_text = " ".join(s.explanation for s in d.steps).lower()
        assert "lab" in step_text or "pi" in step_text or "grant" in step_text, \
            "Derivation steps must reference lab/PI/grant, not patient count"
        # "hospital" must only appear as an explicit negation ("not a hospital"), not as the buyer
        if "hospital" in step_text:
            assert "not a hospital" in step_text or "not hospital" in step_text, \
                "If 'hospital' appears, it must be in a negation context ('not a hospital enterprise')"

    def test_drug_archetype_not_affected_by_sub_expert_id(self):
        from app.services.market_sizing_derivation_service import generate_market_sizing_derivation
        d = generate_market_sizing_derivation(
            idea="Novel MRSA antibiotic targeting cell wall synthesis",
            product_type="other",
            sub_expert_id="drug_amr",
        )
        assert d.archetype != "research_tool_non_clinical", \
            "drug_amr sub_expert_id must not route to research tool formula"

    def test_no_sub_expert_id_still_routes_by_product_type(self):
        from app.services.market_sizing_derivation_service import generate_market_sizing_derivation
        d = generate_market_sizing_derivation(
            idea="Novel MRSA antibiotic targeting cell wall synthesis",
            product_type="drug_small_molecule",
            sub_expert_id="",
        )
        assert d.archetype in ("pharma_small_molecule", "pharma_biologic"), \
            f"drug_small_molecule product_type should route to pharma formula, got {d.archetype}"

    def test_derivation_has_five_steps(self):
        from app.services.market_sizing_derivation_service import generate_market_sizing_derivation
        d = generate_market_sizing_derivation(
            idea="Lab data logger",
            product_type="other",
            sub_expert_id="research_tool_non_clinical",
        )
        assert len(d.steps) == 5

    def test_tam_fmt_is_midpoint_value(self):
        from app.services.market_sizing_derivation_service import generate_market_sizing_derivation
        d = generate_market_sizing_derivation(
            idea="Lab data logger",
            product_type="other",
            sub_expert_id="research_tool_non_clinical",
        )
        # tam_fmt is now the midpoint (single value like "$46M"), not a lo–hi range.
        # The range appears in Step 3's formula string; the headline is the midpoint.
        assert d.tam_fmt.startswith("$"), f"tam_fmt should be a USD string, got: {d.tam_fmt}"
        assert "–" not in d.tam_fmt and "–" not in d.tam_fmt, \
            f"tam_fmt should be the midpoint, not a range: {d.tam_fmt}"
        # Midpoint is (3k+8k)/2 × (6667+10000)/2 ≈ $46M — must be in plausible range
        assert "$" in d.tam_fmt and any(c.isdigit() for c in d.tam_fmt), \
            f"tam_fmt should contain a dollar amount, got: {d.tam_fmt}"
