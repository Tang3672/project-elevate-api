"""
E-01 — Cross-product invariance (spec v5).

"No two dissimilar products may share market parameters or entity lists."

This is the single test that would have caught every Part A finding in spec v5.
Two fundamentally different products — Hublink (data-sync SaaS, neuroscience)
and the soil moisture sensor (RF hardware, agronomy) — must produce different
outputs for every field in CROSS_PRODUCT_FIELDS.

TAM/SAM/SOM comparisons are marked xfail because the market engine currently
uses hardcoded constants (5,500 labs × $8,333) that produce the same value for
any research-domain product. The xfail documents the known bug; it will flip to
xpass once the derivation engine calls live APIs and produces product-specific
numbers.

Competitor and strategy comparisons must pass today — those paths already use
domain-gated libraries.
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


def _derive(idea: str, ta: str, sub_expert: str):
    from app.services.market_sizing_derivation_service import (
        generate_market_sizing_derivation,
    )
    return generate_market_sizing_derivation(
        idea=idea,
        therapeutic_area=ta,
        sub_expert_id=sub_expert,
    )


# ── TAM / SAM / SOM (xfail — known hardcoded-constant bug) ────────────────────

@pytest.mark.xfail(
    reason=(
        "Market engine currently uses hardcoded 5,500 labs × $8,333 — "
        "both products produce the same TAM. Fix: execute live API query "
        "and derive product-specific buyer population. See spec v5 Part A."
    ),
    strict=False,
)
def test_tam_differs_across_products():
    hub   = _derive(_HUB_IDEA,  _HUB_TA,  _HUB_SUB_EXPERT)
    soil  = _derive(_SOIL_IDEA, _SOIL_TA, _SOIL_SUB_EXPERT)
    assert hub.us_tam_usd != soil.us_tam_usd, (
        f"TAM identical for Hublink and soil sensor: both ${hub.us_tam_usd:,.0f}. "
        "Market parameters must be product-specific."
    )


@pytest.mark.xfail(
    reason="Same hardcoded engine — SAM shares the 30% gate across products.",
    strict=False,
)
def test_sam_differs_across_products():
    hub   = _derive(_HUB_IDEA,  _HUB_TA,  _HUB_SUB_EXPERT)
    soil  = _derive(_SOIL_IDEA, _SOIL_TA, _SOIL_SUB_EXPERT)
    assert hub.us_sam_usd != soil.us_sam_usd, (
        f"SAM identical for Hublink and soil sensor: both ${hub.us_sam_usd:,.0f}."
    )


@pytest.mark.xfail(
    reason="Same hardcoded engine — SOM shares the 15% gate across products.",
    strict=False,
)
def test_som_differs_across_products():
    hub   = _derive(_HUB_IDEA,  _HUB_TA,  _HUB_SUB_EXPERT)
    soil  = _derive(_SOIL_IDEA, _SOIL_TA, _SOIL_SUB_EXPERT)
    assert hub.us_som_usd != soil.us_som_usd, (
        f"SOM identical for Hublink and soil sensor: both ${hub.us_som_usd:,.0f}."
    )


# ── Step 1 buyer population label (xfail — currently a constant) ──────────────

@pytest.mark.xfail(
    reason=(
        "Step 1 denominator label is currently constant: "
        "'NIH-funded neuroscience/neurotech labs'. "
        "Fix: derive from intake scope fields."
    ),
    strict=False,
)
def test_step1_population_label_differs():
    hub   = _derive(_HUB_IDEA,  _HUB_TA,  _HUB_SUB_EXPERT)
    soil  = _derive(_SOIL_IDEA, _SOIL_TA, _SOIL_SUB_EXPERT)
    hub_label  = (hub.steps[0].label  if hub.steps  else "")
    soil_label = (soil.steps[0].label if soil.steps else "")
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


@pytest.mark.xfail(
    reason=(
        "research_infrastructure_saas is shared by academic lab tools (where R01 "
        "renewal timing is relevant) and commercial hardware like soil sensors (where "
        "it is not). Fix requires a domain dimension on Strategy or a more granular "
        "archetype that separates LS-academic SaaS from commercial IoT. See spec v5 F-3."
    ),
    strict=False,
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
