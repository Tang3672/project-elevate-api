"""
F-10 — NSF Awards API agency-mapping and query wiring (spec v5 item 9).

C-02: funding landscape used a static agency-mapping table and only queried NIH
RePORTER, leaving NSF-funded labs uncounted in the research-tool buyer population.

Fix: added query_nsf_awards() and _TA_TO_NSF_DIRECTORATE to market_segmentation.py.
build_life_sciences_research_tree() now concurrently queries NIH RePORTER AND NSF
Awards API; IC codes and NSF directorates are both derived from intake via the
mapping tables — never hardcoded at the call site.

All tests here are pure source-inspection or unit tests; no live network calls.
"""

from __future__ import annotations

import ast
import os
import re
import types
import unittest.mock as mock

import pytest

_SVC_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "app", "services", "market_segmentation.py")
)


def _src() -> str:
    with open(_SVC_PATH, encoding="utf-8") as f:
        return f.read()


# ── 1. Agency-mapping table completeness ─────────────────────────────────────

from app.services.market_segmentation import (
    _TA_TO_NSF_DIRECTORATE,
    nsf_directorate_for_ta,
    NSF_AWARDS_URL,
    query_nsf_awards,
)


def test_nsf_directorate_table_exists_and_nonempty():
    assert len(_TA_TO_NSF_DIRECTORATE) >= 5, (
        "_TA_TO_NSF_DIRECTORATE must map at least 5 TAs; got "
        f"{len(_TA_TO_NSF_DIRECTORATE)}"
    )


@pytest.mark.parametrize("ta,expected_dirs", [
    ("neuroscience", ["BIO", "SBE"]),
    ("cns",          ["BIO", "SBE"]),
    ("oncology",     ["BIO"]),
    ("immunology",   ["BIO"]),
    ("gene_therapy", ["BIO"]),
])
def test_nsf_directorate_for_known_ta(ta: str, expected_dirs: list[str]):
    result = nsf_directorate_for_ta(ta)
    assert result == expected_dirs, (
        f"nsf_directorate_for_ta('{ta}') returned {result}, expected {expected_dirs}"
    )


@pytest.mark.parametrize("ta", ["other", "", "agriculture", "food", "unknown_ta"])
def test_nsf_directorate_for_nonbio_ta_returns_empty(ta: str):
    """Non-biology and unknown TAs return [] — no directorate filter = all NSF."""
    result = nsf_directorate_for_ta(ta)
    assert result == [], (
        f"nsf_directorate_for_ta('{ta}') should return [] for non-bio/unknown TAs, got {result}"
    )


def test_nsf_directorate_returns_copy_not_shared_reference():
    """Each call must return an independent list."""
    a = nsf_directorate_for_ta("cns")
    b = nsf_directorate_for_ta("cns")
    a.append("INJECTED")
    assert "INJECTED" not in b, "nsf_directorate_for_ta() must return a copy"


# ── 2. NSF Awards URL and API contract ───────────────────────────────────────

def test_nsf_awards_url_points_to_v1():
    assert "api.nsf.gov" in NSF_AWARDS_URL, "NSF URL must point to api.nsf.gov"
    assert "v1/awards" in NSF_AWARDS_URL, "NSF URL must reference the v1/awards endpoint"


def test_query_nsf_awards_is_async():
    import inspect
    assert inspect.iscoroutinefunction(query_nsf_awards), (
        "query_nsf_awards() must be async so it can be gathered with query_nih_reporter()"
    )


def test_nsf_query_includes_keyword_param():
    src = _src()
    # The function must pass the keyword as a query parameter
    fn_start = src.find("async def query_nsf_awards")
    fn_end   = src.find("\nasync def ", fn_start + 1)
    fn_src   = src[fn_start: fn_end if fn_end != -1 else fn_start + 3000]
    assert '"keyword"' in fn_src or "'keyword'" in fn_src, (
        "query_nsf_awards() must include 'keyword' in its HTTP params"
    )


