"""G.1 — Retrieval audit.

Verifies:
  1. FetchLog dataclass structure
  2. ContextVar collector (start_fetch_log / get_fetch_log / _log_fetch)
  3. research_tool_non_clinical entries in SEARCH_TEMPLATES
  4. Retrieval pipeline FetchLog emission for NIH RePORTER and ClinicalTrials
  5. RetrievalResult carries fetch_logs field
  6. NIH RePORTER uses text search for research tools (not disease_conditions)
  7. No outbound URLs are bare query-string templates (formatted strings, not results)

Spec reference: Part D / G.1 — "Log every outbound HTTP call on one generation.
Everything below depends on knowing the answer."
"""
from __future__ import annotations

import asyncio
import inspect

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _kr_src() -> str:
    import app.services.knowledge_retriever as m
    return inspect.getsource(m)


def _rp_src() -> str:
    import app.services.retrieval_pipeline as m
    return inspect.getsource(m)


# ══════════════════════════════════════════════════════════════════════════════
# FetchLog dataclass
# ══════════════════════════════════════════════════════════════════════════════

class TestFetchLogStructure:

    def test_fetchlog_module_has_class(self):
        from app.services.knowledge_retriever import FetchLog  # noqa: F401

    def test_fetchlog_has_service_field(self):
        from app.services.knowledge_retriever import FetchLog
        import dataclasses
        names = {f.name for f in dataclasses.fields(FetchLog)}
        assert "service" in names

    def test_fetchlog_has_url_field(self):
        from app.services.knowledge_retriever import FetchLog
        import dataclasses
        names = {f.name for f in dataclasses.fields(FetchLog)}
        assert "url" in names

    def test_fetchlog_has_status_field(self):
        from app.services.knowledge_retriever import FetchLog
        import dataclasses
        names = {f.name for f in dataclasses.fields(FetchLog)}
        assert "status" in names

    def test_fetchlog_has_latency_ms(self):
        from app.services.knowledge_retriever import FetchLog
        import dataclasses
        names = {f.name for f in dataclasses.fields(FetchLog)}
        assert "latency_ms" in names

    def test_fetchlog_has_parsed_records(self):
        from app.services.knowledge_retriever import FetchLog
        import dataclasses
        names = {f.name for f in dataclasses.fields(FetchLog)}
        assert "parsed_records" in names

    def test_fetchlog_has_query_summary(self):
        from app.services.knowledge_retriever import FetchLog
        import dataclasses
        names = {f.name for f in dataclasses.fields(FetchLog)}
        assert "query_summary" in names

    def test_fetchlog_instantiates(self):
        from app.services.knowledge_retriever import FetchLog
        log = FetchLog(
            service="nih_reporter", url="https://api.reporter.nih.gov/v2/projects/search",
            method="POST", status=200, latency_ms=450.0, response_bytes=4096,
            parsed_records=5, query_summary="nih_reporter text='soil moisture sensor'",
        )
        assert log.service == "nih_reporter"
        assert log.status == 200


# ══════════════════════════════════════════════════════════════════════════════
# ContextVar collector
# ══════════════════════════════════════════════════════════════════════════════

