"""
Monte Carlo Market Sizing Engine  (Build Spec v6, Part 1)
==========================================================
Replaces the single bottom-up point estimate with a probability distribution
over the funnel, while KEEPING all existing per-product-type revenue models.

Every funnel gate can be:
  • scalar  — backward-compatible with the existing DB funnel (rate / value)
  • dist spec — {"type": "pert"|"normal"|"lognormal"|"triangular"|"uniform", ...}

Auto-widening (when no explicit dist spec is present):
  Gates sourced from analyst_estimate / llm_inference are automatically widened
  to a PERT distribution.  Spread by confidence level:
    high   → ±10%  (tight; public dataset / verified)
    medium → ±25%
    low    → ±45%  (wide; LLM-inferred or expert-required gate)
  Upside asymmetry ×1.30 because addressable markets empirically run larger than
  bottom-up models predict.

Correlation handling:
  Pass correlation_matrix (NxN numpy array) to capture gate co-movement.
  Default = independent (identity).  Internally uses a Gaussian copula so
  correlation is defined on rank, not value (Spearman's ρ).

Reproducibility:
  Same inputs + same seed → IDENTICAL distribution every time.
  Critical for auditability: a PI must be able to re-run and get the same output.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ── Spread table ──────────────────────────────────────────────────────────────
_CONFIDENCE_SPREAD: Dict[str, float] = {
    "high":   0.10,
    "medium": 0.25,
    "low":    0.45,
}
_UPSIDE_MULT = 1.30    # upside asymmetry factor


# ──────────────────────────────────────────────────────────────────────────────
# Gate specification
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class GateSpec:
    """
    One funnel gate, optionally distribution-valued.

    gate_type:
      "absolute" — sets the running population total (first step / absolute count)
      "rate"     — multiplies the running total (a fraction in [0,1])

    dist: explicit distribution spec dict, or None → auto-widen at simulation time.
    """
    name: str
    label: str
    gate_type: str              # "absolute" | "rate"
    value: float                # point estimate / mode
    dist: Optional[Dict]        # explicit spec; None → auto-widen
    confidence: str             # "high" | "medium" | "low"
    source_type: str            # matches confidence_engine source ladder
    is_expert_required: bool = False

    @classmethod
    def from_flow_step(cls, step, is_first: bool = False) -> "GateSpec":
        """
        Build a GateSpec from a patient_flow_engine.FlowStep.
        The first step with rate=None is treated as an absolute population count.
        """
        gate_type = "absolute" if (is_first and step.rate is None) else "rate"
        value = step.running_value if gate_type == "absolute" else (step.rate or 0.0)

        # Map patient_flow confidence → source_type for spread computation
        if step.is_expert_required:
            src = "llm_inference"
        elif step.confidence == "high":
            src = "public_dataset"
        elif step.confidence == "medium":
            src = "analyst_estimate"
        else:
            src = "llm_inference"

        return cls(
            name=step.step,
            label=step.label,
            gate_type=gate_type,
            value=value,
            dist=None,
            confidence=step.confidence,
            source_type=src,
            is_expert_required=step.is_expert_required,
        )

    @classmethod
    def from_dict(cls, d: dict) -> "GateSpec":
        """Build from raw funnel JSON (e.g., from patient_flow_model DB row)."""
        gate_type = d.get("type", "rate")
        value = float(d.get("value") or d.get("rate") or 0.0)
        return cls(
            name=d.get("step", "gate"),
            label=d.get("label", d.get("step", "gate")),
            gate_type=gate_type,
            value=value,
            dist=d.get("dist"),  # explicit dist spec takes precedence
            confidence=d.get("confidence", "low"),
            source_type=d.get("source_type", d.get("source_id", "analyst_estimate")),
            is_expert_required=d.get("is_expert_required", False),
        )


def _auto_widen(gate: GateSpec) -> Dict:
    """
    Convert a scalar gate to a PERT distribution spec based on its confidence.
    Returns the distribution spec dict (never mutates the gate).
    """
    spread = _CONFIDENCE_SPREAD.get(gate.confidence, 0.30)
    if gate.is_expert_required:
        spread = max(spread, 0.30)

    v = gate.value
    if v == 0:
        return {"type": "point", "value": 0.0}

    low = max(0.0, v * (1.0 - spread))
    high = v * (1.0 + spread * _UPSIDE_MULT)

    # Rates must stay in (0, 1]
    if gate.gate_type == "rate":
        high = min(high, 1.0)
        low = max(low, 1e-9)

    if high <= low:
        return {"type": "point", "value": v}

    return {"type": "pert", "low": low, "mode": v, "high": high}


def _effective_dist(gate: GateSpec) -> Dict:
    """Return the gate's explicit dist or auto-widen it."""
    return gate.dist if gate.dist else _auto_widen(gate)


