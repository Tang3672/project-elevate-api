"""G.2 — Cross-run contamination guard.

Spec reference: Part G / G.2 — "Fix cross-run state leakage (A.3);
add test_no_cross_run_contamination."

Three contamination vectors are guarded:
  1. Fetch log ContextVar — run A's FetchLog entries must not appear in run B
  2. product_name sanitizer — stale frontend name must be cleared before generation
  3. Market sizing derivation — pure function, result must be idea-keyed not sequential
"""
from __future__ import annotations

import asyncio
import inspect


# ═══════════════════════════════════════════════════════════════════════════════
# 1.  Fetch-log ContextVar isolation across sequential pipeline runs
# ═══════════════════════════════════════════════════════════════════════════════

class TestFetchLogIsolation:
    """start_fetch_log() must reset the collector so run B never sees run A's entries."""

    def test_no_cross_run_contamination(self):
        """Core G.2 contract: two sequential start_fetch_log() calls are independent."""
        from app.services.knowledge_retriever import start_fetch_log, get_fetch_log, _log_fetch, FetchLog

        # ── Run A ──
        log_a = start_fetch_log()
        _log_fetch(FetchLog(
            service="nih_reporter", url="https://api.reporter.nih.gov/v2/projects/search",
            method="POST", status=200, latency_ms=410.0, response_bytes=4096,
            parsed_records=5, query_summary="run_A nih query",
        ))
        assert len(log_a) == 1, "run A should have 1 entry"

        # ── Run B starts — must not inherit run A's state ──
        log_b = start_fetch_log()
        assert len(log_b) == 0, (
            f"run B fetch log must start empty; inherited {len(log_b)} entries from run A"
        )
        assert log_b is not log_a, "run B must create a NEW list, not reuse run A's"

        # ── run B emits its own entry ──
        _log_fetch(FetchLog(
            service="clinicaltrials_gov", url="https://clinicaltrials.gov/api/v2/studies",
            method="GET", status=200, latency_ms=220.0, response_bytes=2048,
            parsed_records=3, query_summary="run_B clinicaltrials query",
        ))
        assert len(log_b) == 1
        assert log_b[0].service == "clinicaltrials_gov"

        # ── run A's reference is unchanged ──
        assert len(log_a) == 1, "run A list must not be mutated by run B"
        assert log_a[0].service == "nih_reporter"

    def test_get_fetch_log_returns_run_b_after_reset(self):
        from app.services.knowledge_retriever import start_fetch_log, get_fetch_log, _log_fetch, FetchLog
        start_fetch_log()
        _log_fetch(FetchLog("run_a_svc", "https://a.com", "GET", 200, 1.0, 10, 1, "a"))
        start_fetch_log()  # run B
        fetched = get_fetch_log()
        assert all(f.service != "run_a_svc" for f in fetched), (
            "get_fetch_log() after run B start must not return run A entries; "
            "ContextVar must be fully reset"
        )

    def test_empty_run_b_has_no_entries(self):
        from app.services.knowledge_retriever import start_fetch_log, get_fetch_log, _log_fetch, FetchLog
        start_fetch_log()
        _log_fetch(FetchLog("prev_run", "https://prev.com", "GET", 200, 1.0, 10, 1, "prev"))
        start_fetch_log()  # new run, no calls yet
        assert get_fetch_log() == [], (
            "A fresh run with no fetches must return an empty log, "
            "not carry over entries from the prior run"
        )

    def test_three_sequential_runs_isolated(self):
        """Smoke test: three back-to-back runs, each completely independent."""
        from app.services.knowledge_retriever import start_fetch_log, _log_fetch, FetchLog

        def _make_log(service):
            return FetchLog(service, f"https://{service}.com", "GET", 200, 1.0, 10, 1, service)

        log_a = start_fetch_log();  _log_fetch(_make_log("svc_a"))
        log_b = start_fetch_log();  _log_fetch(_make_log("svc_b")); _log_fetch(_make_log("svc_b2"))
        log_c = start_fetch_log();  _log_fetch(_make_log("svc_c"))

        assert [f.service for f in log_a] == ["svc_a"]
        assert [f.service for f in log_b] == ["svc_b", "svc_b2"]
        assert [f.service for f in log_c] == ["svc_c"]

    def test_async_context_isolation(self):
        """Two concurrent async tasks each get their own independent fetch log."""
        from app.services.knowledge_retriever import start_fetch_log, get_fetch_log, _log_fetch, FetchLog

        async def task_a():
            log = start_fetch_log()
            _log_fetch(FetchLog("task_a_svc", "https://a.com", "GET", 200, 1.0, 10, 1, "a"))
            await asyncio.sleep(0)   # yield — task_b may run here
            return get_fetch_log()

        async def task_b():
            log = start_fetch_log()
            _log_fetch(FetchLog("task_b_svc", "https://b.com", "GET", 200, 1.0, 10, 1, "b"))
            await asyncio.sleep(0)
            return get_fetch_log()

        async def _run():
            results = await asyncio.gather(
                asyncio.ensure_future(task_a()),
                asyncio.ensure_future(task_b()),
            )
            return results

        result_a, result_b = asyncio.run(_run())
        # Each task's get_fetch_log() must only contain its own entries
        assert all(f.service == "task_a_svc" for f in result_a), (
            f"Task A log contaminated with task B entries: {[f.service for f in result_a]}"
        )
        assert all(f.service == "task_b_svc" for f in result_b), (
            f"Task B log contaminated with task A entries: {[f.service for f in result_b]}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 2.  product_name sanitizer wired into both API endpoints
# ═══════════════════════════════════════════════════════════════════════════════

class TestProductNameSanitizerWiring:
    """_sanitize_product_name must be called before EVERY generate_pi_report invocation."""

    def _api_src(self) -> str:
        import app.api.alignment as m
        return inspect.getsource(m)

    def test_sanitize_called_in_sync_endpoint(self):
        src = self._api_src()
        assert "_sanitize_product_name" in src, (
            "_sanitize_product_name must be called in the /pi-report endpoint"
        )

    def test_sanitize_called_in_async_endpoint(self):
        src = self._api_src()
        # Both the sync and async variants must call it — count occurrences
        count = src.count("_sanitize_product_name(")
        assert count >= 2, (
            f"_sanitize_product_name must be called in BOTH sync and async endpoints; "
            f"found {count} call(s). The async /pi-report/async endpoint is the primary "
            f"code path and must also sanitize before calling generate_pi_report."
        )

    def test_stale_neuroscience_name_cleared_for_agronomy_idea(self):
        from app.api.alignment import _sanitize_product_name
        result = _sanitize_product_name(
            "Hublink",  # product name from a prior neuroscience run
            "soil moisture sensor for precision agriculture and USDA field trials",
        )
        assert result is None, (
            f"'Hublink' has zero overlap with an agronomy idea — "
            f"must be cleared to None; got {result!r}"
        )

    def test_matching_name_not_cleared(self):
        from app.api.alignment import _sanitize_product_name
        result = _sanitize_product_name(
            "SoilSense",
            "SoilSense is a soil moisture sensor for precision agriculture",
        )
        assert result == "SoilSense"

    def test_none_name_passes_through(self):
        from app.api.alignment import _sanitize_product_name
        assert _sanitize_product_name(None, "any idea at all") is None

    def test_very_short_name_passes_through(self):
        """Names with no words ≥4 chars can't be validated → pass through unchanged."""
        from app.api.alignment import _sanitize_product_name
        assert _sanitize_product_name("BIO", "bioinformatics platform") == "BIO"

    def test_camelcase_name_splits_correctly(self):
        from app.api.alignment import _sanitize_product_name
        # "NeuroLink" → ["neuro", "link"] — "neuro" is in idea
        result = _sanitize_product_name(
            "NeuroLink",
            "neurolink is a brain-computer interface platform",
        )
        assert result == "NeuroLink"


# ═══════════════════════════════════════════════════════════════════════════════
# 3.  Market sizing derivation — pure function, no cross-run state
# ═══════════════════════════════════════════════════════════════════════════════

class TestMarketSizingStatelessness:
    """generate_market_sizing_derivation must produce the same output for the same
    input regardless of call order — no module-level mutable defaults."""

    def _derive(self, idea: str, product_type: str = "research_tool"):
        from app.services.market_sizing_derivation_service import generate_market_sizing_derivation
        return generate_market_sizing_derivation(idea, product_type)

    def test_same_idea_same_result_across_two_calls(self):
        idea = "Data logging infrastructure for animal behaviour research labs"
        r1 = self._derive(idea, "research_tool")
        r2 = self._derive(idea, "research_tool")
        assert r1.us_tam_usd == r2.us_tam_usd, (
            f"us_tam_usd changed between call 1 ({r1.us_tam_usd}) and call 2 ({r2.us_tam_usd}); "
            "derivation is not stateless"
        )
        assert r1.us_sam_usd == r2.us_sam_usd
        assert r1.formula_name == r2.formula_name

    def test_derivation_idea_field_matches_input(self):
        """The derivation must embed the CURRENT idea, not a cached idea from a prior call.
        This is the core contamination contract: the function must not return a memoised
        result from a different idea string."""
        idea_a = "Hublink — cloud sync platform for neuroscience labs"
        idea_b = "Soil moisture sensor for USDA precision agriculture field trials"
        r_a = self._derive(idea_a, "research_tool")
        r_b = self._derive(idea_b, "research_tool")
        # Each derivation must embed its own idea
        assert r_a.idea == idea_a, (
            f"Derivation for idea_a embedded wrong idea: {r_a.idea!r}"
        )
        assert r_b.idea == idea_b, (
            f"Derivation for idea_b embedded wrong idea: {r_b.idea!r}"
        )
        assert r_a.idea != r_b.idea, (
            "Two different ideas produced derivations with identical .idea fields — "
            "possible cross-run state leak"
        )

    def test_result_after_alternate_idea_is_identical_to_first_call(self):
        """Run A → Run B → Run A again: third run must equal first run exactly."""
        idea_a = "Data logging infrastructure for animal behaviour research labs"
        idea_b = "Hublink — cloud sync platform for neuroscience labs"

        r_a1 = self._derive(idea_a, "research_tool")
        _    = self._derive(idea_b, "research_tool")  # run B — should not affect A
        r_a2 = self._derive(idea_a, "research_tool")

        assert r_a1.us_tam_usd  == r_a2.us_tam_usd,  "TAM changed after interleaved run"
        assert r_a1.us_sam_usd  == r_a2.us_sam_usd,  "SAM changed after interleaved run"
        assert r_a1.formula_name == r_a2.formula_name, "formula_name changed after interleaved run"

    def test_no_mutable_defaults_in_derivation_function(self):
        """Module-level mutable defaults mutate silently in Python.
        The derivation function must use None (not [] or {}) as defaults."""
        import inspect as _ins
        from app.services.market_sizing_derivation_service import generate_market_sizing_derivation
        sig = _ins.signature(generate_market_sizing_derivation)
        for name, param in sig.parameters.items():
            default = param.default
            if default is _ins.Parameter.empty:
                continue
            assert not isinstance(default, (list, dict, set)), (
                f"Parameter '{name}' has a mutable default {default!r}. "
                "Use None and create inside the function body to avoid cross-call contamination."
            )


# ═══════════════════════════════════════════════════════════════════════════════
# 4.  Retrieval pipeline LRU cache is content-addressed, not sequential
# ═══════════════════════════════════════════════════════════════════════════════

class TestRetrievalCacheAddressing:
    """The LRU cache in retrieval_pipeline must be keyed by content (source_id + query),
    not by call sequence. Entries from run A must not overwrite entries for run B
    if their queries differ."""

    def test_cache_key_is_content_addressed(self):
        from app.services.retrieval_pipeline import _LRUCache
        cache = _LRUCache(max_size=10)
        cache.set("nih_reporter", "query_a", ["fact_a"], ttl_sec=3600)
        cache.set("nih_reporter", "query_b", ["fact_b"], ttl_sec=3600)

        result_a = cache.get("nih_reporter", "query_a")
        result_b = cache.get("nih_reporter", "query_b")

        assert result_a == ["fact_a"], "query_a returned wrong value"
        assert result_b == ["fact_b"], "query_b returned wrong value"

    def test_different_sources_same_query_are_independent(self):
        from app.services.retrieval_pipeline import _LRUCache
        cache = _LRUCache(max_size=10)
        cache.set("source_A", "same_query", ["from_a"], ttl_sec=3600)
        cache.set("source_B", "same_query", ["from_b"], ttl_sec=3600)

        assert cache.get("source_A", "same_query") == ["from_a"]
        assert cache.get("source_B", "same_query") == ["from_b"]

    def test_cache_miss_returns_none(self):
        from app.services.retrieval_pipeline import _LRUCache
        cache = _LRUCache(max_size=10)
        cache.set("source_X", "query_X", ["data"], ttl_sec=3600)
        # A different query on the same source must be a miss
        assert cache.get("source_X", "query_Y") is None

    def test_global_cache_is_module_singleton(self):
        """The module-level _CACHE must not be reinitialised between imports."""
        from app.services.retrieval_pipeline import _CACHE as c1
        import importlib, app.services.retrieval_pipeline as _m
        c2 = _m._CACHE
        assert c1 is c2, "_CACHE must be a stable module-level singleton"