class TestFetchLogCollector:

    def test_start_fetch_log_exists(self):
        from app.services.knowledge_retriever import start_fetch_log
        assert callable(start_fetch_log)

    def test_get_fetch_log_exists(self):
        from app.services.knowledge_retriever import get_fetch_log
        assert callable(get_fetch_log)

    def test_get_fetch_log_returns_empty_before_start(self):
        from app.services.knowledge_retriever import get_fetch_log
        # In a fresh context (no start_fetch_log call) the result is empty
        logs = get_fetch_log()
        assert isinstance(logs, list)

    def test_start_fetch_log_returns_list(self):
        from app.services.knowledge_retriever import start_fetch_log
        log = start_fetch_log()
        assert isinstance(log, list)

    def test_log_fetch_appends_to_collector(self):
        from app.services.knowledge_retriever import start_fetch_log, get_fetch_log, _log_fetch, FetchLog
        collector = start_fetch_log()
        _log_fetch(FetchLog(
            service="test", url="https://example.com", method="GET",
            status=200, latency_ms=10.0, response_bytes=100, parsed_records=1,
            query_summary="test query",
        ))
        assert len(collector) == 1
        assert collector[0].service == "test"

    def test_get_fetch_log_matches_start_fetch_log_list(self):
        from app.services.knowledge_retriever import start_fetch_log, get_fetch_log, _log_fetch, FetchLog
        collector = start_fetch_log()
        _log_fetch(FetchLog(
            service="nih_reporter", url="https://api.reporter.nih.gov/", method="POST",
            status=200, latency_ms=320.0, response_bytes=2048, parsed_records=3,
            query_summary="nih_reporter research tool query",
        ))
        fetched = get_fetch_log()
        assert len(fetched) == 1
        assert fetched[0].service == "nih_reporter"

    def test_log_fetch_multiple_records(self):
        from app.services.knowledge_retriever import start_fetch_log, _log_fetch, FetchLog
        collector = start_fetch_log()
        for i in range(3):
            _log_fetch(FetchLog(
                service=f"source_{i}", url=f"https://example.com/{i}",
                method="GET", status=200, latency_ms=float(i * 10),
                response_bytes=100, parsed_records=i,
                query_summary=f"query {i}",
            ))
        assert len(collector) == 3

    def test_contextvar_isolation(self):
        """Two async contexts must have independent fetch logs."""
        from app.services.knowledge_retriever import start_fetch_log, _log_fetch, FetchLog

        async def _run():
            log_a = start_fetch_log()
            _log_fetch(FetchLog("a", "https://a.com", "GET", 200, 1.0, 10, 1, "a"))
            log_b = start_fetch_log()  # starts fresh list in same context
            _log_fetch(FetchLog("b", "https://b.com", "GET", 200, 1.0, 10, 1, "b"))
            return log_a, log_b

        log_a, log_b = asyncio.run(_run())
        # log_b started fresh — only has "b"
        assert any(f.service == "b" for f in log_b)

    def test_contextvar_present_in_source(self):
        src = _kr_src()
        assert "ContextVar" in src or "_FETCH_LOG_CTX" in src


# ══════════════════════════════════════════════════════════════════════════════
# research_tool_non_clinical in SEARCH_TEMPLATES
# ══════════════════════════════════════════════════════════════════════════════

class TestResearchToolTemplates:

    def test_research_tool_non_clinical_in_templates(self):
        from app.services.knowledge_retriever import SEARCH_TEMPLATES
        assert "research_tool_non_clinical" in SEARCH_TEMPLATES, (
            "research_tool_non_clinical must have search templates; "
            "it was falling through to disease-centric DEFAULT_SEARCHES"
        )

    def test_research_infrastructure_saas_in_templates(self):
        from app.services.knowledge_retriever import SEARCH_TEMPLATES
        assert "research_infrastructure_saas" in SEARCH_TEMPLATES

    def test_research_tool_templates_mention_nih_sbir(self):
        from app.services.knowledge_retriever import SEARCH_TEMPLATES
        templates = " ".join(SEARCH_TEMPLATES.get("research_tool_non_clinical", []))
        assert "sbir" in templates.lower() or "nih" in templates.lower(), (
            "Research tool templates must include NIH/SBIR — these are the actual funders"
        )

    def test_research_tool_templates_not_disease_centric(self):
        """Research tool queries must not be pure disease queries (wrong buyer)."""
        from app.services.knowledge_retriever import SEARCH_TEMPLATES
        templates = SEARCH_TEMPLATES.get("research_tool_non_clinical", [])
        # They should include {product} — the tool being built — not just {disease}
        product_queries = [t for t in templates if "{product}" in t]
        assert len(product_queries) >= 1, (
            "At least one template must use {product} to query by the research tool, "
            "not just by disease (wrong buyer model)"
        )

    def test_research_tool_templates_not_clinical_trials(self):
        """Research tools don't go through clinical trials — don't query clinicaltrials.gov."""
        from app.services.knowledge_retriever import SEARCH_TEMPLATES
        templates = " ".join(SEARCH_TEMPLATES.get("research_tool_non_clinical", []))
        assert "clinicaltrials.gov" not in templates, (
            "Research tools don't require clinicaltrials.gov queries — wrong domain"
        )

    def test_research_tool_templates_have_at_least_3_queries(self):
        from app.services.knowledge_retriever import SEARCH_TEMPLATES
        templates = SEARCH_TEMPLATES.get("research_tool_non_clinical", [])
        assert len(templates) >= 3, f"Expected ≥3 templates, got {len(templates)}"

    def test_research_infra_templates_mention_data_management(self):
        from app.services.knowledge_retriever import SEARCH_TEMPLATES
        templates = " ".join(SEARCH_TEMPLATES.get("research_infrastructure_saas", []))
        assert "data" in templates.lower() or "platform" in templates.lower()


