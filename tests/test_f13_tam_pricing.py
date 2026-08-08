"""
F-13 — Domain-specific TAM pricing for research tools (spec v5 Part A).

Root cause: `_derive_research_tool_formula` always called
`academic_neurotech_lab_buyer()` regardless of product domain, producing the
same 5,500 labs × $8,333 TAM for every research-tool product.

Fix: `research_tool_buyer_for_domain(ta, idea)` in buyer_model.py returns
domain-specific population and spend parameters keyed by therapeutic_area.
This makes Hublink (neuroscience) and a soil sensor (agronomy) produce
different TAM, SAM, and SOM values, flipping the five E-01 xfails to passes.
"""

from __future__ import annotations

import pytest

from app.services.buyer_model import (
    _RESEARCH_TOOL_DOMAIN_PARAMS,
    research_tool_buyer_for_domain,
)
from app.services.market_sizing_derivation_service import generate_market_sizing_derivation

# ── Product fixtures (same as E-01) ──────────────────────────────────────────

_HUB_IDEA = (
    "Hublink is a cloud-based research data infrastructure platform. "
    "It provides passive, wireless data sync from lab instruments (e.g., running wheels, "
    "force plates) to a secure cloud repository for neuroscience PIs. "
    "No clinical indication."
)
_HUB_TA         = "neuroscience"
_HUB_SUB_EXPERT = "research_tool_non_clinical"

_SOIL_IDEA = (
    "A wireless soil moisture and nutrient sensor array for agronomy research. "
    "Target: university crop-science and ecology labs running multi-season field trials. "
    "Measures volumetric water content, N/P/K, and temperature at 1-hour intervals. "
    "No clinical or medical application."
)
_SOIL_TA         = "agronomy"
_SOIL_SUB_EXPERT = "research_infrastructure_saas"


def _derive(idea, ta, sub_expert):
    return generate_market_sizing_derivation(
        idea=idea, product_type=sub_expert,
        disease_name="", therapeutic_area=ta,
        sub_expert_id=sub_expert,
    )


# ── 1. Domain parameter table ─────────────────────────────────────────────────

def test_domain_params_table_exists_and_nonempty():
    assert len(_RESEARCH_TOOL_DOMAIN_PARAMS) >= 6, (
        "_RESEARCH_TOOL_DOMAIN_PARAMS must have at least 6 domains (including default)"
    )


def test_domain_params_has_default_key():
    assert "default" in _RESEARCH_TOOL_DOMAIN_PARAMS


@pytest.mark.parametrize("domain", [
    "neuroscience", "agronomy", "ecology", "genomics", "microbiology",
])
def test_required_domains_present(domain):
    assert domain in _RESEARCH_TOOL_DOMAIN_PARAMS, (
        f"Domain '{domain}' missing from _RESEARCH_TOOL_DOMAIN_PARAMS"
    )


@pytest.mark.parametrize("domain", [
    "neuroscience", "agronomy", "ecology", "genomics", "microbiology", "default",
])
def test_domain_params_have_required_keys(domain):
    p = _RESEARCH_TOOL_DOMAIN_PARAMS[domain]
    for key in ("pop_lo", "pop_hi", "sp_lo", "sp_hi", "cycle", "denominator", "funder"):
        assert key in p, f"Domain '{domain}' missing key '{key}'"


# ── 2. research_tool_buyer_for_domain factory ─────────────────────────────────

def test_buyer_for_neuroscience_uses_neuroscience_params():
    bm = research_tool_buyer_for_domain("neuroscience")
    p  = _RESEARCH_TOOL_DOMAIN_PARAMS["neuroscience"]
    assert bm.buyer_population_lo == p["pop_lo"]
    assert bm.buyer_population_hi == p["pop_hi"]


def test_buyer_for_agronomy_uses_agronomy_params():
    bm = research_tool_buyer_for_domain("agronomy")
    p  = _RESEARCH_TOOL_DOMAIN_PARAMS["agronomy"]
    assert bm.buyer_population_lo == p["pop_lo"]
    assert bm.buyer_population_hi == p["pop_hi"]


def test_neuroscience_population_larger_than_agronomy():
    neuro = research_tool_buyer_for_domain("neuroscience")
    agro  = research_tool_buyer_for_domain("agronomy")
    assert neuro.buyer_population_hi > agro.buyer_population_hi, (
        "Neuroscience has a larger NIH-funded lab pool than agronomy; "
        "agronomy is funded by NSF/USDA with smaller grant counts"
    )


def test_neuroscience_spend_higher_than_agronomy():
    neuro = research_tool_buyer_for_domain("neuroscience")
    agro  = research_tool_buyer_for_domain("agronomy")
    assert neuro.annualised_spend_hi() > agro.annualised_spend_hi(), (
        "NIH R01 budgets support higher instrument spend than USDA NIFA grants"
    )


