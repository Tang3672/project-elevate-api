"""
Rule 3 — RePORTER query built from intake (Spec v3 Addendum).

Verifies that:
  1. nih_ic_codes_for_ta() maps TAs to NIH IC codes (derived from intake, not hardcoded).
  2. query_nih_reporter() accepts agency_codes and includes them in the API payload.
  3. No IC codes are hardcoded in the query_nih_reporter implementation.
  4. Research-tool TA ("other" / empty) returns an empty IC list — no filter, all NIH.
  5. build_life_sciences_research_tree() and build_segment_tree() pass ta through.
"""

from __future__ import annotations

import ast
import os
import types
import unittest.mock as mock
from typing import Any

import pytest

# ── 1. nih_ic_codes_for_ta() mapping ─────────────────────────────────────────

from app.services.market_segmentation import nih_ic_codes_for_ta, _TA_TO_NIH_IC_CODES


@pytest.mark.parametrize("ta,expected_ics", [
    ("cns",           ["NINDS", "NIMH", "NIA"]),
    ("oncology",      ["NCI"]),
    ("cardiovascular", ["NHLBI"]),
    ("metabolic",     ["NIDDK"]),
    ("immunology",    ["NIAID", "NIAMS"]),
    ("rare_disease",  ["NCATS", "ORDR"]),
    ("gene_therapy",  ["NCI", "NHGRI", "NHLBI"]),
    ("hematology",    ["NCI", "NHLBI"]),
    ("ibd",           ["NIDDK", "NIAID"]),
    ("nash_mash",     ["NIDDK"]),
])
def test_nih_ic_codes_for_known_tas(ta: str, expected_ics: list[str]):
    result = nih_ic_codes_for_ta(ta)
    assert result == expected_ics, (
        f"nih_ic_codes_for_ta('{ta}') returned {result}, expected {expected_ics}"
    )


@pytest.mark.parametrize("ta", ["other", "", "research_tool", "LIFE_SCIENCES_RESEARCH", "unknown_ta"])
def test_nih_ic_codes_for_research_tool_ta_returns_empty(ta: str):
    """Research tools and unknown TAs must return [] — no IC filter means all NIH."""
    result = nih_ic_codes_for_ta(ta)
    assert result == [], (
        f"nih_ic_codes_for_ta('{ta}') should return [] (no IC filter for research tools), got {result}"
    )


def test_nih_ic_codes_returns_copy_not_shared_reference():
    """Each call must return an independent list (not a shared reference)."""
    a = nih_ic_codes_for_ta("cns")
    b = nih_ic_codes_for_ta("cns")
    a.append("INJECTED")
    assert "INJECTED" not in b, "nih_ic_codes_for_ta() must return a copy, not a shared reference"


def test_ta_to_nih_ic_codes_keys_are_lowercase():
    """All keys in _TA_TO_NIH_IC_CODES must be lowercase for case-insensitive lookup."""
    for key in _TA_TO_NIH_IC_CODES:
        assert key == key.lower(), f"Key '{key}' in _TA_TO_NIH_IC_CODES must be lowercase"


# ── 2. query_nih_reporter() payload includes agency_codes when provided ───────

@pytest.mark.asyncio
async def test_query_nih_reporter_payload_includes_agency_codes():
    """When agency_codes are passed, the API payload must include them."""
    from app.services.market_segmentation import query_nih_reporter

    captured: dict = {}

    async def fake_post(url: str, json: dict, **kwargs):
        captured["payload"] = json
        raise Exception("simulated_timeout")

    with mock.patch("httpx.AsyncClient") as MockClient:
        MockClient.return_value.__aenter__ = mock.AsyncMock(
            return_value=mock.AsyncMock(post=mock.AsyncMock(side_effect=Exception("simulated_timeout")))
        )
        MockClient.return_value.__aexit__ = mock.AsyncMock(return_value=False)

        # Patch at module level to capture the payload
        import httpx
        original_post = None

        class _FakeResponse:
            def raise_for_status(self): raise Exception("simulated_timeout")

        class _FakeClient:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                pass
            async def post(self, url, json=None, **kw):
                captured["payload"] = json
                raise Exception("simulated_timeout")

        with mock.patch("app.services.market_segmentation.httpx.AsyncClient", return_value=_FakeClient()):
            await query_nih_reporter("test keyword", agency_codes=["NINDS", "NIMH"])

    assert "payload" in captured, "httpx call was never made"
    criteria = captured["payload"]["criteria"]
    assert "agency_codes" in criteria, (
        "NIH Reporter payload must include 'agency_codes' when agency_codes are passed"
    )
    assert criteria["agency_codes"] == ["NINDS", "NIMH"]


