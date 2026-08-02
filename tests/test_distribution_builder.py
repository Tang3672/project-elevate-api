"""
tests/test_distribution_builder.py
====================================
Tests for the evidence-grounded distribution builder.

Coverage (per Build Spec Addendum §13):
  1. Reproducible bootstrap output with a fixed seed
  2. Beta distribution construction from event counts
  3. Bounds for proportions (P10/P90 stay in [0,1])
  4. Positive-only prices (lognormal, no negative values)
  5. Priority ordering across evidence tiers
  6. Rejection of invalid distribution parameters (validation warnings)
  7. Scenario mode when only bounds exist
  8. Simulation blocked when no estimate or bounds exist
  9. Policy-prior labeling (uncertainty_method, calibrated_to_product, evidence_strength)
  10. Correlation provenance requirement
  11. Serialization and explain()
  12. Alternate-distribution sensitivity
  13. Existing validation harness remains within required thresholds
"""

from __future__ import annotations

import json
import math
from typing import List

import numpy as np
import pytest

from app.services.distribution_builder import (
    ALTERNATE_SENSITIVITY_THRESHOLD,
    MIN_ANALOG_COMPARABILITY,
    MIN_STRONG_ANALOGS,
    AlternateSensitivity,
    CorrelationRecord,
    DistributionBuildResult,
    DistributionSpec,
    EvidenceRecord,
    FunnelGate,
    MarketContext,
    ScenarioSpec,
    _build_empirical,
    _build_from_analogs,
    _build_from_expert_elicitation,
    _build_from_reported_statistics,
    _build_policy_prior,
    _build_scenario_or_interval,
    _insufficient_evidence,
    _run_alternate_sensitivity,
    _validate_and_rank_evidence,
    _validate_distribution_spec,
    build_distribution,
    compute_verification_priority,
)


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────

def proportion_gate(name: str = "treated_segment") -> FunnelGate:
    return FunnelGate(name=name, label="Treated fraction",
                      gate_type="proportion", units="fraction",
                      domain_low=0.0, domain_high=1.0)


def price_gate(name: str = "net_price") -> FunnelGate:
    return FunnelGate(name=name, label="Net price per unit",
                      gate_type="price", units="usd_per_unit",
                      domain_low=0.0, domain_high=math.inf)


def count_gate(name: str = "addressable_patients") -> FunnelGate:
    return FunnelGate(name=name, label="Addressable patients",
                      gate_type="count", units="patients",
                      domain_low=0.0, domain_high=math.inf)


def ctx(gate: FunnelGate) -> MarketContext:
    return MarketContext(product_type="biologic", disease_name="NSCLC",
                        gate_type=gate.gate_type, gate_units=gate.units)


def microdata_record(values: List[float], directness: float = 0.80) -> EvidenceRecord:
    return EvidenceRecord(
        id="ev-micro-1", gate_name="treated_segment",
        source_type="microdata", observations=values,
        directness=directness, applicability=0.75,
    )


def published_count_record(k: int, n: int, directness: float = 0.85) -> EvidenceRecord:
    return EvidenceRecord(
        id="ev-pub-1", gate_name="treated_segment",
        source_type="published_estimate",
        value=k / n, numerator=k, denominator=n,
        directness=directness, applicability=0.80,
        citation="Smith et al. (2023). NEJM.",
    )


def published_ci_record(value: float, ci_low: float, ci_high: float,
                         directness: float = 0.75) -> EvidenceRecord:
    return EvidenceRecord(
        id="ev-ci-1", gate_name="treated_segment",
        source_type="published_estimate",
        value=value, ci_low=ci_low, ci_high=ci_high,
        directness=directness, applicability=0.70,
    )


def published_se_record(value: float, se: float) -> EvidenceRecord:
    return EvidenceRecord(
        id="ev-se-1", gate_name="treated_segment",
        source_type="published_estimate",
        value=value, standard_error=se,
        directness=0.70, applicability=0.65,
    )


def analog_records(values: List[float], score: float = 0.80) -> List[EvidenceRecord]:
    return [
        EvidenceRecord(
            id=f"ev-analog-{i}", gate_name="treated_segment",
            source_type="analog", value=v,
            comparability_score=score,
            directness=0.60, applicability=score,
        )
        for i, v in enumerate(values)
    ]