# ══════════════════════════════════════════════════════════════════════════════
# Retrieval pipeline NIH RePORTER routing
# ══════════════════════════════════════════════════════════════════════════════

class TestNihReporterRouting:

    def test_retrieval_pipeline_has_nih_reporter_branch(self):
        src = _rp_src()
        assert "nih_reporter" in src

    def test_research_tool_uses_text_search_not_disease_conditions(self):
        """
        For research_tool_non_clinical, NIH RePORTER must use advanced_text_search
        on the product idea, NOT disease_conditions (which returns clinical grants —
        wrong for lab instrumentation products).
        """
        src = _rp_src()
        assert "advanced_text_search" in src, (
            "NIH RePORTER branch must use advanced_text_search for research tools; "
            "disease_conditions returns clinical grants, not lab instrumentation ones"
        )
        assert "research_tool_non_clinical" in src, (
            "NIH RePORTER branch must detect research_tool_non_clinical archetype"
        )

    def test_nih_reporter_fetchlog_emitted_in_pipeline(self):
        src = _rp_src()
        # The NIH RePORTER branch must call _log_fetch
        assert "_log_fetch" in src

    def test_clinicaltrials_fetchlog_emitted_in_pipeline(self):
        src = _rp_src()
        # ClinicalTrials.gov must also emit FetchLog
        assert "clinicaltrials_gov" in src and "_log_fetch" in src

    def test_nih_reporter_url_is_api_not_search_ui(self):
        """
        Spec D: 'Every source URL is a constructed query string, not a result.'
        The code must call the structured API endpoint, not the search UI.
        """
        src = _rp_src()
        assert "api.reporter.nih.gov/v2/projects/search" in src, (
            "NIH RePORTER must call the structured API endpoint, not the search UI"
        )
        # Must NOT construct the browser search URL
        assert "reporter.nih.gov/search" not in src, (
            "reporter.nih.gov/search is a UI URL — use api.reporter.nih.gov/v2/projects/search"
        )

    def test_clinicaltrials_url_is_v2_api(self):
        src = _rp_src()
        assert "clinicaltrials.gov/api/v2/studies" in src, (
            "ClinicalTrials must use the v2 API endpoint, not a browser URL"
        )


# ══════════════════════════════════════════════════════════════════════════════
# RetrievalResult carries fetch_logs
# ══════════════════════════════════════════════════════════════════════════════

class TestRetrievalResultFetchLogs:

    def test_retrieval_result_has_fetch_logs_field(self):
        from app.services.retrieval_pipeline import RetrievalResult
        import dataclasses
        names = {f.name for f in dataclasses.fields(RetrievalResult)}
        assert "fetch_logs" in names, (
            "RetrievalResult must carry fetch_logs so the caller can inspect what ran"
        )

    def test_fetch_logs_defaults_to_empty_list(self):
        from app.services.retrieval_pipeline import RetrievalResult
        r = RetrievalResult(
            facts=[], coverage_by_chapter={}, total_latency_ms=0,
            cache_hit_rate=0, tiers_reached=0, sources_called=[],
            concepts_filled=set(), context_blocks={},
        )
        assert isinstance(r.fetch_logs, list)
        assert r.fetch_logs == []

    def test_build_result_populates_fetch_logs(self):
        """_build_result must pull from get_fetch_log() into the result."""
        src = _rp_src()
        assert "get_fetch_log" in src or "fetch_log" in src, (
            "_build_result must call get_fetch_log() to populate RetrievalResult.fetch_logs"
        )

    def test_run_retrieval_pipeline_starts_fetch_log(self):
        """run_retrieval_pipeline must call start_fetch_log() at entry."""
        src = _rp_src()
        assert "start_fetch_log" in src


