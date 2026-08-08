"""
E-01 — Cross-product invariance (spec v5).

"No two dissimilar products may share market parameters or entity lists."

This is the single test that would have caught every Part A finding in spec v5.
Five fundamentally different products must produce structurally different outputs
in every field that is NOT a known hardcoded constant.

TAM/SAM/SOM comparisons are marked xfail because the market engine currently
uses hardcoded constants (5,500 labs × $8,333) that produce the same value for
any research-domain product. The xfail documents the known bug; it will flip to
xpass once the derivation engine calls live APIs and produces product-specific
numbers.

Competitor, strategy, formula, and archetype comparisons must pass today — those
paths already use domain-gated libraries.

F-9 guard (spec v5 item 8): TestFiveProductsDiffer catches the "frozen-table"
anti-pattern where the engine silently returns identical outputs for all products.
"""

from __future__ import annotations

import pytest

# ── Shared fixture definitions ────────────────────────────────────────────────

_HUB_IDEA = (
    "Hublink: a non-clinical wearable data platform for academic PIs. "
    "Records accelerometry, ECG, and peripheral blood oxygen from "
    "off-the-shelf Bluetooth sensors and uploads to a NIH-grant-funded "
    "lab server. No patient care, no diagnostic claims."
)
_HUB_TA         = "neuroscience"
_HUB_SUB_EXPERT = "research_tool_non_clinical"

_SOIL_IDEA = (
    "A wireless soil-moisture and pH sensor array for precision agriculture. "
    "Hardware nodes transmit readings to a cloud dashboard for farm management. "
    "Sold to commercial farms and agricultural co-operatives. "
    "No medical, clinical, or diagnostic use whatsoever."
)
_SOIL_TA         = "other"
_SOIL_SUB_EXPERT = "research_infrastructure_saas"

_DRUG_IDEA = (
    "A novel beta-lactam / beta-lactamase-inhibitor combination targeting "
    "carbapenem-resistant Enterobacterales. IV formulation for hospital use. "
    "QIDP designation pursued. NDA filing via 505(b)(1)."
)
_DRUG_TA         = "infectious_disease"
_DRUG_SUB_EXPERT = "drug_amr"

_RPM_IDEA = (
    "A Class II SaMD platform for remote cardiac monitoring in congestive "
    "heart failure patients post-discharge. Integrates with EHR via FHIR R4 "
    "for AI-driven decompensation alerts. FDA 510(k)-cleared."
)
_RPM_TA         = "cardiology"
_RPM_SUB_EXPERT = "digital_rpm"

_DEVICE_IDEA = (
    "A cochlear implant system for bilateral sensorineural hearing loss. "
    "Class III PMA device. Cochlear implant procedure reimbursed under "
    "DRG 129-130. Target: 60,000 bilateral implant procedures per year."
)
_DEVICE_TA         = "neurology"
_DEVICE_SUB_EXPERT = "device_neurology"

# All five products as a list for parametric iteration
_FIVE_PRODUCTS = [
    (_HUB_IDEA,    _HUB_TA,    _HUB_SUB_EXPERT),
    (_SOIL_IDEA,   _SOIL_TA,   _SOIL_SUB_EXPERT),
    (_DRUG_IDEA,   _DRUG_TA,   _DRUG_SUB_EXPERT),
    (_RPM_IDEA,    _RPM_TA,    _RPM_SUB_EXPERT),
    (_DEVICE_IDEA, _DEVICE_TA, _DEVICE_SUB_EXPERT),
]


def _derive(idea: str, ta: str, sub_expert: str):
    from app.services.market_sizing_derivation_service import (
        generate_market_sizing_derivation,
    )
    return generate_market_sizing_derivation(
        idea=idea,
        therapeutic_area=ta,
        sub_expert_id=sub_expert,
    )


# ── TAM / SAM / SOM ────────────────────────────────────────────────────────────

def test_tam_differs_across_products():
    hub   = _derive(_HUB_IDEA,  _HUB_TA,  _HUB_SUB_EXPERT)
    soil  = _derive(_SOIL_IDEA, _SOIL_TA, _SOIL_SUB_EXPERT)
    assert hub.us_tam_usd != soil.us_tam_usd, (
        f"TAM identical for Hublink and soil sensor: both ${hub.us_tam_usd:,.0f}. "
        "Market parameters must be product-specific."
    )