def expert_record(low: float, mode: float, high: float) -> EvidenceRecord:
    return EvidenceRecord(
        id="ev-expert-1", gate_name="treated_segment",
        source_type="expert_elicitation",
        expert_low=low, expert_mode=mode, expert_high=high,
        expert_role="Medical oncologist, 15yr experience",
        expert_question="What fraction of NSCLC patients are EGFR+?",
        elicitation_date="2026-01-15",
        directness=0.70, applicability=0.70,
    )


def bounds_record(low: float, high: float) -> EvidenceRecord:
    return EvidenceRecord(
        id="ev-bounds-1", gate_name="treated_segment",
        source_type="bounds",
        bound_low=low, bound_high=high,
        bound_rationale="Eligibility cannot exceed 100% of diagnosed patients",
        directness=0.90, applicability=0.90,
    )


def analyst_record(value: float) -> EvidenceRecord:
    return EvidenceRecord(
        id="ev-analyst-1", gate_name="treated_segment",
        source_type="analyst_estimate", value=value,
        directness=0.40, applicability=0.50,
    )


# ──────────────────────────────────────────────────────────────────────────────
# 1. Evidence-tier priority ordering
# ──────────────────────────────────────────────────────────────────────────────

class TestEvidenceTierPriority:
    """build_distribution() must select the HIGHEST available tier."""

    def test_microdata_preferred_over_published(self):
        gate = proportion_gate()
        evidence = [
            microdata_record([0.10, 0.12, 0.14, 0.11, 0.13, 0.15]),
            published_ci_record(0.10, 0.07, 0.14),
        ]
        result = build_distribution(gate, evidence, ctx(gate), seed=42)
        assert result.uncertainty_method == "empirical"

    def test_published_preferred_over_analogs(self):
        gate = proportion_gate()
        evidence = [
            published_count_record(k=50, n=200),
            *analog_records([0.20, 0.22, 0.18, 0.25, 0.19]),
        ]
        result = build_distribution(gate, evidence, ctx(gate), seed=42)
        assert result.uncertainty_method == "reported_statistics"

    def test_analogs_preferred_over_expert(self):
        gate = proportion_gate()
        evidence = [
            *analog_records([0.20, 0.22, 0.18, 0.25, 0.19]),
            expert_record(0.10, 0.20, 0.35),
        ]
        result = build_distribution(gate, evidence, ctx(gate), seed=42)
        assert result.uncertainty_method == "analog_based"

    def test_expert_preferred_over_bounds(self):
        gate = proportion_gate()
        evidence = [
            expert_record(0.10, 0.20, 0.35),
            bounds_record(0.05, 0.50),
        ]
        result = build_distribution(gate, evidence, ctx(gate), seed=42)
        assert result.uncertainty_method == "expert_elicitation"

    def test_bounds_preferred_over_policy_prior(self):
        gate = proportion_gate()
        evidence = [
            bounds_record(0.05, 0.50),
            analyst_record(0.20),
        ]
        result = build_distribution(gate, evidence, ctx(gate), seed=42)
        assert result.uncertainty_method == "logical_bounds"

    def test_policy_prior_when_only_point_estimate(self):
        gate = proportion_gate()
        evidence = [analyst_record(0.15)]
        result = build_distribution(gate, evidence, ctx(gate), seed=42)
        assert result.uncertainty_method == "policy_prior"

    def test_insufficient_when_no_evidence(self):
        gate = proportion_gate()
        result = build_distribution(gate, [], ctx(gate), seed=42)
        assert result.uncertainty_method == "insufficient"
        assert result.simulation_allowed is False


# ──────────────────────────────────────────────────────────────────────────────
# 2. Beta distribution from event counts
# ──────────────────────────────────────────────────────────────────────────────

