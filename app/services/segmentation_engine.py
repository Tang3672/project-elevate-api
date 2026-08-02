"""
Segmentation Engine  (Build Spec Addendum — Stage 1 MVP)
=========================================================
Multi-dimensional market segmentation with crossed (grouped) hierarchy.

Architecture:
  1. Segment tree: crossed-dimension hierarchy encoded as summing matrix S
  2. Bottom-up aggregation: S @ y_bottom
  3. James-Stein shrinkage: stabilize rate estimates for thin segments
  4. Correlated Monte Carlo: Gaussian copula for cross-segment uncertainty

Governing constraint: every number traces to a source or is flagged as an assumption.
The S matrix guarantees coherence — aggregate = sum of children at all levels.

Stage 2 stub: MinT(Shrink) reconciliation (Wickramasuriya et al. JASA 2019)
Stage 3 stub: Cohort Markov patient-flow layer (NumPy transition matrices)

References:
  Hyndman & Athanasopoulos: grouped time-series, summing matrix S
  Efron & Morris (1973): James-Stein estimator, positive-part form
  Fay & Herriot (1979): small-area estimation via partial pooling
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from itertools import combinations as iter_combinations, product as iter_product
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy import stats as scipy_stats

logger = logging.getLogger(__name__)

# James-Stein requires p >= 3; fewer segments → skip shrinkage
JAMES_STEIN_MIN_P: int = 3

# ─── Pre-built dimensions for common therapy axes ─────────────────────────────

def standard_line_of_therapy(lines: List[str] = ("1L", "2L", "3L+")) -> "Dimension":
    """First/second/third-line split."""
    labels = {"1L": "First Line", "2L": "Second Line", "3L+": "Third Line +"}
    return Dimension(
        name="line_of_therapy",
        label="Line of Therapy",
        values=[DimValue(code=c, label=labels.get(c, c)) for c in lines],
    )


def standard_biomarker(statuses: List[str] = ("positive", "negative")) -> "Dimension":
    """Biomarker-positive / biomarker-negative split."""
    labels = {"positive": "Biomarker Positive", "negative": "Biomarker Negative",
              "unknown": "Biomarker Unknown"}
    return Dimension(
        name="biomarker",
        label="Biomarker Status",
        values=[DimValue(code=c, label=labels.get(c, c)) for c in statuses],
    )


def standard_site_of_care() -> "Dimension":
    return Dimension(
        name="site_of_care",
        label="Site of Care",
        values=[
            DimValue(code="academic", label="Academic / Tertiary"),
            DimValue(code="community", label="Community / Regional"),
        ],
    )


def standard_payer() -> "Dimension":
    return Dimension(
        name="payer",
        label="Payer Segment",
        values=[
            DimValue(code="commercial", label="Commercial"),
            DimValue(code="medicare", label="Medicare"),
            DimValue(code="medicaid", label="Medicaid"),
            DimValue(code="other", label="Other / Uninsured"),
        ],
    )


# ─── Input types ──────────────────────────────────────────────────────────────

@dataclass
class DimValue:
    code: str   # "1L"
    label: str  # "First Line"


@dataclass
class Dimension:
    name: str             # "line_of_therapy"
    label: str            # "Line of Therapy"
    values: List[DimValue]


@dataclass
class Segment:
    segment_id: str
    coordinates: Dict[str, str]   # dim_name → value_code  (empty = total)
    is_bottom_level: bool
    level: int                     # 0=total, k=bottom  (k = number of dimensions)
    label: Optional[str] = field(default=None)

    def __post_init__(self) -> None:
        if self.label is None:
            if not self.coordinates:
                self.label = "Total"
            else:
                self.label = ", ".join(
                    f"{k}={v}" for k, v in sorted(self.coordinates.items())
                )


# ─── Segment tree ─────────────────────────────────────────────────────────────

@dataclass
class SegmentTree:
    dimensions: List[Dimension]
    bottom_segments: List[Segment]   # ordered — defines S matrix columns
    all_segments: List[Segment]      # ordered — defines S matrix rows
    S: np.ndarray                    # shape (n_all, n_bottom); 0/1 float64
    seg_to_row: Dict[str, int]       # segment_id → row index in all_segments
    seg_to_col: Dict[str, int]       # segment_id → col index in bottom_segments (bottom only)

    @property
    def n_bottom(self) -> int:
        return len(self.bottom_segments)

    @property
    def n_total(self) -> int:
        return len(self.all_segments)

    def aggregate(self, bottom_values: np.ndarray) -> np.ndarray:
        """
        Compute all series: S @ bottom_values.
        bottom_values: shape (n_bottom,) or (n_bottom, n_sim).
        Returns shape (n_all,) or (n_all, n_sim).
        """
        return self.S @ bottom_values


# ─── Output types ─────────────────────────────────────────────────────────────

@dataclass
class ShrinkageRecord:
    segment_id: str
    original_estimate: float
    shrunk_estimate: float
    shrinkage_fraction: float  # B: 0=no shrinkage, 1=fully shrunk to grand mean
    grand_mean: float


@dataclass
class SegmentEstimate:
    segment_id: str
    p10: float
    p50: float
    p90: float
    mean: float
    contribution: float   # this segment's P50 / TOTAL P50

    def to_dict(self) -> dict:
        return {
            "segment_id": self.segment_id,
            "p10": round(self.p10, 2),
            "p50": round(self.p50, 2),
            "p90": round(self.p90, 2),
            "mean": round(self.mean, 2),
            "contribution": round(self.contribution, 6),
        }


@dataclass
class SegmentSimulationResult:
    tree: SegmentTree
    segment_estimates: Dict[str, SegmentEstimate]  # segment_id → SegmentEstimate
    total_p10: float
    total_p50: float
    total_p90: float
    n_simulations: int
    seed: int
    shrinkage_records: List[ShrinkageRecord]
    warnings: List[str]
    reconciliation_method: str  # "bottom_up" (Stage 1) or "mint_shrink" (Stage 2)

    def top_n_segments(self, n: int = 10) -> List[SegmentEstimate]:
        """Return the n bottom segments ranked by P50 (largest contribution first)."""
        bottom = [
            est
            for seg_id, est in self.segment_estimates.items()
            if seg_id in self.tree.seg_to_col
        ]
        return sorted(bottom, key=lambda e: e.p50, reverse=True)[:n]

    def explain(self) -> str:
        lines = [
            f"Segmentation: {self.tree.n_bottom} bottom segments × "
            f"{len(self.tree.dimensions)} dimensions",
            f"Total  P50={self.total_p50:>14,.2f}  "
            f"[P10={self.total_p10:>14,.2f} — P90={self.total_p90:>14,.2f}]",
            f"Method: {self.reconciliation_method}  "
            f"n_sim={self.n_simulations}  seed={self.seed}",
        ]

        if self.shrinkage_records:
            lines.append(
                f"\nJames-Stein shrinkage applied to "
                f"{len(self.shrinkage_records)} segment(s):"
            )
            for sr in self.shrinkage_records[:8]:
                lines.append(
                    f"  {sr.segment_id}: "
                    f"{sr.original_estimate:.4g} → {sr.shrunk_estimate:.4g} "
                    f"(B={sr.shrinkage_fraction:.3f}, grand_mean={sr.grand_mean:.4g})"
                )

        top = self.top_n_segments(10)
        if top:
            lines.append("\nTop bottom segments by P50:")
            for i, est in enumerate(top, 1):
                lines.append(
                    f"  {i:2d}. {est.segment_id:<45s} "
                    f"P50={est.p50:>12,.2f}  "
                    f"[{est.p10:>12,.2f} — {est.p90:>12,.2f}]  "
                    f"share={est.contribution:.1%}"
                )

        if self.warnings:
            lines.append("\nWarnings:")
            for w in self.warnings:
                lines.append(f"  ! {w}")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "total_p10": round(self.total_p10, 2),
            "total_p50": round(self.total_p50, 2),
            "total_p90": round(self.total_p90, 2),
            "n_simulations": self.n_simulations,
            "seed": self.seed,
            "reconciliation_method": self.reconciliation_method,
            "warnings": self.warnings,
            "shrinkage_applied": len(self.shrinkage_records),
            "segments": {
                seg_id: est.to_dict()
                for seg_id, est in self.segment_estimates.items()
            },
        }


# ─── Core: build_segment_tree ─────────────────────────────────────────────────

def build_segment_tree(dimensions: List[Dimension]) -> SegmentTree:
    """
    Build a crossed (grouped) segment tree for the given dimensions.

    Generates every possible aggregate: all subsets of {D_1, ..., D_k} × all
    value combinations for that subset.  The empty subset is the "Total" node.

    For k dimensions with sizes n_1,...,n_k:
      Total series  = Π(1 + n_i)
      Bottom segs   = Π(n_i)
      S.shape       = (total_series, bottom_segs)

    S[i, j] = 1  iff  bottom_segment[j] satisfies every coordinate constraint
                       of all_segment[i].  (Total has no constraints → all 1s.)

    Feasibility: k ≤ 5, n_i ≤ 5  →  max ~7 776 × 3 125  (sparse; still dense OK).
    """
    n_dims = len(dimensions)
    all_segs: List[Segment] = []

    for r in range(n_dims + 1):
        for dim_indices in iter_combinations(range(n_dims), r):
            selected = [dimensions[i] for i in dim_indices]
            if r == 0:
                all_segs.append(Segment(
                    segment_id="TOTAL",
                    coordinates={},
                    is_bottom_level=(n_dims == 0),  # degenerate: no dims → TOTAL is also bottom
                    level=0,
                ))
            else:
                for combo in iter_product(*[d.values for d in selected]):
                    coords: Dict[str, str] = {
                        d.name: v.code for d, v in zip(selected, combo)
                    }
                    seg_id = "|".join(
                        f"{dim_name}={val_code}"
                        for dim_name, val_code in sorted(coords.items())
                    )
                    all_segs.append(Segment(
                        segment_id=seg_id,
                        coordinates=coords,
                        is_bottom_level=(r == n_dims),
                        level=r,
                    ))

    bottom_segs = [s for s in all_segs if s.is_bottom_level]
    n_all = len(all_segs)
    n_bot = len(bottom_segs)

    seg_to_row: Dict[str, int] = {s.segment_id: i for i, s in enumerate(all_segs)}
    seg_to_col: Dict[str, int] = {s.segment_id: j for j, s in enumerate(bottom_segs)}

    # S[i,j] = 1 iff bottom_segs[j] satisfies all coordinate constraints of all_segs[i]
    S = np.zeros((n_all, n_bot), dtype=np.float64)
    for i, seg in enumerate(all_segs):
        constraints = seg.coordinates  # may be empty (total) or partial (aggregate)
        for j, bot in enumerate(bottom_segs):
            if all(bot.coordinates.get(k) == v for k, v in constraints.items()):
                S[i, j] = 1.0

    return SegmentTree(
        dimensions=dimensions,
        bottom_segments=bottom_segs,
        all_segments=all_segs,
        S=S,
        seg_to_row=seg_to_row,
        seg_to_col=seg_to_col,
    )


# ─── Core: James-Stein shrinkage ──────────────────────────────────────────────

def james_stein(x: np.ndarray, sigma2: float) -> np.ndarray:
    """
    Positive-part James-Stein estimator (Efron-Morris 1973).

    Shrinks p segment-level rate estimates toward their grand mean μ̄:

        shrink = max(0, 1 − (p−3)·σ²/SS)
        x̂ = μ̄ + shrink·(x − μ̄)

    where SS = Σ(x_i − μ̄)² is the between-segment sum of squares.

    sigma2 is the within-segment variance (e.g., the squared standard error of
    the rate estimate for each segment — assumed equal across segments here).

    Notes:
    - Requires p ≥ 3; fewer segments → return x unchanged
    - Positive-part floors shrink at 0: never overshoots the grand mean
    - When all segments identical (SS ≈ 0): no shrinkage possible
    """
    p = len(x)
    if p < JAMES_STEIN_MIN_P:
        return x.copy()

    grand = float(x.mean())
    ss = float(np.sum((x - grand) ** 2))

    if ss < 1e-12:
        return x.copy()

    shrink = max(0.0, 1.0 - (p - 3) * sigma2 / ss)
    return np.asarray(grand + shrink * (x - grand), dtype=x.dtype)


def apply_shrinkage(
    estimates: Dict[str, float],
    variances: Dict[str, float],
    tree: SegmentTree,
) -> Tuple[Dict[str, float], List[ShrinkageRecord]]:
    """
    Apply James-Stein shrinkage to bottom-segment rate/size estimates.

    Uses the average within-segment variance as the scalar σ² for the JS formula
    (a common simplification when variance estimates are noisy themselves).

    Returns:
        adjusted: estimates dict with shrunk values substituted for bottom segments
        records:  audit trail of what was shrunk and by how much
    """
    bottom_ids = [s.segment_id for s in tree.bottom_segments]
    x = np.array([estimates.get(sid, 0.0) for sid in bottom_ids], dtype=float)

    sigma2 = float(np.mean([variances.get(sid, 0.0) for sid in bottom_ids]))
    x_shrunk = james_stein(x, sigma2)

    grand = float(x.mean())
    ss = float(np.sum((x - grand) ** 2))
    p = len(x)
    shrink = max(0.0, 1.0 - (p - 3) * sigma2 / ss) if (p >= JAMES_STEIN_MIN_P and ss > 1e-12) else 1.0
    B = 1.0 - shrink  # fraction shrunk toward grand mean

    adjusted = dict(estimates)
    records: List[ShrinkageRecord] = []

    for sid, orig, shrunk in zip(bottom_ids, x, x_shrunk):
        adjusted[sid] = float(shrunk)
        if abs(float(orig) - float(shrunk)) > 1e-10:
            records.append(ShrinkageRecord(
                segment_id=sid,
                original_estimate=float(orig),
                shrunk_estimate=float(shrunk),
                shrinkage_fraction=B,
                grand_mean=grand,
            ))

    return adjusted, records


# ─── Core: bottom-up aggregation ──────────────────────────────────────────────

def aggregate_bottom_up(
    tree: SegmentTree,
    bottom_estimates: Dict[str, float],
) -> Dict[str, float]:
    """
    Compute all aggregate series via S @ y_bottom.
    Returns estimates at every level of the hierarchy (bottom + all aggregates).
    """
    y_bottom = np.array(
        [bottom_estimates.get(s.segment_id, 0.0) for s in tree.bottom_segments],
        dtype=float,
    )
    y_all = tree.S @ y_bottom
    return {s.segment_id: float(y_all[i]) for i, s in enumerate(tree.all_segments)}


# ─── Core: correlated Monte Carlo ─────────────────────────────────────────────

def _pert_ppf(u: np.ndarray, low: float, mode: float, high: float) -> np.ndarray:
    """
    Inverse CDF of PERT distribution (beta scaled to [low, high]).
    u: uniform values on [0, 1].
    """
    if high <= low:
        return np.full_like(u, float(mode), dtype=float)
    mode_c = float(np.clip(mode, low + 1e-12, high - 1e-12))
    mu = (low + 4.0 * mode_c + high) / 6.0
    r = high - low
    alpha = 6.0 * (mu - low) / r
    beta_p = 6.0 * (high - mu) / r
    if alpha <= 0.0 or beta_p <= 0.0:
        return np.full_like(u, float(mode_c), dtype=float)
    return low + scipy_stats.beta.ppf(u, alpha, beta_p) * r


def simulate_segments(
    tree: SegmentTree,
    bottom_distributions: Dict[str, Tuple[float, float, float]],
    n: int = 10_000,
    seed: int = 42,
    cross_segment_correlation: Optional[np.ndarray] = None,
    apply_js_shrinkage: bool = True,
    segment_variances: Optional[Dict[str, float]] = None,
) -> SegmentSimulationResult:
    """
    Monte Carlo simulation with Gaussian copula for cross-segment correlation.

    bottom_distributions:
        dict of segment_id → (low, mode, high) PERT parameters representing
        each bottom segment's market-size distribution (P10≈low, P50≈mode, P90≈high).

    cross_segment_correlation:
        n_bottom × n_bottom correlation matrix for the Gaussian copula.
        None → independence (diagonal).  A warning is added when independence
        is assumed, since shared market factors likely make tail risk larger.

    apply_js_shrinkage:
        If True, James-Stein shrinkage is applied to the mode estimates before
        simulation.  Only affects location (central estimate), not spread.

    segment_variances:
        Within-segment variance of the mode estimates, used as σ² in the
        James-Stein formula.  None → σ² = 0 (no shrinkage).

    Returns:
        SegmentSimulationResult with P10/P50/P90 at every hierarchy level.
    """
    warnings: List[str] = []
    shrinkage_records: List[ShrinkageRecord] = []
    m = tree.n_bottom
    rng = np.random.default_rng(seed)

    # 1. Optionally shrink mode estimates across bottom segments
    bottom_ids = [s.segment_id for s in tree.bottom_segments]
    modes: Dict[str, float] = {
        sid: bottom_distributions.get(sid, (0.0, 0.0, 0.0))[1]
        for sid in bottom_ids
    }

    if apply_js_shrinkage and m >= JAMES_STEIN_MIN_P:
        variances = segment_variances or {sid: 0.0 for sid in bottom_ids}
        modes, shrinkage_records = apply_shrinkage(modes, variances, tree)

    # Build (possibly shrinkage-adjusted) PERT parameters
    adjusted: List[Tuple[float, float, float]] = []
    for s in tree.bottom_segments:
        sid = s.segment_id
        orig = bottom_distributions.get(sid, (0.0, 0.0, 0.0))
        adjusted.append((orig[0], modes.get(sid, orig[1]), orig[2]))

    # 2. Gaussian copula → correlated uniforms on [0, 1]
    if cross_segment_correlation is None:
        z = rng.standard_normal((n, m))
        warnings.append(
            "Cross-segment independence assumed. "
            "Shared market factors (disease prevalence, reimbursement environment) "
            "may make aggregate tail risk larger than shown."
        )
    else:
        Sigma = np.asarray(cross_segment_correlation, dtype=float)
        try:
            L = np.linalg.cholesky(Sigma)
            z = rng.standard_normal((n, m)) @ L.T
        except np.linalg.LinAlgError:
            warnings.append(
                "Correlation matrix not positive-definite — "
                "nearest PSD approximation applied (eigenvalue clipping)."
            )
            eigvals, eigvecs = np.linalg.eigh(Sigma)
            eigvals = np.maximum(eigvals, 1e-8)
            Sigma_psd = eigvecs @ np.diag(eigvals) @ eigvecs.T
            L = np.linalg.cholesky(Sigma_psd)
            z = rng.standard_normal((n, m)) @ L.T

    u = scipy_stats.norm.cdf(z)  # shape (n, m), uniform on [0, 1]

    # 3. Transform to each segment's PERT distribution
    y_bottom_sims = np.zeros((m, n), dtype=float)
    for j, (low, mode_val, high) in enumerate(adjusted):
        y_bottom_sims[j, :] = _pert_ppf(u[:, j], low, mode_val, high)

    # Market sizes are non-negative
    y_bottom_sims = np.maximum(y_bottom_sims, 0.0)

    # 4. Aggregate all levels via S matrix: shape (n_all, n)
    y_all_sims = tree.S @ y_bottom_sims  # (n_all, n)

    # 5. Compute percentiles and contribution shares
    total_row = tree.seg_to_row["TOTAL"]
    total_sims = y_all_sims[total_row]
    total_p10 = float(np.percentile(total_sims, 10))
    total_p50 = float(np.percentile(total_sims, 50))
    total_p90 = float(np.percentile(total_sims, 90))
    total_mean = float(np.mean(total_sims))

    segment_estimates: Dict[str, SegmentEstimate] = {}
    for i, seg in enumerate(tree.all_segments):
        sims = y_all_sims[i]
        mean = float(np.mean(sims))
        segment_estimates[seg.segment_id] = SegmentEstimate(
            segment_id=seg.segment_id,
            p10=float(np.percentile(sims, 10)),
            p50=float(np.percentile(sims, 50)),
            p90=float(np.percentile(sims, 90)),
            mean=mean,
            # contribution uses mean, not P50: E[sum] = sum(E) so bottom shares add to 1
            contribution=(mean / total_mean) if total_mean > 0.0 else 0.0,
        )

    return SegmentSimulationResult(
        tree=tree,
        segment_estimates=segment_estimates,
        total_p10=total_p10,
        total_p50=total_p50,
        total_p90=total_p90,
        n_simulations=n,
        seed=seed,
        shrinkage_records=shrinkage_records,
        warnings=warnings,
        reconciliation_method="bottom_up",
    )


# ─── Materiality screening ────────────────────────────────────────────────────

def dimension_materiality(
    tree: SegmentTree,
    bottom_estimates: Dict[str, float],
    dim_name: str,
) -> float:
    """
    Coefficient of variation of this dimension's marginal totals.

    For each value v of dim_name, sums the bottom segments that have that value
    (marginalizing over all other dimensions).  Returns CV = std/mean of those
    marginal totals.

    A high CV means the dimension creates meaningful market strata — suppressing
    it would average out real differences.  A low CV means the dimension's values
    are roughly equal in size and little is lost by pooling.
    """
    dim = next((d for d in tree.dimensions if d.name == dim_name), None)
    if dim is None:
        return 0.0

    value_totals: List[float] = []
    for val in dim.values:
        subtotal = sum(
            bottom_estimates.get(s.segment_id, 0.0)
            for s in tree.bottom_segments
            if s.coordinates.get(dim_name) == val.code
        )
        value_totals.append(subtotal)

    arr = np.array(value_totals, dtype=float)
    if arr.mean() == 0.0:
        return 0.0
    return float(arr.std() / arr.mean())


def recommend_material_dimensions(
    tree: SegmentTree,
    bottom_estimates: Dict[str, float],
    threshold: float = 0.10,
) -> List[str]:
    """
    Return dimension names whose CV exceeds `threshold`, ranked descending.

    Rule of thumb: CV > 0.10 means the dimension creates >10% relative spread
    in marginal market size — worth keeping in the hierarchy.
    """
    scores = {
        d.name: dimension_materiality(tree, bottom_estimates, d.name)
        for d in tree.dimensions
    }
    return sorted(
        [name for name, score in scores.items() if score > threshold],
        key=lambda name: scores[name],
        reverse=True,
    )


# ─── Stage 2 stub: MinT(Shrink) reconciliation ────────────────────────────────

def reconcile_mint_shrink(
    tree: SegmentTree,
    base_bottom_estimates: Dict[str, float],
) -> Dict[str, float]:
    """
    Stage 2 placeholder — MinT(Shrink) optimal reconciliation.

    Minimises total forecast-error variance subject to hierarchy coherence:
        ỹ = S · G · ŷ  (G is the optimal gain matrix)

    Wickramasuriya, Athanasopoulos & Hyndman, JASA 2019.
    Requires:  pip install hierarchicalforecast

    Falls back to bottom-up until Stage 2 is fully implemented.
    """
    try:
        from hierarchicalforecast.methods import MinTrace  # noqa: F401
        logger.warning(
            "MinT(Shrink) is a Stage 2 feature — "
            "falling back to bottom-up aggregation."
        )
    except ImportError:
        pass

    return aggregate_bottom_up(tree, base_bottom_estimates)


# ─── Stage 3 stub: Cohort Markov patient-flow ─────────────────────────────────

def cohort_markov_flow(
    transition_matrix: np.ndarray,
    initial_cohort: np.ndarray,
    n_cycles: int = 12,
) -> np.ndarray:
    """
    Stage 3 placeholder — Cohort Markov state-transition model.

    transition_matrix: (n_states × n_states) column-stochastic
    initial_cohort:    (n_states,) cohort size per state at t=0
    n_cycles:          number of time steps (months)

    Returns (n_cycles+1, n_states) cohort trace over time.
    This is a pure NumPy computation — no external deps.
    """
    n_states = transition_matrix.shape[0]
    trace = np.zeros((n_cycles + 1, n_states), dtype=float)
    trace[0] = initial_cohort
    for t in range(1, n_cycles + 1):
        trace[t] = transition_matrix @ trace[t - 1]
    return trace