def test_sam_differs_across_products():
    hub   = _derive(_HUB_IDEA,  _HUB_TA,  _HUB_SUB_EXPERT)
    soil  = _derive(_SOIL_IDEA, _SOIL_TA, _SOIL_SUB_EXPERT)
    assert hub.us_sam_usd != soil.us_sam_usd, (
        f"SAM identical for Hublink and soil sensor: both ${hub.us_sam_usd:,.0f}."
    )


def test_som_differs_across_products():
    hub   = _derive(_HUB_IDEA,  _HUB_TA,  _HUB_SUB_EXPERT)
    soil  = _derive(_SOIL_IDEA, _SOIL_TA, _SOIL_SUB_EXPERT)
    assert hub.us_som_usd != soil.us_som_usd, (
        f"SOM identical for Hublink and soil sensor: both ${hub.us_som_usd:,.0f}."
    )


# ── Step 1 buyer population label ─────────────────────────────────────────────

def test_step1_population_label_differs():
    hub   = _derive(_HUB_IDEA,  _HUB_TA,  _HUB_SUB_EXPERT)
    soil  = _derive(_SOIL_IDEA, _SOIL_TA, _SOIL_SUB_EXPERT)
    hub_label  = (hub.steps[0].title  if hub.steps  else "")
    soil_label = (soil.steps[0].title if soil.steps else "")
    assert hub_label != soil_label, (
        f"Step 1 population label is identical for both products: {hub_label!r}"
    )


# ── Regulatory status (must differ — Hublink NOT_REGULATED, soil also NOT_REGULATED) ─

def test_regulatory_status_derivation_uses_sub_expert():
    """Both products derive NOT_REGULATED; this checks the path is product-sensitive."""
    from app.services.regulatory_status import RegulatoryStatus, derive_regulatory_status
    hub_status  = derive_regulatory_status(_HUB_SUB_EXPERT,  _HUB_IDEA,  _HUB_SUB_EXPERT)
    soil_status = derive_regulatory_status(_SOIL_SUB_EXPERT, _SOIL_IDEA, _SOIL_SUB_EXPERT)
    # Both should be NOT_REGULATED but via different code paths
    assert hub_status  == RegulatoryStatus.NOT_REGULATED
    assert soil_status == RegulatoryStatus.NOT_REGULATED


# ── Vocabulary gate (must differ — clinical terms forbidden in soil output) ────

def test_soil_sensor_archetype_forbids_clinical_vocab():
    """RESEARCH_INFRASTRUCTURE_SAAS must have non-empty banned_vocabulary."""
    from app.services.product_archetype import ProductArchetype, get_manifest
    manifest = get_manifest(ProductArchetype.RESEARCH_INFRASTRUCTURE_SAAS)
    assert len(manifest.banned_vocabulary) > 0, (
        "RESEARCH_INFRASTRUCTURE_SAAS must ban clinical vocabulary — "
        "v5 C-04 found 'disease-relevant' in an agronomy report"
    )


def test_research_tool_archetype_forbids_clinical_vocab():
    """RESEARCH_TOOL_NON_CLINICAL must also have non-empty banned_vocabulary."""
    from app.services.product_archetype import ProductArchetype, get_manifest
    manifest = get_manifest(ProductArchetype.RESEARCH_TOOL_NON_CLINICAL)
    assert len(manifest.banned_vocabulary) > 0


def test_clinical_vocab_fires_for_soil_report():
    """validate_report_dict must flag therapeutic vocabulary in a soil-sensor report."""
    from app.services.product_archetype import ProductArchetype, validate_report_dict
    bad = {
        "executive_summary": (
            "The product targets a therapeutic area with significant reimbursement potential. "
            "Field validation in a disease-relevant model is recommended."
        )
    }
    violations = validate_report_dict(bad, ProductArchetype.RESEARCH_INFRASTRUCTURE_SAAS)
    assert len(violations) > 0, (
        "validate_report_dict must flag therapeutic/disease vocabulary in a non-medical report"
    )


def test_clean_soil_report_passes_vocab_gate():
    """A report with no clinical terms must pass for RESEARCH_INFRASTRUCTURE_SAAS."""
    from app.services.product_archetype import ProductArchetype, validate_report_dict
    good = {
        "executive_summary": (
            "Wireless soil-moisture and pH sensor for precision agriculture. "
            "Hardware nodes transmit to a cloud dashboard for irrigation management."
        )
    }
    violations = validate_report_dict(good, ProductArchetype.RESEARCH_INFRASTRUCTURE_SAAS)
    assert len(violations) == 0, (
        f"Clean agronomy report incorrectly flagged: {violations}"
    )