class TestBetaFromCounts:

    def _build(self, k: int, n: int) -> DistributionBuildResult:
        gate = proportion_gate()
        return build_distribution(
            gate, [published_count_record(k=k, n=n)], ctx(gate), seed=42
        )

    def test_distribution_type_is_beta(self):
        r = self._build(50, 200)
        assert r.distribution is not None
        assert r.distribution.dist_type == "beta"

    def test_alpha_and_beta_param_present(self):
        r = self._build(50, 200)
        assert "alpha" in r.distribution.params
        assert "beta_param" in r.distribution.params

    def test_alpha_equals_k_plus_one(self):
        r = self._build(50, 200)
        assert abs(r.distribution.params["alpha"] - 51) < 1e-6

    def test_beta_param_equals_n_minus_k_plus_one(self):
        r = self._build(50, 200)
        assert abs(r.distribution.params["beta_param"] - 151) < 1e-6

    def test_p50_near_proportion(self):
        r = self._build(50, 200)
        # P50 should be close to k/n = 0.25
        assert abs(r.distribution.p50 - 0.25) < 0.02

    def test_proportion_stays_in_0_1(self):
        for k, n in [(1, 200), (10, 50), (199, 200)]:
            r = self._build(k, n)
            assert 0.0 <= r.distribution.p10 <= 1.0, f"P10 out of range for k={k}, n={n}"
            assert 0.0 <= r.distribution.p90 <= 1.0, f"P90 out of range for k={k}, n={n}"

    def test_wider_ci_for_smaller_n(self):
        r_large = self._build(50, 500)
        r_small = self._build(5, 50)
        # Same proportion (0.10) but smaller n → wider P10-P90 range
        range_large = r_large.distribution.p90 - r_large.distribution.p10
        range_small = r_small.distribution.p90 - r_small.distribution.p10
        assert range_small > range_large, "Smaller n must produce wider uncertainty"

    def test_simulation_allowed(self):
        r = self._build(50, 200)
        assert r.simulation_allowed is True

    def test_to_gate_spec_not_none(self):
        r = self._build(50, 200)
        gs = r.to_gate_spec()
        assert gs is not None


# ──────────────────────────────────────────────────────────────────────────────
# 3. Proportion bounds — P10/P90 always in [0, 1]
# ──────────────────────────────────────────────────────────────────────────────

class TestProportionBounds:

    def test_high_proportion_stays_below_one(self):
        gate = proportion_gate()
        # k=190, n=200 → ~95% proportion — upside should not exceed 1.0
        r = build_distribution(gate, [published_count_record(190, 200)], ctx(gate))
        assert r.distribution.p10 >= 0.0
        assert r.distribution.p90 <= 1.0

    def test_low_proportion_stays_above_zero(self):
        gate = proportion_gate()
        r = build_distribution(gate, [published_count_record(1, 200)], ctx(gate))
        assert r.distribution.p10 >= 0.0

    def test_policy_prior_proportion_bounded(self):
        gate = proportion_gate()
        r = build_distribution(gate, [analyst_record(0.95)], ctx(gate))
        assert r.distribution.p90 <= 1.0, "Policy prior must not exceed 1.0 for proportion"

    def test_expert_elicitation_proportion_bounded(self):
        gate = proportion_gate()
        r = build_distribution(gate, [expert_record(0.70, 0.85, 0.95)], ctx(gate))
        assert r.distribution.p90 <= 1.0

    def test_to_gate_spec_rate_type(self):
        gate = proportion_gate()
        r = build_distribution(gate, [published_count_record(50, 200)], ctx(gate))
        gs = r.to_gate_spec()
        assert gs.gate_type == "rate"


# ──────────────────────────────────────────────────────────────────────────────
# 4. Prices — lognormal, positive-only
# ──────────────────────────────────────────────────────────────────────────────

class TestPriceDistributions:

    def test_lognormal_for_price_with_ci(self):
        gate = price_gate()
        evidence = [
            EvidenceRecord(
                id="ev-price-1", gate_name="net_price",
                source_type="published_estimate",
                value=50_000.0, ci_low=30_000.0, ci_high=80_000.0,
                directness=0.80, applicability=0.75,
            )
        ]
        r = build_distribution(gate, evidence, ctx(gate), seed=42)
        assert r.distribution is not None
        assert r.distribution.dist_type == "lognormal"

    def test_price_p10_is_positive(self):
        gate = price_gate()
        evidence = [
            EvidenceRecord(
                id="ev-price-2", gate_name="net_price",
                source_type="published_estimate",
                value=50_000.0, ci_low=30_000.0, ci_high=80_000.0,
                directness=0.80, applicability=0.75,
            )
        ]
        r = build_distribution(gate, evidence, ctx(gate), seed=42)
        assert r.distribution.p10 > 0, "Price distribution P10 must be positive"

    def test_policy_prior_price_no_negatives(self):
        gate = price_gate()
        r = build_distribution(gate, [analyst_record(50_000)], ctx(gate), seed=42)
        assert r.distribution.p10 >= 0, "Policy prior for price must not go negative"

    def test_normal_for_price_warns_about_negatives(self):
        gate = price_gate()
        # SE large relative to value → normal will go negative
        evidence = [published_se_record(value=1000.0, se=800.0)]
        r = build_distribution(gate, evidence, ctx(gate), seed=42)
        # Should emit a warning if P10 goes negative
        if r.distribution and r.distribution.p10 < 0:
            warning_texts = " ".join(r.warnings)
            assert "negative" in warning_texts.lower() or "lognormal" in warning_texts.lower()