def test_nsf_query_has_fallback():
    src = _src()
    fn_start = src.find("async def query_nsf_awards")
    fn_end   = src.find("\nasync def ", fn_start + 1)
    fn_src   = src[fn_start: fn_end if fn_end != -1 else fn_start + 3000]
    assert "fallback_used" in fn_src, (
        "query_nsf_awards() must return a dict with 'fallback_used' key (mirrors query_nih_reporter contract)"
    )
    assert "fallback" in fn_src.lower(), (
        "query_nsf_awards() must have a fallback path for network failures"
    )


# ── 3. build_life_sciences_research_tree wiring ───────────────────────────────

def test_build_tree_calls_both_nih_and_nsf():
    src = _src()
    fn_start = src.find("async def build_life_sciences_research_tree")
    fn_end   = src.find("\nasync def ", fn_start + 1)
    if fn_end == -1:
        fn_end = src.find("\ndef ", fn_start + 1)
    fn_src = src[fn_start: fn_end if fn_end != -1 else fn_start + 5000]
    assert "query_nih_reporter" in fn_src, (
        "build_life_sciences_research_tree must call query_nih_reporter"
    )
    assert "query_nsf_awards" in fn_src, (
        "build_life_sciences_research_tree must call query_nsf_awards (F-10)"
    )


def test_build_tree_uses_asyncio_gather_for_concurrent_queries():
    src = _src()
    fn_start = src.find("async def build_life_sciences_research_tree")
    fn_end   = src.find("\nasync def ", fn_start + 1)
    if fn_end == -1:
        fn_end = src.find("\ndef ", fn_start + 1)
    fn_src = src[fn_start: fn_end if fn_end != -1 else fn_start + 5000]
    assert "asyncio.gather" in fn_src, (
        "build_life_sciences_research_tree must use asyncio.gather to run "
        "NIH and NSF queries concurrently — sequential awaits would double latency"
    )


def test_build_tree_derives_nsf_directorates_from_ta():
    src = _src()
    fn_start = src.find("async def build_life_sciences_research_tree")
    fn_end   = src.find("\nasync def ", fn_start + 1)
    if fn_end == -1:
        fn_end = src.find("\ndef ", fn_start + 1)
    fn_src = src[fn_start: fn_end if fn_end != -1 else fn_start + 5000]
    assert "nsf_directorate_for_ta" in fn_src, (
        "build_life_sciences_research_tree must derive NSF directorates from ta "
        "via nsf_directorate_for_ta() — Rule 3 (no hardcoded IC/directorate codes)"
    )


# ── 4. query_nsf_awards fallback behaviour (mocked) ───────────────────────────

@pytest.mark.asyncio
async def test_query_nsf_awards_returns_fallback_on_network_error():
    with mock.patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get.side_effect = Exception("timeout")
        result = await query_nsf_awards("laboratory sensor", directorates=["BIO"])
    assert result["fallback_used"] is True, (
        "query_nsf_awards() must return fallback_used=True on network failure"
    )
    assert result["award_count"] > 0, (
        "Fallback must provide a positive award_count so downstream funnel is non-zero"
    )


@pytest.mark.asyncio
async def test_query_nsf_awards_returns_live_count_on_success():
    mock_response = mock.MagicMock()
    mock_response.raise_for_status = mock.MagicMock()
    mock_response.json.return_value = {
        "response": {
            "award": [{"id": "2312345"}, {"id": "2312346"}, {"id": "2312347"}]
        }
    }
    with mock.patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.get = mock.AsyncMock(
            return_value=mock_response
        )
        result = await query_nsf_awards("laboratory sensor", directorates=["BIO"])
    assert result["fallback_used"] is False, (
        "query_nsf_awards() must return fallback_used=False when API succeeds"
    )
    assert result["award_count"] == 3, (
        f"Expected 3 awards from mock response, got {result['award_count']}"
    )
    assert "api.nsf.gov" in result["source"], (
        "Live source string must reference api.nsf.gov"
    )