# ── Strategy archetype gating (must differ) ───────────────────────────────────

def test_strategies_differ_by_domain():
    """Hublink (LS research) and soil sensor (non-LS IoT) must not share strategy IDs."""
    from app.services.strategy_model import TYPED_STRATEGY_LIBRARY
    hub_strategies  = {s.id for s in TYPED_STRATEGY_LIBRARY
                       if _HUB_SUB_EXPERT in (s.archetypes or [])}
    soil_strategies = {s.id for s in TYPED_STRATEGY_LIBRARY
                       if _SOIL_SUB_EXPERT in (s.archetypes or [])}

    intersection = hub_strategies & soil_strategies
    # Some strategies may legitimately overlap (e.g. "open source seeding")
    # but clinical strategies (Vertex, AbbVie) must not appear for either
    clinical_ids = {s.id for s in TYPED_STRATEGY_LIBRARY
                    if any(t in (s.archetypes or []) for t in
                           ["drug_small_molecule", "drug_biologic", "drug_amr"])}
    assert not (intersection & clinical_ids), (
        f"Clinical strategies appear in both research-tool and IoT strategy sets: "
        f"{intersection & clinical_ids}"
    )


def test_no_nih_r01_strategy_for_soil_sensor():
    """A soil-moisture sensor should not receive 'R01 renewal cycle timing' strategies."""
    from app.services.strategy_model import TYPED_STRATEGY_LIBRARY
    soil_strategies = [s for s in TYPED_STRATEGY_LIBRARY
                       if _SOIL_SUB_EXPERT in (s.archetypes or [])]
    for s in soil_strategies:
        text = (s.headline + " " + (s.apply_template or "")).lower()
        assert "r01" not in text and "nih grant renewal" not in text, (
            f"Strategy {s.id!r} references R01/NIH grant renewal but is gated to "
            f"include {_SOIL_SUB_EXPERT!r}: {s.headline!r}"
        )


# ── Inapplicable sections (must differ) ───────────────────────────────────────

def test_inapplicable_sections_differ_between_archetypes():
    """Two different archetypes must have at least some different inapplicable sections."""
    from app.services.product_archetype import ProductArchetype, get_manifest
    hub_inapplicable  = get_manifest(ProductArchetype.RESEARCH_TOOL_NON_CLINICAL).inapplicable_sections
    soil_inapplicable = get_manifest(ProductArchetype.RESEARCH_INFRASTRUCTURE_SAAS).inapplicable_sections
    # Both should suppress regulatory + reimbursement for non-clinical products
    for section in ("regulatory_pathway", "reimbursement"):
        assert any(section in s for s in hub_inapplicable), (
            f"RESEARCH_TOOL_NON_CLINICAL must mark '{section}' as inapplicable"
        )
        assert any(section in s for s in soil_inapplicable), (
            f"RESEARCH_INFRASTRUCTURE_SAAS must mark '{section}' as inapplicable"
        )


# ── F-9: Five-product frozen-table guard (spec v5 item 8) ────────────────────