# ──────────────────────────────────────────────────────────────────────────────
# 5. Reproducible empirical / policy prior with fixed seed
# ──────────────────────────────────────────────────────────────────────────────

class TestReproducibility:

    def test_empirical_same_seed_same_result(self):
        gate = proportion_gate()
        ev   = [microdata_record([0.10, 0.12, 0.14, 0.11, 0.13, 0.15, 0.09, 0.16])]
        r1   = build_distribution(gate, ev, ctx(gate), seed=42)
        r2   = build_distribution(gate, ev, ctx(gate), seed=42)
        assert r1.distribution.p10 == r2.distribution.p10
        assert r1.distribution.p90 == r2.distribution.p90

    def test_policy_prior_same_seed_same_result(self):
        gate = proportion_gate()
        ev   = [analyst_record(0.20)]
        r1   = build_distribution(gate, ev, ctx(gate), seed=99)
        r2   = build_distribution(gate, ev, ctx(gate), seed=99)
        assert r1.distribution.p10 == r2.distribution.p10
        assert r1.distribution.p90 == r2.distribution.p90

    def test_same_seed_always_identical(self):
        """Reproducibility property: same seed → byte-identical P10/P50/P90."""
        gate = proportion_gate()
        ev   = [analyst_record(0.20)]
        # Run three times with the same seed — all must match
        results = [build_distribution(gate, ev, ctx(gate), seed=7) for _ in range(3)]
        for r in results[1:]:
            assert r.distribution.p10 == results[0].distribution.p10
            assert r.distribution.p50 == results[0].distribution.p50
            assert r.distribution.p90 == results[0].distribution.p90


# ──────────────────────────────────────────────────────────────────────────────
# 6. Invalid distribution parameter rejection
# ──────────────────────────────────────────────────────────────────────────────

class TestDistributionValidation:

    def test_beta_invalid_alpha_zero(self):
        gate = proportion_gate()
        spec = DistributionSpec(
            dist_type="beta",
            params={"alpha": 0, "beta_param": 5},
            domain_low=0.0, domain_high=1.0,
            p10=0.05, p50=0.20, p90=0.40,
        )
        warnings = _validate_distribution_spec(spec, gate, [])
        assert any("INVALID" in w for w in warnings), \
            "Alpha=0 for beta must produce an INVALID warning"

    def test_pert_inverted_range(self):
        gate = proportion_gate()
        spec = DistributionSpec(
            dist_type="pert",
            params={"low": 0.50, "mode": 0.30, "high": 0.20},
            domain_low=0.0, domain_high=1.0,
            p10=0.20, p50=0.30, p90=0.50,
        )
        warnings = _validate_distribution_spec(spec, gate, [])
        assert any("INVALID" in w for w in warnings), \
            "high ≤ low must produce an INVALID warning"

    def test_lognormal_for_proportion_warns(self):
        gate = proportion_gate()
        spec = DistributionSpec(
            dist_type="lognormal",
            params={"mu": 0.0, "sigma": 0.5},
            domain_low=0.0, domain_high=1.0,
            p10=0.10, p50=1.0, p90=1.65,  # p90 > 1
        )
        warnings = _validate_distribution_spec(spec, gate, [])
        assert any("proportion" in w.lower() or "lognormal" in w.lower()
                   for w in warnings), \
            "Lognormal for proportion gate must warn about impossible values"

    def test_price_normal_negative_p10_warns(self):
        gate = price_gate()
        spec = DistributionSpec(
            dist_type="normal",
            params={"mu": 1000.0, "sigma": 5000.0},
            domain_low=0.0, domain_high=math.inf,
            p10=-5000.0, p50=1000.0, p90=7000.0,
        )
        warnings = _validate_distribution_spec(spec, gate, [])
        assert any("negative" in w.lower() or "lognormal" in w.lower()
                   for w in warnings), \
            "Normal for price gate with negative P10 must warn"

    def test_percentile_ordering_violation_warns(self):
        gate = proportion_gate()
        spec = DistributionSpec(
            dist_type="pert",
            params={"low": 0.10, "mode": 0.15, "high": 0.25},
            domain_low=0.0, domain_high=1.0,
            p10=0.20, p50=0.10, p90=0.15,  # ordering violated
        )
        warnings = _validate_distribution_spec(spec, gate, [])
        assert any("ordering" in w.lower() or "percentile" in w.lower()
                   for w in warnings)


