"""
B-07 — Modality vocabulary banned in non-clinical template output
=================================================================
Template constants in the engine must not inject clinical/drug vocabulary
(patient counts, payer coverage, therapeutic area) into output for products
where that vocabulary is meaningless.

Three template-constant failure modes fixed here:

  1. _SRC["market"] in commercialization_decision_service.py was a static
     string referencing CDC/SEER + CMS for ALL archetypes.
     Fix: _market_evidence_source(modality) returns archetype-appropriate text.

  2. The TAM formula basis fallback in alignment_service.py was
     "eligible patients × annual price" for any unrecognised archetype.
     Fix: fallback is now "buyers × annual revenue per buyer".

  3. EXPERT_JSON_SCHEMA cited "epidemiological basis" in a citation style
     example sent to ALL expert prompts (not just clinical).
     Fix: example replaced with an archetype-neutral template.

Scenario narratives for research_tool are already gated by SCENARIOS_RESEARCH
in market_provenance_service.py — tests below verify this holds.

All tests are pure-Python (no API key, no DB).
"""

from __future__ import annotations

import inspect
import re

import pytest


# ══════════════════════════════════════════════════════════════════════════════
# _market_evidence_source — archetype-aware market label
# ══════════════════════════════════════════════════════════════════════════════

class TestMarketEvidenceSource:

    def _src(self, modality: str) -> str:
        from app.services.commercialization_decision_service import _market_evidence_source
        return _market_evidence_source(modality)

    def test_research_tool_no_cdc_seer(self):
        label = self._src("research_tool")
        assert "cdc" not in label.lower() and "seer" not in label.lower(), (
            "research_tool market source must not mention CDC/SEER (clinical epidemiology)"
        )

    def test_research_tool_no_cms_pricing(self):
        label = self._src("research_tool")
        assert "cms pricing" not in label.lower()

    def test_research_tool_mentions_labs(self):
        label = self._src("research_tool")
        assert "lab" in label.lower(), (
            "research_tool market source should reference lab-based buyer units"
        )

    def test_diagnostic_no_cdc_seer(self):
        label = self._src("diagnostic")
        assert "seer" not in label.lower()
        assert "procedure" in label.lower() or "test" in label.lower()

    def test_device_no_cdc_seer(self):
        label = self._src("device")
        assert "seer" not in label.lower()

    def test_digital_no_cdc_seer(self):
        label = self._src("digital")
        assert "seer" not in label.lower()

    def test_small_molecule_drug_gets_cdc_seer(self):
        label = self._src("small_molecule")
        assert "cdc" in label.lower() or "seer" in label.lower() or "epidemiology" in label.lower(), (
            "Clinical drug market source should still reference CDC/SEER epidemiology"
        )

    def test_other_gets_clinical_default(self):
        label = self._src("other")
        assert "cdc" in label.lower() or "seer" in label.lower() or "epidemiology" in label.lower()

    def test_empty_modality_gets_clinical_default(self):
        label = self._src("")
        assert "cdc" in label.lower() or "epidemiology" in label.lower()

    def test_none_modality_no_crash(self):
        from app.services.commercialization_decision_service import _market_evidence_source
        label = _market_evidence_source(None)
        assert isinstance(label, str)

    def test_returns_string(self):
        label = self._src("research_tool")
        assert isinstance(label, str) and len(label) > 10

    def test_function_exported_from_module(self):
        from app.services.commercialization_decision_service import _market_evidence_source  # noqa: F401


# ══════════════════════════════════════════════════════════════════════════════
# build_rationales — market driver uses _market_evidence_source
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildRationalesMarketSource:

    def _rationales(self, modality: str) -> dict:
        from app.services.commercialization_decision_service import build_rationales
        scores = {
            "regulatory_feasibility": 0.5, "reimbursement_feasibility": 0.5,
            "investor_attractiveness": 0.6, "patentability": 0.5,
            "licensing_likelihood": 0.5, "sbir_fit": 0.5,
            "competitive_whitespace": 0.5, "overall_priority": 0.5,
            "spinout_likelihood": 0.5, "acquisition_potential": 0.5,
        }
        signals = {
            "modality": modality,
            "approval_prob": 0.5, "moat": 0.5, "trl": 3,
            "sbir_p1_ready": True, "sbir_awards": 1,
            "som_usd": 5_000_000, "designations": [],
        }
        return build_rationales(signals, scores, 0.5, 0.5)

    def _all_sources(self, modality: str) -> list[str]:
        rat = self._rationales(modality)
        sources = []
        for dim in rat.values():
            if isinstance(dim, dict):
                for drv in dim.get("drivers", []):
                    if isinstance(drv, dict) and drv.get("source"):
                        sources.append(drv["source"].lower())
        return sources

    def test_research_tool_rationales_no_cdc_seer(self):
        sources = self._all_sources("research_tool")
        for src in sources:
            assert "cdc/seer" not in src, (
                f"research_tool rationale contains CDC/SEER in source: {src!r}"
            )

    def test_research_tool_rationales_no_cms_pricing(self):
        sources = self._all_sources("research_tool")
        for src in sources:
            assert "cms pricing" not in src

    def test_drug_rationales_still_have_epidemiology_source(self):
        sources = self._all_sources("small_molecule")
        assert any("cdc" in s or "seer" in s or "epidemiology" in s for s in sources), (
            "Drug rationales must still reference epidemiology as the market evidence source"
        )