# ──────────────────────────────────────────────────────────────────────────────
# Sampling primitives  (all accept numpy Generator for seeded reproducibility)
# ──────────────────────────────────────────────────────────────────────────────

def _sample(dist_spec: Dict, n: int, rng: np.random.Generator) -> np.ndarray:
    """Draw n samples from a distribution spec dict."""
    dtype = (dist_spec.get("type") or "point").lower()

    if dtype == "point":
        return np.full(n, float(dist_spec.get("value", 0.0)))

    elif dtype == "pert":
        return _sample_pert(
            float(dist_spec["low"]), float(dist_spec["mode"]),
            float(dist_spec["high"]), n, rng,
        )

    elif dtype == "normal":
        return rng.normal(float(dist_spec["mean"]), float(dist_spec["sd"]), n)

    elif dtype == "lognormal":
        return rng.lognormal(float(dist_spec["mu"]), float(dist_spec["sigma"]), n)

    elif dtype == "triangular":
        return rng.triangular(
            float(dist_spec["low"]), float(dist_spec["mode"]),
            float(dist_spec["high"]), n,
        )

    elif dtype == "uniform":
        return rng.uniform(float(dist_spec["low"]), float(dist_spec["high"]), n)

    # Unknown → treat as point at mode/mean/value
    v = dist_spec.get("mode") or dist_spec.get("mean") or dist_spec.get("value") or 0.0
    return np.full(n, float(v))


def _sample_pert(low: float, mode: float, high: float,
                 n: int, rng: np.random.Generator) -> np.ndarray:
    """
    PERT distribution via Beta approximation.

    μ = (low + 4·mode + high) / 6
    α = 6·(μ−low) / (high−low)
    β = 6·(high−μ) / (high−low)
    sample = low + (high−low) · Beta(α,β)
    """
    if high <= low:
        return np.full(n, mode)
    # Clamp mode strictly inside (low, high)
    mode = float(np.clip(mode, low + 1e-12, high - 1e-12))
    mu = (low + 4.0 * mode + high) / 6.0
    r = high - low
    alpha = 6.0 * (mu - low) / r
    beta_p = 6.0 * (high - mu) / r
    if alpha <= 0 or beta_p <= 0:
        # Degenerate: fall back to triangular
        return rng.triangular(low, mode, high, n)
    raw = rng.beta(alpha, beta_p, n)
    return low + raw * r


def _dist_percentile(dist_spec: Dict, p: float,
                     n: int = 4_000, seed: int = 31337) -> float:
    """Estimate a single percentile from a dist spec (fast small-n run)."""
    rng = np.random.default_rng(seed)
    return float(np.percentile(_sample(dist_spec, n, rng), p * 100.0))


# ──────────────────────────────────────────────────────────────────────────────
# Output types
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class TornadoItem:
    """
    Single entry in the sensitivity/tornado analysis.

    Quantitatively answers: "Which gate, if it moved from P10 to P90
    (while all others stay at their mode), produces the largest swing in P50?"
    """
    gate_name: str
    gate_label: str
    p50_at_gate_p10: float    # P50 market when gate is at its P10 (pessimistic)
    p50_at_gate_p90: float    # P50 market when gate is at its P90 (optimistic)
    swing_usd: float          # |p50_high − p50_low|
    swing_pct: float          # swing / baseline_p50
    expert_question: str      # the KOL question that would narrow this uncertainty

    def to_dict(self) -> dict:
        return {
            "gate_name": self.gate_name,
            "gate_label": self.gate_label,
            "p50_at_gate_p10": round(self.p50_at_gate_p10),
            "p50_at_gate_p90": round(self.p50_at_gate_p90),
            "swing_usd": round(self.swing_usd),
            "swing_pct": round(self.swing_pct, 4),
            "expert_question": self.expert_question,
        }


@dataclass
class GateSummary:
    name: str
    label: str
    gate_type: str
    mode: float
    p10: float
    p90: float
    dist_type: str
    confidence: str
    source_type: str

    def to_dict(self) -> dict:
        return {
            "name": self.name, "label": self.label, "gate_type": self.gate_type,
            "mode": self.mode, "p10": self.p10, "p90": self.p90,
            "dist_type": self.dist_type, "confidence": self.confidence,
            "source_type": self.source_type,
        }