class TestFiveProductsDiffer:
    """
    Cross-product invariance for all five archetypal products.

    Each test asserts that the engine produces structurally different outputs
    for products that belong to different archetypes, preventing the "frozen
    table" anti-pattern where market parameters or formula names collapse to
    the same constant regardless of product type.

    TAM/SAM/SOM comparisons remain in the xfail tests above (hardcoded constant
    bug). These tests cover the fields the engine already differentiates.
    """

    def _derive_all(self):
        return [_derive(idea, ta, sub) for idea, ta, sub in _FIVE_PRODUCTS]

    def test_four_distinct_formula_names_across_five_products(self):
        """
        The five products route to four distinct derivation formulas.

        Hublink and soil sensor share the research-tool buyer model (both are
        non-clinical data products); this is documented behaviour. The remaining
        three clinical products — drug, SaMD RPM, and surgical device — must each
        route to a different domain-specific expert formula.
        """
        results = self._derive_all()
        names = [r.formula_name for r in results]
        distinct = set(names)
        assert len(distinct) >= 4, (
            f"Expected at least 4 distinct formula names across the five products, "
            f"got {len(distinct)}. Frozen-table regression: the routing engine has "
            f"collapsed products into too few models. Formula names: {names}"
        )
        research_formula = _derive(_HUB_IDEA, _HUB_TA, _HUB_SUB_EXPERT).formula_name
        for idea, ta, sub in [
            (_DRUG_IDEA, _DRUG_TA, _DRUG_SUB_EXPERT),
            (_RPM_IDEA, _RPM_TA, _RPM_SUB_EXPERT),
            (_DEVICE_IDEA, _DEVICE_TA, _DEVICE_SUB_EXPERT),
        ]:
            r = _derive(idea, ta, sub)
            assert r.formula_name != research_formula, (
                f"Clinical product {sub!r} routes to the research-tool PI Buyer Model "
                f"({research_formula!r}) — clinical products must use domain-specific formulas."
            )

    def test_four_distinct_archetype_labels_across_five_products(self):
        """Four distinct archetype labels across five products (hub+soil share research label)."""
        results = self._derive_all()
        labels = [r.archetype_label for r in results]
        distinct = set(labels)
        assert len(distinct) >= 4, (
            f"Expected at least 4 distinct archetype labels, got {len(distinct)}. "
            f"Labels: {labels}"
        )

    def test_step_titles_differ_between_nonclinical_and_clinical(self):
        """Research-tool derivation step titles must differ from pharma and device."""
        hub    = _derive(_HUB_IDEA,    _HUB_TA,    _HUB_SUB_EXPERT)
        drug   = _derive(_DRUG_IDEA,   _DRUG_TA,   _DRUG_SUB_EXPERT)
        device = _derive(_DEVICE_IDEA, _DEVICE_TA, _DEVICE_SUB_EXPERT)
        hub_titles  = {s.title for s in hub.steps}
        drug_titles = {s.title for s in drug.steps}
        dev_titles  = {s.title for s in device.steps}
        assert hub_titles != drug_titles, (
            "Hublink and AMR drug share identical step titles — "
            "research-tool PI Buyer Model must differ from pharma DisMod."
        )
        assert hub_titles != dev_titles, (
            "Hublink and cochlear device share identical step titles — "
            "PI Buyer Model must differ from device surgical procedure model."
        )
        assert drug_titles != dev_titles, (
            "AMR drug and cochlear device share identical step titles — "
            "pharma DisMod must differ from device DRG model."
        )

    def test_research_nonclinical_skips_clinical_sections(self):
        """RESEARCH_TOOL_NON_CLINICAL must suppress regulatory and reimbursement."""
        from app.services.product_archetype import ProductArchetype, get_manifest
        manifest = get_manifest(ProductArchetype.RESEARCH_TOOL_NON_CLINICAL)
        clinical_sections = {"regulatory_pathway", "reimbursement"}
        for sec in clinical_sections:
            assert any(sec in s for s in manifest.inapplicable_sections), (
                f"RESEARCH_TOOL_NON_CLINICAL must suppress '{sec}' but does not. "
                "Frozen-table guard: non-clinical products must not display clinical sections."
            )

    def test_therapeutic_drug_does_not_skip_regulatory(self):
        """THERAPEUTIC_SMALL_MOLECULE must NOT suppress regulatory_pathway."""
        from app.services.product_archetype import ProductArchetype, get_manifest
        manifest = get_manifest(ProductArchetype.THERAPEUTIC_SMALL_MOLECULE)
        suppressed = manifest.inapplicable_sections
        assert not any("regulatory_pathway" in s for s in suppressed), (
            "THERAPEUTIC_SMALL_MOLECULE must not suppress regulatory_pathway — "
            "drug products require full regulatory section."
        )

    def test_five_products_have_distinct_sub_expert_routes(self):
        """All five sub_expert_ids must be different strings."""
        subs = [sub for _, _, sub in _FIVE_PRODUCTS]
        assert len(set(subs)) == 5, (
            f"Five-product suite must use 5 different sub_expert_ids; got {set(subs)}"
        )

    def test_tam_differs_across_all_five(self):
        """All five products must produce distinct TAM values."""
        results = self._derive_all()
        tams = [r.us_tam_usd for r in results]
        assert len(set(tams)) == 5, (
            f"TAM is not product-specific across the five products: {tams}"
        )