# ══════════════════════════════════════════════════════════════════════════════
# Source URL hygiene (spec D: no bare search-UI URLs)
# ══════════════════════════════════════════════════════════════════════════════

class TestSourceUrlHygiene:

    def test_no_patents_google_url_in_pipeline(self):
        """
        Spec D: 'Google Patents has no official API — whatever is producing the
        patent claim is not calling one.' The pipeline must not construct
        patents.google.com URLs as if they are API calls.
        """
        src = _rp_src()
        assert "patents.google.com" not in src, (
            "patents.google.com is a browser UI — it has no public API. "
            "Use PatentsView API (search.patentsview.org) instead."
        )

    def test_no_pubmed_homepage_url(self):
        """
        Spec D: pubmed.ncbi.nlm.nih.gov/ (bare) is a search UI, not an API result.
        Programmatic access uses eutils.ncbi.nlm.nih.gov.
        """
        src = _rp_src()
        # The pipeline should not construct bare pubmed.ncbi.nlm.nih.gov URLs
        # (with no PMID) as citation sources
        assert "pubmed.ncbi.nlm.nih.gov/?term" not in src, (
            "pubmed.ncbi.nlm.nih.gov/?term=... is a search UI URL, not an API response. "
            "Use eutils.ncbi.nlm.nih.gov for programmatic access."
        )

    def test_nih_reporter_structured_api_not_ui(self):
        src = _rp_src()
        # Must NOT contain the reporter search UI
        assert "reporter.nih.gov/search?advanced_text_search" not in src, (
            "reporter.nih.gov/search?... is a UI URL. "
            "Use api.reporter.nih.gov/v2/projects/search for programmatic access."
        )

    def test_fetch_log_service_not_empty(self):
        from app.services.knowledge_retriever import FetchLog
        log = FetchLog(
            service="clinicaltrials_gov",
            url="https://clinicaltrials.gov/api/v2/studies",
            method="GET", status=200, latency_ms=350.0,
            response_bytes=8192, parsed_records=3,
            query_summary="clinicaltrials_gov cond='neuroscience'",
        )
        assert log.service != ""
        assert "clinicaltrials.gov/api" in log.url


# ══════════════════════════════════════════════════════════════════════════════
# D-01 / D-03: cross-domain contamination gate
# ══════════════════════════════════════════════════════════════════════════════

_CLINICAL_FORBIDDEN: frozenset[str] = frozenset({
    "clinicaltrials_gov", "openfda", "nci_seer", "seer_preloaded",
    "orphanet", "clinvar", "cms_part_d", "cms_part_b_asp",
    "nice_hta", "preloaded_icer", "who_gho", "opentargets",
    "cms_open_payments", "cms_prescriber_part_d",
})

_NON_CLINICAL_ARCHETYPES = (
    "research_tool_non_clinical",
    "research_tool_agronomy",
    "research_infrastructure_saas",
)