@dataclass
class SizingDistribution:
    """
    Full Monte Carlo output.  P50 is the headline; P10-P90 is the honest range.
    Never present P50 alone in a report — always pair with P10/P90.
    """
    p5: float
    p10: float
    p25: float
    p50: float
    p75: float
    p90: float
    p95: float
    mean: float
    std: float
    revenue_model: str
    monetization_unit: str
    n_simulations: int
    seed: int
    tornado: List[TornadoItem]
    gate_summaries: List[GateSummary]

    # ── Derived helpers ───────────────────────────────────────────────────────

    def explain(self) -> str:
        """
        Plain-text derivation of the distribution.
        A skeptical analyst must be able to read this and check every number
        against the gate inputs and revenue model. No black-box language.
        """
        def _fm(v: float) -> str:
            if v >= 1e9: return f"${v/1e9:.1f}B"
            if v >= 1e6: return f"${v/1e6:.0f}M"
            return f"${v:,.0f}"

        lines = [
            f"Monte Carlo sizing  (n={self.n_simulations:,} simulations, seed={self.seed})",
            f"Revenue model: {self.revenue_model} | Monetization unit: {self.monetization_unit}",
            "",
            f"P50 (headline):         {_fm(self.p50)}",
            f"80% CI (P10 – P90):     {_fm(self.p10)} – {_fm(self.p90)}",
            f"90% CI (P5  – P95):     {_fm(self.p5)} – {_fm(self.p95)}",
            "",
            "Gate inputs (mode → distribution):",
        ]
        for g in self.gate_summaries:
            lines.append(
                f"  {g.label:<42}  mode={_fm(g.mode):>10}  "
                f"P10={_fm(g.p10):>10}  P90={_fm(g.p90):>10}  "
                f"src={g.source_type}  conf={g.confidence}"
            )

        if self.tornado:
            top = self.tornado[0]
            lines += [
                "",
                f"Largest uncertainty — '{top.gate_label}':",
                f"  P50 swings from {_fm(top.p50_at_gate_p10)} (pessimistic) "
                f"to {_fm(top.p50_at_gate_p90)} (optimistic)  [{top.swing_pct:.0%} swing]",
                f"  KOL question: {top.expert_question}",
            ]
            if len(self.tornado) > 1:
                second = self.tornado[1]
                lines.append(
                    f"Second driver — '{second.gate_label}': "
                    f"{_fm(second.p50_at_gate_p10)} – {_fm(second.p50_at_gate_p90)} "
                    f"[{second.swing_pct:.0%}]"
                )

        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "p5": round(self.p5), "p10": round(self.p10), "p25": round(self.p25),
            "p50": round(self.p50), "p75": round(self.p75),
            "p90": round(self.p90), "p95": round(self.p95),
            "mean": round(self.mean), "std": round(self.std),
            "revenue_model": self.revenue_model,
            "monetization_unit": self.monetization_unit,
            "n_simulations": self.n_simulations,
            "seed": self.seed,
            "tornado": [t.to_dict() for t in self.tornado],
            "gate_summaries": [g.to_dict() for g in self.gate_summaries],
        }


# ──────────────────────────────────────────────────────────────────────────────
# Tornado / sensitivity analysis
# ──────────────────────────────────────────────────────────────────────────────

def _kol_question(gate: GateSpec, is_price: bool = False) -> str:
    """Generate a targeted expert question for this gate."""
    if is_price:
        return (
            f"What is the actual net acquisition cost (after discounts, rebates, GPO) "
            f"per {gate.label}? The engine used ${gate.value:,.0f}. "
            "Verify against WAC, ASP files, or payer contracts."
        )
    gt = gate.gate_type
    if gt == "absolute":
        return (
            f"What is the actual addressable population size for {gate.label}? "
            f"Current estimate: {gate.value:,.0f}. Verify with claims data or a "
            "clinical KOL who treats this population."
        )
    return (
        f"What fraction of patients/sites meet the criteria for '{gate.label}'? "
        f"Current assumption: {gate.value:.1%}. "
        "Verify with a clinician or payer medical director."
    )