@pytest.mark.asyncio
async def test_query_nih_reporter_payload_no_agency_codes_when_empty():
    """When no agency_codes are passed, the payload must NOT include agency_codes."""
    from app.services.market_segmentation import query_nih_reporter

    captured: dict = {}

    class _FakeClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, url, json=None, **kw):
            captured["payload"] = json
            raise Exception("simulated_timeout")

    with mock.patch("app.services.market_segmentation.httpx.AsyncClient", return_value=_FakeClient()):
        await query_nih_reporter("test keyword")  # no agency_codes

    criteria = captured["payload"]["criteria"]
    assert "agency_codes" not in criteria, (
        "NIH Reporter payload must NOT include 'agency_codes' when none are passed "
        "(research tools query all NIH)"
    )


# ── 3. No hardcoded IC codes in query_nih_reporter implementation ─────────────

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))


def _extract_function_source(filepath: str, func_name: str) -> str:
    """Return the source of a top-level function from a .py file using AST."""
    with open(filepath, encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(source, filename=filepath)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == func_name:
            lines = source.splitlines()
            return "\n".join(lines[node.lineno - 1: node.end_lineno])
    raise ValueError(f"Function '{func_name}' not found in {filepath}")


@pytest.mark.parametrize("hardcoded_ic", [
    '"NINDS"', "'NINDS'",
    '"NCI"',   "'NCI'",
    '"NHLBI"', "'NHLBI'",
    '"NIMH"',  "'NIMH'",
])
def test_query_nih_reporter_has_no_hardcoded_ic_string(hardcoded_ic: str):
    """
    query_nih_reporter() must not contain any hardcoded IC strings as literals.
    All IC codes must flow in via the agency_codes parameter (derived from intake).
    """
    path = os.path.join(_REPO_ROOT, "app", "services", "market_segmentation.py")
    func_src = _extract_function_source(path, "query_nih_reporter")
    assert hardcoded_ic not in func_src, (
        f"query_nih_reporter() contains hardcoded IC string {hardcoded_ic}. "
        "Per Rule 3, IC codes must be derived from intake via nih_ic_codes_for_ta(), "
        "not hardcoded in the function body."
    )


# ── 4. build_life_sciences_research_tree passes ta to query_nih_reporter ──────

@pytest.mark.asyncio
async def test_build_life_sciences_research_tree_passes_ta():
    """
    build_life_sciences_research_tree(ta='cns') must call query_nih_reporter
    with agency_codes derived from nih_ic_codes_for_ta('cns'), not hardcoded.
    """
    from app.services.market_segmentation import build_life_sciences_research_tree

    captured: dict = {}

    async def fake_query_nih_reporter(keyword: str, agency_codes=()):
        captured["agency_codes"] = list(agency_codes)
        return {
            "lab_count": 5000,
            "total_projects": 100,
            "distinct_pis": 50,
            "source": "test",
            "fallback_used": False,
        }

    with mock.patch("app.services.market_segmentation.query_nih_reporter", side_effect=fake_query_nih_reporter):
        await build_life_sciences_research_tree(idea="test idea", ta="cns")

    assert "agency_codes" in captured
    assert "NINDS" in captured["agency_codes"], (
        "build_life_sciences_research_tree(ta='cns') must pass NINDS to query_nih_reporter"
    )


@pytest.mark.asyncio
async def test_build_life_sciences_research_tree_no_ta_passes_empty_codes():
    """
    build_life_sciences_research_tree() with no ta must pass empty agency_codes
    (cross-disease research tool: search all NIH).
    """
    from app.services.market_segmentation import build_life_sciences_research_tree

    captured: dict = {}

    async def fake_query_nih_reporter(keyword: str, agency_codes=()):
        captured["agency_codes"] = list(agency_codes)
        return {
            "lab_count": 5000,
            "total_projects": 100,
            "distinct_pis": 50,
            "source": "test",
            "fallback_used": False,
        }

    with mock.patch("app.services.market_segmentation.query_nih_reporter", side_effect=fake_query_nih_reporter):
        await build_life_sciences_research_tree(idea="test idea")  # no ta

    assert captured["agency_codes"] == [], (
        "build_life_sciences_research_tree() with no ta must pass [] to query_nih_reporter "
        "(research tools should not be IC-filtered)"
    )


# ── 5. build_segment_tree threads ta through ──────────────────────────────────

@pytest.mark.asyncio
async def test_build_segment_tree_passes_ta_to_template_builder():
    from app.services.market_segmentation import build_segment_tree, LIFE_SCIENCES_RESEARCH

    captured: dict = {}

    async def fake_build_lsr(idea="", product_name="", ta=""):
        captured["ta"] = ta
        raise Exception("stop_after_capture")

    with mock.patch(
        "app.services.market_segmentation.build_life_sciences_research_tree",
        side_effect=fake_build_lsr,
    ):
        with pytest.raises(Exception, match="stop_after_capture"):
            await build_segment_tree(
                template=LIFE_SCIENCES_RESEARCH,
                idea="test",
                ta="oncology",
            )

    assert captured.get("ta") == "oncology", (
        "build_segment_tree() must pass ta= to build_life_sciences_research_tree()"
    )