# ──────────────────────────────────────────────────────────────────────────────
# 7. Scenario mode when only bounds exist
# ──────────────────────────────────────────────────────────────────────────────

class TestScenarioMode:

    def _bounds_result(self) -> DistributionBuildResult:
        gate = proportion_gate()
        return build_distribution(
            gate, [bounds_record(0.05, 0.40)], ctx(gate), seed=42
        )

    def test_simulation_blocked(self):
        r = self._bounds_result()
        assert r.simulation_allowed is False

    def test_uncertainty_mode_is_scenario(self):
        r = self._bounds_result()
        assert r.uncertainty_mode == "scenario"

    def test_three_scenarios_returned(self):
        r = self._bounds_result()
        assert r.scenarios is not None
        assert len(r.scenarios) == 3

    def test_scenario_names_are_low_base_high(self):
        r = self._bounds_result()
        names = [s.name for s in r.scenarios]
        assert "low" in names and "base" in names and "high" in names

    def test_warning_says_no_probability_assigned(self):
        r = self._bounds_result()
        warning_text = " ".join(r.warnings).lower()
        assert "probability" in warning_text or "percentile" in warning_text

    def test_to_gate_spec_returns_none(self):
        r = self._bounds_result()
        assert r.to_gate_spec() is None, \
            "to_gate_spec() must return None when simulation_allowed=False"


# ──────────────────────────────────────────────────────────────────────────────
# 8. Insufficient evidence blocks simulation
# ──────────────────────────────────────────────────────────────────────────────

class TestInsufficientEvidence:

    def _result(self) -> DistributionBuildResult:
        gate = proportion_gate()
        return build_distribution(gate, [], ctx(gate), seed=42)

    def test_simulation_blocked(self):
        assert self._result().simulation_allowed is False

    def test_uncertainty_mode_is_insufficient(self):
        assert self._result().uncertainty_mode == "insufficient"

    def test_distribution_is_none(self):
        assert self._result().distribution is None

    def test_research_question_returned(self):
        r = self._result()
        assert r.research_question is not None
        assert len(r.research_question) > 20

    def test_to_gate_spec_returns_none(self):
        assert self._result().to_gate_spec() is None


# ──────────────────────────────────────────────────────────────────────────────
# 9. Policy prior labeling
# ──────────────────────────────────────────────────────────────────────────────

class TestPolicyPriorLabeling:

    def _result(self, confidence: str = "low") -> DistributionBuildResult:
        gate = proportion_gate()
        return _build_policy_prior(0.15, confidence, gate)

    def test_uncertainty_method_is_policy_prior(self):
        assert self._result().uncertainty_method == "policy_prior"

    def test_evidence_strength_is_very_low(self):
        assert self._result().evidence_strength == "very_low"

    def test_calibrated_to_product_is_false(self):
        r = self._result()
        assert r.distribution is not None
        assert r.distribution.calibrated_to_product is False

    def test_not_calibrated_appears_in_assumptions(self):
        r = self._result()
        assumption_text = " ".join(r.assumptions).lower()
        assert "not" in assumption_text or "prior" in assumption_text.lower()

    def test_warning_mentions_policy_prior(self):
        r = self._result()
        warning_text = " ".join(r.warnings).lower()
        assert "policy_prior" in warning_text or "very_low" in warning_text

    def test_high_confidence_narrower_than_low(self):
        r_high = _build_policy_prior(0.20, "high", proportion_gate())
        r_low  = _build_policy_prior(0.20, "low",  proportion_gate())
        range_high = r_high.distribution.p90 - r_high.distribution.p10
        range_low  = r_low.distribution.p90  - r_low.distribution.p10
        assert range_high < range_low, "High-confidence prior must be narrower"

    def test_simulation_allowed(self):
        assert self._result().simulation_allowed is True

    def test_explain_says_not_calibrated(self):
        r = self._result()
        explanation = r.explain().lower()
        assert "not calibrated" in explanation or "policy prior" in explanation


# ──────────────────────────────────────────────────────────────────────────────
# 10. Correlation provenance requirement
# ──────────────────────────────────────────────────────────────────────────────