def _compute_tornado(
    gates: List[GateSpec],
    resolved_dists: List[Dict],
    price_dist: Dict,
    net_price_usd: float,
    baseline_p50: float,
) -> List[TornadoItem]:
    """
    Analytical tornado: for each gate, hold all others at their mode value and
    swing that gate from its P10 to its P90.

    For a purely multiplicative funnel  (M = pop × r1 × r2 × ... × price):
      P50_when_gate_i=x = baseline × (x / mode_i)

    This is exact for independent gates with a multiplicative funnel.
    For correlated gates, interpret as the marginal sensitivity.
    """
    if baseline_p50 <= 0:
        return []

    items: List[TornadoItem] = []

    # Gate entries
    for gate, dist in zip(gates, resolved_dists):
        if gate.value <= 0:
            continue
        gate_p10 = _dist_percentile(dist, 0.10)
        gate_p90 = _dist_percentile(dist, 0.90)

        p50_lo = baseline_p50 * (gate_p10 / gate.value)
        p50_hi = baseline_p50 * (gate_p90 / gate.value)
        swing = abs(p50_hi - p50_lo)

        items.append(TornadoItem(
            gate_name=gate.name,
            gate_label=gate.label,
            p50_at_gate_p10=p50_lo,
            p50_at_gate_p90=p50_hi,
            swing_usd=swing,
            swing_pct=swing / baseline_p50,
            expert_question=_kol_question(gate),
        ))

    # Price as implicit gate
    if net_price_usd > 0:
        price_p10 = _dist_percentile(price_dist, 0.10)
        price_p90 = _dist_percentile(price_dist, 0.90)
        p50_lo = baseline_p50 * (price_p10 / net_price_usd)
        p50_hi = baseline_p50 * (price_p90 / net_price_usd)
        swing = abs(p50_hi - p50_lo)
        price_gate = GateSpec("price", "Net price per unit", "rate",
                              net_price_usd, price_dist, "medium", "analyst_estimate")
        items.append(TornadoItem(
            gate_name="price",
            gate_label="Net price per unit",
            p50_at_gate_p10=p50_lo,
            p50_at_gate_p90=p50_hi,
            swing_usd=swing,
            swing_pct=swing / baseline_p50,
            expert_question=_kol_question(price_gate, is_price=True),
        ))

    return sorted(items, key=lambda x: x.swing_usd, reverse=True)


# ──────────────────────────────────────────────────────────────────────────────
# Correlated sampling (Gaussian copula)
# ──────────────────────────────────────────────────────────────────────────────

def _copula_samples(
    resolved_dists: List[Dict],
    corr_matrix: np.ndarray,
    n: int,
    rng: np.random.Generator,
) -> List[np.ndarray]:
    """
    Sample from gates with Spearman rank correlation via Gaussian copula.
    Each marginal distribution is sampled independently but the joint rank
    structure is imposed by the multivariate normal correlation matrix.
    """
    from scipy import stats as scipy_stats

    k = len(resolved_dists)
    # Cholesky decomposition for MV normal with correlation structure
    try:
        chol = np.linalg.cholesky(corr_matrix)
    except np.linalg.LinAlgError:
        # Not positive-definite — fall back to independent
        logger.warning("Correlation matrix not PD; falling back to independent sampling")
        return [_sample(d, n, rng) for d in resolved_dists]

    # Draw iid standard normal and transform
    z_iid = rng.standard_normal((k, n))
    z_corr = chol @ z_iid                        # shape (k, n)
    uniforms = scipy_stats.norm.cdf(z_corr)       # shape (k, n), values in (0,1)

    samples = []
    for i, dist in enumerate(resolved_dists):
        u = uniforms[i]
        # Invert CDF numerically: get the percentile of each uniform draw
        gate_samples = _invert_cdf(dist, u)
        samples.append(gate_samples)
    return samples


def _invert_cdf(dist_spec: Dict, uniforms: np.ndarray) -> np.ndarray:
    """Approximate inverse CDF of a distribution spec via percentile interpolation."""
    pct_grid = np.linspace(0.001, 0.999, 500)
    rng_tmp = np.random.default_rng(999)
    samples_tmp = _sample(dist_spec, 50_000, rng_tmp)
    quantile_vals = np.percentile(samples_tmp, pct_grid * 100)
    return np.interp(uniforms, pct_grid, quantile_vals)


# ──────────────────────────────────────────────────────────────────────────────
# Main simulation entry point
# ──────────────────────────────────────────────────────────────────────────────

