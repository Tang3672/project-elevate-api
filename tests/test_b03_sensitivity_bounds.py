"""B-03 — Sensitivity bounds.

Verifies:
  1. swing_pct is always bounded in [0, 500] in _run_research_tool_sensitivity
  2. impact_pct is always bounded in [0, 500] in sensitivity_analysis
  3. som_base <= 0 raises ValueError (degenerate baseline guard)
"""
from __future__ import annotations

import math
import pytest


# ── market_segmentation.py: impact_pct clamp ─────────────────────────────────

def _make_segment_tree(base_value: float, high_value: float):
    """Build a minimal single-leaf SegmentTree for sensitivity tests."""
    from app.services.market_segmentation import SegmentNode, SegmentTree

    root = SegmentNode(
        id="root", label="All labs", parent_id=None,
        value=base_value, unit="labs", method="assumed",
        low=base_value * 0.5, high=high_value, confidence=0.5,
        price_model={"annual_usd": 5_000, "tier": "academic"},
    )
    tree = SegmentTree(nodes=[root], root_id="root", product_name="Test Tool")
    return tree


def test_sensitivity_analysis_impact_pct_clamp():
    """impact_pct must not exceed 500% even with extreme high_value."""
    from app.services.market_segmentation import sensitivity_analysis

    # high = 100x base → unclamped impact would be ~10,000%; clamped to 500%
    tree = _make_segment_tree(base_value=1_000, high_value=100_000)
    result = sensitivity_analysis(tree)
    assert isinstance(result, list)
    for entry in result:
        impact = entry.get("impact_pct", 0)
        assert impact <= 500.0, (
            f"impact_pct {impact} exceeds 500% cap in {entry.get('label', '?')}"
        )
        assert impact >= 0.0, (
            f"impact_pct {impact} is negative in {entry.get('label', '?')}"
        )


def test_sensitivity_analysis_returns_valid_structure():
    """sensitivity_analysis should always return a list."""
    from app.services.market_segmentation import sensitivity_analysis

    tree = _make_segment_tree(base_value=2_000, high_value=4_000)
    result = sensitivity_analysis(tree)
    assert isinstance(result, list)


# ── market_sizing_derivation_service: swing_pct clamp and som_base guard ─────

def test_swing_pct_clamp_in_research_tool_sensitivity():
    """swing_pct must be <= 500 for all tornado entries even with extreme lo/hi bands."""
    from app.services.market_sizing_derivation_service import _run_research_tool_sensitivity

    result = _run_research_tool_sensitivity(
        pop_lo=1,          pop_hi=1_000_000,
        sp_lo=100,         sp_hi=100_000,
        sam_lo=0.001,      sam_hi=0.999,
        som_lo=0.001,      som_hi=0.999,
        n_samples=1_000,
    )
    for entry in result.sensitivity_ranking:
        assert entry.swing_pct <= 500.0, (
            f"swing_pct {entry.swing_pct} exceeds 500% cap for {entry.parameter}"
        )
        assert entry.swing_pct >= 0.0, (
            f"swing_pct {entry.swing_pct} is negative for {entry.parameter}"
        )


def test_som_base_zero_raises_value_error():
    """If any midpoint is zero, som_base == 0 and must raise ValueError."""
    from app.services.market_sizing_derivation_service import _run_research_tool_sensitivity

    with pytest.raises(ValueError, match="degenerate baseline"):
        _run_research_tool_sensitivity(
            pop_lo=100,   pop_hi=1_000,
            sp_lo=0,      sp_hi=0,      # mid = 0
            sam_lo=0.10,  sam_hi=0.30,
            som_lo=0.05,  som_hi=0.20,
            n_samples=100,
        )


def test_swing_pct_normal_inputs_within_bounds():
    """Normal inputs should produce swing_pct well within 0–500%."""
    from app.services.market_sizing_derivation_service import _run_research_tool_sensitivity

    result = _run_research_tool_sensitivity(
        pop_lo=1_500, pop_hi=3_000,
        sp_lo=4_000,  sp_hi=7_000,
        sam_lo=0.15,  sam_hi=0.30,
        som_lo=0.05,  som_hi=0.15,
        n_samples=1_000,
    )
    assert len(result.sensitivity_ranking) == 4, "Should produce 4 tornado entries"
    for entry in result.sensitivity_ranking:
        assert 0.0 <= entry.swing_pct <= 500.0
        assert math.isfinite(entry.swing_pct)


def test_sensitivity_ranking_sorted_descending():
    """Tornado entries must be sorted by swing_pct descending (widest first)."""
    from app.services.market_sizing_derivation_service import _run_research_tool_sensitivity

    result = _run_research_tool_sensitivity(
        pop_lo=1_000, pop_hi=5_000,
        sp_lo=2_000,  sp_hi=10_000,
        sam_lo=0.10,  sam_hi=0.40,
        som_lo=0.05,  som_hi=0.20,
        n_samples=1_000,
    )
    swings = [e.swing_pct for e in result.sensitivity_ranking]
    assert swings == sorted(swings, reverse=True), (
        f"Tornado entries not sorted descending: {swings}"
    )