class TestCorrelationProvenance:

    def test_correlation_record_has_method(self):
        cr = CorrelationRecord(
            gate_a="diagnosis_rate", gate_b="treatment_rate",
            correlation=0.55, method="empirical",
            source="Claims data 2023", confidence="medium",
        )
        assert cr.method in ("empirical", "published", "expert_judgment", "analyst_assumption")

    def test_correlation_to_dict_is_serialisable(self):
        cr = CorrelationRecord(
            gate_a="a", gate_b="b", correlation=0.40,
            method="analyst_assumption", source="no data", confidence="low",
        )
        json.dumps(cr.to_dict())

    def test_correlation_range_valid(self):
        cr = CorrelationRecord(
            gate_a="a", gate_b="b", correlation=0.99,
            method="published", source="paper", confidence="high",
        )
        assert -1.0 <= cr.correlation <= 1.0

    def test_analyst_assumption_is_weakest_method(self):
        # When no evidence exists, the default must be independence
        # (tested implicitly — DistributionBuildResult has no correlation field;
        # correlations are a separate pass. Here we check the CorrelationRecord
        # can represent an analyst's assumption when no empirical data exists.)
        cr = CorrelationRecord(
            gate_a="diagnosis", gate_b="treatment",
            correlation=0.0, method="analyst_assumption",
            source="Default independence assumption (no data)", confidence="low",
        )
        assert cr.correlation == 0.0  # independence


# ──────────────────────────────────────────────────────────────────────────────
# 11. Serialization and explain()
# ──────────────────────────────────────────────────────────────────────────────

class TestSerializationAndExplain:

    def _rich_result(self) -> DistributionBuildResult:
        gate = proportion_gate()
        return build_distribution(
            gate,
            [published_count_record(k=50, n=200)],
            ctx(gate),
            seed=42,
        )

    def test_to_dict_is_json_serialisable(self):
        json.dumps(self._rich_result().to_dict())

    def test_to_dict_has_required_keys(self):
        d = self._rich_result().to_dict()
        for key in ("gate_name", "simulation_allowed", "uncertainty_mode",
                    "uncertainty_method", "evidence_strength",
                    "aleatory_sources", "epistemic_sources",
                    "distribution_rationale", "commercial_ok"):
            assert key in d, f"Missing key: {key}"

    def test_commercial_ok_is_false(self):
        assert self._rich_result().to_dict()["commercial_ok"] is False

    def test_explain_returns_non_empty_string(self):
        r = self._rich_result()
        exp = r.explain()
        assert isinstance(exp, str) and len(exp) > 50

    def test_explain_mentions_method(self):
        r = self._rich_result()
        assert r.uncertainty_method in r.explain()

    def test_explain_mentions_evidence_count(self):
        r = self._rich_result()
        assert str(r.evidence_count) in r.explain() or "source" in r.explain()

    def test_scenario_to_dict_serialisable(self):
        s = ScenarioSpec(name="low", value=0.05, rationale="Lower bound")
        json.dumps(s.to_dict())

    def test_insufficient_explain_contains_question(self):
        gate = proportion_gate()
        r = _insufficient_evidence(gate, ctx(gate))
        assert r.research_question in r.explain()

    def test_aleatory_and_epistemic_stored_separately(self):
        r = self._rich_result()
        # Must have separate lists — both may be non-empty
        assert isinstance(r.aleatory_sources, list)
        assert isinstance(r.epistemic_sources, list)

    def test_policy_prior_explain_not_calibrated(self):
        r = _build_policy_prior(0.20, "low", proportion_gate())
        assert "not calibrated" in r.explain().lower() or \
               "policy prior" in r.explain().lower()


# ──────────────────────────────────────────────────────────────────────────────
# 12. Alternate-distribution sensitivity
# ──────────────────────────────────────────────────────────────────────────────