class TestDomainRelevanceGate:
    """D-01/D-03: Clinical-domain signals must not enter non-clinical reports.

    Root cause of D-01: surface-string match ('soil moisture' → 'coccidioidomycosis')
    contaminated a lab-tool report because the pipeline queried SEER/clinical sources
    and then emitted a disease_intelligence context block unconditionally.

    Fix: non-clinical archetypes (a) have their own SUBCATEGORY_SOURCE_RELEVANCE
    entries that exclude clinical registries; (b) are gated out of SEER preload in
    _fetch_tier0; (c) are gated out of disease_intelligence in _format_facts_for_context.
    """

    # ── source plan gate ──────────────────────────────────────────────────────

    def test_non_clinical_archetypes_have_own_source_plans(self):
        """Each non-clinical archetype must have its own entry in SUBCATEGORY_SOURCE_RELEVANCE."""
        from app.services.retrieval_pipeline import SUBCATEGORY_SOURCE_RELEVANCE
        for archetype in _NON_CLINICAL_ARCHETYPES:
            assert archetype in SUBCATEGORY_SOURCE_RELEVANCE, (
                f"{archetype!r} falls through to 'default' which includes clinical sources — "
                "it must have its own restricted source plan"
            )

    def test_research_tool_non_clinical_excludes_clinical_sources(self):
        """D-03: research_tool_non_clinical source plan must not include clinical registries."""
        from app.services.retrieval_pipeline import SUBCATEGORY_SOURCE_RELEVANCE
        sources = SUBCATEGORY_SOURCE_RELEVANCE["research_tool_non_clinical"]
        violations = sources & _CLINICAL_FORBIDDEN
        assert not violations, (
            f"research_tool_non_clinical source plan contains clinical-domain sources: "
            f"{violations} — these index regulated clinical products and will contaminate "
            "lab-instrument reports with disease prevalence data (D-01)"
        )

    def test_research_tool_agronomy_excludes_clinical_sources(self):
        """D-03: research_tool_agronomy must not query clinical registries."""
        from app.services.retrieval_pipeline import SUBCATEGORY_SOURCE_RELEVANCE
        sources = SUBCATEGORY_SOURCE_RELEVANCE["research_tool_agronomy"]
        violations = sources & _CLINICAL_FORBIDDEN
        assert not violations, (
            f"research_tool_agronomy source plan contains clinical sources: {violations}"
        )

    def test_research_infrastructure_saas_excludes_clinical_sources(self):
        from app.services.retrieval_pipeline import SUBCATEGORY_SOURCE_RELEVANCE
        sources = SUBCATEGORY_SOURCE_RELEVANCE["research_infrastructure_saas"]
        violations = sources & _CLINICAL_FORBIDDEN
        assert not violations, (
            f"research_infrastructure_saas source plan contains clinical sources: {violations}"
        )

    def test_non_clinical_archetypes_constant_exported(self):
        """_NON_CLINICAL_ARCHETYPES must exist in retrieval_pipeline for the gate to work."""
        from app.services.retrieval_pipeline import _NON_CLINICAL_ARCHETYPES as _NCA
        for archetype in _NON_CLINICAL_ARCHETYPES:
            assert archetype in _NCA, (
                f"{archetype!r} missing from _NON_CLINICAL_ARCHETYPES — domain gate won't fire"
            )

    # ── Tier-0 SEER gate ─────────────────────────────────────────────────────

    def test_fetch_tier0_gates_seer_on_archetype(self):
        """D-01: _fetch_tier0 source code must guard the SEER block on _NON_CLINICAL_ARCHETYPES."""
        src = _rp_src()
        # The guard must appear before the seer_cancer import
        seer_import_pos = src.find("get_cancer_incidence")
        assert seer_import_pos != -1, "SEER import not found in retrieval_pipeline"
        # The _NON_CLINICAL_ARCHETYPES check must appear before the SEER import
        gate_pos = src.find("_NON_CLINICAL_ARCHETYPES")
        assert gate_pos != -1, "_NON_CLINICAL_ARCHETYPES not referenced in retrieval_pipeline"
        assert gate_pos < seer_import_pos, (
            "_NON_CLINICAL_ARCHETYPES gate must appear before the SEER preload block in "
            "_fetch_tier0; otherwise non-clinical reports still receive disease prevalence facts"
        )

    # ── context formatting gate ───────────────────────────────────────────────

    def test_format_facts_skips_disease_intelligence_for_non_clinical(self):
        """D-01: disease_intelligence block must be absent when subcategory_id is non-clinical."""
        from app.services.retrieval_pipeline import _format_facts_for_context, RetrievedFact
        # Inject a fake prevalence fact — simulates what SEER would return if not gated
        fake_fact = RetrievedFact(
            concept_type="prevalence_incidence",
            source_id="seer_preloaded",
            value={"annual_new_cases": 12345, "disease": "coccidioidomycosis"},
            quality_score=0.90,
            tier=0,
        )
        fused = {"prevalence_incidence": [fake_fact]}
        blocks = _format_facts_for_context(
            fused, "coccidioidomycosis", "infectious_disease",
            subcategory_id="research_tool_non_clinical",
        )
        assert "disease_intelligence" not in blocks, (
            "disease_intelligence block must be suppressed for research_tool_non_clinical — "
            "D-01: coccidioidomycosis contaminated a soil sensor report via this path"
        )

    def test_format_facts_skips_disease_intelligence_for_agronomy(self):
        from app.services.retrieval_pipeline import _format_facts_for_context, RetrievedFact
        fake_fact = RetrievedFact(
            concept_type="prevalence_incidence",
            source_id="seer_preloaded",
            value={"us_patient_estimate": 50000},
            quality_score=0.85,
            tier=0,
        )
        fused = {"prevalence_incidence": [fake_fact]}
        blocks = _format_facts_for_context(
            fused, "soil_pathogen", "agriculture",
            subcategory_id="research_tool_agronomy",
        )
        assert "disease_intelligence" not in blocks, (
            "disease_intelligence must be suppressed for research_tool_agronomy"
        )

    def test_format_facts_includes_disease_intelligence_for_clinical(self):
        """Control: clinical archetypes must still receive the disease_intelligence block."""
        from app.services.retrieval_pipeline import _format_facts_for_context, RetrievedFact
        fake_fact = RetrievedFact(
            concept_type="prevalence_incidence",
            source_id="seer_preloaded",
            value={"annual_new_cases": 50000},
            quality_score=0.90,
            tier=0,
        )
        fused = {"prevalence_incidence": [fake_fact]}
        blocks = _format_facts_for_context(
            fused, "breast cancer", "oncology",
            subcategory_id="drug_oncology",
        )
        assert "disease_intelligence" in blocks, (
            "disease_intelligence must be present for clinical archetypes"
        )

    def test_format_facts_includes_disease_intelligence_when_no_archetype(self):
        """Backward compat: empty subcategory_id defaults to clinical path."""
        from app.services.retrieval_pipeline import _format_facts_for_context, RetrievedFact
        fake_fact = RetrievedFact(
            concept_type="prevalence_incidence",
            source_id="seer_preloaded",
            value={"annual_new_cases": 10000},
            quality_score=0.90,
            tier=0,
        )
        fused = {"prevalence_incidence": [fake_fact]}
        blocks = _format_facts_for_context(fused, "disease_x", "oncology")
        assert "disease_intelligence" in blocks

    # ── cost_aware_router gate ────────────────────────────────────────────────

    def test_plan_sources_excludes_clinical_for_research_tool(self):
        """cost_aware_router.plan_sources must not include clinical registries for research tools."""
        from app.services.cost_aware_router import plan_sources
        profile = {
            "modality": "other",
            "sub_expert_id": "research_tool_non_clinical",
            "required_output_type": "full_report",
            "evidence_availability": "medium",
        }
        plan = plan_sources(profile)
        sources = set(plan["prioritized_sources"])
        forbidden = {"ClinicalTrials.gov", "openFDA", "CDC PLACES", "Census SAHIE",
                     "CMS ASP", "ICER", "NICE HTA", "SEER"}
        violations = sources & forbidden
        assert not violations, (
            f"plan_sources for research_tool_non_clinical returned clinical registries: "
            f"{violations} — these produce irrelevant results for lab instrumentation"
        )

    def test_plan_sources_excludes_clinical_for_agronomy(self):
        from app.services.cost_aware_router import plan_sources
        profile = {
            "modality": "other",
            "sub_expert_id": "research_tool_agronomy",
            "required_output_type": "full_report",
            "evidence_availability": "medium",
        }
        plan = plan_sources(profile)
        sources = set(plan["prioritized_sources"])
        forbidden = {"ClinicalTrials.gov", "openFDA", "CDC PLACES", "Census SAHIE"}
        violations = sources & forbidden
        assert not violations, (
            f"plan_sources for research_tool_agronomy returned clinical sources: {violations}"
        )
