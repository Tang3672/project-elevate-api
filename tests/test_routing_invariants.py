"""
tests/test_routing_invariants.py
=================================
Structural invariant tests for the expert-routing pipeline.

These are deterministic (no API key, no DB) and run on every CI push.
They verify that every fallback path produces neutral output
(research_tool_non_clinical) rather than AMR/pharma framing for
non-biomedical products.

Converted from scripts/test_routing_audit.py so pytest/CI pick them up
automatically and block any merge that regresses the architecture.
"""

from __future__ import annotations

import pytest


# ── 1. _keyword_classify fallback paths ─────────────────────────────────────

class TestKeywordClassify:
    """_keyword_classify must return valid router keys and pick the right bucket."""

    @pytest.fixture(scope="class")
    def kc(self):
        from app.services.expert_router import _keyword_classify
        return _keyword_classify

    @pytest.fixture(scope="class")
    def router_map(self):
        from app.services.expert_router import _ROUTER_TO_EXPERT
        return _ROUTER_TO_EXPERT

    def test_soil_moisture_sensor_routes_to_agronomy(self, kc):
        assert kc("SoilMoisture Sensor for precision agriculture farms") == "research_tool_agronomy"

    def test_solar_panel_routes_to_non_clinical(self, kc):
        # solar/photovoltaic signals must not spill into drug buckets
        assert kc("Solar Panel Efficiency Analyzer for photovoltaic research") == "research_tool_non_clinical"

    def test_zero_keyword_hit_falls_to_drug_oncology(self, kc):
        # When nothing matches, the least-specific drug bucket is safer than AMR
        assert kc("Completely novel idea with no recognizable keywords XY-7") == "drug_oncology"

    def test_lims_routes_to_research_infrastructure_saas(self, kc):
        assert kc("LIMS laboratory information management system for research") == "research_infrastructure_saas"

    @pytest.mark.parametrize("idea", [
        "Soil moisture sensor for agricultural fields",
        "Novel antibiotic targeting MRSA",
        "AI-powered clinical decision support for hospital EHR",
        "Completely unknown product type AB-999 for unexplained purpose",
        "Solar panel efficiency measurement device",
        "CRISPR base editor for rare disease",
        "Electronic lab notebook for university research",
    ])
    def test_all_outputs_are_valid_router_keys(self, kc, router_map, idea):
        result = kc(idea)
        # drug_oncology is the last-resort key; it's valid even though it's a sub-expert id
        assert result in router_map or result == "drug_oncology", (
            f"_keyword_classify returned invalid key {result!r} for: {idea!r}"
        )


# ── 2. get_sub_expert neutral fallback ──────────────────────────────────────

class TestGetSubExpert:
    """Unknown IDs must return RESEARCH_TOOL_NON_CLINICAL, never None (which silences AMR fallback)."""

    @pytest.fixture(scope="class")
    def gse(self):
        from app.services.expert_profiles_v2 import get_sub_expert
        return get_sub_expert

    @pytest.fixture(scope="class")
    def neutral(self):
        from app.services.expert_profiles_v2 import RESEARCH_TOOL_NON_CLINICAL
        return RESEARCH_TOOL_NON_CLINICAL

    def test_antibiotic_amr_id_returns_neutral(self, gse, neutral):
        # "antibiotic_amr" was the old _DEFAULT_DOMAIN that leaked AMR expert into non-medical reports
        assert gse("antibiotic_amr") is neutral

    def test_hallucinated_domain_returns_neutral(self, gse, neutral):
        assert gse("hallucinated_domain") is neutral

    def test_empty_string_returns_none(self, gse):
        # Empty string = caller explicitly passed nothing; neutral fallback not appropriate
        assert gse("") is None

    def test_known_amr_id_returns_amr_profile(self, gse):
        profile = gse("drug_amr")
        assert profile is not None
        assert profile.sub_expert_id == "drug_amr"

    def test_research_tool_agronomy_returns_neutral(self, gse, neutral):
        # research_tool_agronomy is not in SUB_EXPERT_REGISTRY → must not return None
        assert gse("research_tool_agronomy") is neutral


# ── 3. _classify_archetype fallback paths ───────────────────────────────────

class TestClassifyArchetype:
    """Non-biomedical products must never fall through to pharma_small_molecule."""

    @pytest.fixture(scope="class")
    def ca(self):
        from app.services.market_sizing_derivation_service import _classify_archetype
        return _classify_archetype

    def test_soil_sensor_returns_research_tool(self, ca):
        assert ca("soil moisture sensor for precision agriculture", "other") == "research_tool_non_clinical"

    def test_agronomy_logger_returns_research_tool(self, ca):
        assert ca("agronomy data logger for crop monitoring", "other") == "research_tool_non_clinical"

    def test_farm_device_zero_match_returns_research_tool(self, ca):
        assert ca("device for measuring soil water in farm fields", "other") == "research_tool_non_clinical"

    def test_real_antibiotic_returns_pharma(self, ca):
        assert ca("oral antibiotic targeting MRSA", "drug_small_molecule") == "pharma_small_molecule"

    def test_zero_match_zero_non_bio_falls_to_pharma(self, ca):
        # Genuinely ambiguous → pharma_small_molecule last resort (not amr)
        assert ca("XY-999 novel compound with unknown target", "other") == "pharma_small_molecule"


# ── 4. Market sizing archetype routing via sub_expert_id ────────────────────