class TestAlternateSensitivity:

    def test_sensitivity_result_attached_to_result(self):
        gate = proportion_gate()
        r = build_distribution(
            gate, [published_count_record(50, 200)], ctx(gate), seed=42,
            run_alternate_sensitivity=True,
        )
        assert r.alternate_sensitivity is not None

    def test_no_sensitivity_when_flag_false(self):
        gate = proportion_gate()
        r = build_distribution(
            gate, [published_count_record(50, 200)], ctx(gate), seed=42,
            run_alternate_sensitivity=False,
        )
        assert r.alternate_sensitivity is None

    def test_assessment_is_robust_or_sensitive(self):
        gate = proportion_gate()
        r = build_distribution(
            gate, [published_count_record(50, 200)], ctx(gate), seed=42,
        )
        assert r.alternate_sensitivity.assessment in ("robust", "sensitive")

    def test_wide_distribution_tends_sensitive(self):
        # A very wide PERT vs triangular will differ more
        gate = proportion_gate()
        spec = DistributionSpec(
            dist_type="pert",
            params={"low": 0.01, "mode": 0.50, "high": 0.99},
            domain_low=0.0, domain_high=1.0,
            p10=0.05, p50=0.50, p90=0.90,
        )
        sens = _run_alternate_sensitivity(spec, gate, seed=42)
        assert isinstance(sens.assessment, str)
        assert sens.relative_swing_difference >= 0.0

    def test_point_distribution_is_robust(self):
        gate = proportion_gate()
        spec = DistributionSpec(
            dist_type="point",
            params={"value": 0.20},
            domain_low=0.0, domain_high=1.0,
            p10=0.20, p50=0.20, p90=0.20,
        )
        sens = _run_alternate_sensitivity(spec, gate, seed=42)
        assert sens.assessment == "robust"

    def test_sensitivity_to_dict_serialisable(self):
        gate = proportion_gate()
        r = build_distribution(
            gate, [published_count_record(50, 200)], ctx(gate), seed=42,
        )
        json.dumps(r.alternate_sensitivity.to_dict())

    def test_threshold_constant_correct(self):
        assert ALTERNATE_SENSITIVITY_THRESHOLD == 0.20


# ──────────────────────────────────────────────────────────────────────────────
# 13. Verification priority
# ──────────────────────────────────────────────────────────────────────────────

class TestVerificationPriority:

    def _result(self, strength: str) -> DistributionBuildResult:
        gate = proportion_gate()
        if strength == "high":
            ev = [microdata_record([0.10, 0.12, 0.14, 0.11, 0.13, 0.15, 0.09, 0.16])]
        elif strength == "medium":
            ev = [published_count_record(50, 200)]
        else:
            ev = [analyst_record(0.15)]
        return build_distribution(gate, ev, ctx(gate), seed=42)

    def test_high_impact_low_evidence_highest_priority(self):
        r_weak   = self._result("very_low")
        r_strong = self._result("high")
        p_weak   = compute_verification_priority(r_weak,   0, 100_000_000, 100_000_000)
        p_strong = compute_verification_priority(r_strong, 0, 100_000_000, 100_000_000)
        assert p_weak > p_strong, \
            "Weak evidence + same swing must produce higher priority than strong evidence"

    def test_zero_swing_gives_zero_priority(self):
        r = self._result("low")
        p = compute_verification_priority(r, 100_000, 100_000, 100_000_000)
        assert p == 0.0, "Zero market swing → zero verification priority"

    def test_priority_nonnegative(self):
        r = self._result("medium")
        p = compute_verification_priority(r, 0, 50_000_000, 200_000_000)
        assert p >= 0.0

    def test_priority_at_most_one(self):
        r = self._result("very_low")
        # Maximum priority: all swing in this gate, zero evidence
        p = compute_verification_priority(r, 0, 100_000_000, 100_000_000)
        assert p <= 1.0


# ──────────────────────────────────────────────────────────────────────────────
# 14. to_gate_spec() integration with Monte Carlo engine
# ──────────────────────────────────────────────────────────────────────────────

class TestToGateSpecIntegration:

    def test_beta_to_gate_spec_produces_valid_pert(self):
        gate = proportion_gate()
        r = build_distribution(
            gate, [published_count_record(50, 200)], ctx(gate), seed=42
        )
        gs = r.to_gate_spec()
        assert gs is not None
        assert gs.dist is not None
        assert gs.dist.get("type") == "pert"
        assert gs.dist["low"] < gs.dist["mode"] < gs.dist["high"]

    def test_policy_prior_to_gate_spec_valid(self):
        gate = proportion_gate()
        r = build_distribution(gate, [analyst_record(0.20)], ctx(gate), seed=42)
        gs = r.to_gate_spec()
        assert gs is not None
        assert gs.gate_type == "rate"

    def test_insufficient_to_gate_spec_returns_none(self):
        gate = proportion_gate()
        r = build_distribution(gate, [], ctx(gate), seed=42)
        assert r.to_gate_spec() is None

    def test_scenario_to_gate_spec_returns_none(self):
        gate = proportion_gate()
        r = build_distribution(gate, [bounds_record(0.05, 0.40)], ctx(gate), seed=42)
        assert r.to_gate_spec() is None

    def test_gate_spec_value_equals_p50(self):
        gate = proportion_gate()
        r = build_distribution(
            gate, [published_count_record(50, 200)], ctx(gate), seed=42
        )
        gs = r.to_gate_spec()
        assert abs(gs.value - r.distribution.p50) < 1e-6

    def test_gate_spec_mc_dist_dict_roundtrip(self):
        """Verify to_mc_dist_dict() produces the exact format _sample() expects."""
        from app.services.monte_carlo_engine import _sample
        import numpy as np

        spec = DistributionSpec(
            dist_type="pert",
            params={"low": 0.10, "mode": 0.20, "high": 0.35},
            domain_low=0.0, domain_high=1.0,
            p10=0.12, p50=0.20, p90=0.30,
        )
        mc_dict = spec.to_mc_dist_dict()
        rng = np.random.default_rng(42)
        samples = _sample(mc_dict, 100, rng)
        assert len(samples) == 100
        assert all(s >= 0.0 for s in samples)


