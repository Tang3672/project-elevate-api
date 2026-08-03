"""
tests/test_monte_carlo.py
=========================
Tests for app/services/monte_carlo_engine.py (Build Spec v6, Part 1).

Governing rule: no test uses mocks — we test the actual math.
P50 ≈ deterministic mode is the core correctness property (ensures MdAPE parity).
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from app.services.monte_carlo_engine import (
    GateSpec,
    SizingDistribution,
    TornadoItem,
    _auto_widen,
    _dist_percentile,
    _sample,
    _sample_pert,
    simulate,
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_gate(value: float, gate_type: str = "rate", confidence: str = "medium",
               source_type: str = "analyst_estimate") -> GateSpec:
    return GateSpec(
        name="test_gate", label="Test gate",
        gate_type=gate_type, value=value,
        dist=None, confidence=confidence, source_type=source_type,
    )


def _simple_funnel(pop: float = 100_000, rate: float = 0.20) -> list:
    return [
        GateSpec("pop", "Population", "absolute", pop, None, "high", "public_dataset"),
        GateSpec("treat", "Treatment rate", "rate", rate, None, "medium", "analyst_estimate"),
    ]


# ──────────────────────────────────────────────────────────────────────────────
# 1. Seeded reproducibility — same inputs → identical distributions
# ──────────────────────────────────────────────────────────────────────────────

class TestReproducibility:

    def test_identical_p50_same_seed(self):
        gates = _simple_funnel()
        r1 = simulate(gates, net_price_usd=50_000, revenue_model="per_patient_per_year",
                      monetization_unit="patients", seed=42)
        r2 = simulate(gates, net_price_usd=50_000, revenue_model="per_patient_per_year",
                      monetization_unit="patients", seed=42)
        assert r1.p50 == r2.p50, "Same seed must produce identical P50"

    def test_different_p50_different_seed(self):
        gates = _simple_funnel()
        r1 = simulate(gates, net_price_usd=50_000, revenue_model="per_patient_per_year",
                      monetization_unit="patients", seed=42)
        r2 = simulate(gates, net_price_usd=50_000, revenue_model="per_patient_per_year",
                      monetization_unit="patients", seed=99)
        # With 10k samples from a wide distribution, P50 must differ
        assert r1.p50 != r2.p50, "Different seeds should produce different P50"

    def test_all_percentiles_identical_same_seed(self):
        gates = _simple_funnel()
        kw = dict(net_price_usd=80_000, revenue_model="per_patient_per_year",
                  monetization_unit="patients", seed=7777)
        r1 = simulate(gates, **kw)
        r2 = simulate(gates, **kw)
        for attr in ("p5", "p10", "p25", "p50", "p75", "p90", "p95"):
            assert getattr(r1, attr) == getattr(r2, attr), f"{attr} must match with same seed"


# ──────────────────────────────────────────────────────────────────────────────
# 2. PERT distribution — samples must stay within [low, high]
# ──────────────────────────────────────────────────────────────────────────────

class TestPertDistribution:

    def test_pert_within_bounds(self):
        rng = np.random.default_rng(42)
        low, mode, high = 10_000, 50_000, 200_000
        samples = _sample_pert(low, mode, high, n=5_000, rng=rng)
        assert samples.min() >= low * 0.999, "PERT samples must not go below low"
        assert samples.max() <= high * 1.001, "PERT samples must not exceed high"

    def test_pert_mode_near_median(self):
        """For a symmetric PERT, median should be close to mode."""
        rng = np.random.default_rng(0)
        low, mode, high = 40_000, 50_000, 60_000  # symmetric
        samples = _sample_pert(low, mode, high, n=20_000, rng=rng)
        median = np.median(samples)
        assert abs(median - mode) / mode < 0.05, (
            f"Symmetric PERT median {median:.0f} should be within 5% of mode {mode}"
        )

    def test_pert_asymmetric_upside(self):
        """When high >> low, the mean should exceed the mode (right skew)."""
        rng = np.random.default_rng(1)
        low, mode, high = 10_000, 50_000, 300_000   # strong right skew
        samples = _sample_pert(low, mode, high, n=20_000, rng=rng)
        mean = float(np.mean(samples))
        assert mean > mode, f"Right-skewed PERT mean {mean:.0f} should exceed mode {mode}"

    def test_pert_degenerate_fallback_when_high_eq_low(self):
        """When high == low, _sample_pert must return the mode without crashing."""
        rng = np.random.default_rng(5)
        samples = _sample_pert(low=100, mode=100, high=100, n=100, rng=rng)
        assert all(s == 100 for s in samples), "Degenerate PERT must return mode"


# ──────────────────────────────────────────────────────────────────────────────
# 3. Percentile ordering invariant
# ──────────────────────────────────────────────────────────────────────────────

class TestPercentileOrdering:

    def test_percentile_order(self):
        gates = _simple_funnel()
        r = simulate(gates, net_price_usd=50_000, revenue_model="per_patient_per_year",
                     monetization_unit="patients", seed=42)
        assert r.p5 <= r.p10 <= r.p25 <= r.p50 <= r.p75 <= r.p90 <= r.p95, (
            "Percentiles must be non-decreasing: p5 ≤ p10 ≤ p25 ≤ p50 ≤ p75 ≤ p90 ≤ p95"
        )

    def test_p50_positive_for_positive_funnel(self):
        gates = _simple_funnel(pop=100_000, rate=0.20)
        r = simulate(gates, net_price_usd=50_000, revenue_model="per_patient_per_year",
                     monetization_unit="patients", seed=42)
        assert r.p50 > 0, "P50 must be positive for a positive-rate funnel"

    def test_p50_near_deterministic_estimate(self):
        """
        Core MdAPE parity test: P50 must be within 20% of the mode-based point estimate.
        This ensures Monte Carlo doesn't regress vs the validated engine.
        """
        pop, rate, price = 100_000, 0.15, 80_000
        deterministic = pop * rate * price   # $1.2B
        gates = _simple_funnel(pop=pop, rate=rate)
        r = simulate(gates, net_price_usd=price, revenue_model="per_patient_per_year",
                     monetization_unit="patients", seed=42, n=20_000)
        pct_err = abs(r.p50 - deterministic) / deterministic
        assert pct_err < 0.20, (
            f"P50 {r.p50:,.0f} is {pct_err:.1%} from deterministic {deterministic:,.0f}; "
            "must be within 20% (MdAPE budget)"
        )

    def test_p10_lt_p90_non_trivially(self):
        """P10 must be meaningfully below P90 — not a degenerate point mass."""
        gates = _simple_funnel()
        r = simulate(gates, net_price_usd=50_000, revenue_model="per_patient_per_year",
                     monetization_unit="patients", seed=42)
        ratio = r.p90 / r.p10
        assert ratio > 1.5, (
            f"P90/P10 ratio {ratio:.2f} is too low; distribution appears degenerate. "
            "Auto-widening should produce a meaningful spread."
        )


# ──────────────────────────────────────────────────────────────────────────────
# 4. Auto-widening — confidence levels produce correct spread
# ──────────────────────────────────────────────────────────────────────────────

class TestAutoWidening:

    def test_high_confidence_narrower_than_low(self):
        # Use absolute gate_type with population-scale values (rates cap at 1.0 and become degenerate)
        gate_high = _make_gate(value=100_000, gate_type="absolute", confidence="high")
        gate_low  = _make_gate(value=100_000, gate_type="absolute", confidence="low")
        d_high = _auto_widen(gate_high)
        d_low  = _auto_widen(gate_low)
        spread_high = d_high["high"] - d_high["low"]
        spread_low  = d_low["high"]  - d_low["low"]
        assert spread_high < spread_low, (
            "High-confidence auto-widen must produce a narrower range than low-confidence"
        )

    def test_auto_widen_is_pert(self):
        # Use a rate value within [0, 1] so the rate clamping doesn't trigger the degenerate fallback
        gate = _make_gate(value=0.20, gate_type="rate", confidence="medium")
        d = _auto_widen(gate)
        assert d["type"] == "pert", "Auto-widen should produce a PERT distribution"

    def test_rate_gate_stays_below_one(self):
        gate = _make_gate(value=0.70, gate_type="rate", confidence="low")
        d = _auto_widen(gate)
        assert d.get("high", 1.0) <= 1.0, "Rate gate auto-widen must cap at 1.0"

    def test_zero_value_returns_point(self):
        gate = _make_gate(value=0.0, gate_type="absolute", confidence="high")
        d = _auto_widen(gate)
        assert d["type"] == "point" and d["value"] == 0.0


# ──────────────────────────────────────────────────────────────────────────────
# 5. Tornado ranking — largest-swing gates ranked first
# ──────────────────────────────────────────────────────────────────────────────

class TestTornadoRanking:

    def test_tornado_sorted_descending_by_swing(self):
        # Wide population gate + tight rate → population should rank higher
        gates = [
            GateSpec("pop",   "Population",     "absolute", 100_000, None, "low",    "llm_inference"),
            GateSpec("treat", "Treatment rate", "rate",     0.15,    None, "high",   "public_dataset"),
        ]
        r = simulate(gates, net_price_usd=50_000, revenue_model="per_patient_per_year",
                     monetization_unit="patients", seed=42)
        assert len(r.tornado) >= 2, "Should have ≥2 tornado items (gates + price)"
        swings = [t.swing_usd for t in r.tornado]
        assert swings == sorted(swings, reverse=True), (
            "Tornado items must be sorted by swing_usd descending"
        )

    def test_tornado_includes_price_gate(self):
        gates = _simple_funnel()
        r = simulate(gates, net_price_usd=100_000, revenue_model="per_patient_per_year",
                     monetization_unit="patients", seed=42)
        names = [t.gate_name for t in r.tornado]
        assert "price" in names, "Tornado must include price as a gate"

    def test_tornado_expert_question_not_empty(self):
        gates = _simple_funnel()
        r = simulate(gates, net_price_usd=50_000, revenue_model="per_patient_per_year",
                     monetization_unit="patients", seed=42)
        for item in r.tornado:
            assert item.expert_question, f"Tornado item {item.gate_name} must have an expert_question"


# ──────────────────────────────────────────────────────────────────────────────
# 6. explain() output — plain-text derivation
# ──────────────────────────────────────────────────────────────────────────────

class TestExplain:

    def test_explain_returns_string(self):
        gates = _simple_funnel()
        r = simulate(gates, net_price_usd=50_000, revenue_model="per_patient_per_year",
                     monetization_unit="patients", seed=42)
        exp = r.explain()
        assert isinstance(exp, str) and len(exp) > 100, "explain() must return a non-trivial string"

    def test_explain_contains_p50(self):
        gates = _simple_funnel()
        r = simulate(gates, net_price_usd=50_000, revenue_model="per_patient_per_year",
                     monetization_unit="patients", seed=42)
        exp = r.explain()
        assert "P50" in exp, "explain() must include P50 headline"

    def test_explain_contains_gate_table(self):
        gates = _simple_funnel()
        r = simulate(gates, net_price_usd=50_000, revenue_model="per_patient_per_year",
                     monetization_unit="patients", seed=42)
        exp = r.explain()
        assert "Population" in exp or "Treatment rate" in exp, (
            "explain() must include a gate table with gate labels"
        )

    def test_explain_contains_seed(self):
        gates = _simple_funnel()
        r = simulate(gates, net_price_usd=50_000, revenue_model="per_patient_per_year",
                     monetization_unit="patients", seed=42)
        exp = r.explain()
        assert "42" in exp, "explain() must surface the seed for reproducibility"

    def test_explain_mentions_largest_driver(self):
        gates = [
            GateSpec("pop",   "Population",     "absolute", 200_000, None, "low",  "llm_inference"),
            GateSpec("treat", "Treatment rate", "rate",     0.10,    None, "high", "public_dataset"),
        ]
        r = simulate(gates, net_price_usd=50_000, revenue_model="per_patient_per_year",
                     monetization_unit="patients", seed=42)
        exp = r.explain()
        # At least one tornado gate label must appear in the explain output
        if r.tornado:
            assert r.tornado[0].gate_label in exp, (
                "explain() must mention the largest uncertainty driver"
            )


# ──────────────────────────────────────────────────────────────────────────────
# 7. JSON serialization — to_dict() must be JSON-safe
# ──────────────────────────────────────────────────────────────────────────────

class TestJsonSerialization:

    def test_to_dict_is_json_serializable(self):
        gates = _simple_funnel()
        r = simulate(gates, net_price_usd=50_000, revenue_model="per_patient_per_year",
                     monetization_unit="patients", seed=42)
        d = r.to_dict()
        serialized = json.dumps(d)  # must not raise
        assert len(serialized) > 100, "to_dict() should produce a non-trivial JSON payload"

    def test_to_dict_has_required_keys(self):
        gates = _simple_funnel()
        r = simulate(gates, net_price_usd=50_000, revenue_model="per_patient_per_year",
                     monetization_unit="patients", seed=42)
        d = r.to_dict()
        for key in ("p10", "p50", "p90", "revenue_model", "n_simulations", "seed",
                    "tornado", "gate_summaries"):
            assert key in d, f"to_dict() missing required key: {key}"

    def test_tornado_items_json_serializable(self):
        gates = _simple_funnel()
        r = simulate(gates, net_price_usd=50_000, revenue_model="per_patient_per_year",
                     monetization_unit="patients", seed=42)
        for item in r.tornado:
            d = item.to_dict()
            json.dumps(d)  # must not raise

    def test_n_simulations_correct(self):
        gates = _simple_funnel()
        r = simulate(gates, net_price_usd=50_000, revenue_model="per_patient_per_year",
                     monetization_unit="patients", seed=42, n=5_000)
        assert r.n_simulations == 5_000
        assert r.to_dict()["n_simulations"] == 5_000


# ──────────────────────────────────────────────────────────────────────────────
# 8. Empty funnel — must not crash
# ──────────────────────────────────────────────────────────────────────────────

class TestEdgeCases:

    def test_empty_gates_returns_zero_distribution(self):
        r = simulate([], net_price_usd=50_000, revenue_model="per_patient_per_year",
                     monetization_unit="patients", seed=42)
        assert r.p50 == 0, "Empty funnel must return P50=0"

    def test_single_absolute_gate(self):
        gates = [GateSpec("pop", "Pop", "absolute", 50_000, None, "high", "public_dataset")]
        r = simulate(gates, net_price_usd=100, revenue_model="per_patient_per_year",
                     monetization_unit="patients", seed=42)
        # Revenue = pop × price; P50 should be near 50_000 × 100 = $5M
        assert r.p50 > 0, "Single absolute gate must produce positive P50"

    def test_gate_with_explicit_dist_spec(self):
        """Explicit dist spec on a gate overrides auto-widen."""
        gates = [
            GateSpec("pop", "Population", "absolute", 100_000,
                     {"type": "uniform", "low": 80_000, "high": 120_000},
                     "high", "public_dataset"),
        ]
        r = simulate(gates, net_price_usd=50_000, revenue_model="per_patient_per_year",
                     monetization_unit="patients", seed=42)
        assert r.p10 >= 80_000 * 50_000 * 0.8, "Explicit uniform dist must bound the output"