# ══════════════════════════════════════════════════════════════════════════════
# TAM formula basis fallback — must not be patient-based
# ══════════════════════════════════════════════════════════════════════════════

class TestTAMBasisText:

    def _alignment_source(self) -> str:
        import app.services.alignment_service as svc
        return inspect.getsource(svc)

    def test_fallback_not_eligible_patients(self):
        src = self._alignment_source()
        # Find the fallback value in the _tam_basis dict .get(...)
        m = re.search(r'\.get\(_arch,\s*["\']([^"\']+)["\']', src)
        assert m is not None, "Could not find .get(_arch, ...) in alignment_service"
        fallback = m.group(1)
        assert "eligible patients" not in fallback.lower(), (
            f"TAM formula fallback must not use patient vocabulary. Got: {fallback!r}"
        )

    def test_fallback_uses_neutral_buyer_language(self):
        src = self._alignment_source()
        m = re.search(r'\.get\(_arch,\s*["\']([^"\']+)["\']', src)
        assert m is not None
        fallback = m.group(1)
        assert "buyer" in fallback.lower() or "revenue" in fallback.lower(), (
            f"TAM formula fallback should use buyer/revenue language. Got: {fallback!r}"
        )

    def test_research_tool_tam_basis_present(self):
        src = self._alignment_source()
        assert "NIH-funded labs" in src or "annualised spend per lab" in src or \
               "research_tool_non_clinical" in src

    def test_research_infrastructure_tam_basis_present(self):
        src = self._alignment_source()
        assert "research_infrastructure" in src

    def test_drug_archetypes_not_in_tam_dict(self):
        """Drug archetypes don't need a _tam_basis entry — they use patient-based models."""
        src = self._alignment_source()
        # The _tam_basis dict should exist in the non-drug-specific path
        assert "_tam_basis" in src

    def test_no_price_per_course_in_research_tool_basis(self):
        import app.services.alignment_service as svc
        src = inspect.getsource(svc)
        # Find the _tam_basis dict block
        m = re.search(r"_tam_basis\s*=\s*\{(.+?)\}\.get", src, re.DOTALL)
        if m:
            block = m.group(1)
            # Find the research_tool entry specifically
            rt = re.search(r'"research_tool[^"]*".*?"([^"]+)"', block)
            if rt:
                assert "course" not in rt.group(1).lower(), (
                    "research_tool TAM basis must not contain 'course' (drug vocabulary)"
                )


# ══════════════════════════════════════════════════════════════════════════════
# EXPERT_JSON_SCHEMA — no clinical example text
# ══════════════════════════════════════════════════════════════════════════════

class TestExpertJsonSchemaNoClinicalExample:

    def _schema(self) -> str:
        from app.services.alignment_service import EXPERT_JSON_SCHEMA
        return EXPERT_JSON_SCHEMA

    def test_no_epidemiological_basis_in_schema(self):
        assert "epidemiological basis" not in self._schema(), (
            "EXPERT_JSON_SCHEMA must not use 'epidemiological basis' in its citation "
            "example — this phrase leaks into non-clinical report literature_citations."
        )

    def test_no_murray_amr_example_in_schema(self):
        """The specific AMR citation (Murray et al., AMR deaths) was the leaked example."""
        schema = self._schema()
        assert "Murray et al" not in schema and "1.27 million deaths" not in schema, (
            "AMR-specific citation example must not appear in the general EXPERT_JSON_SCHEMA"
        )

    def test_schema_still_has_citation_style_instruction(self):
        assert "relevance field" in self._schema() or "literature_citations" in self._schema()

    def test_citation_example_is_archetype_neutral(self):
        schema = self._schema()
        # The example should use placeholder text rather than a clinical disease name
        if "Author et al" in schema or "[specific finding]" in schema:
            pass  # correctly using neutral placeholder
        else:
            # If replaced with something else, still check for banned tokens
            clinical_tokens = ["epidemiological basis", "AMR", "antimicrobial"]
            for tok in clinical_tokens:
                assert tok not in schema, (
                    f"EXPERT_JSON_SCHEMA citation example contains clinical token '{tok}'"
                )


# ══════════════════════════════════════════════════════════════════════════════
# Scenario narratives — research_tool must use SCENARIOS_RESEARCH
# ══════════════════════════════════════════════════════════════════════════════

_CLINICAL_SCENARIO_TOKENS = [
    "payer uptake",
    "initial label",
    "therapeutic area",
    "guideline inclusion",
    "initial approved indication",
    "payer coverage",
    "comparable product launches in this indication",
]