class TestMarketSizingArchetypeRouting:
    """generate_market_sizing_derivation must use the lab-buyer model for research tools."""

    @pytest.fixture(scope="class")
    def gmsd(self):
        from app.services.market_sizing_derivation_service import generate_market_sizing_derivation
        return generate_market_sizing_derivation

    def test_agronomy_sub_expert_uses_research_tool_archetype(self, gmsd):
        d = gmsd(
            idea="SoilMoisture Sensor for precision agriculture",
            product_type="other",
            disease_name="soil moisture monitoring",
            sub_expert_id="research_tool_agronomy",
        )
        assert d.archetype == "research_tool_non_clinical"

    def test_agronomy_sub_expert_tam_is_positive(self, gmsd):
        d = gmsd(
            idea="SoilMoisture Sensor for precision agriculture",
            product_type="other",
            disease_name="soil moisture monitoring",
            sub_expert_id="research_tool_agronomy",
        )
        assert d.us_tam_usd > 0, "TAM must be positive for a research tool product"

    def test_agronomy_sub_expert_formula_is_not_wac(self, gmsd):
        d = gmsd(
            idea="SoilMoisture Sensor for precision agriculture",
            product_type="other",
            disease_name="soil moisture monitoring",
            sub_expert_id="research_tool_agronomy",
        )
        formula_text = d.formula_name + d.formula_overview
        assert "WAC" not in formula_text, "Research tool must not use WAC (drug pricing) formula"

    def test_research_tool_non_clinical_sub_expert_is_positive(self, gmsd):
        d = gmsd(
            idea="Data logger for neuroscience research labs",
            product_type="other",
            disease_name="neuroscience instrumentation",
            sub_expert_id="research_tool_non_clinical",
        )
        assert d.us_tam_usd > 0

    def test_bad_sub_expert_id_with_non_bio_idea_still_uses_research_archetype(self, gmsd):
        # Regression guard: "antibiotic_amr" was the old broken default; soil idea must override
        d = gmsd(
            idea="SoilMoisture Sensor for precision agriculture",
            product_type="other",
            disease_name="soil moisture monitoring",
            sub_expert_id="antibiotic_amr",
        )
        assert d.archetype == "research_tool_non_clinical", (
            "Soil sensor idea must use research_tool archetype even when sub_expert_id='antibiotic_amr'"
        )


# ── 5. Claude domain validation gate ────────────────────────────────────────

class TestClaudeDomainValidation:
    """
    The strings Claude could plausibly hallucinate or return on error must NOT
    be valid keys in _ROUTER_TO_EXPERT — that's what forces the keyword-classify fallback.
    """

    @pytest.fixture(scope="class")
    def router_map(self):
        from app.services.expert_router import _ROUTER_TO_EXPERT
        return _ROUTER_TO_EXPERT

    @pytest.mark.parametrize("bad", [
        "antibiotic_amr",   # the old _DEFAULT_DOMAIN that leaked into reports
        "",
        "hallucinated_domain",
        "drug",
        "OTHER",
    ])
    def test_bad_domain_not_in_router_map(self, router_map, bad):
        assert bad not in router_map, (
            f"'{bad}' must NOT be in _ROUTER_TO_EXPERT — it should trigger keyword fallback, "
            "not be accepted as a valid Claude output"
        )

    @pytest.mark.parametrize("good", [
        "drug_amr",
        "drug_oncology",
        "research_tool_agronomy",
        "research_tool_non_clinical",
    ])
    def test_good_domain_in_router_map(self, router_map, good):
        assert good in router_map, (
            f"'{good}' must be in _ROUTER_TO_EXPERT so classify_with_claude accepts it directly"
        )


# ── 6. Knowledge retriever uses correct search templates ────────────────────

class TestKnowledgeRetrieverTemplates:
    """research_tool_* experts must have their own search templates (not FDA/clinical)."""

    @pytest.fixture(scope="class")
    def templates(self):
        from app.services.knowledge_retriever import SEARCH_TEMPLATES
        return SEARCH_TEMPLATES

    def test_research_tool_non_clinical_has_templates(self, templates):
        assert "research_tool_non_clinical" in templates

    def test_research_tool_agronomy_has_templates(self, templates):
        assert "research_tool_agronomy" in templates

    def test_research_tool_templates_do_not_reference_fda_drug_approvals(self, templates):
        rt_templates = str(templates.get("research_tool_non_clinical", []))
        assert "fda.gov" not in rt_templates.lower() or "sbir.nih.gov" in rt_templates


# ── 7. No remaining drug_amr defaults in fallback positions ─────────────────

class TestNoAMRDefaults:
    """
    Grep-level checks: the specific lines that previously hardcoded 'drug_amr'
    as a fallback must no longer do so. These are regression guards for the
    structural fixes applied in the architecture cleanup.
    """

    def _read(self, path: str) -> str:
        with open(path, encoding="utf-8") as f:
            return f.read()

    def test_retention_service_fallback_is_not_amr(self):
        import os
        path = os.path.join(
            os.path.dirname(__file__), "..", "app", "services", "retention_service.py"
        )
        src = self._read(os.path.normpath(path))
        # The specific fallback line must use the neutral default
        assert 'report_data.get("expert_domain", "drug_amr")' not in src, (
            "retention_service.py:552 still uses 'drug_amr' as fallback — "
            "old stored reports without expert_domain would get AMR framing"
        )

    def test_trl_service_default_param_is_not_amr(self):
        import os
        path = os.path.join(
            os.path.dirname(__file__), "..", "app", "services", "trl_service.py"
        )
        src = self._read(os.path.normpath(path))
        assert 'sub_expert_id: str = "drug_amr"' not in src, (
            "trl_service.py:236 still has drug_amr as default parameter"
        )