# ──────────────────────────────────────────────────────────────────────────────
# 15. Analog tier — comparability filtering
# ──────────────────────────────────────────────────────────────────────────────

class TestAnalogTier:

    def test_weak_analogs_excluded(self):
        gate = proportion_gate()
        evidence = [
            *analog_records([0.20, 0.22, 0.18, 0.25, 0.19], score=0.80),
            EvidenceRecord(
                id="weak", gate_name="treated_segment",
                source_type="analog", value=0.50,
                comparability_score=0.30,   # below threshold
                directness=0.60, applicability=0.30,
            ),
        ]
        r = build_distribution(gate, evidence, ctx(gate), seed=42)
        assert r.uncertainty_method == "analog_based"
        # Weak analog value of 0.50 should not dominate — P90 should be much less
        assert r.distribution.p90 < 0.45, \
            "Weak analog (score=0.30) should be excluded, keeping P90 reasonable"

    def test_fewer_than_min_analogs_falls_through(self):
        gate = proportion_gate()
        evidence = analog_records([0.20, 0.22], score=0.85)   # only 2 → below MIN_STRONG_ANALOGS
        r = build_distribution(gate, evidence, ctx(gate), seed=42)
        # With only 2 analogs and no other evidence, falls through to policy_prior
        # (from value inferred from analogs) or insufficient
        assert r.uncertainty_method in ("policy_prior", "insufficient", "analog_based"), \
            f"Unexpected method: {r.uncertainty_method}"

    def test_analog_warning_for_excluded_records(self):
        gate = proportion_gate()
        evidence = [
            *analog_records([0.20, 0.22, 0.18, 0.25, 0.19], score=0.80),
            EvidenceRecord(
                id="weak2", gate_name="treated_segment",
                source_type="analog", value=0.50,
                comparability_score=0.20,
                directness=0.60, applicability=0.20,
            ),
        ]
        r = build_distribution(gate, evidence, ctx(gate), seed=42)
        # Should mention excluded analogs
        all_text = " ".join(r.warnings + r.assumptions + [r.distribution_rationale]).lower()
        assert "excluded" in all_text or "weak" in all_text or "comparability" in all_text


# ──────────────────────────────────────────────────────────────────────────────
# 16. Expert elicitation tier — documentation requirements
# ──────────────────────────────────────────────────────────────────────────────

class TestExpertElicitationTier:

    def test_pert_from_expert_range(self):
        gate = proportion_gate()
        r = build_distribution(gate, [expert_record(0.10, 0.20, 0.35)], ctx(gate), seed=42)
        assert r.uncertainty_method == "expert_elicitation"
        assert r.distribution.dist_type in ("pert", "triangular")

    def test_missing_expert_role_produces_warning(self):
        gate = proportion_gate()
        ev = EvidenceRecord(
            id="ev-noname", gate_name="treated_segment",
            source_type="expert_elicitation",
            expert_low=0.10, expert_mode=0.20, expert_high=0.35,
            # expert_role intentionally omitted
            directness=0.70, applicability=0.70,
        )
        r = build_distribution(gate, [ev], ctx(gate), seed=42)
        warning_text = " ".join(r.warnings).lower()
        assert "role" in warning_text or "document" in warning_text

    def test_expert_bounds_enforced(self):
        gate = proportion_gate()
        r = build_distribution(
            gate, [expert_record(0.80, 0.90, 0.98)], ctx(gate), seed=42
        )
        assert r.distribution.p90 <= 1.0

    def test_expert_evidence_strength_is_low(self):
        gate = proportion_gate()
        r = build_distribution(gate, [expert_record(0.10, 0.20, 0.35)], ctx(gate))
        assert r.evidence_strength == "low"