def simulate(
    gates: List[GateSpec],
    net_price_usd: float,
    revenue_model: str,
    monetization_unit: str,
    n: int = 10_000,
    seed: int = 42,
    price_confidence: str = "medium",
    correlation_matrix: Optional[np.ndarray] = None,
) -> SizingDistribution:
    """
    Run the Monte Carlo simulation and return a full SizingDistribution.

    Parameters
    ----------
    gates           : ordered list of GateSpec (absolute first, then rates)
    net_price_usd   : net price per monetization unit (point estimate)
    revenue_model   : "per_patient" | "per_procedure" | "site_license" | "per_test"
    monetization_unit : human label for the unit
    n               : number of simulations (10,000 gives stable P10/P90)
    seed            : deterministic seed — MUST be stable for reproducibility
    price_confidence: confidence tier on the price estimate
    correlation_matrix: NxN numpy array; default None = independent gates
    """
    if not gates:
        return _empty_distribution(revenue_model, monetization_unit, n, seed)

    rng = np.random.default_rng(seed)

    # Resolve every gate's distribution
    resolved: List[Dict] = [_effective_dist(g) for g in gates]

    # Price distribution (PERT centred on net_price_usd)
    price_spread = _CONFIDENCE_SPREAD.get(price_confidence, 0.25)
    price_dist: Dict = {
        "type": "pert",
        "low":  max(0.0, net_price_usd * (1.0 - price_spread)),
        "mode": net_price_usd,
        "high": net_price_usd * (1.0 + price_spread * _UPSIDE_MULT),
    }

    # Sample
    if correlation_matrix is not None and len(gates) > 1:
        gate_samples = _copula_samples(resolved, correlation_matrix, n, rng)
    else:
        gate_samples = [_sample(d, n, rng) for d in resolved]

    price_samples = _sample(price_dist, n, rng)

    # Walk funnel — vectorized over all n simulations at once
    running = np.ones(n)
    for gate, drawn in zip(gates, gate_samples):
        if gate.gate_type == "absolute":
            running = drawn
        else:
            running = running * drawn

    revenue_samples = running * price_samples

    # Percentiles
    pcts = np.percentile(revenue_samples, [5, 10, 25, 50, 75, 90, 95])

    # Gate summaries (for explain() and the report)
    gate_summaries: List[GateSummary] = []
    for gate, dist in zip(gates, resolved):
        gate_summaries.append(GateSummary(
            name=gate.name, label=gate.label, gate_type=gate.gate_type,
            mode=gate.value,
            p10=_dist_percentile(dist, 0.10),
            p90=_dist_percentile(dist, 0.90),
            dist_type=dist.get("type", "point"),
            confidence=gate.confidence,
            source_type=gate.source_type,
        ))

    baseline_p50 = float(pcts[3])
    tornado_items = _compute_tornado(
        gates, resolved, price_dist, net_price_usd, baseline_p50
    )

    return SizingDistribution(
        p5=float(pcts[0]),  p10=float(pcts[1]), p25=float(pcts[2]),
        p50=float(pcts[3]), p75=float(pcts[4]), p90=float(pcts[5]), p95=float(pcts[6]),
        mean=float(np.mean(revenue_samples)),
        std=float(np.std(revenue_samples)),
        revenue_model=revenue_model,
        monetization_unit=monetization_unit,
        n_simulations=n,
        seed=seed,
        tornado=tornado_items,
        gate_summaries=gate_summaries,
    )


def simulate_from_patient_flow(
    patient_flow_result,          # PatientFlowResult from patient_flow_engine
    net_price_usd: float,
    revenue_model: str,
    monetization_unit: str,
    n: int = 10_000,
    seed: int = 42,
    price_confidence: str = "medium",
) -> SizingDistribution:
    """
    Convenience wrapper: build GateSpecs from a PatientFlowResult and simulate.
    Used by the orchestrator to avoid exposing raw funnel JSON externally.
    """
    steps = patient_flow_result.steps
    if not steps:
        return _empty_distribution(revenue_model, monetization_unit, n, seed)

    gates: List[GateSpec] = []
    for i, step in enumerate(steps):
        gates.append(GateSpec.from_flow_step(step, is_first=(i == 0)))

    return simulate(
        gates=gates,
        net_price_usd=net_price_usd,
        revenue_model=revenue_model,
        monetization_unit=monetization_unit,
        n=n,
        seed=seed,
        price_confidence=price_confidence,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _empty_distribution(
    revenue_model: str, monetization_unit: str, n: int, seed: int
) -> SizingDistribution:
    return SizingDistribution(
        p5=0, p10=0, p25=0, p50=0, p75=0, p90=0, p95=0,
        mean=0, std=0,
        revenue_model=revenue_model,
        monetization_unit=monetization_unit,
        n_simulations=n,
        seed=seed,
        tornado=[],
        gate_summaries=[],
    )


def build_gates_from_funnel_json(funnel: List[dict]) -> List[GateSpec]:
    """
    Build GateSpec list from a raw patient_flow_model funnel JSON
    (for callers that have the DB row directly).
    """
    gates = []
    for i, step in enumerate(funnel):
        gs = GateSpec.from_dict(step)
        if i == 0 and step.get("type") == "absolute":
            gs.gate_type = "absolute"
        gates.append(gs)
    return gates
