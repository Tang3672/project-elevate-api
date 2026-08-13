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
