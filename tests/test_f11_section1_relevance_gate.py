"""
F-11 — §1 relevance gate + source tiering (spec v5 item 10).

C-01: facts injected into Claude's §1 (executive summary) context were not
filtered by quality score, so low-authority or off-domain facts could appear
in the prompt alongside high-quality NCI SEER data. No tier label was present,
so Claude could not signal source quality in the narrative.

Fix (retrieval_pipeline.py):
  - _MIN_QUALITY_SECTION1 = 0.60 — minimum quality score for §1 context
  - _best_fact_above_threshold() — replaces bare `for fact in fused[concept]:…break`
  - _tier_label(tier) — returns "[T0]"–"[T3]" label
  - All six di_lines concepts, three reg_lines concepts, three ma_lines concepts,
    and two sp_lines concepts now use _best_fact_above_threshold instead of
    unconditional break.

All tests are pure unit tests; no live network calls.
"""

from __future__ import annotations

import dataclasses

import pytest

from app.services.retrieval_pipeline import (
    RetrievedFact,
    _MIN_QUALITY_SECTION1,
    _best_fact_above_threshold,
    _format_facts_for_context,
    _tier_label,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fact(concept: str, value, quality: float, tier: int = 0) -> RetrievedFact:
    return RetrievedFact(
        concept_type=concept,
        source_id="test_source",
        value=value,
        quality_score=quality,
        tier=tier,
        formatted_text="",
    )


# ── 1. Constants ──────────────────────────────────────────────────────────────

def test_min_quality_section1_exists():
    assert _MIN_QUALITY_SECTION1 is not None


def test_min_quality_section1_is_at_least_0_60():
    assert _MIN_QUALITY_SECTION1 >= 0.60, (
        f"_MIN_QUALITY_SECTION1={_MIN_QUALITY_SECTION1} is too low; "
        "§1 context must exclude facts with quality_score < 0.60"
    )


def test_min_quality_section1_is_at_most_0_85():
    assert _MIN_QUALITY_SECTION1 <= 0.85, (
        f"_MIN_QUALITY_SECTION1={_MIN_QUALITY_SECTION1} is too high; "
        "threshold above 0.85 would exclude too many legitimate T1 facts"
    )


# ── 2. _tier_label ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tier,expected", [
    (0, "[T0]"),
    (1, "[T1]"),
    (2, "[T2]"),
    (3, "[T3]"),
])
def test_tier_label_format(tier: int, expected: str):
    assert _tier_label(tier) == expected, (
        f"_tier_label({tier}) returned {_tier_label(tier)!r}, expected {expected!r}"
    )


# ── 3. _best_fact_above_threshold ─────────────────────────────────────────────

def test_returns_none_when_no_facts():
    assert _best_fact_above_threshold({}, "prevalence_incidence") is None


def test_returns_none_when_concept_absent():
    fused = {"other_concept": [_fact("other_concept", {"x": 1}, quality=0.90)]}
    assert _best_fact_above_threshold(fused, "prevalence_incidence") is None


def test_returns_none_when_all_facts_below_threshold():
    fused = {
        "prevalence_incidence": [
            _fact("prevalence_incidence", {"annual_new_cases": 50_000}, quality=0.55),
            _fact("prevalence_incidence", {"annual_new_cases": 50_000}, quality=0.40),
        ]
    }
    result = _best_fact_above_threshold(fused, "prevalence_incidence")
    assert result is None, (
        "All facts below _MIN_QUALITY_SECTION1 must be excluded from §1 context"
    )


def test_returns_first_fact_at_threshold():
    fused = {
        "prevalence_incidence": [
            _fact("prevalence_incidence", {"annual_new_cases": 50_000}, quality=0.60),
        ]
    }
    result = _best_fact_above_threshold(fused, "prevalence_incidence")
    assert result is not None
    assert result.quality_score == 0.60


def test_returns_highest_quality_fact_above_threshold():
    fused = {
        "prevalence_incidence": [
            _fact("prevalence_incidence", {"annual_new_cases": 99_000}, quality=0.95, tier=0),
            _fact("prevalence_incidence", {"annual_new_cases": 50_000}, quality=0.70, tier=1),
            _fact("prevalence_incidence", {"annual_new_cases": 30_000}, quality=0.30, tier=2),
        ]
    }
    result = _best_fact_above_threshold(fused, "prevalence_incidence")
    assert result is not None
    assert result.quality_score == 0.95, (
        "Should return the highest-quality fact when multiple are above threshold"
    )


def test_skips_low_quality_returns_medium_quality():
    """When top fact is below threshold but second is above, return the second."""
    fused = {
        "gene_variant_data": [
            _fact("gene_variant_data", {"found": True, "gene_symbol": "BRCA1"}, quality=0.45),
            _fact("gene_variant_data", {"found": True, "gene_symbol": "BRCA2"}, quality=0.72, tier=1),
        ]
    }
    result = _best_fact_above_threshold(fused, "gene_variant_data")
    assert result is not None
    assert result.quality_score == 0.72


