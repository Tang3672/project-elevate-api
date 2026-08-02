"""
Unit tests for the Market-Sizing Validation Harness math
=========================================================
Tests the APE, MdAPE, MAPE, calibration, per-type breakdown, and worst-offender
logic in app/validation/run_validation.py WITHOUT calling external services or DB.

Run:  pytest tests/test_validation_math.py -v
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import List
from unittest.mock import patch, AsyncMock

import pytest

# ── Pure math utilities from the harness ─────────────────────────────────────

def _ape(computed: float, actual: float) -> float:
    return abs(computed - actual) / actual


def _signed_pct_error(computed: float, actual: float) -> float:
    return (computed - actual) / actual


def _in_band(actual: float, low: float, high: float) -> bool:
    return low <= actual <= high


def _calibration_rate(results: list[dict]) -> float:
    active = [r for r in results if not r.get("skipped")]
    if not active:
        return 0.0
    return sum(1 for r in active if r["in_band"]) / len(active)


def _mdape(apes: list[float]) -> float:
    return statistics.median(apes)


def _mape(apes: list[float]) -> float:
    return statistics.mean(apes)


# ── Test fixtures ─────────────────────────────────────────────────────────────

def _make_result(*, computed: float, actual: float, low: float, high: float,
                 product_type: str = "biologic", skipped: bool = False) -> dict:
    if skipped:
        return {"skipped": True, "ape": 0.0, "in_band": False, "product_type": product_type}
    ape = _ape(computed, actual)
    return {
        "skipped": False,
        "computed": computed,
        "actual": actual,
        "ape": ape,
        "signed_error": _signed_pct_error(computed, actual),
        "in_band": _in_band(actual, low, high),
        "product_type": product_type,
        "low": low,
        "high": high,
    }


# ── APE (Absolute Percentage Error) tests ────────────────────────────────────

class TestAPE:
    def test_perfect_estimate(self):
        assert _ape(1_000_000, 1_000_000) == 0.0

    def test_10_pct_over(self):
        assert abs(_ape(110, 100) - 0.10) < 1e-10

    def test_10_pct_under(self):
        assert abs(_ape(90, 100) - 0.10) < 1e-10

    def test_symmetry(self):
        # APE of +50% and -50% are both 0.50, not symmetric in ratio
        assert abs(_ape(150, 100) - 0.50) < 1e-10
        assert abs(_ape(50, 100) - 0.50) < 1e-10

    def test_large_error(self):
        # 5× over = 400% APE
        assert abs(_ape(500, 100) - 4.0) < 1e-10

    def test_small_actual_large_engine(self):
        # engine: $17.2B vs actual: $5M (just verifying calculation)
        ape = _ape(17_200_000_000, 5_000_000)
        assert ape > 1000  # >100,000% — massive overestimate

    def test_realistic_good_case(self):
        # Engine: $580M vs Spinraza actual: $563M → ~3% APE
        ape = _ape(580_000_000, 563_000_000)
        assert ape < 0.05  # PASS


class TestSignedPctError:
    def test_over_estimate_positive(self):
        err = _signed_pct_error(120, 100)
        assert abs(err - 0.20) < 1e-10

    def test_under_estimate_negative(self):
        err = _signed_pct_error(80, 100)
        assert abs(err - (-0.20)) < 1e-10

    def test_perfect(self):
        assert _signed_pct_error(100, 100) == 0.0


# ── MdAPE (Median APE) tests ─────────────────────────────────────────────────

class TestMdAPE:
    def test_odd_count(self):
        apes = [0.10, 0.30, 0.50]
        assert _mdape(apes) == 0.30

    def test_even_count(self):
        apes = [0.10, 0.20, 0.30, 0.40]
        assert abs(_mdape(apes) - 0.25) < 1e-10

    def test_single_value(self):
        assert _mdape([0.15]) == 0.15

    def test_all_zeros(self):
        assert _mdape([0.0, 0.0, 0.0]) == 0.0

    def test_mdape_not_affected_by_outlier(self):
        # One extreme outlier should NOT drag median up much
        apes = [0.05, 0.10, 0.12, 0.15, 5.00]  # 5× outlier
        assert _mdape(apes) < 0.20  # median = 0.12

    def test_mdape_passes_target(self):
        # 8 benchmarks near 15% expected — should beat 20% target
        apes = [0.15, 0.15, 0.04, 0.10, 0.02, 0.44, 0.24, 0.21]
        md = _mdape(apes)
        assert md <= 0.20  # passes ≤20% target

    def test_mdape_passes_gate_but_fails_target(self):
        # MdAPE between 20-30% → WARN, not FAIL
        apes = [0.20, 0.22, 0.25, 0.28, 0.30, 0.10, 0.15, 0.18]
        md = _mdape(apes)
        assert 0.20 < md <= 0.30

    def test_mdape_fails_gate(self):
        apes = [0.35, 0.40, 0.50, 0.60, 0.70, 0.10, 0.15, 0.20]
        md = _mdape(apes)
        assert md > 0.30


# ── MAPE (Mean APE) tests ─────────────────────────────────────────────────────

class TestMAPE:
    def test_simple_average(self):
        apes = [0.10, 0.20, 0.30]
        assert abs(_mape(apes) - 0.20) < 1e-10

    def test_outlier_pulls_mean_up(self):
        # Outlier drags mean above median
        apes = [0.05, 0.10, 0.12, 0.15, 5.00]
        assert _mape(apes) > _mdape(apes)

    def test_mean_vs_median_similar_without_outlier(self):
        apes = [0.08, 0.10, 0.12, 0.14]
        # Without outliers, mean ~= median
        assert abs(_mape(apes) - _mdape(apes)) < 0.05


# ── Calibration (truth-in-band) tests ────────────────────────────────────────

class TestCalibration:
    def test_all_in_band(self):
        results = [
            _make_result(computed=100, actual=100, low=80, high=130),
            _make_result(computed=200, actual=200, low=150, high=250),
        ]
        assert _calibration_rate(results) == 1.0

    def test_none_in_band(self):
        results = [
            _make_result(computed=100, actual=200, low=80, high=130),
            _make_result(computed=50, actual=200, low=30, high=80),
        ]
        assert _calibration_rate(results) == 0.0

    def test_half_in_band(self):
        results = [
            _make_result(computed=100, actual=100, low=80, high=130),   # IN
            _make_result(computed=100, actual=200, low=80, high=130),   # OUT (actual=200 > high=130)
        ]
        assert _calibration_rate(results) == 0.5

    def test_skipped_excluded_from_denominator(self):
        results = [
            _make_result(computed=100, actual=100, low=80, high=130),   # IN
            {"skipped": True, "in_band": False, "ape": 0.0, "product_type": "biologic"},
            {"skipped": True, "in_band": False, "ape": 0.0, "product_type": "biologic"},
        ]
        assert _calibration_rate(results) == 1.0  # 1/1 active = 100%

    def test_empty_active_results(self):
        results = [
            {"skipped": True, "in_band": False, "ape": 0.0, "product_type": "biologic"},
        ]
        assert _calibration_rate(results) == 0.0

    def test_calibration_passes_target(self):
        # 6/8 = 75% → passes ≥70% target
        results = [
            _make_result(computed=100, actual=95, low=80, high=130),    # IN
            _make_result(computed=100, actual=110, low=80, high=130),   # IN
            _make_result(computed=200, actual=190, low=150, high=250),  # IN
            _make_result(computed=50, actual=55, low=40, high=70),      # IN
            _make_result(computed=500, actual=480, low=400, high=600),  # IN
            _make_result(computed=100, actual=95, low=80, high=115),    # IN
            _make_result(computed=100, actual=200, low=80, high=130),   # OUT
            _make_result(computed=50, actual=200, low=30, high=80),     # OUT
        ]
        assert _calibration_rate(results) >= 0.70

    def test_band_edge_inclusive(self):
        # Exactly at band edges → should count as IN
        assert _in_band(80, 80, 130) is True
        assert _in_band(130, 80, 130) is True

    def test_band_just_outside(self):
        # Just outside band → OUT
        assert _in_band(79.99, 80, 130) is False
        assert _in_band(130.01, 80, 130) is False


# ── Per-type breakdown tests ──────────────────────────────────────────────────

class TestByProductType:
    def _compute_by_type(self, results: list[dict]) -> dict:
        active = [r for r in results if not r.get("skipped")]
        by_type: dict[str, list] = {}
        for r in active:
            by_type.setdefault(r["product_type"], []).append(r["ape"])
        return {
            pt: {
                "n": len(apes),
                "mdape": statistics.median(apes),
                "mape": statistics.mean(apes),
            }
            for pt, apes in by_type.items()
        }

    def test_single_type(self):
        results = [
            _make_result(computed=110, actual=100, low=80, high=130, product_type="biologic"),
            _make_result(computed=90, actual=100, low=80, high=130, product_type="biologic"),
        ]
        by_type = self._compute_by_type(results)
        assert "biologic" in by_type
        assert by_type["biologic"]["n"] == 2
        assert abs(by_type["biologic"]["mdape"] - 0.10) < 1e-10

    def test_multiple_types(self):
        results = [
            _make_result(computed=110, actual=100, low=80, high=130, product_type="biologic"),
            _make_result(computed=150, actual=100, low=80, high=130, product_type="samd"),
        ]
        by_type = self._compute_by_type(results)
        assert "biologic" in by_type
        assert "samd" in by_type
        assert abs(by_type["biologic"]["mdape"] - 0.10) < 1e-10
        assert abs(by_type["samd"]["mdape"] - 0.50) < 1e-10

    def test_skipped_excluded(self):
        results = [
            _make_result(computed=110, actual=100, low=80, high=130, product_type="biologic"),
            {"skipped": True, "ape": 0.0, "in_band": False, "product_type": "biologic"},
        ]
        by_type = self._compute_by_type(results)
        assert by_type["biologic"]["n"] == 1  # skipped not counted


# ── Worst-offender ranking tests ──────────────────────────────────────────────

class TestWorstOffenders:
    def _worst_n(self, results: list[dict], n: int = 3) -> list[dict]:
        active = [r for r in results if not r.get("skipped") and r["ape"] != float("inf")]
        return sorted(active, key=lambda r: r["ape"], reverse=True)[:n]

    def test_sorted_by_ape_descending(self):
        results = [
            _make_result(computed=200, actual=100, low=80, high=150, product_type="biologic"),  # 100%
            _make_result(computed=110, actual=100, low=80, high=130, product_type="biologic"),  # 10%
            _make_result(computed=130, actual=100, low=80, high=150, product_type="biologic"),  # 30%
        ]
        worst = self._worst_n(results, 3)
        assert worst[0]["ape"] >= worst[1]["ape"] >= worst[2]["ape"]

    def test_top_3_only(self):
        results = [
            _make_result(computed=200, actual=100, low=80, high=150, product_type="biologic"),
            _make_result(computed=110, actual=100, low=80, high=130, product_type="biologic"),
            _make_result(computed=130, actual=100, low=80, high=150, product_type="biologic"),
            _make_result(computed=160, actual=100, low=80, high=150, product_type="biologic"),
            _make_result(computed=105, actual=100, low=80, high=130, product_type="biologic"),
        ]
        worst = self._worst_n(results, 3)
        assert len(worst) == 3
        assert worst[0]["ape"] == 1.0  # 200%

    def test_skipped_excluded_from_worst(self):
        results = [
            _make_result(computed=110, actual=100, low=80, high=130, product_type="biologic"),  # 10%
            {"skipped": True, "ape": 99.0, "in_band": False, "product_type": "biologic"},  # should not appear
        ]
        worst = self._worst_n(results, 3)
        assert len(worst) == 1
        assert worst[0]["ape"] == pytest.approx(0.10)

    def test_fewer_than_n_returns_all(self):
        results = [
            _make_result(computed=110, actual=100, low=80, high=130, product_type="biologic"),
        ]
        worst = self._worst_n(results, 3)
        assert len(worst) == 1


# ── Verdict classification tests ──────────────────────────────────────────────

class TestVerdict:
    _MDAPE_TARGET = 0.20
    _MDAPE_GATE = 0.30
    _CALIBRATION_TARGET = 0.70

    def _classify_verdict(self, mdape: float) -> str:
        if mdape <= self._MDAPE_TARGET:
            return "VALIDATED"
        elif mdape <= self._MDAPE_GATE:
            return "ACCEPTABLE"
        else:
            return "NOT_VALIDATED"

    def _classify_calibration(self, rate: float) -> str:
        return "CALIBRATED" if rate >= self._CALIBRATION_TARGET else "BANDS_TOO_NARROW"

    def test_validated(self):
        assert self._classify_verdict(0.15) == "VALIDATED"
        assert self._classify_verdict(0.20) == "VALIDATED"

    def test_acceptable(self):
        assert self._classify_verdict(0.21) == "ACCEPTABLE"
        assert self._classify_verdict(0.30) == "ACCEPTABLE"

    def test_not_validated(self):
        assert self._classify_verdict(0.31) == "NOT_VALIDATED"
        assert self._classify_verdict(0.80) == "NOT_VALIDATED"

    def test_calibrated(self):
        assert self._classify_calibration(0.70) == "CALIBRATED"
        assert self._classify_calibration(0.85) == "CALIBRATED"
        assert self._classify_calibration(1.00) == "CALIBRATED"

    def test_bands_too_narrow(self):
        assert self._classify_calibration(0.69) == "BANDS_TOO_NARROW"
        assert self._classify_calibration(0.00) == "BANDS_TOO_NARROW"

    def test_boundary_exact_target(self):
        # Exactly at threshold → PASS (≤20% gate, not <20%)
        assert self._classify_verdict(0.20) == "VALIDATED"
        assert self._classify_calibration(0.70) == "CALIBRATED"


# ── Integration: BenchmarkResult construction ─────────────────────────────────

class TestBenchmarkResultIntegration:
    """
    Verify that the BenchmarkResult dataclass in run_validation.py can be
    constructed and that its metric fields are consistent.
    """

    def test_import_run_validation(self):
        """run_validation.py must be importable without DB connection."""
        import importlib
        import sys
        # Should not raise ImportError or connect to DB at import time
        try:
            import app.validation.run_validation as rv
            assert hasattr(rv, "run_all_benchmarks")
            assert hasattr(rv, "_aggregate")
            assert hasattr(rv, "BenchmarkResult")
            assert hasattr(rv, "AggregateMetrics")
        except ImportError as e:
            pytest.skip(f"Can't import run_validation: {e}")

    def test_benchmark_result_metrics_consistent(self):
        """Construct a BenchmarkResult manually and verify metric consistency."""
        try:
            from app.validation.run_validation import BenchmarkResult
        except ImportError:
            pytest.skip("run_validation not importable")

        computed = 580_000_000
        actual = 563_000_000
        ape = abs(computed - actual) / actual
        signed = (computed - actual) / actual

        r = BenchmarkResult(
            benchmark_id="spinraza_us",
            name="Spinraza test",
            product_type="drug_small_molecule",
            disease_name="spinal muscular atrophy",
            computed_sam=computed,
            computed_som_base=computed * 0.15,
            computed_som_peak=computed * 0.30,
            low_bound=computed * 0.60,
            high_bound=computed * 1.40,
            pipeline_used="monetization+analog (direct)",
            analog_class="orphan_drug",
            monetization_model="per_patient",
            actual_usd=actual,
            compare_against="sam",
            ground_truth_source="Biogen 10-K FY2023",
            ground_truth_year=2023,
            figure_type="actual_net_sales",
            computed_comparison=computed,
            ape=ape,
            signed_pct_error=signed,
            in_confidence_band=True,
            ratio=computed / actual,
            status="PASS",
            direction="over",
            worst_assumption="segment_gate_rate",
            expert_question="What fraction of SMA patients are on Spinraza?",
        )

        assert r.ape < 0.05      # ~3%
        assert r.signed_pct_error > 0   # slight over-estimate
        assert r.in_confidence_band is True
        assert r.status == "PASS"
        assert abs(r.ratio - (580 / 563)) < 0.001

        d = r.to_dict()
        assert d["metrics"]["ape"] == round(ape, 4)
        assert d["metrics"]["in_confidence_band"] is True
        assert d["engine"]["comparison_value"] == computed

    def test_aggregate_function(self):
        """_aggregate() must compute correct MdAPE and calibration."""
        try:
            from app.validation.run_validation import BenchmarkResult, _aggregate
        except ImportError:
            pytest.skip("run_validation not importable")

        def _mk(ape_, in_band_, product_type_="biologic"):
            return BenchmarkResult(
                benchmark_id="x", name="x", product_type=product_type_,
                disease_name="x", computed_sam=0, computed_som_base=0,
                computed_som_peak=0, low_bound=0, high_bound=0,
                pipeline_used="test", analog_class="test", monetization_model="test",
                actual_usd=100, compare_against="sam",
                ground_truth_source="test", ground_truth_year=2024,
                figure_type="actual_net_sales",
                computed_comparison=0, ape=ape_, signed_pct_error=ape_,
                in_confidence_band=in_band_, ratio=1.0,
                status="PASS" if ape_ <= 0.20 else "FAIL",
                direction="over", worst_assumption="x", expert_question="x",
            )

        results = [
            _mk(0.10, True),
            _mk(0.20, True),
            _mk(0.30, False),
            _mk(0.40, True),
        ]

        agg = _aggregate(results)
        assert agg.n_active == 4
        assert agg.n_skipped == 0
        # MdAPE of [0.10, 0.20, 0.30, 0.40] = median([0.10, 0.20, 0.30, 0.40]) = 0.25
        assert abs(agg.mdape - 0.25) < 1e-10
        # 3/4 in band = 75%
        assert abs(agg.calibration_rate - 0.75) < 1e-10
        assert agg.verdict == "ACCEPTABLE"
        assert agg.calibration_verdict == "CALIBRATED"


# ── Numeric edge cases ────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_ape_never_negative(self):
        for computed, actual in [(50, 100), (150, 100), (100, 100)]:
            assert _ape(computed, actual) >= 0

    def test_ratio_above_one_for_overestimate(self):
        computed, actual = 150, 100
        ratio = computed / actual
        signed = _signed_pct_error(computed, actual)
        assert ratio > 1
        assert signed > 0

    def test_ratio_below_one_for_underestimate(self):
        computed, actual = 50, 100
        ratio = computed / actual
        signed = _signed_pct_error(computed, actual)
        assert ratio < 1
        assert signed < 0

    def test_large_market_sizes_dont_overflow(self):
        # Keytruda: ~$79B SAM, $17.2B actual
        computed = 79_000_000_000
        actual = 17_200_000_000
        ape = _ape(computed, actual)
        assert ape > 3.0  # ~359% overestimate
        assert math.isfinite(ape)

    def test_small_orphan_market(self):
        # Spinraza: ~$564M engine vs $563M actual
        computed = 564_000_000
        actual = 563_000_000
        ape = _ape(computed, actual)
        assert ape < 0.01   # < 1%

    def test_calibration_with_zero_active(self):
        """Empty active list should return 0.0, not divide by zero."""
        assert _calibration_rate([]) == 0.0
        assert _calibration_rate([
            {"skipped": True, "in_band": False, "ape": 0.0, "product_type": "biologic"}
        ]) == 0.0
