"""
Distribution Builder  (Build Spec Addendum — Evidence-Grounded Distribution Layer)
===================================================================================
Sits between evidence retrieval and the Monte Carlo engine.

Determines whether available evidence supports a probability distribution for
each market-sizing gate, constructs that distribution when defensible, and
refuses or downgrades probabilistic simulation when evidence is insufficient.

Monte Carlo NEVER invents distribution parameters — it only propagates
distributions supplied here.

Evidence hierarchy (highest to lowest):
  Tier 1 — Representative microdata / claims / registry observations
  Tier 2 — Published estimate with reported uncertainty (CI, SE, counts)
  Tier 3 — Multiple comparable analogs (≥ 3, comparability ≥ 0.50)
  Tier 4 — Structured expert elicitation (low / mode / high documented)
  Tier 5 — Defensible logical bounds → scenario mode, simulation_allowed=False
  Tier 6 — Point estimate only → labeled policy prior ("very_low" strength)
  Tier 7 — Nothing → insufficient, simulation_allowed=False

Aleatory variability (real market variation) and epistemic uncertainty
(lack of knowledge) are stored and surfaced separately.

Reference methodology:
  NIST: Monte Carlo requires explicitly defined joint distribution for inputs.
  EPA:  Distribution selection uses representativeness; sensitivity tests shape dependence.
  EFSA: Document distribution origin; separate variability from uncertainty.
  NASA: Distinguish reducible (epistemic) from irreducible (aleatory) uncertainty.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Tuple

import numpy as np
from scipy import stats as scipy_stats

logger = logging.getLogger(__name__)

# ─── Constants ────────────────────────────────────────────────────────────────

MIN_STRONG_ANALOGS        = 3      # minimum analogs to use the analog tier
MIN_ANALOG_COMPARABILITY  = 0.50   # below this, analogs are weak and excluded
MIN_MICRODATA_N           = 5      # minimum observations for empirical tier
ALTERNATE_SENSITIVITY_THRESHOLD = 0.20  # P10-P90 range difference flagged as sensitive

# Policy prior widening — matches monte_carlo_engine._auto_widen()
_POLICY_PRIOR_HALF = {"high": 0.10, "medium": 0.25, "low": 0.45}
_POLICY_PRIOR_UPSIDE = 1.30        # asymmetric upside multiplier

_EVIDENCE_STRENGTH_SCORE: Dict[str, float] = {
    "high": 1.0, "medium": 0.75, "low": 0.40, "very_low": 0.15, "none": 0.0,
}


# ─── Input types ──────────────────────────────────────────────────────────────

@dataclass
class FunnelGate:
    """Minimal descriptor for the market-sizing gate being modeled."""
    name: str
    label: str
    gate_type: Literal["proportion", "price", "count"]
    units: str              # "fraction", "usd_per_unit", "patients", "sites", "tests"
    domain_low: float = 0.0
    domain_high: float = 1.0  # set to math.inf for price/count gates


@dataclass
class EvidenceRecord:
    """
    One piece of evidence supporting a distribution for a funnel gate.
    source_type determines which evidence tier this record qualifies for.
    """
    id: str
    gate_name: str
    source_type: Literal[
        "microdata",          # Tier 1: list of observed values
        "published_estimate", # Tier 2: point estimate with CI / SE / counts
        "analog",             # Tier 3: comparable product launch value
        "expert_elicitation", # Tier 4: low / mode / high from a subject expert
        "bounds",             # Tier 5: logical constraint (no probability inside)
        "analyst_estimate",   # Tier 6: single analyst point estimate
    ]

    # Tier 1 — microdata
    observations: Optional[List[float]] = field(default=None)

    # Tier 2 — published estimate
    value: Optional[float] = field(default=None)
    ci_low: Optional[float] = field(default=None)
    ci_high: Optional[float] = field(default=None)
    standard_error: Optional[float] = field(default=None)
    numerator: Optional[int] = field(default=None)
    denominator: Optional[int] = field(default=None)
    sample_size: Optional[int] = field(default=None)
    ci_level: float = field(default=0.95)   # e.g. 0.95 for 95% CI

    # Tier 3 — analog
    comparability_score: float = field(default=1.0)   # 0.0–1.0
    analog_attributes: Optional[Dict] = field(default=None)

    # Tier 4 — expert elicitation
    expert_low: Optional[float] = field(default=None)
    expert_mode: Optional[float] = field(default=None)
    expert_high: Optional[float] = field(default=None)
    expert_role: Optional[str] = field(default=None)
    expert_question: Optional[str] = field(default=None)
    elicitation_date: Optional[str] = field(default=None)

    # Tier 5 — logical bounds
    bound_low: Optional[float] = field(default=None)
    bound_high: Optional[float] = field(default=None)
    bound_rationale: Optional[str] = field(default=None)

    # Quality metadata (all tiers)
    directness: float = field(default=0.50)      # 0.0–1.0; how directly applicable
    applicability: float = field(default=0.50)   # 0.0–1.0; market context fit
    citation: Optional[str] = field(default=None)
    notes: Optional[str] = field(default=None)

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class MarketContext:
    """Product and market context used when evaluating evidence applicability."""
    product_type: str
    disease_name: str
    gate_type: str    # "proportion", "price", "count"
    gate_units: str


# ─── Output types ─────────────────────────────────────────────────────────────

@dataclass
class DistributionSpec:
    """
    A fully-parameterized probability distribution ready for Monte Carlo sampling.

    dist_type → params keys:
      "beta"       → alpha, beta_param
      "pert"       → low, mode, high
      "triangular" → low, mode, high
      "lognormal"  → mu, sigma
      "normal"     → mu, sigma
      "empirical"  → samples (list), p5, p95
      "point"      → value
    """
    dist_type: Literal[
        "beta", "pert", "triangular", "lognormal", "normal",
        "empirical", "point"
    ]
    params: Dict
    domain_low: float
    domain_high: float
    p10: float
    p50: float
    p90: float
    calibrated_to_product: bool = field(default=True)

    def to_dict(self) -> dict:
        p = dict(self.params)
        # Omit large samples array from serialisation to keep JSON compact
        p.pop("samples", None)
        return {
            "dist_type": self.dist_type,
            "params": p,
            "domain_low": self.domain_low,
            "domain_high": self.domain_high,
            "p10": round(self.p10, 6),
            "p50": round(self.p50, 6),
            "p90": round(self.p90, 6),
            "calibrated_to_product": self.calibrated_to_product,
        }

    def to_mc_dist_dict(self) -> dict:
        """
        Convert to the dict format consumed by monte_carlo_engine._sample()
        (key "type", not "distribution").

        Beta → PERT via P5/mode/P95 (preserves 90% of the probability mass).
        Empirical → PERT via P5/P50/P95 of the stored samples.
        """
        if self.dist_type == "beta":
            alpha   = self.params["alpha"]
            beta_p  = self.params["beta_param"]
            rv      = scipy_stats.beta(alpha, beta_p)
            mode    = ((alpha - 1) / (alpha + beta_p - 2)
                       if alpha > 1 and beta_p > 1
                       else float(rv.mean()))
            low     = max(float(rv.ppf(0.05)), self.domain_low)
            high    = min(float(rv.ppf(0.95)), self.domain_high)
            return {"type": "pert", "low": low, "mode": mode, "high": high}

        if self.dist_type == "empirical":
            samples = self.params.get("samples", [])
            if samples:
                arr   = np.asarray(samples, dtype=float)
                low   = max(float(np.percentile(arr, 5)), self.domain_low)
                mode  = float(np.percentile(arr, 50))
                high  = min(float(np.percentile(arr, 95)), self.domain_high)
            else:
                low, mode, high = self.p10, self.p50, self.p90
            return {"type": "pert", "low": low, "mode": mode, "high": high}

        if self.dist_type == "point":
            v = self.params["value"]
            return {"type": "point", "value": v}

        if self.dist_type == "lognormal":
            return {"type": "lognormal",
                    "mu": self.params["mu"], "sigma": self.params["sigma"]}

        if self.dist_type == "normal":
            return {"type": "normal",
                    "mean": self.params["mu"], "sd": self.params["sigma"]}

        # pert, triangular — use params directly
        return {"type": self.dist_type, **self.params}


@dataclass
class ScenarioSpec:
    name: str        # "low", "base", "high"
    value: float
    rationale: str

    def to_dict(self) -> dict:
        return {"name": self.name, "value": self.value, "rationale": self.rationale}


@dataclass
class AlternateSensitivity:
    """
    Compares primary distribution P10–P90 range against an alternate distribution
    with the same low/mode/high. When relative range difference > threshold,
    market sizing conclusion depends on the distributional choice.
    """
    primary_distribution: str
    alternate_distribution: str
    p10_primary: float
    p90_primary: float
    p10_alternate: float
    p90_alternate: float
    relative_swing_difference: float   # |range_alt – range_primary| / range_primary
    assessment: Literal["robust", "sensitive"]

    def to_dict(self) -> dict:
        return {
            "primary_distribution":    self.primary_distribution,
            "alternate_distribution":  self.alternate_distribution,
            "p10_primary":             round(self.p10_primary, 6),
            "p90_primary":             round(self.p90_primary, 6),
            "p10_alternate":           round(self.p10_alternate, 6),
            "p90_alternate":           round(self.p90_alternate, 6),
            "relative_swing_difference": round(self.relative_swing_difference, 4),
            "assessment":              self.assessment,
        }


@dataclass
class CorrelationRecord:
    """
    Proposed correlation between two funnel gates.
    Every proposed correlation must document its provenance.
    Default = independence when no record exists.
    """
    gate_a: str
    gate_b: str
    correlation: float   # Pearson r ∈ [−1, 1]
    method: Literal["empirical", "published", "expert_judgment", "analyst_assumption"]
    source: str
    confidence: Literal["high", "medium", "low"]

    def to_dict(self) -> dict:
        return {
            "gate_a": self.gate_a, "gate_b": self.gate_b,
            "correlation": self.correlation, "method": self.method,
            "source": self.source, "confidence": self.confidence,
        }


@dataclass
class DistributionBuildResult:
    """
    Full output of build_distribution() for one funnel gate.

    When simulation_allowed=False, the Monte Carlo engine must not run for this
    gate — the caller should surface scenarios or the research_question instead.
    """
    gate_name: str
    simulation_allowed: bool

    uncertainty_mode: Literal["probabilistic", "scenario", "interval", "insufficient"]

    distribution: Optional[DistributionSpec]
    scenarios: Optional[List[ScenarioSpec]]

    uncertainty_method: Literal[
        "empirical", "bootstrap", "reported_statistics", "analog_based",
        "expert_elicitation", "logical_bounds", "policy_prior", "insufficient"
    ]

    evidence_strength: Literal["high", "medium", "low", "very_low", "none"]

    aleatory_sources: List[str]         # real market variability
    epistemic_sources: List[str]        # gaps in knowledge
    unquantified_uncertainties: List[str]

    evidence_ids: List[str]
    evidence_count: int
    directness_score: float             # 0.0–1.0
    applicability_score: float          # 0.0–1.0

    distribution_rationale: str
    assumptions: List[str]
    warnings: List[str]
    research_question: Optional[str]

    alternate_sensitivity: Optional[AlternateSensitivity] = field(default=None)
    commercial_ok: bool = field(default=False)

    # ── explain() ─────────────────────────────────────────────────────────────

    def explain(self) -> str:
        """Human-readable audit trail covering method, evidence, and what is NOT modeled."""
        lines = [
            f"Gate: {self.gate_name}",
            f"Uncertainty mode: {self.uncertainty_mode}",
            f"Method: {self.uncertainty_method}",
            f"Evidence strength: {self.evidence_strength}  "
            f"({self.evidence_count} source(s); "
            f"directness={self.directness_score:.2f}, "
            f"applicability={self.applicability_score:.2f})",
            f"Simulation allowed: {'yes' if self.simulation_allowed else 'no'}",
            "",
            self.distribution_rationale,
        ]

        if self.distribution and self.simulation_allowed:
            d = self.distribution
            lines.append(
                f"\nDistribution: {d.dist_type}  "
                f"P10={d.p10:.4g}  P50={d.p50:.4g}  P90={d.p90:.4g}"
            )
            display_params = {k: v for k, v in d.params.items() if k != "samples"}
            lines.append(f"Parameters: {display_params}")
            lines.append(
                f"Calibrated to this product: "
                f"{'yes' if d.calibrated_to_product else 'NO — generic policy prior'}"
            )

        if self.scenarios:
            lines.append(
                "\nScenarios returned — no probability has been assigned "
                "across scenarios:"
            )
            for s in self.scenarios:
                lines.append(f"  {s.name:6s}  {s.value:.4g}  — {s.rationale}")

        if self.aleatory_sources:
            lines.append("\nAleatory variability (real market variation, modeled):")
            for src in self.aleatory_sources:
                lines.append(f"  • {src}")

        if self.epistemic_sources:
            lines.append("\nEpistemic uncertainty (gaps in knowledge, partially modeled):")
            for src in self.epistemic_sources:
                lines.append(f"  • {src}")

        if self.unquantified_uncertainties:
            lines.append("\nUnmodeled uncertainties (NOT in simulation):")
            for u in self.unquantified_uncertainties:
                lines.append(f"  ! {u}")

        if self.assumptions:
            lines.append("\nAssumptions:")
            for a in self.assumptions:
                lines.append(f"  - {a}")

        if self.warnings:
            lines.append("\nWarnings:")
            for w in self.warnings:
                lines.append(f"  ⚠ {w}")

        if self.research_question:
            lines.append(f"\nMissing research question: {self.research_question}")

        if self.alternate_sensitivity:
            a = self.alternate_sensitivity
            lines.append(
                f"\nAlternate-distribution sensitivity "
                f"({a.primary_distribution} vs {a.alternate_distribution}): "
                f"{a.assessment.upper()}  "
                f"(relative P10–P90 range difference = "
                f"{a.relative_swing_difference:.0%})"
            )

        return "\n".join(lines)

    # ── to_dict() ─────────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "gate_name":           self.gate_name,
            "simulation_allowed":  self.simulation_allowed,
            "uncertainty_mode":    self.uncertainty_mode,
            "distribution":        self.distribution.to_dict() if self.distribution else None,
            "scenarios":           [s.to_dict() for s in self.scenarios] if self.scenarios else None,
            "uncertainty_method":  self.uncertainty_method,
            "evidence_strength":   self.evidence_strength,
            "aleatory_sources":    self.aleatory_sources,
            "epistemic_sources":   self.epistemic_sources,
            "unquantified_uncertainties": self.unquantified_uncertainties,
            "evidence_ids":        self.evidence_ids,
            "evidence_count":      self.evidence_count,
            "directness_score":    round(self.directness_score, 3),
            "applicability_score": round(self.applicability_score, 3),
            "distribution_rationale": self.distribution_rationale,
            "assumptions":         self.assumptions,
            "warnings":            self.warnings,
            "research_question":   self.research_question,
            "alternate_sensitivity": (
                self.alternate_sensitivity.to_dict()
                if self.alternate_sensitivity else None
            ),
            "commercial_ok":       self.commercial_ok,
        }

    # ── to_gate_spec() ────────────────────────────────────────────────────────

    def to_gate_spec(self):
        """
        Convert to a GateSpec for the Monte Carlo engine.
        Returns None when simulation_allowed=False.
        """
        if not self.simulation_allowed or self.distribution is None:
            return None

        from app.services.monte_carlo_engine import GateSpec

        mc_dist = self.distribution.to_mc_dist_dict()
        gate_type = "rate" if self.distribution.domain_high <= 1.0 else "absolute"
        confidence = (self.evidence_strength
                      if self.evidence_strength in ("high", "medium", "low")
                      else "low")

        return GateSpec(
            name=self.gate_name,
            label=self.gate_name,
            gate_type=gate_type,
            value=self.distribution.p50,
            dist=mc_dist,
            confidence=confidence,
            source_type=self.uncertainty_method,
        )


# ─── Internal evidence classification ────────────────────────────────────────

@dataclass
class _ValidatedEvidence:
    has_representative_microdata: bool
    has_reported_estimate_and_uncertainty: bool
    has_multiple_strong_analogs: bool
    has_structured_expert_elicitation: bool
    has_defensible_bounds: bool
    has_point_estimate: bool
    best_estimate: Optional[float]
    best_confidence: str
    microdata_obs: List[float]
    estimate_records: List[EvidenceRecord]
    strong_analogs: List[EvidenceRecord]
    elicitation_records: List[EvidenceRecord]
    bound_records: List[EvidenceRecord]
    all_records: List[EvidenceRecord]
    directness_score: float
    applicability_score: float
    evidence_ids: List[str]


def _validate_and_rank_evidence(
    evidence: List[EvidenceRecord],
    context: MarketContext,
) -> _ValidatedEvidence:
    """Classify evidence records into tiers and compute aggregate quality scores."""

    microdata_obs: List[float] = []
    estimate_records: List[EvidenceRecord] = []
    strong_analogs: List[EvidenceRecord] = []
    elicitation_records: List[EvidenceRecord] = []
    bound_records: List[EvidenceRecord] = []

    for rec in evidence:
        if rec.gate_name and rec.gate_name != context.gate_type:
            pass  # cross-gate evidence — still usable, applicability is lower

        if rec.source_type == "microdata" and rec.observations:
            microdata_obs.extend(rec.observations)

        elif rec.source_type == "published_estimate":
            has_uncertainty = (
                (rec.ci_low is not None and rec.ci_high is not None)
                or rec.standard_error is not None
                or (rec.numerator is not None and rec.denominator is not None)
            )
            if rec.value is not None and has_uncertainty:
                estimate_records.append(rec)
            elif rec.value is not None:
                # Point estimate without uncertainty → lower tier
                estimate_records.append(rec)

        elif rec.source_type == "analog":
            if rec.comparability_score >= MIN_ANALOG_COMPARABILITY and rec.value is not None:
                strong_analogs.append(rec)

        elif rec.source_type == "expert_elicitation":
            if (rec.expert_low is not None
                    and rec.expert_mode is not None
                    and rec.expert_high is not None):
                elicitation_records.append(rec)

        elif rec.source_type == "bounds":
            if rec.bound_low is not None and rec.bound_high is not None:
                bound_records.append(rec)

        elif rec.source_type == "analyst_estimate":
            # Tier 6: point estimate without uncertainty — stored alongside published
            # estimates so it contributes to best_estimate, but never sets the
            # has_reported_estimate_and_uncertainty flag (no CI/SE/counts).
            if rec.value is not None:
                estimate_records.append(rec)

    # Quality scores: weighted average of directness × applicability per record
    all_records = evidence or []
    if all_records:
        directness_score  = float(np.mean([r.directness   for r in all_records]))
        applicability_score = float(np.mean([r.applicability for r in all_records]))
    else:
        directness_score = applicability_score = 0.0

    evidence_ids = [r.id for r in all_records]

    # Best point estimate: prefer high-directness estimates
    best_estimate = None
    best_confidence = "low"
    if microdata_obs:
        best_estimate = float(np.median(microdata_obs))
        best_confidence = "high"
    elif estimate_records:
        best_rec = max(estimate_records, key=lambda r: r.directness)
        best_estimate = best_rec.value
        best_confidence = "medium" if best_rec.directness >= 0.70 else "low"
    elif strong_analogs:
        best_estimate = float(np.median([r.value for r in strong_analogs]))
        best_confidence = "low"
    elif elicitation_records:
        best_estimate = elicitation_records[0].expert_mode
        best_confidence = "low"

    # Tier flags
    has_microdata = len(microdata_obs) >= MIN_MICRODATA_N
    has_estimate_and_uncertainty = any(
        (r.ci_low is not None and r.ci_high is not None)
        or r.standard_error is not None
        or (r.numerator is not None and r.denominator is not None)
        for r in estimate_records
    )
    has_point_estimate = best_estimate is not None

    return _ValidatedEvidence(
        has_representative_microdata=has_microdata,
        has_reported_estimate_and_uncertainty=has_estimate_and_uncertainty,
        has_multiple_strong_analogs=len(strong_analogs) >= MIN_STRONG_ANALOGS,
        has_structured_expert_elicitation=len(elicitation_records) > 0,
        has_defensible_bounds=len(bound_records) > 0,
        has_point_estimate=has_point_estimate,
        best_estimate=best_estimate,
        best_confidence=best_confidence,
        microdata_obs=microdata_obs,
        estimate_records=estimate_records,
        strong_analogs=strong_analogs,
        elicitation_records=elicitation_records,
        bound_records=bound_records,
        all_records=all_records,
        directness_score=directness_score,
        applicability_score=applicability_score,
        evidence_ids=evidence_ids,
    )


# ─── Main entry point ─────────────────────────────────────────────────────────

def build_distribution(
    gate: FunnelGate,
    evidence: List[EvidenceRecord],
    context: MarketContext,
    seed: int = 42,
    run_alternate_sensitivity: bool = True,
) -> DistributionBuildResult:
    """
    Core decision algorithm (Build Spec §5).
    Selects the highest evidence tier and constructs the corresponding distribution.
    """
    validated = _validate_and_rank_evidence(evidence, context)

    if validated.has_representative_microdata:
        result = _build_empirical(validated, gate, seed)
    elif validated.has_reported_estimate_and_uncertainty:
        result = _build_from_reported_statistics(validated, gate, context)
    elif validated.has_multiple_strong_analogs:
        result = _build_from_analogs(validated, gate, seed)
    elif validated.has_structured_expert_elicitation:
        result = _build_from_expert_elicitation(validated, gate, seed)
    elif validated.has_defensible_bounds:
        result = _build_scenario_or_interval(validated, gate)
    elif validated.has_point_estimate:
        result = _build_policy_prior(
            validated.best_estimate, validated.best_confidence, gate, seed
        )
    else:
        result = _insufficient_evidence(gate, context)

    # Alternate-distribution sensitivity (§11)
    if (run_alternate_sensitivity
            and result.simulation_allowed
            and result.distribution is not None):
        result.alternate_sensitivity = _run_alternate_sensitivity(
            result.distribution, gate, seed
        )

    return result


# ─── Tier 1: empirical / bootstrap ───────────────────────────────────────────

def _build_empirical(
    v: _ValidatedEvidence,
    gate: FunnelGate,
    seed: int,
) -> DistributionBuildResult:
    obs = np.asarray(v.microdata_obs, dtype=float)
    obs = np.clip(obs, gate.domain_low, gate.domain_high)

    p5  = float(np.percentile(obs, 5))
    p10 = float(np.percentile(obs, 10))
    p50 = float(np.percentile(obs, 50))
    p90 = float(np.percentile(obs, 90))
    p95 = float(np.percentile(obs, 95))

    spec = DistributionSpec(
        dist_type="empirical",
        params={"samples": obs.tolist(), "p5": p5, "p95": p95,
                "n": len(obs), "min": float(obs.min()), "max": float(obs.max())},
        domain_low=gate.domain_low,
        domain_high=gate.domain_high,
        p10=p10, p50=p50, p90=p90,
    )

    warnings = _validate_distribution_spec(spec, gate, v.all_records)

    n = len(obs)
    rationale = (
        f"Empirical distribution from {n} observed values. "
        f"Range {obs.min():.4g}–{obs.max():.4g}, median {p50:.4g}. "
        f"P10={p10:.4g}, P90={p90:.4g}."
    )

    return DistributionBuildResult(
        gate_name=gate.name,
        simulation_allowed=True,
        uncertainty_mode="probabilistic",
        distribution=spec,
        scenarios=None,
        uncertainty_method="empirical",
        evidence_strength="high",
        aleatory_sources=[
            f"Observed variation across {n} microdata records "
            f"(range {obs.min():.4g}–{obs.max():.4g})"
        ],
        epistemic_sources=[
            "Sample may not represent this specific market sub-segment"
            if v.applicability_score < 0.70 else
            "Sampling error in the observed dataset"
        ],
        unquantified_uncertainties=[
            "Future market conditions not reflected in historical data",
            "Competitive entry not modeled in the empirical distribution",
        ],
        evidence_ids=v.evidence_ids,
        evidence_count=len(v.all_records),
        directness_score=v.directness_score,
        applicability_score=v.applicability_score,
        distribution_rationale=rationale,
        assumptions=["Observed values are exchangeable with future market outcomes"],
        warnings=warnings,
        research_question=None,
    )


# ─── Tier 2: published estimate + uncertainty ─────────────────────────────────

def _build_from_reported_statistics(
    v: _ValidatedEvidence,
    gate: FunnelGate,
    context: MarketContext,
) -> DistributionBuildResult:
    # Prefer the highest-directness record that has uncertainty
    rec = max(
        (r for r in v.estimate_records
         if (r.ci_low is not None and r.ci_high is not None)
         or r.standard_error is not None
         or (r.numerator is not None and r.denominator is not None)),
        key=lambda r: r.directness,
        default=v.estimate_records[0] if v.estimate_records else None,
    )

    if rec is None:
        return _build_policy_prior(v.best_estimate, v.best_confidence, gate)

    warnings: List[str] = []
    spec: Optional[DistributionSpec] = None

    # ── Sub-case A: proportion with counts → Beta distribution ──
    if (gate.gate_type == "proportion"
            and rec.numerator is not None
            and rec.denominator is not None
            and rec.denominator > 0):
        k = max(rec.numerator, 0)
        n = rec.denominator
        alpha   = float(k + 1)        # Bayesian posterior with uniform prior
        beta_p  = float(n - k + 1)
        rv      = scipy_stats.beta(alpha, beta_p)
        p10 = max(float(rv.ppf(0.10)), gate.domain_low)
        p50 = max(float(rv.ppf(0.50)), gate.domain_low)
        p90 = min(float(rv.ppf(0.90)), gate.domain_high)
        spec = DistributionSpec(
            dist_type="beta",
            params={"alpha": alpha, "beta_param": beta_p, "n": n, "k": k},
            domain_low=gate.domain_low,
            domain_high=gate.domain_high,
            p10=p10, p50=p50, p90=p90,
        )
        rationale = (
            f"Beta({alpha:.1f}, {beta_p:.1f}) from published counts "
            f"(k={k}, n={n}; Bayesian with uniform prior). "
            f"Source: {rec.citation or rec.id}."
        )

    # ── Sub-case B: proportion with CI ──
    elif (gate.gate_type == "proportion"
            and rec.ci_low is not None
            and rec.ci_high is not None
            and rec.value is not None):
        mu     = float(rec.value)
        ci_low = float(rec.ci_low)
        ci_high = float(rec.ci_high)
        z     = scipy_stats.norm.ppf(0.5 + rec.ci_level / 2.0)
        sigma = (ci_high - ci_low) / (2 * z)
        # Normal approximation clipped to domain for proportions
        rv    = scipy_stats.norm(mu, sigma)
        p10   = float(max(rv.ppf(0.10), gate.domain_low))
        p50   = float(max(min(rv.ppf(0.50), gate.domain_high), gate.domain_low))
        p90   = float(min(rv.ppf(0.90), gate.domain_high))
        if ci_low <= 0 or ci_high >= 1:
            warnings.append(
                "CI touches domain boundary for a proportion gate — "
                "distribution is truncated at [0, 1]. "
                "Consider beta distribution if counts are available."
            )
        spec = DistributionSpec(
            dist_type="normal",
            params={"mu": mu, "sigma": sigma},
            domain_low=gate.domain_low,
            domain_high=gate.domain_high,
            p10=p10, p50=p50, p90=p90,
        )
        rationale = (
            f"Normal({mu:.4g}, σ={sigma:.4g}) from reported {rec.ci_level:.0%} CI "
            f"[{ci_low:.4g}, {ci_high:.4g}]. "
            f"Source: {rec.citation or rec.id}."
        )

    # ── Sub-case C: any estimate with standard error ──
    elif rec.standard_error is not None and rec.value is not None:
        mu     = float(rec.value)
        sigma  = float(rec.standard_error)
        rv     = scipy_stats.norm(mu, sigma)
        p10    = float(max(rv.ppf(0.10), gate.domain_low))
        p50    = float(rv.ppf(0.50))
        p90    = float(min(rv.ppf(0.90), gate.domain_high))
        if gate.gate_type == "price" and p10 < 0:
            warnings.append(
                "Normal distribution produces negative price at P10. "
                "Consider lognormal for price/revenue gates."
            )
        spec = DistributionSpec(
            dist_type="normal",
            params={"mu": mu, "sigma": sigma},
            domain_low=gate.domain_low,
            domain_high=gate.domain_high,
            p10=p10, p50=p50, p90=p90,
        )
        rationale = (
            f"Normal({mu:.4g}, σ={sigma:.4g}) from reported standard error. "
            f"Source: {rec.citation or rec.id}."
        )

    # ── Sub-case D: price/count with CI → lognormal ──
    elif (gate.gate_type == "price"
            and rec.ci_low is not None
            and rec.ci_high is not None
            and rec.value is not None
            and rec.value > 0):
        mu_ln  = math.log(float(rec.value))
        z      = scipy_stats.norm.ppf(0.5 + rec.ci_level / 2.0)
        sigma_ln = (math.log(float(rec.ci_high)) - math.log(float(rec.ci_low))) / (2 * z)
        rv     = scipy_stats.lognorm(s=sigma_ln, scale=math.exp(mu_ln))
        p10    = float(rv.ppf(0.10))
        p50    = float(rv.ppf(0.50))
        p90    = float(rv.ppf(0.90))
        spec   = DistributionSpec(
            dist_type="lognormal",
            params={"mu": mu_ln, "sigma": sigma_ln},
            domain_low=gate.domain_low,
            domain_high=gate.domain_high,
            p10=p10, p50=p50, p90=p90,
        )
        rationale = (
            f"Lognormal(μ={mu_ln:.4g}, σ={sigma_ln:.4g}) from reported CI. "
            f"Source: {rec.citation or rec.id}."
        )

    else:
        # Fallback: point estimate only → policy prior
        return _build_policy_prior(rec.value or v.best_estimate, v.best_confidence, gate)

    warnings += _validate_distribution_spec(spec, gate, v.all_records)

    strength = "high" if v.directness_score >= 0.80 else "medium"
    return DistributionBuildResult(
        gate_name=gate.name,
        simulation_allowed=True,
        uncertainty_mode="probabilistic",
        distribution=spec,
        scenarios=None,
        uncertainty_method="reported_statistics",
        evidence_strength=strength,
        aleatory_sources=["Patient/site-level variability across the study population"],
        epistemic_sources=["Statistical uncertainty in the published point estimate"],
        unquantified_uncertainties=[
            "Publication bias toward significant results",
            "Difference between study population and this specific market context",
        ],
        evidence_ids=v.evidence_ids,
        evidence_count=len(v.all_records),
        directness_score=v.directness_score,
        applicability_score=v.applicability_score,
        distribution_rationale=rationale,
        assumptions=[
            f"Study population is representative of this market (applicability={v.applicability_score:.2f})"
        ],
        warnings=warnings,
        research_question=None,
    )


# ─── Tier 3: analogs ─────────────────────────────────────────────────────────

def _build_from_analogs(
    v: _ValidatedEvidence,
    gate: FunnelGate,
    seed: int,
) -> DistributionBuildResult:
    analogs = v.strong_analogs
    values  = np.asarray([r.value for r in analogs], dtype=float)
    weights = np.asarray([r.comparability_score for r in analogs], dtype=float)

    # Weighted percentiles via sorted order
    idx     = np.argsort(values)
    vals_s  = values[idx]
    wts_s   = weights[idx] / weights.sum()
    cum     = np.cumsum(wts_s)

    def wpctile(p: float) -> float:
        i = np.searchsorted(cum, p)
        return float(vals_s[min(i, len(vals_s) - 1)])

    p10 = max(wpctile(0.10), gate.domain_low)
    p50 = wpctile(0.50)
    p90 = min(wpctile(0.90), gate.domain_high)
    mode = float(np.average(values, weights=weights))

    low  = max(wpctile(0.05), gate.domain_low)
    high = min(wpctile(0.95), gate.domain_high)

    if high <= low:
        high = min(p90 * 1.30, gate.domain_high)
        low  = max(p10 * 0.70, gate.domain_low)

    spec = DistributionSpec(
        dist_type="pert",
        params={"low": low, "mode": mode, "high": high},
        domain_low=gate.domain_low,
        domain_high=gate.domain_high,
        p10=p10, p50=p50, p90=p90,
    )

    weak_count = sum(
        1 for r in v.all_records
        if r.source_type == "analog"
        and r.comparability_score < MIN_ANALOG_COMPARABILITY
    )

    warnings = _validate_distribution_spec(spec, gate, v.all_records)
    if weak_count:
        warnings.append(
            f"{weak_count} analog(s) excluded: comparability score < "
            f"{MIN_ANALOG_COMPARABILITY}."
        )

    analog_labels = [r.citation or r.id for r in analogs]
    rationale = (
        f"PERT from {len(analogs)} comparable analogs "
        f"(weighted by comparability). "
        f"Analog values: {[round(float(r.value), 4) for r in analogs]}. "
        f"Sources: {analog_labels}."
    )

    return DistributionBuildResult(
        gate_name=gate.name,
        simulation_allowed=True,
        uncertainty_mode="probabilistic",
        distribution=spec,
        scenarios=None,
        uncertainty_method="analog_based",
        evidence_strength="medium",
        aleatory_sources=["Cross-product variation in launch adoption trajectories"],
        epistemic_sources=[
            "Uncertainty about whether analogs accurately represent this product",
            "Unknown buyer-level heterogeneity not captured in analog data",
        ],
        unquantified_uncertainties=[
            "Competitive response at time of this product's launch",
            f"{weak_count} weak analogs excluded — may underrepresent downside"
            if weak_count else "All analogs met comparability threshold",
        ],
        evidence_ids=v.evidence_ids,
        evidence_count=len(analogs),
        directness_score=v.directness_score,
        applicability_score=float(np.mean(weights)),
        distribution_rationale=rationale,
        assumptions=[
            "Analog comparability attributes adequately control for market differences",
            "Analogs are not systematically biased by survivorship (successful launches only)",
        ],
        warnings=warnings,
        research_question=None,
    )


# ─── Tier 4: expert elicitation ──────────────────────────────────────────────

def _build_from_expert_elicitation(
    v: _ValidatedEvidence,
    gate: FunnelGate,
    seed: int = 42,
) -> DistributionBuildResult:
    rec  = v.elicitation_records[0]    # use the first documented elicitation
    low  = max(float(rec.expert_low),  gate.domain_low)
    mode = float(rec.expert_mode)
    high = min(float(rec.expert_high), gate.domain_high)

    warnings: List[str] = []
    if not rec.expert_role:
        warnings.append(
            "Expert role not documented. Elicitation reviewability is reduced. "
            "Record: expert title, institution, and relevant experience."
        )
    if not rec.elicitation_date:
        warnings.append("Elicitation date not recorded.")
    if not rec.expert_question:
        warnings.append(
            "Elicitation question not recorded — future replication is not possible."
        )
    if len(v.elicitation_records) > 1:
        modes = [r.expert_mode for r in v.elicitation_records]
        if max(modes) / max(min(modes), 1e-12) > 1.50:
            warnings.append(
                f"Expert disagreement: modes range from {min(modes):.4g} to "
                f"{max(modes):.4g} (>{50}% spread). Consider reconciliation."
            )

    if high <= low:
        high = max(mode * 1.30, low + 1e-9)
        warnings.append("Expert high ≤ low — widened to mode × 1.30.")

    # Use PERT (preferred per spec) when mode is well-defined; triangular otherwise
    dist_type: Literal["pert", "triangular"] = (
        "triangular" if rec.expert_mode == rec.expert_low
        or rec.expert_mode == rec.expert_high
        else "pert"
    )

    # Compute percentiles via sampling
    rng = np.random.default_rng(seed)
    if dist_type == "pert":
        from app.services.monte_carlo_engine import _sample_pert
        samples = _sample_pert(low, mode, high, 10_000, rng)
    else:
        samples = rng.triangular(low, mode, high, 10_000)
    samples = np.clip(samples, gate.domain_low, gate.domain_high)
    p10 = float(np.percentile(samples, 10))
    p50 = float(np.percentile(samples, 50))
    p90 = float(np.percentile(samples, 90))

    spec = DistributionSpec(
        dist_type=dist_type,
        params={"low": low, "mode": mode, "high": high},
        domain_low=gate.domain_low,
        domain_high=gate.domain_high,
        p10=p10, p50=p50, p90=p90,
    )

    warnings += _validate_distribution_spec(spec, gate, v.all_records)

    n_experts = len(v.elicitation_records)
    rationale = (
        f"{dist_type.upper()} from structured expert elicitation "
        f"({n_experts} expert(s)). "
        f"Low={low:.4g}, Mode={mode:.4g}, High={high:.4g}. "
        f"Expert role: {rec.expert_role or 'not documented'}. "
        f"Question: {rec.expert_question or 'not documented'}."
    )

    return DistributionBuildResult(
        gate_name=gate.name,
        simulation_allowed=True,
        uncertainty_mode="probabilistic",
        distribution=spec,
        scenarios=None,
        uncertainty_method="expert_elicitation",
        evidence_strength="low",
        aleatory_sources=["Expert estimate of real market variability"],
        epistemic_sources=[
            "Expert uncertainty about the likely value",
            "Potential anchoring or availability bias in elicitation",
        ],
        unquantified_uncertainties=[
            "Expert range may underestimate tail risk (well-documented in literature)"
        ],
        evidence_ids=v.evidence_ids,
        evidence_count=n_experts,
        directness_score=v.directness_score,
        applicability_score=v.applicability_score,
        distribution_rationale=rationale,
        assumptions=[
            "Expert range represents an honest 90% credible interval",
            "Expert has direct knowledge of this specific market sub-segment",
        ],
        warnings=warnings,
        research_question=None,
    )


# ─── Tier 5: logical bounds → scenario ───────────────────────────────────────

def _build_scenario_or_interval(
    v: _ValidatedEvidence,
    gate: FunnelGate,
) -> DistributionBuildResult:
    rec      = v.bound_records[0]
    bound_lo = max(float(rec.bound_low),  gate.domain_low)
    bound_hi = min(float(rec.bound_high), gate.domain_high)
    base     = v.best_estimate if v.best_estimate is not None else (bound_lo + bound_hi) / 2

    scenarios = [
        ScenarioSpec("low",  bound_lo, rec.bound_rationale or "Lower logical bound"),
        ScenarioSpec("base", float(base), "Best available estimate (unvalidated)"),
        ScenarioSpec("high", bound_hi, rec.bound_rationale or "Upper logical bound"),
    ]

    rationale = (
        f"Logical bounds [{bound_lo:.4g}, {bound_hi:.4g}] — "
        f"no probability assigned within bounds. "
        f"Rationale: {rec.bound_rationale or 'domain constraint'}. "
        "Simulation blocked: bounds do not specify probability mass distribution."
    )

    return DistributionBuildResult(
        gate_name=gate.name,
        simulation_allowed=False,
        uncertainty_mode="scenario",
        distribution=None,
        scenarios=scenarios,
        uncertainty_method="logical_bounds",
        evidence_strength="low",
        aleatory_sources=[],
        epistemic_sources=[
            "Unknown distribution of probability within the logical bounds",
            "Insufficient data to assign probabilities to scenarios",
        ],
        unquantified_uncertainties=[
            "Whether the true value is uniformly or non-uniformly distributed "
            "within the bounds is unknown"
        ],
        evidence_ids=v.evidence_ids,
        evidence_count=len(v.all_records),
        directness_score=v.directness_score,
        applicability_score=v.applicability_score,
        distribution_rationale=rationale,
        assumptions=[
            "Bounds reflect hard constraints, not probability-weighted estimates"
        ],
        warnings=[
            "Report must present three conditional market results (low/base/high), "
            "not P10–P90 percentiles."
        ],
        research_question=(
            f"What is the most likely value for {gate.label} in this specific "
            f"market context? What evidence would narrow these bounds?"
        ),
    )


# ─── Tier 6: policy prior ─────────────────────────────────────────────────────

def _build_policy_prior(
    point_estimate: Optional[float],
    confidence: str,
    gate: FunnelGate,
    seed: int = 42,
) -> DistributionBuildResult:
    if point_estimate is None:
        return _insufficient_evidence(
            gate,
            MarketContext(
                product_type="", disease_name="", gate_type=gate.gate_type,
                gate_units=gate.units
            ),
        )

    v = float(point_estimate)
    half = _POLICY_PRIOR_HALF.get(confidence, 0.45)

    low  = max(v * (1.0 - half),       gate.domain_low)
    high = min(v * (1.0 + half * _POLICY_PRIOR_UPSIDE), gate.domain_high)

    if gate.gate_type == "proportion":
        low  = max(low,  gate.domain_low)
        high = min(high, gate.domain_high)

    if high <= low:
        low  = max(gate.domain_low, v * 0.50)
        high = min(gate.domain_high, v * 1.50)

    # Percentiles via small PERT sample
    rng = np.random.default_rng(seed)
    from app.services.monte_carlo_engine import _sample_pert
    mode = float(np.clip(v, low + 1e-9, high - 1e-9))
    samples = _sample_pert(low, mode, high, 10_000, rng)
    samples = np.clip(samples, gate.domain_low, gate.domain_high)
    p10 = float(np.percentile(samples, 10))
    p50 = float(np.percentile(samples, 50))
    p90 = float(np.percentile(samples, 90))

    spec = DistributionSpec(
        dist_type="pert",
        params={"low": low, "mode": mode, "high": high},
        domain_low=gate.domain_low,
        domain_high=gate.domain_high,
        p10=p10, p50=p50, p90=p90,
        calibrated_to_product=False,     # ← explicitly labeled per spec
    )

    rationale = (
        f"Policy prior around analyst estimate {v:.4g} "
        f"using configured {confidence}-confidence widening rule "
        f"(±{half:.0%} with ×{_POLICY_PRIOR_UPSIDE} upside asymmetry). "
        f"This range is NOT calibrated to this product. "
        f"evidence_strength=very_low."
    )

    return DistributionBuildResult(
        gate_name=gate.name,
        simulation_allowed=True,
        uncertainty_mode="probabilistic",
        distribution=spec,
        scenarios=None,
        uncertainty_method="policy_prior",
        evidence_strength="very_low",
        aleatory_sources=[],
        epistemic_sources=[
            "Policy prior based on generic widening rule, not product-specific data",
            "Analyst estimate is unvalidated",
        ],
        unquantified_uncertainties=[
            "Full extent of uncertainty — this prior may dramatically understate or "
            "overstate the true range"
        ],
        evidence_ids=[],
        evidence_count=0,
        directness_score=0.0,
        applicability_score=0.0,
        distribution_rationale=rationale,
        assumptions=[
            f"Analyst estimate {v:.4g} is approximately correct",
            "Generic widening rule is applicable to this gate type and market context",
            "This is a last-resort prior — NOT evidence-derived",
        ],
        warnings=[
            "uncertainty_method=policy_prior  |  "
            "evidence_strength=very_low  |  "
            "calibrated_to_product=False. "
            "Verify with domain evidence before presenting to a PI."
        ],
        research_question=(
            f"What empirical data, published estimates, or documented expert "
            f"judgment supports the value of {gate.label}?"
        ),
    )


# ─── Tier 7: insufficient evidence ───────────────────────────────────────────

def _insufficient_evidence(
    gate: FunnelGate,
    context: MarketContext,
) -> DistributionBuildResult:
    question = (
        f"What is the expected value and uncertainty range for '{gate.label}' "
        f"({gate.units}) in the context of {context.disease_name or 'this indication'} "
        f"with {context.product_type or 'this product type'}? "
        f"Which published sources, registry analyses, or subject-matter experts "
        f"could provide a defensible estimate?"
    )

    return DistributionBuildResult(
        gate_name=gate.name,
        simulation_allowed=False,
        uncertainty_mode="insufficient",
        distribution=None,
        scenarios=None,
        uncertainty_method="insufficient",
        evidence_strength="none",
        aleatory_sources=[],
        epistemic_sources=["No evidence available to characterize this gate"],
        unquantified_uncertainties=["All uncertainty for this gate is unquantified"],
        evidence_ids=[],
        evidence_count=0,
        directness_score=0.0,
        applicability_score=0.0,
        distribution_rationale=(
            f"Insufficient evidence for gate '{gate.name}'. "
            "No estimate, bounds, analogs, or expert elicitation available. "
            "Monte Carlo simulation is blocked until this gate is resolved."
        ),
        assumptions=[],
        warnings=[
            "simulation_allowed=False — this gate blocks probabilistic simulation. "
            "Resolve via data collection, analog search, or expert elicitation."
        ],
        research_question=question,
    )


# ─── Distribution validation ─────────────────────────────────────────────────

def _validate_distribution_spec(
    spec: DistributionSpec,
    gate: FunnelGate,
    evidence: List[EvidenceRecord],
) -> List[str]:
    """Return a list of warning strings; empty list = no issues found."""
    warnings: List[str] = []

    # 1. Parameter validity
    if spec.dist_type == "beta":
        if spec.params.get("alpha", 0) <= 0 or spec.params.get("beta_param", 0) <= 0:
            warnings.append(
                "INVALID: beta distribution requires alpha > 0 and beta_param > 0."
            )
    elif spec.dist_type in ("pert", "triangular"):
        if spec.params.get("high", 0) <= spec.params.get("low", 0):
            warnings.append(
                "INVALID: distribution high ≤ low — degenerate or inverted range."
            )
    elif spec.dist_type == "lognormal":
        if spec.params.get("sigma", 0) <= 0:
            warnings.append("INVALID: lognormal sigma must be > 0.")
    elif spec.dist_type == "normal":
        if spec.params.get("sigma", 0) <= 0:
            warnings.append("INVALID: normal sigma must be > 0.")

    # 2. Domain bounds
    if spec.p10 < gate.domain_low:
        warnings.append(
            f"P10={spec.p10:.4g} is below domain lower bound {gate.domain_low}. "
            "Samples will be clipped."
        )
    if spec.p90 > gate.domain_high:
        warnings.append(
            f"P90={spec.p90:.4g} exceeds domain upper bound {gate.domain_high}. "
            "Samples will be clipped."
        )

    # 3. Proportion gate with non-proportion distribution
    if gate.gate_type == "proportion":
        if spec.dist_type in ("lognormal",):
            warnings.append(
                "Lognormal distribution used for a proportion gate — "
                "values above 1.0 are possible. Use beta or PERT with domain clipping."
            )
        if spec.p90 > 1.0:
            warnings.append(
                f"P90={spec.p90:.4g} > 1.0 for a proportion gate — "
                "impossible values will be generated."
            )

    # 4. Price gate with normal distribution that allows negatives
    if gate.gate_type == "price" and spec.dist_type == "normal":
        if spec.p10 < 0:
            warnings.append(
                "Normal distribution for a price gate produces negative values at P10. "
                "Use lognormal for positive-only gates."
            )

    # 5. Ordering of percentiles
    if not (spec.p10 <= spec.p50 <= spec.p90):
        warnings.append(
            f"Percentile ordering violated: P10={spec.p10:.4g} P50={spec.p50:.4g} "
            f"P90={spec.p90:.4g}. Distribution may be degenerate."
        )

    return warnings


# ─── Alternate-distribution sensitivity ──────────────────────────────────────

def _run_alternate_sensitivity(
    spec: DistributionSpec,
    gate: FunnelGate,
    seed: int,
    n: int = 10_000,
) -> AlternateSensitivity:
    """
    Compare primary distribution P10-P90 range against a triangular distribution
    with the same support. When the relative range differs by > threshold, the
    conclusion depends on the distributional assumption.
    """
    rng = np.random.default_rng(seed + 7)   # deterministic, different from main seed

    # Determine low/mode/high for the alternate (triangular) comparison
    if spec.dist_type in ("pert", "triangular"):
        low  = spec.params.get("low",  spec.p10)
        mode = spec.params.get("mode", spec.p50)
        high = spec.params.get("high", spec.p90)
    elif spec.dist_type == "beta":
        alpha  = spec.params["alpha"]
        beta_p = spec.params["beta_param"]
        rv     = scipy_stats.beta(alpha, beta_p)
        low    = float(rv.ppf(0.05))
        mode   = ((alpha - 1) / (alpha + beta_p - 2)
                  if alpha > 1 and beta_p > 1
                  else float(rv.mean()))
        high   = float(rv.ppf(0.95))
    else:
        low, mode, high = spec.p10, spec.p50, spec.p90

    low  = max(low,  gate.domain_low)
    high = min(high, gate.domain_high)
    mode = float(np.clip(mode, low + 1e-9, high - 1e-9))

    # Primary P10/P90
    p10_primary = spec.p10
    p90_primary = spec.p90
    range_primary = max(p90_primary - p10_primary, 1e-12)

    # Alternate (triangular) P10/P90
    if high > low:
        alt_samples = np.clip(
            rng.triangular(low, mode, high, n), gate.domain_low, gate.domain_high
        )
        p10_alt = float(np.percentile(alt_samples, 10))
        p90_alt = float(np.percentile(alt_samples, 90))
    else:
        p10_alt = p10_primary
        p90_alt = p90_primary

    range_alt = abs(p90_alt - p10_alt)
    if range_primary < 1e-9 and range_alt < 1e-9:
        # Both distributions are effectively point masses — shape choice is irrelevant
        relative_diff = 0.0
    else:
        relative_diff = abs(range_alt - range_primary) / max(range_primary, 1e-12)
    assessment: Literal["robust", "sensitive"] = (
        "sensitive" if relative_diff > ALTERNATE_SENSITIVITY_THRESHOLD else "robust"
    )

    return AlternateSensitivity(
        primary_distribution=spec.dist_type,
        alternate_distribution="triangular",
        p10_primary=p10_primary,
        p90_primary=p90_primary,
        p10_alternate=p10_alt,
        p90_alternate=p90_alt,
        relative_swing_difference=relative_diff,
        assessment=assessment,
    )


# ─── Verification priority ────────────────────────────────────────────────────

def compute_verification_priority(
    result: DistributionBuildResult,
    p10_market_usd: float,
    p90_market_usd: float,
    total_market_swing_usd: float,
) -> float:
    """
    Priority score for PI verification: combines market impact with evidence weakness.

    verification_priority = normalized_market_impact × (1 − evidence_strength_score)

    High impact + weak evidence → verify first.
    Low impact + strong evidence → verify last (or not at all).
    """
    evidence_score  = _EVIDENCE_STRENGTH_SCORE.get(result.evidence_strength, 0.0)
    gate_swing      = abs(p90_market_usd - p10_market_usd)
    norm_impact     = gate_swing / max(abs(total_market_swing_usd), 1.0)
    return float(norm_impact * (1.0 - evidence_score))


def verification_priority_label(result: DistributionBuildResult,
                                 p10_market_usd: float,
                                 p90_market_usd: float,
                                 total_market_swing_usd: float) -> str:
    """
    Human-readable tornado label combining market swing with evidence strength.
    Suitable for injecting into the report's sensitivity section.
    """
    priority = compute_verification_priority(
        result, p10_market_usd, p90_market_usd, total_market_swing_usd
    )
    swing_m = abs(p90_market_usd - p10_market_usd) / 1_000_000
    return (
        f"{result.gate_name} is {'high' if priority > 0.25 else 'moderate' if priority > 0.10 else 'low'}-"
        f"priority to verify: ${swing_m:.0f}M P10–P90 market swing, "
        f"evidence_strength={result.evidence_strength}."
    )