def test_custom_min_quality_parameter():
    """_best_fact_above_threshold accepts a custom min_quality override."""
    fused = {
        "prevalence_incidence": [
            _fact("prevalence_incidence", {"annual_new_cases": 10_000}, quality=0.50),
        ]
    }
    assert _best_fact_above_threshold(fused, "prevalence_incidence", min_quality=0.80) is None
    assert _best_fact_above_threshold(fused, "prevalence_incidence", min_quality=0.40) is not None


# ── 4. _format_facts_for_context — quality gate applied ──────────────────────

def test_low_quality_prevalence_excluded_from_disease_intelligence():
    """A prevalence fact below _MIN_QUALITY_SECTION1 must not appear in disease_intelligence."""
    fused = {
        "prevalence_incidence": [
            _fact("prevalence_incidence", {"annual_new_cases": 999_999}, quality=0.50, tier=2),
        ]
    }
    blocks = _format_facts_for_context(fused, "test_disease", "oncology")
    di = blocks.get("disease_intelligence", "")
    assert "999,999" not in di, (
        "Low-quality (0.50) prevalence fact must be excluded from disease_intelligence block"
    )


def test_high_quality_prevalence_included_in_disease_intelligence():
    """A prevalence fact at or above _MIN_QUALITY_SECTION1 must appear in disease_intelligence."""
    fused = {
        "prevalence_incidence": [
            _fact("prevalence_incidence", {"annual_new_cases": 123_456}, quality=0.90, tier=0),
        ]
    }
    blocks = _format_facts_for_context(fused, "test_disease", "oncology")
    di = blocks.get("disease_intelligence", "")
    assert "123,456" in di, (
        "High-quality (0.90) prevalence fact must appear in disease_intelligence block"
    )


def test_tier_label_present_in_disease_intelligence():
    """Tier label [T0] must appear in disease_intelligence block for T0 facts."""
    fused = {
        "prevalence_incidence": [
            _fact("prevalence_incidence", {"annual_new_cases": 50_000}, quality=0.95, tier=0),
        ]
    }
    blocks = _format_facts_for_context(fused, "test_disease", "oncology")
    di = blocks.get("disease_intelligence", "")
    assert "[T0]" in di, (
        "Tier label [T0] must appear in disease_intelligence context so Claude "
        "can signal source quality in §1 narrative"
    )


def test_tier_label_reflects_actual_tier():
    """Tier label must match the fact's tier, not always [T0]."""
    fused = {
        "prevalence_incidence": [
            _fact("prevalence_incidence", {"annual_new_cases": 50_000}, quality=0.85, tier=2),
        ]
    }
    blocks = _format_facts_for_context(fused, "test_disease", "oncology")
    di = blocks.get("disease_intelligence", "")
    assert "[T2]" in di, (
        "Tier label must reflect the fact's actual tier (T2 here), not a hardcoded value"
    )
    assert "[T0]" not in di


def test_low_quality_regulatory_fact_excluded():
    """A regulatory fact below threshold must not appear in regulatory_pathway block."""
    fused = {
        "ptrs_probability": [
            _fact("ptrs_probability", {"ptrs_pct": 42.0, "citation": "BIO2020"}, quality=0.45, tier=0),
        ]
    }
    blocks = _format_facts_for_context(fused, "test_disease", "oncology")
    reg = blocks.get("regulatory_pathway", "")
    assert "42.0%" not in reg, (
        "Low-quality PTRS fact (0.45) must be excluded by relevance gate"
    )


def test_high_quality_regulatory_fact_included_with_tier():
    """A high-quality regulatory fact must appear in regulatory_pathway with tier label."""
    fused = {
        "ptrs_probability": [
            _fact("ptrs_probability", {"ptrs_pct": 7.9, "citation": "BIO2020"}, quality=0.80, tier=0),
        ]
    }
    blocks = _format_facts_for_context(fused, "test_disease", "oncology")
    reg = blocks.get("regulatory_pathway", "")
    assert "7.9%" in reg
    assert "[T0]" in reg


# ── 5. Source-inspection: _format_facts_for_context uses gate helper ──────────

def test_format_facts_source_uses_best_fact_helper():
    """_format_facts_for_context must call _best_fact_above_threshold (not raw fused.get...break)."""
    import ast
    import inspect
    src = inspect.getsource(_format_facts_for_context)
    assert "_best_fact_above_threshold" in src, (
        "_format_facts_for_context must use _best_fact_above_threshold() for relevance gating; "
        "bare 'for fact in fused.get(…): … break' bypasses the quality threshold"
    )