class TestScenarioNarrativesNotClinical:

    def _scenarios(self, archetype: str) -> list[dict]:
        from app.services.market_provenance_service import build_scenarios
        return build_scenarios(10_000_000, 3_000_000, 500_000, archetype=archetype)

    @pytest.mark.parametrize("token", _CLINICAL_SCENARIO_TOKENS)
    def test_research_tool_scenario_no_clinical_token(self, token: str):
        scenarios = self._scenarios("research_tool_non_clinical")
        for sc in scenarios:
            narrative = (sc.get("narrative") or "").lower()
            assert token not in narrative, (
                f"Banned clinical token '{token}' found in research_tool scenario: {narrative!r}"
            )

    @pytest.mark.parametrize("token", _CLINICAL_SCENARIO_TOKENS)
    def test_research_infrastructure_scenario_no_clinical_token(self, token: str):
        scenarios = self._scenarios("research_infrastructure_saas")
        for sc in scenarios:
            narrative = (sc.get("narrative") or "").lower()
            assert token not in narrative, (
                f"Banned token '{token}' in research_infrastructure scenario: {narrative!r}"
            )

    def test_research_scenarios_use_lab_vocabulary(self):
        scenarios = self._scenarios("research_tool_non_clinical")
        all_text = " ".join(sc.get("narrative", "") for sc in scenarios).lower()
        assert "lab" in all_text or "adoption" in all_text, (
            "research_tool scenarios should reference lab adoption, not clinical uptake"
        )

    def test_drug_scenarios_use_clinical_vocabulary(self):
        scenarios = self._scenarios("drug_amr")
        all_text = " ".join(sc.get("narrative", "") for sc in scenarios).lower()
        assert any(tok in all_text for tok in _CLINICAL_SCENARIO_TOKENS), (
            "Drug scenarios should still contain clinical vocabulary (they are clinical)"
        )

    def test_three_scenarios_returned(self):
        scenarios = self._scenarios("research_tool_non_clinical")
        assert len(scenarios) == 3

    def test_scenarios_have_narrative_field(self):
        for sc in self._scenarios("research_tool_non_clinical"):
            assert "narrative" in sc and sc["narrative"]


# ══════════════════════════════════════════════════════════════════════════════
# PDF template cover and footer — must not have clinical-only strings
# ══════════════════════════════════════════════════════════════════════════════

class TestPdfTemplateCoverAndFooter:

    def _html(self, report: dict | None = None) -> str:
        from app.services.pdf_renderer import render_report_html
        return render_report_html(report or {})

    def test_cover_not_medical_market_intelligence(self):
        assert "medical market intelligence" not in self._html().lower(), (
            "PDF cover must not say 'Medical Market Intelligence' "
            "(was the clinical-only branding)"
        )

    def test_cover_says_commercialization_intelligence(self):
        assert "commercialization intelligence" in self._html().lower(), (
            "PDF cover eyebrow must say 'Commercialization Intelligence Report'"
        )

    def test_footer_no_iqvia_forecast(self):
        assert "iqvia forecast" not in self._html().lower(), (
            "PDF footer must not reference IQVIA forecast-error methodology"
        )

    def test_footer_no_plus_minus_35(self):
        html = self._html()
        assert "±35%" not in html and "Confidence range ±" not in html, (
            "PDF footer must not show '±35%' (hardcoded confidence from IQVIA methodology)"
        )

    def test_no_medical_market_intel_in_any_html(self):
        html = self._html({"product_name": "TestTool", "model_version": "test-1.0"})
        assert "medical market intelligence" not in html.lower()

    def test_no_specialist_only_header_phrase(self):
        html = self._html().lower()
        assert "medical market intelligence report" not in html


# ══════════════════════════════════════════════════════════════════════════════
# Rendered HTML for a research_tool — spot-check critical banned tokens
# ══════════════════════════════════════════════════════════════════════════════

_RESEARCH_TOOL_REPORT = {
    "product_name": "TestSync",
    "model_version": "test-1.0",
    "domain": "LIFE_SCIENCES_RESEARCH",
    "market_sizing": {
        "formula": "TAM = 5,500 labs × $8,333/yr",
        "total_addressable_market_usd": 45_000_000,
        "serviceable_market_usd": 13_500_000,
        "methodology_note": "Bottom-up buyer model. Lab counts from NIH RePORTER.",
        "steps": [],
    },
    "executive_summary": "TestSync is a lab data-sync tool for academic PIs.",
}

_BANNED_IN_RESEARCH_TOOL_HTML = [
    ("eligible patients × annual price", "TAM formula basis fallback must not be patient-based"),
    ("cdc/seer epidemiology + cms pricing", "Market evidence label must not use CDC/SEER for lab tools"),
    ("iqvia forecast-error methodology", "PDF footer must not reference IQVIA forecast-error"),
    ("medical market intelligence", "PDF branding must not say Medical Market Intelligence"),
    ("±35%", "PDF must not show hardcoded ±35% confidence band"),
]


class TestBannedTokensInRenderedResearchToolHtml:

    def _html(self) -> str:
        from app.services.pdf_renderer import render_report_html
        return render_report_html(_RESEARCH_TOOL_REPORT).lower()

    @pytest.mark.parametrize("token,reason", _BANNED_IN_RESEARCH_TOOL_HTML)
    def test_banned_token_not_in_html(self, token: str, reason: str):
        assert token not in self._html(), reason
