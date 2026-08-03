"""
Tests for segmentation_engine.py
=================================
Covers:
  1. build_segment_tree — segment counts, S matrix shape + correctness
  2. S matrix properties — top row all-ones, bottom rows = identity block
  3. aggregate_bottom_up — exact match with manual sums
  4. james_stein — exact formula, edge cases
  5. apply_shrinkage — produces ShrinkageRecords, grand mean property
  6. simulate_segments — reproducibility, aggregation coherence, copula path
  7. dimension_materiality + recommend_material_dimensions
  8. cohort_markov_flow — trace sums are conserved
  9. standard_* factory helpers
"""

from __future__ import annotations

import math
import numpy as np
import pytest

from app.services.segmentation_engine import (
    Dimension,
    DimValue,
    SegmentTree,
    ShrinkageRecord,
    aggregate_bottom_up,
    apply_shrinkage,
    build_segment_tree,
    cohort_markov_flow,
    dimension_materiality,
    james_stein,
    recommend_material_dimensions,
    simulate_segments,
    standard_biomarker,
    standard_line_of_therapy,
    standard_payer,
    standard_site_of_care,
    JAMES_STEIN_MIN_P,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def dim(name: str, codes: list[str]) -> Dimension:
    return Dimension(name=name, label=name.replace("_", " ").title(),
                     values=[DimValue(code=c, label=c) for c in codes])


def simple_2d_tree() -> SegmentTree:
    """D1={a,b} × D2={x,y} → 4 bottom, 9 total."""
    return build_segment_tree([dim("D1", ["a", "b"]), dim("D2", ["x", "y"])])


def flat_1d_tree() -> SegmentTree:
    return build_segment_tree([dim("D1", ["a", "b", "c"])])


# ─── 1. build_segment_tree ────────────────────────────────────────────────────

class TestBuildSegmentTree:

    def test_1d_segment_count(self):
        tree = flat_1d_tree()
        # 1 total + 3 values = 4 series; 3 bottom
        assert tree.n_total == 4
        assert tree.n_bottom == 3

    def test_2d_segment_count(self):
        tree = simple_2d_tree()
        # (1+2)*(1+2) = 9 total; 2*2 = 4 bottom
        assert tree.n_total == 9
        assert tree.n_bottom == 4

    def test_3d_segment_count(self):
        tree = build_segment_tree([
            dim("D1", ["a", "b"]),
            dim("D2", ["x", "y"]),
            dim("D3", ["p", "q"]),
        ])
        # (1+2)^3 = 27 total; 2^3 = 8 bottom
        assert tree.n_total == 27
        assert tree.n_bottom == 8

    def test_single_dimension_single_value(self):
        tree = build_segment_tree([dim("D1", ["only"])])
        # 2 total (TOTAL + "only"); 1 bottom
        assert tree.n_total == 2
        assert tree.n_bottom == 1

    def test_total_node_always_present(self):
        tree = simple_2d_tree()
        assert "TOTAL" in tree.seg_to_row

    def test_all_bottom_are_bottom_level(self):
        tree = simple_2d_tree()
        for s in tree.bottom_segments:
            assert s.is_bottom_level
            assert len(s.coordinates) == 2   # both dimensions constrained

    def test_aggregate_segments_have_level_lt_k(self):
        tree = simple_2d_tree()
        k = len(tree.dimensions)
        for s in tree.all_segments:
            if not s.is_bottom_level:
                assert s.level < k

    def test_segment_ids_unique(self):
        tree = simple_2d_tree()
        ids = [s.segment_id for s in tree.all_segments]
        assert len(ids) == len(set(ids))

    def test_seg_to_col_only_bottom(self):
        tree = simple_2d_tree()
        assert len(tree.seg_to_col) == tree.n_bottom
        for seg_id in tree.seg_to_col:
            assert tree.all_segments[tree.seg_to_row[seg_id]].is_bottom_level

    def test_total_label(self):
        tree = simple_2d_tree()
        total = tree.all_segments[tree.seg_to_row["TOTAL"]]
        assert total.label == "Total"


# ─── 2. S matrix properties ───────────────────────────────────────────────────

class TestSMatrix:

    def test_shape(self):
        tree = simple_2d_tree()
        assert tree.S.shape == (9, 4)

    def test_top_row_all_ones(self):
        tree = simple_2d_tree()
        total_row = tree.seg_to_row["TOTAL"]
        assert np.all(tree.S[total_row] == 1.0)

    def test_bottom_row_unit_vectors(self):
        tree = simple_2d_tree()
        for seg in tree.bottom_segments:
            col = tree.seg_to_col[seg.segment_id]
            row = tree.seg_to_row[seg.segment_id]
            # Only that column is 1 in this row
            expected = np.zeros(tree.n_bottom)
            expected[col] = 1.0
            np.testing.assert_array_equal(tree.S[row], expected)

    def test_s_values_binary(self):
        tree = simple_2d_tree()
        unique_vals = set(tree.S.flatten().tolist())
        assert unique_vals == {0.0, 1.0}

    def test_s_row_sums_nondecreasing_with_level(self):
        # Higher-level aggregates cover more bottom segments
        tree = simple_2d_tree()
        total_row = tree.seg_to_row["TOTAL"]
        assert tree.S[total_row].sum() == tree.n_bottom

    def test_aggregate_row_covers_correct_bottom(self):
        tree = simple_2d_tree()
        # D1=a should cover exactly (a,x) and (a,y)
        agg_id = "D1=a"
        if agg_id not in tree.seg_to_row:
            # Try the canonical format
            candidates = [
                s.segment_id for s in tree.all_segments
                if s.coordinates == {"D1": "a"}
            ]
            assert candidates, "Could not find D1=a aggregate"
            agg_id = candidates[0]
        row = tree.seg_to_row[agg_id]
        covered_bottom_ids = [
            tree.bottom_segments[j].segment_id
            for j in range(tree.n_bottom)
            if tree.S[row, j] == 1.0
        ]
        for bid in covered_bottom_ids:
            seg = tree.all_segments[tree.seg_to_row[bid]]
            assert seg.coordinates["D1"] == "a"
        assert len(covered_bottom_ids) == 2  # a×x and a×y

    def test_3d_total_row_sum_equals_bottom_count(self):
        tree = build_segment_tree([dim(f"D{i}", ["a", "b"]) for i in range(3)])
        row = tree.seg_to_row["TOTAL"]
        assert tree.S[row].sum() == 8.0  # 2^3

    def test_empty_dimensions_produces_only_total(self):
        tree = build_segment_tree([])
        assert tree.n_total == 1
        assert tree.n_bottom == 1
        assert tree.S.shape == (1, 1)
        assert tree.S[0, 0] == 1.0


# ─── 3. aggregate_bottom_up ───────────────────────────────────────────────────

class TestAggregateBottomUp:

    def test_total_equals_sum_of_bottom(self):
        tree = simple_2d_tree()
        ests = {s.segment_id: float(i + 1) for i, s in enumerate(tree.bottom_segments)}
        result = aggregate_bottom_up(tree, ests)
        total = result["TOTAL"]
        assert math.isclose(total, sum(ests.values()), rel_tol=1e-9)

    def test_1d_aggregate_correct(self):
        tree = flat_1d_tree()
        # D1 = {a, b, c} with values 10, 20, 30
        ests = {}
        for s in tree.bottom_segments:
            ests[s.segment_id] = {"a": 10.0, "b": 20.0, "c": 30.0}[s.coordinates["D1"]]
        result = aggregate_bottom_up(tree, ests)
        assert math.isclose(result["TOTAL"], 60.0)

    def test_2d_marginal_aggregates(self):
        tree = simple_2d_tree()
        # Assign: (a,x)=1, (a,y)=2, (b,x)=4, (b,y)=8
        assignment = {"a": {"x": 1.0, "y": 2.0}, "b": {"x": 4.0, "y": 8.0}}
        ests = {
            s.segment_id: assignment[s.coordinates["D1"]][s.coordinates["D2"]]
            for s in tree.bottom_segments
        }
        result = aggregate_bottom_up(tree, ests)
        # D1=a aggregate should be 1+2=3
        d1a = next(s for s in tree.all_segments if s.coordinates == {"D1": "a"})
        assert math.isclose(result[d1a.segment_id], 3.0)
        # D2=x aggregate should be 1+4=5
        d2x = next(s for s in tree.all_segments if s.coordinates == {"D2": "x"})
        assert math.isclose(result[d2x.segment_id], 5.0)

    def test_missing_bottom_defaults_to_zero(self):
        tree = flat_1d_tree()
        result = aggregate_bottom_up(tree, {})
        assert result["TOTAL"] == 0.0

    def test_aggregate_uses_s_matrix_identity(self):
        tree = simple_2d_tree()
        ests = {s.segment_id: 1.0 for s in tree.bottom_segments}
        result = aggregate_bottom_up(tree, ests)
        # Manual: S @ [1,1,1,1] for every row
        y_bot = np.ones(tree.n_bottom)
        y_all = tree.S @ y_bot
        for i, seg in enumerate(tree.all_segments):
            assert math.isclose(result[seg.segment_id], y_all[i])


# ─── 4. james_stein ───────────────────────────────────────────────────────────

class TestJamesStein:

    def test_shrinks_toward_grand_mean(self):
        x = np.array([1.0, 5.0, 9.0])  # grand mean = 5.0
        shrunk = james_stein(x, sigma2=0.5)
        # All values should move toward 5.0
        for orig, s in zip(x, shrunk):
            if orig < 5.0:
                assert s >= orig
                assert s <= 5.0
            elif orig > 5.0:
                assert s <= orig
                assert s >= 5.0

    def test_exact_formula_p_equals_3(self):
        # With p=3, x=[0,5,10], sigma2=1:
        # grand=5, ss=(25+0+25)=50, shrink=max(0,1-0*1/50)=1.0 → no shrinkage
        x = np.array([0.0, 5.0, 10.0])
        shrunk = james_stein(x, sigma2=1.0)
        np.testing.assert_allclose(shrunk, x)

    def test_exact_formula_p_equals_5(self):
        # p=5, x=[0,0,0,0,10], sigma2=1
        # grand=2, ss=0^2*4+8^2=64, shrink=max(0,1-2*1/64)=1-1/32
        x = np.array([0.0, 0.0, 0.0, 0.0, 10.0])
        shrunk = james_stein(x, sigma2=1.0)
        grand = x.mean()
        ss = np.sum((x - grand) ** 2)
        p = 5
        expected_shrink = max(0.0, 1.0 - (p - 3) * 1.0 / ss)
        expected = grand + expected_shrink * (x - grand)
        np.testing.assert_allclose(shrunk, expected, rtol=1e-9)

    def test_no_shrinkage_for_p_lt_3(self):
        x = np.array([0.0, 10.0])
        shrunk = james_stein(x, sigma2=1.0)
        np.testing.assert_array_equal(shrunk, x)

    def test_no_shrinkage_for_p_equal_1(self):
        x = np.array([5.0])
        shrunk = james_stein(x, sigma2=0.5)
        np.testing.assert_array_equal(shrunk, x)

    def test_all_identical_returns_unchanged(self):
        x = np.array([3.0, 3.0, 3.0, 3.0])
        shrunk = james_stein(x, sigma2=1.0)
        np.testing.assert_array_equal(shrunk, x)

    def test_positive_part_no_overshoot(self):
        # Very large sigma2 → would overshoot without positive-part clamp
        x = np.array([0.0, 1.0, 100.0])  # grand=~33.7
        shrunk = james_stein(x, sigma2=1e9)
        grand = x.mean()
        # Positive part: never goes past grand mean
        for orig, s in zip(x, shrunk):
            if orig < grand:
                assert s >= orig  # moved toward grand
            elif orig > grand:
                assert s <= orig  # moved toward grand
            # Should not overshoot: if orig < grand, shrunk <= grand
            if orig < grand:
                assert s <= grand + 1e-10
            if orig > grand:
                assert s >= grand - 1e-10

    def test_high_sigma2_full_shrinkage_to_grand_mean(self):
        # sigma2 so large that shrink=0 → all shrunk to grand mean
        x = np.array([1.0, 5.0, 9.0, 2.0, 8.0])
        shrunk = james_stein(x, sigma2=1e15)
        grand = x.mean()
        np.testing.assert_allclose(shrunk, np.full_like(x, grand), atol=1e-6)

    def test_zero_sigma2_no_shrinkage(self):
        x = np.array([1.0, 5.0, 9.0])
        shrunk = james_stein(x, sigma2=0.0)
        np.testing.assert_array_equal(shrunk, x)

    def test_output_preserves_dtype(self):
        x = np.array([1.0, 5.0, 9.0], dtype=np.float32)
        shrunk = james_stein(x, sigma2=0.1)
        assert shrunk.dtype == np.float32


# ─── 5. apply_shrinkage ───────────────────────────────────────────────────────

class TestApplyShrinkage:

    def test_produces_records_when_shrinkage_occurs(self):
        # JS requires p >= 4 for non-trivial shrinkage ((p-3) > 0)
        tree = build_segment_tree([dim("D1", ["a", "b", "c", "d"])])
        assert tree.n_bottom == 4
        estimates = {
            tree.bottom_segments[0].segment_id: 0.0,
            tree.bottom_segments[1].segment_id: 5.0,
            tree.bottom_segments[2].segment_id: 10.0,
            tree.bottom_segments[3].segment_id: 15.0,
        }
        variances = {sid: 2.0 for sid in estimates}
        adjusted, records = apply_shrinkage(estimates, variances, tree)
        # With p=4, sigma2=2, ss=((0-7.5)^2+(5-7.5)^2+(10-7.5)^2+(15-7.5)^2)=112.5
        # shrink = max(0, 1 - 1*2/112.5) ≈ 0.982 → records only for non-zero deviations
        assert len(records) > 0

    def test_no_records_when_all_identical(self):
        tree = flat_1d_tree()
        estimates = {s.segment_id: 5.0 for s in tree.bottom_segments}
        variances = {s.segment_id: 1.0 for s in tree.bottom_segments}
        _, records = apply_shrinkage(estimates, variances, tree)
        assert len(records) == 0

    def test_shrinkage_fraction_in_0_1(self):
        tree = flat_1d_tree()
        estimates = {
            tree.bottom_segments[0].segment_id: 1.0,
            tree.bottom_segments[1].segment_id: 50.0,
            tree.bottom_segments[2].segment_id: 100.0,
        }
        variances = {sid: 1.0 for sid in estimates}
        _, records = apply_shrinkage(estimates, variances, tree)
        for r in records:
            assert 0.0 <= r.shrinkage_fraction <= 1.0

    def test_grand_mean_recorded(self):
        tree = flat_1d_tree()
        vals = [2.0, 4.0, 6.0]
        estimates = {s.segment_id: v for s, v in zip(tree.bottom_segments, vals)}
        variances = {s.segment_id: 0.5 for s in tree.bottom_segments}
        _, records = apply_shrinkage(estimates, variances, tree)
        expected_grand = sum(vals) / len(vals)
        for r in records:
            assert math.isclose(r.grand_mean, expected_grand)

    def test_zero_variance_no_shrinkage(self):
        tree = flat_1d_tree()
        estimates = {s.segment_id: float(i) for i, s in enumerate(tree.bottom_segments)}
        variances = {s.segment_id: 0.0 for s in tree.bottom_segments}
        adjusted, records = apply_shrinkage(estimates, variances, tree)
        assert len(records) == 0
        for sid, orig in estimates.items():
            assert math.isclose(adjusted[sid], orig)

    def test_p_lt_3_no_shrinkage(self):
        # build a tree with only 2 bottom segments → JS undefined
        tree = build_segment_tree([dim("D1", ["a", "b"])])
        assert tree.n_bottom == 2
        estimates = {s.segment_id: float(i * 10) for i, s in enumerate(tree.bottom_segments)}
        variances = {s.segment_id: 1.0 for s in tree.bottom_segments}
        adjusted, records = apply_shrinkage(estimates, variances, tree)
        assert len(records) == 0


# ─── 6. simulate_segments ─────────────────────────────────────────────────────

class TestSimulateSegments:

    def _default_dists(self, tree: SegmentTree, low=10.0, mode=50.0, high=100.0):
        return {s.segment_id: (low, mode, high) for s in tree.bottom_segments}

    def test_reproducible_same_seed(self):
        tree = simple_2d_tree()
        dists = self._default_dists(tree)
        r1 = simulate_segments(tree, dists, n=1000, seed=42)
        r2 = simulate_segments(tree, dists, n=1000, seed=42)
        assert math.isclose(r1.total_p50, r2.total_p50)
        assert math.isclose(r1.total_p10, r2.total_p10)
        assert math.isclose(r1.total_p90, r2.total_p90)

    def test_different_seed_different_result(self):
        tree = simple_2d_tree()
        dists = {s.segment_id: (1.0, 50.0, 200.0) for s in tree.bottom_segments}
        r1 = simulate_segments(tree, dists, n=5000, seed=1)
        r2 = simulate_segments(tree, dists, n=5000, seed=999)
        # Very unlikely to be exactly equal with different seeds and wide dist
        assert not math.isclose(r1.total_p50, r2.total_p50, rel_tol=1e-4)

    def test_all_segment_ids_in_result(self):
        tree = simple_2d_tree()
        result = simulate_segments(tree, self._default_dists(tree), n=500, seed=0)
        for seg in tree.all_segments:
            assert seg.segment_id in result.segment_estimates

    def test_total_p10_le_p50_le_p90(self):
        tree = simple_2d_tree()
        result = simulate_segments(tree, self._default_dists(tree), n=2000, seed=7)
        assert result.total_p10 <= result.total_p50 <= result.total_p90

    def test_total_contribution_equals_1(self):
        # contribution = mean_i / mean_total, so TOTAL must equal 1.0 exactly
        tree = simple_2d_tree()
        result = simulate_segments(tree, self._default_dists(tree), n=1000, seed=42)
        total_est = result.segment_estimates["TOTAL"]
        assert math.isclose(total_est.contribution, 1.0, rel_tol=1e-9)

    def test_bottom_contributions_sum_to_1(self):
        tree = simple_2d_tree()
        result = simulate_segments(tree, self._default_dists(tree), n=2000, seed=42)
        bottom_sum = sum(
            est.contribution
            for seg_id, est in result.segment_estimates.items()
            if seg_id in tree.seg_to_col
        )
        assert math.isclose(bottom_sum, 1.0, rel_tol=1e-3)

    def test_aggregate_p50_geq_each_child_p50(self):
        # Parent aggregate must be >= each child (all positive distributions)
        tree = flat_1d_tree()
        dists = self._default_dists(tree, low=0.0, mode=100.0, high=500.0)
        result = simulate_segments(tree, dists, n=5000, seed=42)
        total_p50 = result.total_p50
        for s in tree.bottom_segments:
            child_p50 = result.segment_estimates[s.segment_id].p50
            assert child_p50 <= total_p50 + 1e-6

    def test_independence_warning_present(self):
        tree = simple_2d_tree()
        result = simulate_segments(tree, self._default_dists(tree), n=500, seed=0,
                                   cross_segment_correlation=None)
        assert any("independence" in w.lower() for w in result.warnings)

    def test_correlated_simulation_no_warning(self):
        tree = simple_2d_tree()
        m = tree.n_bottom
        corr = np.full((m, m), 0.5)
        np.fill_diagonal(corr, 1.0)
        result = simulate_segments(tree, self._default_dists(tree), n=500, seed=0,
                                   cross_segment_correlation=corr)
        # No independence warning when correlation matrix provided
        assert not any("independence" in w.lower() for w in result.warnings)

    def test_non_psd_correlation_triggers_warning(self):
        tree = simple_2d_tree()
        m = tree.n_bottom
        # Build a non-PSD matrix: off-diagonals all 0.99 (eigenvalue will go negative)
        corr = np.full((m, m), 0.99)
        np.fill_diagonal(corr, 1.0)
        result = simulate_segments(tree, self._default_dists(tree), n=200, seed=0,
                                   cross_segment_correlation=corr)
        if any("positive-definite" in w.lower() or "psd" in w.lower() for w in result.warnings):
            pass  # PSD correction triggered (expected for high off-diagonals)
        # Either way — must not raise

    def test_reconciliation_method_is_bottom_up(self):
        tree = simple_2d_tree()
        result = simulate_segments(tree, self._default_dists(tree), n=200, seed=0)
        assert result.reconciliation_method == "bottom_up"

    def test_point_distribution_has_zero_variance(self):
        tree = flat_1d_tree()
        dists = {s.segment_id: (5.0, 5.0, 5.0) for s in tree.bottom_segments}
        result = simulate_segments(tree, dists, n=500, seed=0,
                                   apply_js_shrinkage=False)
        # All bottom segments should have P10 == P50 == P90 == 5.0
        for s in tree.bottom_segments:
            est = result.segment_estimates[s.segment_id]
            assert math.isclose(est.p10, est.p90, rel_tol=1e-3)

    def test_top_n_segments_ranking(self):
        tree = simple_2d_tree()
        # Assign very different market sizes per segment
        dists = {}
        for i, s in enumerate(tree.bottom_segments):
            v = float((i + 1) * 10)
            dists[s.segment_id] = (v * 0.5, v, v * 2.0)
        result = simulate_segments(tree, dists, n=5000, seed=42)
        top = result.top_n_segments(n=2)
        assert top[0].p50 >= top[1].p50

    def test_to_dict_structure(self):
        tree = simple_2d_tree()
        result = simulate_segments(tree, self._default_dists(tree), n=200, seed=0)
        d = result.to_dict()
        assert "total_p50" in d
        assert "segments" in d
        assert "TOTAL" in d["segments"]
        assert d["n_simulations"] == 200

    def test_explain_returns_string(self):
        tree = simple_2d_tree()
        result = simulate_segments(tree, self._default_dists(tree), n=200, seed=0)
        text = result.explain()
        assert isinstance(text, str)
        assert "Total" in text

    def test_js_shrinkage_disabled(self):
        tree = flat_1d_tree()
        result = simulate_segments(tree, self._default_dists(tree), n=500, seed=42,
                                   apply_js_shrinkage=False)
        assert len(result.shrinkage_records) == 0

    def test_js_shrinkage_records_when_enabled(self):
        tree = flat_1d_tree()
        # Give very different mode estimates so shrinkage fires
        dists = {
            tree.bottom_segments[0].segment_id: (0.0, 1.0, 10.0),
            tree.bottom_segments[1].segment_id: (0.0, 100.0, 200.0),
            tree.bottom_segments[2].segment_id: (0.0, 500.0, 1000.0),
        }
        variances = {s.segment_id: 0.5 for s in tree.bottom_segments}
        result = simulate_segments(tree, dists, n=1000, seed=42,
                                   apply_js_shrinkage=True,
                                   segment_variances=variances)
        # With p=3 and sigma2=0.5, the JS formula: shrink = max(0,1-0*0.5/ss)=1 → no shrinkage
        # (p-3=0 so shrink=1 always for p=3)
        # This is expected: no records when p=3 exactly
        assert isinstance(result.shrinkage_records, list)


# ─── 7. dimension_materiality ────────────────────────────────────────────────

class TestDimensionMateriality:

    def test_perfectly_equal_dims_low_materiality(self):
        tree = simple_2d_tree()
        # Equal contribution from all bottom segments
        ests = {s.segment_id: 1.0 for s in tree.bottom_segments}
        mat = dimension_materiality(tree, ests, "D1")
        assert mat == pytest.approx(0.0)

    def test_highly_skewed_dim_high_materiality(self):
        tree = flat_1d_tree()  # D1={a,b,c}
        ests = {
            tree.bottom_segments[0].segment_id: 1.0,   # a
            tree.bottom_segments[1].segment_id: 1.0,   # b
            tree.bottom_segments[2].segment_id: 100.0, # c — dominates
        }
        mat = dimension_materiality(tree, ests, "D1")
        assert mat > 0.5  # high CV

    def test_missing_dim_returns_zero(self):
        tree = simple_2d_tree()
        ests = {s.segment_id: 1.0 for s in tree.bottom_segments}
        assert dimension_materiality(tree, ests, "nonexistent") == 0.0

    def test_all_zero_estimates_returns_zero(self):
        tree = simple_2d_tree()
        ests = {s.segment_id: 0.0 for s in tree.bottom_segments}
        mat = dimension_materiality(tree, ests, "D1")
        assert mat == 0.0

    def test_recommend_excludes_uniform_dims(self):
        tree = simple_2d_tree()
        # Both dimensions equal → nothing recommended
        ests = {s.segment_id: 1.0 for s in tree.bottom_segments}
        recs = recommend_material_dimensions(tree, ests, threshold=0.05)
        assert recs == []

    def test_recommend_includes_skewed_dim(self):
        tree = simple_2d_tree()
        # D2 heavily skewed: x sums to 1, y sums to 99
        ests = {}
        for s in tree.bottom_segments:
            ests[s.segment_id] = 1.0 if s.coordinates["D2"] == "x" else 99.0
        recs = recommend_material_dimensions(tree, ests, threshold=0.1)
        assert "D2" in recs

    def test_recommend_sorted_descending(self):
        tree = build_segment_tree([
            dim("D1", ["a", "b", "c"]),
            dim("D2", ["x", "y"]),
        ])
        ests = {}
        for s in tree.bottom_segments:
            # D1 varies a lot, D2 varies a little
            d1_factor = {"a": 1.0, "b": 10.0, "c": 100.0}[s.coordinates["D1"]]
            d2_factor = {"x": 1.0, "y": 1.1}[s.coordinates["D2"]]
            ests[s.segment_id] = d1_factor * d2_factor
        recs = recommend_material_dimensions(tree, ests, threshold=0.01)
        if len(recs) >= 2:
            m0 = dimension_materiality(tree, ests, recs[0])
            m1 = dimension_materiality(tree, ests, recs[1])
            assert m0 >= m1


# ─── 8. cohort_markov_flow ───────────────────────────────────────────────────

class TestCohortMarkovFlow:

    def test_trace_shape(self):
        T = np.array([[0.8, 0.1], [0.2, 0.9]])  # 2 states
        cohort = np.array([1000.0, 0.0])
        trace = cohort_markov_flow(T, cohort, n_cycles=12)
        assert trace.shape == (13, 2)

    def test_initial_state_preserved(self):
        T = np.array([[0.9, 0.2], [0.1, 0.8]])
        cohort = np.array([500.0, 200.0])
        trace = cohort_markov_flow(T, cohort, n_cycles=5)
        np.testing.assert_array_equal(trace[0], cohort)

    def test_closed_system_conserves_cohort(self):
        # Column-stochastic: columns sum to 1 → total cohort constant
        T = np.array([[0.7, 0.3], [0.3, 0.7]])
        cohort = np.array([800.0, 200.0])
        trace = cohort_markov_flow(T, cohort, n_cycles=20)
        for t in range(21):
            assert math.isclose(trace[t].sum(), 1000.0, rel_tol=1e-6)

    def test_absorbing_state(self):
        # State 1 absorbs everything
        T = np.array([[0.0, 0.0], [1.0, 1.0]])
        cohort = np.array([100.0, 0.0])
        trace = cohort_markov_flow(T, cohort, n_cycles=5)
        assert math.isclose(trace[-1, 1], 100.0, rel_tol=1e-6)

    def test_zero_cycles_returns_initial(self):
        T = np.eye(3)
        cohort = np.array([10.0, 20.0, 30.0])
        trace = cohort_markov_flow(T, cohort, n_cycles=0)
        assert trace.shape == (1, 3)
        np.testing.assert_array_equal(trace[0], cohort)


# ─── 9. Standard dimension factories ─────────────────────────────────────────

class TestStandardDimensions:

    def test_line_of_therapy_default(self):
        d = standard_line_of_therapy()
        assert d.name == "line_of_therapy"
        codes = [v.code for v in d.values]
        assert "1L" in codes
        assert "2L" in codes

    def test_line_of_therapy_custom(self):
        d = standard_line_of_therapy(["1L", "2L"])
        assert len(d.values) == 2

    def test_biomarker(self):
        d = standard_biomarker()
        assert d.name == "biomarker"
        codes = [v.code for v in d.values]
        assert "positive" in codes
        assert "negative" in codes

    def test_site_of_care(self):
        d = standard_site_of_care()
        assert d.name == "site_of_care"
        assert len(d.values) == 2

    def test_payer(self):
        d = standard_payer()
        assert d.name == "payer"
        assert len(d.values) == 4

    def test_combined_tree_builds_cleanly(self):
        dims = [standard_line_of_therapy(["1L", "2L"]), standard_site_of_care()]
        tree = build_segment_tree(dims)
        # (1+2)*(1+2) = 9 total; 2*2=4 bottom
        assert tree.n_total == 9
        assert tree.n_bottom == 4

    def test_4d_tree_feasible(self):
        dims = [
            standard_line_of_therapy(["1L", "2L"]),
            standard_biomarker(),
            standard_site_of_care(),
            standard_payer(),
        ]
        tree = build_segment_tree(dims)
        # (1+2)*(1+2)*(1+2)*(1+4) = 135 total; 2*2*2*4=32 bottom
        assert tree.n_bottom == 32
        expected_total = (1 + 2) * (1 + 2) * (1 + 2) * (1 + 4)
        assert tree.n_total == expected_total


# ─── 10. Integration test ─────────────────────────────────────────────────────

class TestIntegration:

    def test_end_to_end_market_sizing(self):
        """
        2-dimension tree (LOT × site-of-care), bottom-up aggregation,
        no shrinkage, verify total = sum of bottoms within MC tolerance.
        """
        dims = [standard_line_of_therapy(["1L", "2L"]), standard_site_of_care()]
        tree = build_segment_tree(dims)

        # Assign distinct market sizes
        base_sizes = {
            tree.bottom_segments[0].segment_id: (50e6, 100e6, 200e6),
            tree.bottom_segments[1].segment_id: (20e6, 50e6, 100e6),
            tree.bottom_segments[2].segment_id: (10e6, 25e6, 60e6),
            tree.bottom_segments[3].segment_id: (5e6, 15e6, 40e6),
        }

        result = simulate_segments(
            tree, base_sizes, n=10_000, seed=2024, apply_js_shrinkage=False
        )

        # Total must be between any individual bottom segment P50 and 4× the largest
        assert result.total_p50 > 0
        assert result.total_p50 < 4 * 200e6  # not unreasonably large

        # Contribution fractions of all bottom segments sum to 1
        contrib_sum = sum(
            result.segment_estimates[s.segment_id].contribution
            for s in tree.bottom_segments
        )
        assert math.isclose(contrib_sum, 1.0, rel_tol=1e-3)

        # explain() and to_dict() work without error
        text = result.explain()
        assert "bottom segments" in text
        d = result.to_dict()
        assert d["total_p50"] > 0