def test_unknown_ta_returns_default_params():
    bm = research_tool_buyer_for_domain("completely_unknown_field_xyz")
    p  = _RESEARCH_TOOL_DOMAIN_PARAMS["default"]
    assert bm.buyer_population_lo == p["pop_lo"]
    assert bm.buyer_population_hi == p["pop_hi"]


def test_empty_ta_returns_default_params():
    bm = research_tool_buyer_for_domain("")
    p  = _RESEARCH_TOOL_DOMAIN_PARAMS["default"]
    assert bm.buyer_population_lo == p["pop_lo"]


def test_keyword_in_idea_text_routes_correctly():
    """'soil' in idea text should route to agronomy even with empty TA."""
    bm = research_tool_buyer_for_domain("", idea="wireless soil moisture sensor")
    p  = _RESEARCH_TOOL_DOMAIN_PARAMS["agronomy"]
    assert bm.buyer_population_lo == p["pop_lo"], (
        "Keyword 'soil' in idea should route to agronomy buyer params"
    )


def test_denominator_is_domain_specific():
    neuro = research_tool_buyer_for_domain("neuroscience")
    agro  = research_tool_buyer_for_domain("agronomy")
    assert neuro.population_denominator != agro.population_denominator, (
        "population_denominator must be domain-specific, not a constant string"
    )


def test_returns_independent_buyer_model_instances():
    """Two calls must return independent objects."""
    bm1 = research_tool_buyer_for_domain("neuroscience")
    bm2 = research_tool_buyer_for_domain("neuroscience")
    assert bm1 is not bm2


# ── 3. TAM / SAM / SOM invariance (flipped from xfail) ───────────────────────

def test_hub_and_soil_tam_differ():
    hub  = _derive(_HUB_IDEA,  _HUB_TA,  _HUB_SUB_EXPERT)
    soil = _derive(_SOIL_IDEA, _SOIL_TA, _SOIL_SUB_EXPERT)
    assert hub.us_tam_usd != soil.us_tam_usd, (
        f"TAM identical: hub=${hub.us_tam_usd:,.0f}, soil=${soil.us_tam_usd:,.0f}. "
        "Domain-specific buyer model must produce different population × spend."
    )


def test_hub_and_soil_sam_differ():
    hub  = _derive(_HUB_IDEA,  _HUB_TA,  _HUB_SUB_EXPERT)
    soil = _derive(_SOIL_IDEA, _SOIL_TA, _SOIL_SUB_EXPERT)
    assert hub.us_sam_usd != soil.us_sam_usd


def test_hub_and_soil_som_differ():
    hub  = _derive(_HUB_IDEA,  _HUB_TA,  _HUB_SUB_EXPERT)
    soil = _derive(_SOIL_IDEA, _SOIL_TA, _SOIL_SUB_EXPERT)
    assert hub.us_som_usd != soil.us_som_usd


def test_hub_tam_larger_than_soil_tam():
    """Neuroscience lab pool is larger; hub TAM should exceed soil TAM."""
    hub  = _derive(_HUB_IDEA,  _HUB_TA,  _HUB_SUB_EXPERT)
    soil = _derive(_SOIL_IDEA, _SOIL_TA, _SOIL_SUB_EXPERT)
    assert hub.us_tam_usd > soil.us_tam_usd, (
        f"Hub TAM ${hub.us_tam_usd:,.0f} should be larger than soil TAM ${soil.us_tam_usd:,.0f} "
        "(more NIH neurotech labs at higher spend than agronomy labs)"
    )


def test_step1_title_includes_domain():
    """Step 1 title must be domain-specific so reports read correctly."""
    hub  = _derive(_HUB_IDEA,  _HUB_TA,  _HUB_SUB_EXPERT)
    soil = _derive(_SOIL_IDEA, _SOIL_TA, _SOIL_SUB_EXPERT)
    assert hub.steps[0].title != soil.steps[0].title, (
        "Step 1 title must differ between products — domain label must appear in the title"
    )


# ── 4. archetype_label formula_overview reflect domain ────────────────────────

def test_formula_overview_contains_domain_population():
    """formula_overview must embed the domain-specific lab count, not a constant."""
    hub  = _derive(_HUB_IDEA,  _HUB_TA,  _HUB_SUB_EXPERT)
    soil = _derive(_SOIL_IDEA, _SOIL_TA, _SOIL_SUB_EXPERT)
    assert hub.formula_overview != soil.formula_overview, (
        "formula_overview must differ when buyer populations differ"
    )
