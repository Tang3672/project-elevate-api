"""B-03 — Sensitivity bounds.

Verifies:
  1. swing_pct is always bounded in [0, 500] in _run_research_tool_sensitivity
  2. impact_pct uses max one-sided deviation / base_tam (not full range / base_tam)
  3. som_base <= 0 raises ValueError (degenerate baseline guard)
"""
from __future__ import annotations

import math
import pytest


# ── market_segmentation.py: impact_pct formula ───────────────────────────────

def _make_three_node_tree(root_value: float, mid_frac: float, leaf_frac: float, price_usd: float):
    """
    Build a root → assumed_mid → derived_leaf tree.

    Sensitivity analysis operates on intermediate assumed nodes, not price-bearing
    leaves. _compute_tam_from_node_vals recomputes leaf value from its parent's
    propagated value, so the assumed node must be an ancestor of the leaf.
    """
    from app.services.market_segmentation import SegmentNode, SegmentTree

    mid_value  = root_value * mid_frac
    leaf_value = mid_value  * leaf_frac
    root = SegmentNode(
        id="root", label="All labs", parent_id=None,
        value=root_value, unit="labs", method="retrieved",
        low=root_value * 0.8, high=root_value * 1.2, confidence=0.85,
        price_model=None,
    )
    mid = SegmentNode(
        id="mid", label="Funnel labs", parent_id="root",
        value=mid_value, unit="labs", method="assumed",
        low=mid_value * 0.5, high=mid_value * 1.5, confidence=0.5,
        price_model=None,
    )
    leaf = SegmentNode(
        id="leaf", label="Addressable labs", parent_id="mid",
        value=leaf_value, unit="labs", method="derived",
        low=leaf_value * 0.5, high=leaf_value * 1.5, confidence=0.6,
        price_model={"annual_usd": price_usd, "tier": "academic"},
    )
    return SegmentTree(nodes=[root, mid, leaf], root_id="root", product_name="Test Tool")


def test_sensitivity_analysis_impact_pct_formula():
    """±50% input variation on an intermediate node must produce ~50% impact_pct.

    The old formula used abs(high - low) / base * 100 which gives ~100%.
    The correct formula is max(abs(high - base), abs(low - base)) / base * 100 = ~50%.
    """
    from app.services.market_segmentation import sensitivity_analysis

    # mid_frac=0.5, leaf_frac=0.8 → base_tam = 1000 * 0.5 * 0.8 * 10000 = $4M
    # varying mid ±50%: tam_low ≈ $2M, tam_high ≈ $6M
    # impact_pct = max(|6M - 4M|, |2M - 4M|) / 4M * 100 = 50%
    tree = _make_three_node_tree(root_value=1_000, mid_frac=0.5, leaf_frac=0.8, price_usd=10_000)
    result = sensitivity_analysis(tree)
    assert len(result) == 1
    pct = result[0]["impact_pct"]
    assert 45.0 <= pct <= 55.0, f"Expected ~50% impact for ±50% variation, got {pct}%"


def test_sensitivity_analysis_returns_valid_structure():
    """sensitivity_analysis should always return a list."""
    from app.services.market_segmentation import sensitivity_analysis

    tree = _make_three_node_tree(root_value=2_000, mid_frac=0.4, leaf_frac=0.7, price_usd=7_000)
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
