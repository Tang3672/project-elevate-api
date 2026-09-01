"""
Market Sizing Engine v3 — Full Five-Stage Mathematical Pipeline
================================================================
Implements every equation from the Advanced Mathematical Frameworks for Medical
Product Market Sizing and Epidemiological Forecasting document:

  Stage 1  DisMod Population Cascade               §1 / §6.1
           Prevalence × Diagnostic Yield × Treatment Eligibility

  Stage 2  Parametric Survival Models (Weibull/Gompertz/Poly-Hazard)  §5
           S(t) = 1 − ∫₀ᵗ f(u|θ)du   h(t) = f(t)/S(t)
           Poly-Hazard: h(t) = Σₖ hₖ(t)  (§5.2)
           Duration of Therapy = ∫₀^∞ S(t) dt

  Stage 3  Bass Diffusion Model (§4.1)
           f(t) = dF/dt = [p + qF(t)][1 − F(t)]
           F(t) = (1 − e^{−(p+q)t}) / (1 + (q/p)e^{−(p+q)t})

  Stage 3b UCRCD Duopolistic Competition — Lotka-Volterra with Churn (§4.2)
           Guseo & Guidolin (Ann. Appl. Stat. 2015)
           Phase 1 (monopoly): z'₁ = (p₁ₐ + q₁ₐz₁)/mₐ × [mₐ − z₁]
           Phase 2 (duopoly):
             z'₁ = (p₁ + a₁z₁ + b₁z₂)/(m₁+m₂) × [(m₁−z₁) + (m₂−z₂)]
             z'₂ = (p₂ + a₂z₂ + b₂z₁)/(m₂+m₁) × [(m₂−z₂) + (m₁−z₁)]
           b₁,b₂ < 0 → cannibalization; b₁,b₂ > 0 → class effect

  Stage 4  BLP Random Coefficients Logit (§3.1–3.2)
           Berry, Levinsohn & Pakes (1995); Nevo (2000)
           s_{jt} = (1/nₛ) Σᵢ exp(δ_j + Σₖ σₖvᵢᵏxⱼᵏ) / (1 + Σₘ exp(...))
           Contraction mapping: δ^{h+1} = δ^h + ln S_{·t} − ln s(δ^h; θ₂)
           For pre-launch assets: target S derived from BLP utility model

  Stage 5  Gross-to-Net Pricing + BIA Affordability Gate (§6)
           ISPOR/Mauskopf Population Cascade + payer budget constraint
           Net Budget Impact ΔB triggers dampening if payer ceiling exceeded
"""

from __future__ import annotations

import logging
import math
import random
from typing import Optional

try:
    import numpy as np
    from scipy.integrate import solve_ivp
    from scipy.special import gamma as gamma_fn
    _SCIPY_OK = True
    # numpy.trapz removed in NumPy 2.0; trapezoid is the replacement
    _np_trapz = getattr(np, "trapezoid", None) or getattr(np, "trapz", None)
except ImportError:
    _SCIPY_OK = False
    np = None
    _np_trapz = None
    solve_ivp = None
    def gamma_fn(x: float) -> float:
        # Stirling approximation fallback — accurate to <1% for x > 1
        import math
        if x <= 0:
            return 1.0
        return math.sqrt(2 * math.pi / x) * (x / math.e) ** x

logger = logging.getLogger(__name__)

# Seed for reproducible Monte Carlo
_RNG_SEED = 42


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 1: DIMOD POPULATION CASCADE (§1 / §6.1)
# ══════════════════════════════════════════════════════════════════════════════

_DIAGNOSTIC_YIELD: dict[str, float] = {
    "oncology":        0.85,
    "hematology":      0.88,
    "rare_disease":    0.38,
    "gene_therapy":    0.35,
    "cns":             0.58,
    "cardiovascular":  0.78,
    "metabolic":       0.82,
    "amr_infectious":  0.52,
    "immunology":      0.68,
    "ophthalmology":   0.72,
    "vaccine":         0.90,
    "device":          0.88,
    "diagnostic":      0.90,
    "respiratory":     0.68,
    "other":           0.62,
}

_TREATMENT_ELIGIBLE: dict[str, float] = {
    "oncology":        0.38,
    "hematology":      0.55,
    "rare_disease":    0.88,
    "gene_therapy":    0.92,
    "cns":             0.52,
    "cardiovascular":  0.40,
    "metabolic":       0.28,
    "amr_infectious":  0.72,
    "immunology":      0.32,
    "ophthalmology":   0.65,
    "vaccine":         0.85,
    "device":          0.70,
    "diagnostic":      0.95,
    "respiratory":     0.42,
    "other":           0.52,
}


def apply_population_cascade(
    prevalent_patients: int,
    therapeutic_area: str,
    is_biomarker_selected: bool = False,
    is_first_in_class: bool = False,
) -> tuple[int, float, float, str]:
    ta = therapeutic_area.lower()
    diag_yield  = _DIAGNOSTIC_YIELD.get(ta, 0.62)
    treat_elig  = _TREATMENT_ELIGIBLE.get(ta, 0.52)
    if is_biomarker_selected and ta not in ("rare_disease", "gene_therapy"):
        treat_elig *= 0.65
    if is_first_in_class:
        treat_elig = min(treat_elig * 1.25, 0.95)
    diagnosed = int(prevalent_patients * diag_yield)
    eligible  = int(diagnosed * treat_elig)
    summary = (f"Prevalence {prevalent_patients:,} → Diagnosed {diagnosed:,} "
               f"({diag_yield:.0%} yield) → Eligible {eligible:,} ({treat_elig:.0%})")
    return eligible, diag_yield, treat_elig, summary


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 2: PARAMETRIC SURVIVAL MODELS + POLY-HAZARD (§5.1 / §5.2)
# ══════════════════════════════════════════════════════════════════════════════

def weibull_survival(t: float, k: float, lam: float) -> float:
    """
    Weibull survival function: S(t) = exp(−(t/λ)^k)
    h(t) = (k/λ)(t/λ)^{k−1}   — monotonically increasing (k>1) or decreasing (k<1)
    Source: NICE TSD 14 §5
    """
    if t <= 0:
        return 1.0
    return math.exp(-((t / lam) ** k))


def gompertz_survival(t: float, alpha: float, gamma: float) -> float:
    """
    Gompertz survival function: S(t) = exp(−α/γ × (e^{γt} − 1))
    h(t) = α·exp(γ·t)   — log-hazard linear in time (aging cohorts)
    Source: NICE TSD 14 §5
    """
    if t <= 0:
        return 1.0
    return math.exp(-alpha / gamma * (math.exp(gamma * t) - 1))


def expected_dot_weibull(k: float, lam: float) -> float:
    """
    E[T] = λ × Γ(1 + 1/k)   — analytical mean of Weibull distribution.
    Integrates the area under S(t) = exp(−(t/λ)^k).
    """
    return lam * gamma_fn(1.0 + 1.0 / k)


def expected_dot_gompertz(alpha: float, gamma: float, t_max: float = 40.0) -> float:
    """E[T] = ∫₀^∞ S(t) dt — numerical integration of Gompertz survival."""
    if not _SCIPY_OK:
        # Analytical approximation: E[T] ≈ -ln(α/γ)/γ when alpha/gamma < 1
        # Fallback: use the mode of the Gompertz as a proxy for the mean
        return max(0.5, (math.log(max(alpha, 1e-9)) / max(gamma, 1e-9)) * -1)
    t_pts = np.linspace(0, t_max, 2000)
    s_pts = np.array([gompertz_survival(t, alpha, gamma) for t in t_pts])
    return float(_np_trapz(s_pts, t_pts))


def poly_hazard_survival(t, phases: list[dict]):
    """
    Poly-Hazard model: h(t) = Σₖ hₖ(t)    §5.2
    S(t) = exp(−∫₀ᵗ h(u) du)

    Each phase dict: {type: "weibull"|"gompertz"|"exponential",
                      k/alpha/mu, lam/gamma/rate, weight: float}
    Weights control relative contribution of each hazard phase.
    """
    if not _SCIPY_OK:
        # Fallback: use the dominant phase's expected DoT
        dominant = max(phases, key=lambda p: p.get("weight", 1.0))
        if dominant.get("type") == "weibull":
            return [weibull_survival(ti, dominant["k"], dominant["lam"]) for ti in t]
        return [math.exp(-0.1 * ti) for ti in t]

    H = np.zeros_like(t, dtype=float)
    for ph in phases:
        ptype  = ph.get("type", "weibull")
        weight = ph.get("weight", 1.0)
        if ptype == "weibull":
            k, lam = ph["k"], ph["lam"]
            h = weight * (k / lam) * ((t / lam) ** (k - 1))
        elif ptype == "gompertz":
            alpha, gam = ph["alpha"], ph["gamma"]
            h = weight * alpha * np.exp(gam * t)
        else:
            rate = ph.get("rate", 0.1)
            h = weight * rate * np.ones_like(t)
        H += h
    # BUG-14: was O(n²) list-comp calling trapz on growing prefix — 2M ops at n=2000.
    # cumsum of trapezoid slices is O(n) and mathematically identical.
    _dt = np.diff(t, prepend=t[0])
    _h_mid = np.concatenate(([0.0], 0.5 * (H[:-1] + H[1:]) * np.diff(t)))
    H_cum = np.cumsum(_h_mid)
    return np.exp(-H_cum)


def expected_dot_poly_hazard(phases: list[dict], t_max: float = 20.0) -> float:
    """E[T] = ∫₀^∞ S(t) dt for poly-hazard model."""
    if not _SCIPY_OK:
        dominant = max(phases, key=lambda p: p.get("weight", 1.0))
        if dominant.get("type") == "weibull":
            return expected_dot_weibull(dominant["k"], dominant["lam"])
        return 3.0  # reasonable CAR-T fallback
    t_pts = np.linspace(0, t_max, 2000)
    s_pts = poly_hazard_survival(t_pts, phases)
    return float(_np_trapz(s_pts, t_pts))


# ── Disease-specific survival parameterization ────────────────────────────────
# Weibull/Gompertz parameters calibrated to published PFS medians (NICE TSD 14).
# k>1 = progressive (oncology); k≈1 = stable; k<1 = early drop-off (CAR-T)

_SURVIVAL_PARAMS: dict[str, dict] = {
    # Oncology: Weibull k=1.5, median PFS ~18mo → lam ≈ 1.8yr/(-ln0.5)^(1/1.5)
    ("oncology",        "drug_small_molecule"): {"type": "weibull", "k": 1.5, "lam": 1.6},
    ("oncology",        "biologic"):            {"type": "weibull", "k": 1.5, "lam": 2.1},
    # CAR-T: poly-hazard (early toxicity spike + stable remission)
    ("oncology",        "gene_cell_therapy"):   {"type": "poly_hazard", "phases": [
        {"type": "weibull",     "k": 3.0, "lam": 0.25, "weight": 0.30},  # early toxicity
        {"type": "gompertz",    "alpha": 0.05, "gamma": 0.15, "weight": 0.70},  # remission
    ]},
    ("hematology",      "biologic"):            {"type": "weibull", "k": 1.3, "lam": 3.0},
    ("hematology",      "gene_cell_therapy"):   {"type": "poly_hazard", "phases": [
        {"type": "weibull",     "k": 2.5, "lam": 0.20, "weight": 0.25},
        {"type": "gompertz",    "alpha": 0.03, "gamma": 0.10, "weight": 0.75},
    ]},
    # Gene therapy: single curative administration — very long effective benefit
    ("gene_therapy",    "gene_cell_therapy"):   {"type": "weibull", "k": 0.8, "lam": 22.0},
    ("rare_disease",    "gene_cell_therapy"):   {"type": "weibull", "k": 0.8, "lam": 20.0},
    # AMR: acute short course — exponential decay after treatment duration
    ("amr_infectious",  "drug_small_molecule"): {"type": "exponential", "rate": 26.0},  # 14-day
    ("amr_infectious",  "biologic"):            {"type": "exponential", "rate": 18.0},  # 20-day
    # CNS: Gompertz (aging + neurodegeneration acceleration)
    ("cns",             "drug_small_molecule"): {"type": "gompertz", "alpha": 0.05, "gamma": 0.12},
    ("cns",             "biologic"):            {"type": "gompertz", "alpha": 0.06, "gamma": 0.10},
    # Chronic maintenance: Weibull k≈1 (near-exponential, minimal hazard increase)
    ("cardiovascular",  "drug_small_molecule"): {"type": "weibull", "k": 1.05, "lam": 12.0},
    ("metabolic",       "drug_small_molecule"): {"type": "weibull", "k": 1.02, "lam": 14.0},
    ("immunology",      "biologic"):            {"type": "weibull", "k": 1.10, "lam": 7.5},
    ("ophthalmology",   "biologic"):            {"type": "weibull", "k": 1.0,  "lam": 12.0},
    ("respiratory",     "drug_small_molecule"): {"type": "weibull", "k": 1.05, "lam": 9.0},
    ("vaccine",         "vaccine_immunotherapy"):{"type": "exponential", "rate": 0.22},  # ~4.5yr
    ("device",          "medical_device"):       {"type": "weibull", "k": 1.8, "lam": 9.0},
    ("diagnostic",      "diagnostic"):           {"type": "exponential", "rate": 50.0},  # ~7 days
}

_TA_SURVIVAL_DEFAULTS: dict[str, dict] = {
    "oncology":       {"type": "weibull", "k": 1.5, "lam": 1.8},
    "hematology":     {"type": "weibull", "k": 1.3, "lam": 2.8},
    "rare_disease":   {"type": "weibull", "k": 1.0, "lam": 14.0},
    "gene_therapy":   {"type": "weibull", "k": 0.8, "lam": 20.0},
    "cns":            {"type": "gompertz","alpha": 0.05, "gamma": 0.12},
    "cardiovascular": {"type": "weibull", "k": 1.05, "lam": 11.0},
    "metabolic":      {"type": "weibull", "k": 1.02, "lam": 13.0},
    "amr_infectious": {"type": "exponential", "rate": 26.0},
    "immunology":     {"type": "weibull", "k": 1.10, "lam": 7.0},
    "vaccine":        {"type": "exponential", "rate": 0.22},
    "ophthalmology":  {"type": "weibull", "k": 1.0, "lam": 11.0},
    "device":         {"type": "weibull", "k": 1.8, "lam": 9.0},
    "diagnostic":     {"type": "exponential", "rate": 50.0},
    "respiratory":    {"type": "weibull", "k": 1.05, "lam": 8.0},
    "other":          {"type": "weibull", "k": 1.1, "lam": 6.0},
}


def compute_dot_survival(therapeutic_area: str,
                          modality: str = "drug_small_molecule") -> tuple[float, str]:
    """
    Stage 2: Compute expected Duration of Therapy from the appropriate parametric
    survival distribution. Returns (dot_years, distribution_type).
    """
    ta  = therapeutic_area.lower()
    mod = modality.lower()
    sp  = _SURVIVAL_PARAMS.get((ta, mod)) or _TA_SURVIVAL_DEFAULTS.get(ta,
              {"type": "weibull", "k": 1.1, "lam": 6.0})

    dist = sp["type"]
    if dist == "weibull":
        dot = expected_dot_weibull(sp["k"], sp["lam"])
    elif dist == "gompertz":
        dot = expected_dot_gompertz(sp["alpha"], sp["gamma"])
    elif dist == "poly_hazard":
        dot = expected_dot_poly_hazard(sp["phases"])
    else:  # exponential: E[T] = 1/rate
        dot = 1.0 / sp["rate"]

    return round(dot, 3), dist


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 3: BASS DIFFUSION MODEL (§4.1)
# F(t) = (1 − e^{−(p+q)t}) / (1 + (q/p)e^{−(p+q)t})
# ══════════════════════════════════════════════════════════════════════════════

_BASS_PARAMS: dict[str, tuple[float, float]] = {
    "oncology":        (0.030, 0.350),
    "hematology":      (0.025, 0.380),
    "rare_disease":    (0.018, 0.150),
    "gene_therapy":    (0.015, 0.120),
    "cns":             (0.020, 0.220),
    "cardiovascular":  (0.015, 0.280),
    "metabolic":       (0.028, 0.400),
    "amr_infectious":  (0.010, 0.080),
    "immunology":      (0.022, 0.320),
    "vaccine":         (0.020, 0.300),
    "ophthalmology":   (0.018, 0.250),
    "device":          (0.012, 0.200),
    "diagnostic":      (0.025, 0.350),
    "respiratory":     (0.018, 0.260),
    "other":           (0.020, 0.250),
}


def bass_cumulative(t: float, p: float, q: float) -> float:
    """F(t) = (1 − e^{−(p+q)t}) / (1 + (q/p)e^{−(p+q)t})"""
    if p + q <= 0 or t <= 0:
        return 0.0
    exp_t = math.exp(-(p + q) * t)
    return (1.0 - exp_t) / (1.0 + (q / p) * exp_t)


def bass_peak_time(p: float, q: float) -> float:
    """t_peak = ln(q/p)/(p+q)"""
    if p <= 0 or q <= 0:
        return 5.0
    return math.log(q / p) / (p + q)


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 3b: UCRCD DUOPOLISTIC COMPETITION — LOTKA-VOLTERRA (§4.2)
# Guseo & Guidolin (Ann. Appl. Stat. 2015)
# ══════════════════════════════════════════════════════════════════════════════

# Cross-product word-of-mouth (b) by TA:
#   b < 0 → cannibalization (novel drug steals directly from SoC)
#   b > 0 → class effect (both drugs benefit from combined awareness)
_CROSS_WOM: dict[str, float] = {
    "oncology":        -0.12,   # Fixed-indication; pure cannibalization
    "hematology":      -0.08,
    "rare_disease":     0.05,   # Small field; class awareness helps both
    "gene_therapy":     0.08,   # New modality creates category awareness
    "cns":             -0.05,
    "cardiovascular":  -0.10,
    "metabolic":        0.15,   # GLP-1 class effect proven
    "amr_infectious":   0.10,   # AMR awareness campaigns benefit all drugs
    "immunology":      -0.08,
    "vaccine":          0.05,
    "ophthalmology":   -0.06,
    "device":           0.08,   # Device category awareness
    "diagnostic":       0.12,
    "respiratory":     -0.04,
    "other":            0.00,
}

# Within-product WOM (a) — internal word-of-mouth from own user base
_WITHIN_WOM: dict[str, float] = {
    "oncology":    0.35, "hematology": 0.38, "rare_disease": 0.15,
    "gene_therapy":0.12, "cns":        0.22, "cardiovascular":0.28,
    "metabolic":   0.40, "amr_infectious": 0.08, "immunology": 0.32,
    "vaccine":     0.30, "ophthalmology":  0.25, "device":     0.20,
    "diagnostic":  0.35, "respiratory":    0.26, "other":      0.25,
}


def _ucrcd_odes(t, z, p1, p2, a1, a2, b1, b2, m1, m2):
    """
    UCRCD Phase 2 coupled ODEs (Guseo-Guidolin §4.2.2):
      z'₁ = (p₁ + a₁z₁ + b₁z₂)/(m₁+m₂) × [(m₁−z₁) + (m₂−z₂)]
      z'₂ = (p₂ + a₂z₂ + b₂z₁)/(m₂+m₁) × [(m₂−z₂) + (m₁−z₁)]
    """
    z1, z2    = z
    denom     = m1 + m2
    residual1 = (m1 - z1) + (m2 - z2)
    residual2 = (m2 - z2) + (m1 - z1)
    dz1 = (p1 + a1 * z1 + b1 * z2) / denom * residual1
    dz2 = (p2 + a2 * z2 + b2 * z1) / denom * residual2
    return [dz1, dz2]


def ucrcd_penetration(
    therapeutic_area: str,
    approved_treatments_count: int,
    is_first_in_class: bool,
    years: float = 5.0,
) -> tuple[float, float, dict]:
    """
    Stage 3b: UCRCD Lotka-Volterra market dynamics.

    Models novel drug (Drug 2) entering against existing standard of care (Drug 1).
    Phase 1 = monopolistic Bass curve for novel drug before major competitor response.
    Phase 2 = coupled ODEs with cross-product WOM.

    Returns:
      (novel_drug_share_y5, peak_time, metadata)
    """
    ta = therapeutic_area.lower()
    p2, q2   = _BASS_PARAMS.get(ta, (0.020, 0.250))
    a_wom    = _WITHIN_WOM.get(ta, 0.25)
    b_cross  = _CROSS_WOM.get(ta, 0.0)

    if is_first_in_class:
        p2 *= 1.30   # FIC education effect: higher innovation coefficient

    # Market potentials
    # m1 = SoC market (normalised to 1.0 representing 100% of eligible patients)
    # m2 = Novel drug potential (fraction of m1 it can capture)
    # Entry share heuristic: each additional approved drug splits the market
    existing = max(1, approved_treatments_count)
    m1 = 1.0
    m2 = min(0.70, 1.0 / existing)  # Novel drug potential: inversely related to competition

    # Phase 1: Stand-Alone Bass curve for novel drug (monopolistic, §4.2.1)
    # Lasts until the first major competitive response (assume 1yr for late entrants, 2yr for FIC)
    c2 = 2.0 if is_first_in_class else 1.0
    phase1_end = min(c2, years)
    z1_at_c2   = bass_cumulative(phase1_end, p2, q2) * m2

    if years <= c2:
        # Still in monopolistic phase
        z2_final = bass_cumulative(years, p2, q2) * m2
        return z2_final, bass_peak_time(p2, q2), {
            "phase": "monopolistic",
            "novel_share_y5": round(z2_final, 4),
            "b_cross_wom": round(b_cross, 3),
        }

    # Phase 2: Solve UCRCD coupled ODEs (§4.2.2)
    soc_penetration_at_c2 = min(0.80, bass_cumulative(3.0, 0.020, 0.300))
    z1_at_c2_val = soc_penetration_at_c2 * m1

    if not _SCIPY_OK:
        # scipy unavailable — fall back to Bass-only penetration scaled by entry share
        entry_share = min(0.70, 1.0 / max(1, approved_treatments_count + 1))
        z2_final = bass_cumulative(years, p2, q2) * m2 * entry_share
        z2_final = max(0.0, z2_final)
        return z2_final, bass_peak_time(p2, q2), {
            "phase": "bass_fallback_no_scipy",
            "novel_share_y5": round(z2_final, 4),
            "b_cross_wom": round(b_cross, 3),
        }

    try:
        sol = solve_ivp(
            _ucrcd_odes,
            t_span=(c2, years),
            y0=[z1_at_c2_val, z1_at_c2],
            args=(0.015, p2, a_wom, a_wom, b_cross, b_cross, m1, m2),
            method="RK45",
            rtol=1e-5, atol=1e-7,
            dense_output=False,
        )
        z2_final = float(sol.y[1][-1]) if sol.success else z1_at_c2
    except Exception as e:
        logger.warning("UCRCD ODE failed for %s: %s — falling back to Bass", ta, e)
        z2_final = bass_cumulative(years, p2, q2) * m2

    t_peak = bass_peak_time(p2, q2)

    return z2_final, t_peak, {
        "phase":        "duopolistic_ucrcd",
        "novel_share_y5": round(z2_final, 4),
        "b_cross_wom":  round(b_cross, 3),
        "m1_soc":       round(m1, 3),
        "m2_novel":     round(m2, 3),
        "class_effect": b_cross > 0,
    }


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 4: BLP RANDOM COEFFICIENTS LOGIT (§3.1–3.2)
# Berry, Levinsohn & Pakes (1995); Nevo (2000)
# ══════════════════════════════════════════════════════════════════════════════

# Taste heterogeneity parameters σₖ by TA:
# High σ → patients strongly disagree on drug value (e.g., oncology patients
# tolerate severe toxicity very differently)
_BLP_SIGMA: dict[str, dict] = {
    "oncology":       {"efficacy": 0.45, "safety": 0.55, "price": 0.30, "convenience": 0.20},
    "hematology":     {"efficacy": 0.40, "safety": 0.50, "price": 0.25, "convenience": 0.20},
    "rare_disease":   {"efficacy": 0.35, "safety": 0.30, "price": 0.15, "convenience": 0.25},
    "gene_therapy":   {"efficacy": 0.30, "safety": 0.40, "price": 0.10, "convenience": 0.15},
    "cns":            {"efficacy": 0.40, "safety": 0.45, "price": 0.35, "convenience": 0.30},
    "cardiovascular": {"efficacy": 0.30, "safety": 0.35, "price": 0.40, "convenience": 0.35},
    "metabolic":      {"efficacy": 0.35, "safety": 0.30, "price": 0.50, "convenience": 0.45},
    "amr_infectious": {"efficacy": 0.50, "safety": 0.40, "price": 0.20, "convenience": 0.15},
    "immunology":     {"efficacy": 0.40, "safety": 0.50, "price": 0.35, "convenience": 0.30},
    "vaccine":        {"efficacy": 0.20, "safety": 0.40, "price": 0.45, "convenience": 0.50},
    "ophthalmology":  {"efficacy": 0.45, "safety": 0.40, "price": 0.30, "convenience": 0.40},
    "device":         {"efficacy": 0.35, "safety": 0.30, "price": 0.35, "convenience": 0.45},
    "other":          {"efficacy": 0.35, "safety": 0.35, "price": 0.35, "convenience": 0.30},
}

_BLP_DEFAULT_SIGMA = {"efficacy": 0.35, "safety": 0.35, "price": 0.35, "convenience": 0.30}


def _mean_utility(
    efficacy_vs_soc: float,    # Novel drug efficacy lift vs standard of care (−1..+1)
    safety_vs_soc: float,      # Safety profile vs SoC (−1=worse, +1=better)
    convenience_vs_soc: float, # Administration convenience (−1=worse, +1=better)
    price_rank: float,         # Relative price rank (0=cheapest, 1=most expensive)
    is_first_in_class: bool,
    approved_count: int,
) -> float:
    """
    Compute mean utility δ_j for the novel drug.
    Calibrated so an identical-to-SoC drug with premium price has δ≈0 (base utility).
    First-in-class premium reflects unobserved quality shock (KOL endorsement, novelty).
    """
    fic_premium   = 1.2 if is_first_in_class else 0.0
    novelty_decay = max(0, 0.5 - approved_count * 0.05)   # Novelty fades with more approvals
    delta = (
        2.5 * efficacy_vs_soc
        + 1.5 * safety_vs_soc
        + 0.8 * convenience_vs_soc
        - 2.0 * price_rank
        + fic_premium
        + novelty_decay
    )
    return delta


def blp_market_share_simulation(
    therapeutic_area: str,
    approved_treatments_count: int,
    is_first_in_class: bool = False,
    has_biomarker: bool = False,
    efficacy_lift: float = 0.25,      # Assumed efficacy improvement vs SoC
    safety_vs_soc: float = 0.0,       # Safety profile (0 = same as SoC)
    convenience_vs_soc: float = 0.10, # Slightly better convenience assumed
    n_simulated: int = 500,
) -> tuple[float, float, dict]:
    """
    Stage 4: Simplified BLP Monte Carlo (Berry-Levinsohn-Pakes §3.1).

    Simulates n_s heterogeneous patients drawing individual taste shocks v_i^k.
    Each patient i chooses the product maximising their utility:
      u_ij = δ_j + Σₖ σₖ v_i^k x_j^k + ε_ij

    Returns:
      (mean_share, std_share, metadata)
      mean_share = fraction of simulated patients choosing novel drug
    """
    ta   = therapeutic_area.lower()
    sig  = _BLP_SIGMA.get(ta, _BLP_DEFAULT_SIGMA)

    if not _SCIPY_OK:
        # numpy unavailable — analytical BLP approximation using logit market share
        # s_j = exp(δ_j) / (1 + Σ exp(δ_k))  — standard logit (no heterogeneity)
        price_rank  = 0.55 if is_first_in_class else 0.75
        if has_biomarker:
            efficacy_lift = min(efficacy_lift * 1.4, 0.70)
        delta_novel = _mean_utility(efficacy_lift, safety_vs_soc, convenience_vs_soc,
                                    price_rank, is_first_in_class, approved_treatments_count)
        n_comp = min(approved_treatments_count, 6)
        comp_utils = sum(math.exp(-0.3 - 0.3 * i / max(n_comp, 1)) for i in range(n_comp))
        denom = 1.0 + math.exp(delta_novel) + comp_utils   # +1 for outside good
        share = math.exp(delta_novel) / denom
        share = max(0.01, min(0.90, share))
        return share, 0.1, {
            "delta_novel_final": round(delta_novel, 4),
            "mean_share": round(share, 4),
            "std_share": 0.1,
            "target_prior_share": round(share, 3),
            "n_simulated": 0,
            "contraction_mapping": False,
        }

    rng = np.random.default_rng(_RNG_SEED)

    # Relative price rank: novel drug is premium-priced (0.7 = 70th percentile)
    price_rank = 0.55 if is_first_in_class else 0.75

    # Biomarker-selected drugs have clearer efficacy story → higher efficacy lift
    if has_biomarker:
        efficacy_lift = min(efficacy_lift * 1.4, 0.70)

    # Mean utility of novel drug (δ_novel)
    delta_novel = _mean_utility(
        efficacy_vs_soc=efficacy_lift,
        safety_vs_soc=safety_vs_soc,
        convenience_vs_soc=convenience_vs_soc,
        price_rank=price_rank,
        is_first_in_class=is_first_in_class,
        approved_count=approved_treatments_count,
    )

    # Build competitor utility vector
    # Existing drugs: mean utility = 0 (normalized reference), generic price advantage
    n_competitors = min(approved_treatments_count, 6)
    comp_deltas   = []
    for i in range(n_competitors):
        # Each existing drug: progressively more discounted, no novelty premium
        price_adv  = -0.3 * (i / max(n_competitors, 1))   # cheaper
        comp_delta = -0.3 + price_adv    # baseline mild preference for existing drugs
        comp_deltas.append(comp_delta)
    # Outside good (no treatment): utility = 0 if unmet need is high, < 0 if low
    u_outside_mean = -1.5 if approved_treatments_count == 0 else -0.5

    # Monte Carlo: draw n_s patients
    v_efficacy   = rng.standard_normal(n_simulated)
    v_safety     = rng.standard_normal(n_simulated)
    v_price      = rng.standard_normal(n_simulated)
    v_convenience= rng.standard_normal(n_simulated)

    # C-07: draw all Gumbel noise ONCE — fixed across contraction iterations for stationarity
    eps_novel = rng.gumbel(size=n_simulated)
    eps_comps = [rng.gumbel(size=n_simulated) for _ in comp_deltas]
    eps_out   = rng.gumbel(size=n_simulated)

    # Individual utility for novel drug (BLP §3.1):
    # u_i = δ_novel + σ_eff·v_eff·x_eff + σ_safe·v_safe·x_safe + σ_price·v_price·(-x_price) + ε_i
    u_novel = (
        delta_novel
        + sig["efficacy"]     * v_efficacy    * efficacy_lift
        + sig["safety"]       * v_safety      * (safety_vs_soc + 0.5)
        - sig["price"]        * v_price       * price_rank
        + sig["convenience"]  * v_convenience * (convenience_vs_soc + 0.5)
        + eps_novel
    )

    # Build n_s × n_products utility matrix
    all_utils = [u_novel]
    for cd, eps_c in zip(comp_deltas, eps_comps):
        u_comp = (cd
                  + sig["efficacy"]    * v_efficacy   * 0.5
                  - sig["price"]       * v_price      * 0.4
                  + eps_c)
        all_utils.append(u_comp)
    # Outside good
    u_out = u_outside_mean + eps_out
    all_utils.append(u_out)

    # Matrix (n_products × n_simulated) → each patient argmax
    util_matrix  = np.stack(all_utils, axis=0)
    choices      = np.argmax(util_matrix, axis=0)  # shape: (n_simulated,)
    novel_chosen = (choices == 0).astype(float)

    # ── BLP Contraction Mapping (§3.2) ────────────────────────────────────────
    # We calibrate the mean utility δ_novel via a simplified contraction until
    # simulated shares converge to a target "prior share" (our BLP inversion).
    # Target = order-of-entry share heuristic (BLP utility-consistent prior)
    _ENTRY_SHARE_PRIOR = {1: 0.55, 2: 0.38, 3: 0.27, 4: 0.20, 5: 0.15}
    target_share = _ENTRY_SHARE_PRIOR.get(min(approved_treatments_count + 1, 5), 0.12)

    # Contraction mapping: δ^{h+1} = δ^h + ln(S_target) − ln(s_simulated)
    delta_h      = delta_novel
    tolerance    = 1e-4
    max_iter     = 50
    for _ in range(max_iter):
        s_sim = float(np.mean(novel_chosen))
        if abs(s_sim - target_share) < tolerance:  # C-07: removed s_sim<=0 early exit — raises delta to attract patients
            break
        delta_h = delta_h + math.log(max(target_share, 1e-6)) - math.log(max(s_sim, 1e-6))
        # Re-compute utilities with updated δ — C-07: reuse fixed Gumbel noise (eps_novel)
        u_novel_new = (delta_h
                       + sig["efficacy"]    * v_efficacy    * efficacy_lift
                       + sig["safety"]      * v_safety      * (safety_vs_soc + 0.5)
                       - sig["price"]       * v_price       * price_rank
                       + sig["convenience"] * v_convenience * (convenience_vs_soc + 0.5)
                       + eps_novel)
        all_utils[0]  = u_novel_new
        util_matrix   = np.stack(all_utils, axis=0)
        choices       = np.argmax(util_matrix, axis=0)
        novel_chosen  = (choices == 0).astype(float)

    mean_share = float(np.mean(novel_chosen))
    std_share  = float(np.std(novel_chosen))

    return mean_share, std_share, {
        "delta_novel_final":  round(delta_h, 4),
        "mean_share":         round(mean_share, 4),
        "std_share":          round(std_share, 4),
        "target_prior_share": round(target_share, 3),
        "n_simulated":        n_simulated,
        "contraction_mapping": True,
    }


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 5: GROSS-TO-NET + BIA AFFORDABILITY GATE (§6)
# ══════════════════════════════════════════════════════════════════════════════

_GROSS_TO_NET: dict[str, float] = {
    "gene_therapy":    0.88,
    "rare_disease":    0.78,
    "oncology":        0.72,
    "hematology":      0.70,
    "amr_infectious":  0.80,
    "vaccine":         0.82,
    "diagnostic":      0.85,
    "device":          0.75,
    "cns":             0.68,
    "cardiovascular":  0.58,
    "metabolic":       0.55,
    "immunology":      0.60,
    "ophthalmology":   0.70,
    "respiratory":     0.62,
    "other":           0.65,
}

_BIA_PER_PATIENT_THRESHOLD = 300_000
_BIA_TOTAL_BUDGET_THRESHOLD = 500_000_000


def gross_to_net_price(wac_usd: float, therapeutic_area: str,
                        has_orphan: bool = False) -> tuple[float, float]:
    ta  = therapeutic_area.lower()
    pct = _GROSS_TO_NET.get(ta, 0.65)
    if has_orphan:
        pct = min(pct + 0.08, 0.92)
    return wac_usd * pct, pct


def bia_affordability(net_price_per_year: float, eligible_patients: int,
                       therapeutic_area: str, dot_years: float) -> tuple[bool, float, str]:
    annual_cost        = net_price_per_year if dot_years >= 1.0 else net_price_per_year * dot_years
    total_annual_spend = annual_cost * eligible_patients
    concern, dampening, reason = False, 1.0, "Within payer affordability thresholds"

    if annual_cost > _BIA_PER_PATIENT_THRESHOLD:
        concern     = True
        excess      = annual_cost / _BIA_PER_PATIENT_THRESHOLD
        dampening   = max(0.45, 1.0 / (1.0 + math.log(excess)))
        reason      = f"Per-patient cost ${annual_cost:,.0f} > BIA threshold ${_BIA_PER_PATIENT_THRESHOLD:,}"
    elif total_annual_spend > _BIA_TOTAL_BUDGET_THRESHOLD:
        concern     = True
        excess_b    = total_annual_spend / _BIA_TOTAL_BUDGET_THRESHOLD
        dampening   = max(0.55, 1.0 / (1.0 + 0.5 * math.log(excess_b)))
        reason      = f"US annual spend ${total_annual_spend/1e6:.0f}M > BIA budget threshold ${_BIA_TOTAL_BUDGET_THRESHOLD/1e6:.0f}M"

    return concern, dampening, reason


# ══════════════════════════════════════════════════════════════════════════════
# MASTER PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

def compute_market_size(
    *,
    disease_name: str,
    therapeutic_area: str,
    prevalent_patients: int,
    wac_annual_usd: float,
    approved_treatments_count: int = 0,
    modality: str = "drug_small_molecule",
    designations: Optional[list[str]] = None,
    is_first_in_class: bool = False,
    has_biomarker: bool = False,
    development_phase: str = "phase2",
    years_to_peak: float = 5.0,
) -> dict:
    """
    Full five-stage market sizing pipeline.

    Stage 1: DisMod population cascade  →  eligible patients
    Stage 2: Weibull/Gompertz/Poly-Hazard survival  →  Duration of Therapy
    Stage 3: Bass diffusion  →  total addressable penetration
    Stage 3b: UCRCD Lotka-Volterra  →  competitive market share trajectory
    Stage 4: BLP Monte Carlo + Contraction Mapping  →  patient preference share
    Stage 5: Gross-to-Net pricing + BIA gate  →  realizable peak revenue
    """
    designations = [d.lower() for d in (designations or [])]
    has_orphan   = any("orphan" in d for d in designations)
    ta           = therapeutic_area.lower()

    # ── Stage 1: Population Cascade ──────────────────────────────────────────
    eligible, diag_yield, treat_elig, cascade_summary = apply_population_cascade(
        prevalent_patients, ta,
        is_biomarker_selected=has_biomarker,
        is_first_in_class=is_first_in_class,
    )

    # ── Stage 2: Survival-based DoT ──────────────────────────────────────────
    dot, survival_dist = compute_dot_survival(ta, modality)
    dot_capped = min(dot, 25.0)

    # ── Stage 3: Bass diffusion (total market adoption) ───────────────────────
    p, q    = _BASS_PARAMS.get(ta, (0.020, 0.250))
    if is_first_in_class:
        p *= 1.30
    bass_total_y5 = bass_cumulative(years_to_peak, p, q)
    t_peak_bass   = bass_peak_time(p, q)

    # ── Stage 3b: UCRCD competitive dynamics ──────────────────────────────────
    ucrcd_share, t_peak_ucrcd, ucrcd_meta = ucrcd_penetration(
        ta, approved_treatments_count, is_first_in_class, years=years_to_peak
    )

    # ── Stage 4: BLP market share simulation ─────────────────────────────────
    blp_share, blp_std, blp_meta = blp_market_share_simulation(
        ta,
        approved_treatments_count=approved_treatments_count,
        is_first_in_class=is_first_in_class,
        has_biomarker=has_biomarker,
    )

    # Synthesise penetration: weighted geometric mean of UCRCD + BLP
    # UCRCD captures time dynamics; BLP captures patient heterogeneity.
    # Clamp both to [0,1] — UCRCD ODE can return small negative values near t=0
    ucrcd_share = max(0.0, min(1.0, ucrcd_share))
    blp_share   = max(0.0, min(1.0, blp_share))
    # Geometric mean requires positive base; floor at 0.001 to avoid 0^0.6 = 0
    combined_penetration = (max(ucrcd_share, 0.001) ** 0.60) * (max(blp_share, 0.001) ** 0.40)

    # ── Stage 5: Pricing + BIA ────────────────────────────────────────────────
    net_price, gtn_pct = gross_to_net_price(wac_annual_usd, ta, has_orphan)

    # Revenue per patient (annualised)
    # BUG-27: `dot >= 15.0` could flip chronic metabolic/CNS therapies into one-time revenue model
    # when Weibull lam drifts marginally above 15. One-time dosing is only valid for gene/cell.
    _one_time_modalities = {"gene_cell_therapy", "gene_therapy", "cell_therapy"}
    is_one_time = modality.lower() in _one_time_modalities
    # C-06: diagnostic DoT (~0.02yr) must NOT discount the per-test price — price is per test, not per year
    _is_diag = modality.lower().startswith("diagnostic")
    if is_one_time:
        annual_cohort      = max(1, eligible / max(1.0, dot))
        annual_per_patient = net_price
        us_tam_usd         = annual_cohort * annual_per_patient
    elif dot < 1.0 and not _is_diag:
        annual_per_patient = net_price * dot
        us_tam_usd         = eligible * annual_per_patient
    else:
        annual_per_patient = net_price
        us_tam_usd         = eligible * annual_per_patient

    peak_revenue_raw = us_tam_usd * combined_penetration

    bia_flag, dampening, bia_reason = bia_affordability(
        net_price, eligible, ta, dot
    )
    peak_revenue_usd = peak_revenue_raw * dampening

    # ── Pricing rationale ─────────────────────────────────────────────────────
    pricing_rationale = (
        f"Net price ${net_price:,.0f} ({gtn_pct:.0%} of WAC, {ta}); "
        f"DoT {dot:.1f}yr ({survival_dist}); "
        f"Penetration Y{years_to_peak:.0f}: UCRCD {ucrcd_share:.1%} × BLP {blp_share:.1%} "
        f"→ combined {combined_penetration:.1%}; "
        f"Eligible {eligible:,} ({diag_yield:.0%} diag × {treat_elig:.0%} eligible)"
    )
    if bia_flag:
        pricing_rationale += f"; ⚠ BIA: {bia_reason}"

    return {
        "us_tam_usd":        round(us_tam_usd),
        "peak_revenue_usd":  round(peak_revenue_usd),
        "formula":           "market_sizing_engine_v3",
        "pricing_rationale": pricing_rationale,
        "cascade": {
            "prevalent_patients": prevalent_patients,
            "diagnosed":          int(prevalent_patients * diag_yield),
            "eligible":           eligible,
            "diagnostic_yield":   round(diag_yield, 3),
            "treatment_eligible": round(treat_elig, 3),
            "summary":            cascade_summary,
        },
        "dot": {
            "years":        round(dot, 2),
            "distribution": survival_dist,
            "category":     "acute" if dot < 1 else "chronic" if dot < 5 else "lifelong",
            "is_one_time":  is_one_time,
        },
        "bass": {
            "p": round(p, 4), "q": round(q, 4),
            "total_market_penetration_y5": round(bass_total_y5, 3),
            "capturable_y5": round(combined_penetration, 3),   # alias for scorer compatibility
            "peak_adoption_year": round(t_peak_bass, 1),
        },
        "ucrcd": ucrcd_meta,
        "blp":   blp_meta,
        "combined_penetration": round(combined_penetration, 4),
        "pricing": {
            "wac_annual_usd":     round(wac_annual_usd),
            "net_annual_usd":     round(net_price),
            "gross_to_net_pct":   round(gtn_pct, 3),
            "has_orphan_premium": has_orphan,
        },
        "bia": {
            "affordability_concern": bia_flag,
            "revenue_dampening":     round(dampening, 3),
            "reason":                bia_reason,
        },
        "us_tam_fmt":        _fmt(us_tam_usd),
        "peak_revenue_fmt":  _fmt(peak_revenue_usd),
        "peak_penetration":  round(combined_penetration, 3),
    }


def _fmt(usd: float) -> str:
    if usd >= 1e9:  return f"${usd / 1e9:.1f}B"
    if usd >= 1e6:  return f"${usd / 1e6:.0f}M"
    return f"${usd / 1e3:.0f}K"


# ── Initial-vs-eventual indication resolver (Build Spec v3, Part 2) ───────────

_DISEASE_INITIAL_FRACTIONS: dict[str, dict] = {
    # disease keyword → {fraction, expansion_years, rationale}
    "acute ischemic stroke": {
        "fraction": 0.20, "expansion_years": 4,
        "rationale": "IV-tPA and thrombectomy-eligible patients are ~20% of total stroke incidence at launch (time-window + hospital-access constraints). Label expands as evidence grows.",
        "basis": "disease_specific",
        "source": "AHA/ASA stroke guidelines; Albers et al. NEJM 2018 thrombectomy trial enrollment criteria",
    },
    "ischemic stroke": {
        "fraction": 0.22, "expansion_years": 4,
        "rationale": "Initial indication typically restricted to LVO or tPA-eligible subset.",
        "basis": "disease_specific",
        "source": "AHA/ASA 2019 guidelines; NovaSys stroke market model",
    },
    "alzheimer": {
        "fraction": 0.10, "expansion_years": 6,
        "rationale": "MCI/early-AD diagnostic criteria restrict initial label; biomarker confirmation required (amyloid PET or CSF). Broad population unlocks over multiple label expansions.",
        "basis": "disease_specific",
        "source": "FDA Lecanemab approval 2023; Aducanumab label history",
    },
    "nsclc": {
        "fraction": 0.15, "expansion_years": 3,
        "rationale": "First approval typically in 2L+ or biomarker-defined subset; 1L frontline follows.",
        "basis": "disease_specific",
        "source": "FDA approval history for PD-L1 checkpoint inhibitors",
    },
    "breast cancer": {
        "fraction": 0.12, "expansion_years": 3,
        "rationale": "HER2+ or BRCA-defined subpopulation at launch; broader HER2-low expansion follows.",
        "basis": "disease_specific",
        "source": "DESTINY-Breast04; FDA T-DXd label 2022",
    },
    "multiple sclerosis": {
        "fraction": 0.18, "expansion_years": 4,
        "rationale": "RRMS (relapsing) typically first; PPMS/SPMS label expansions follow.",
        "basis": "disease_specific",
        "source": "Ocrelizumab PPMS label expansion 2017; MSIF epidemiology",
    },
    "rheumatoid arthritis": {
        "fraction": 0.25, "expansion_years": 3,
        "rationale": "MTX-inadequate responders (2L) often first; 1L biologic naive follows.",
        "basis": "disease_specific",
        "source": "ACR 2021 RA guidelines; Rinvoq label history",
    },
    "atrial fibrillation": {
        "fraction": 0.30, "expansion_years": 3,
        "rationale": "Non-valvular AF is the standard initial label; valvular and device-related AF follows.",
        "basis": "disease_specific",
        "source": "ESC 2020 AF guidelines; CMS NVAF claims data",
    },
    "heart failure": {
        "fraction": 0.35, "expansion_years": 3,
        "rationale": "HFrEF (reduced ejection fraction) typically approved first; HFpEF expansion follows.",
        "basis": "disease_specific",
        "source": "ACC/AHA 2022 HF guidelines; EMPEROR-Preserved trial",
    },
    "type 2 diabetes": {
        "fraction": 0.40, "expansion_years": 2,
        "rationale": "Add-on to metformin or standalone after metformin failure is the initial label; obesity co-indication broadens market.",
        "basis": "disease_specific",
        "source": "ADA 2023 standards; Ozempic/Wegovy label chronology",
    },
    "crohn": {
        "fraction": 0.30, "expansion_years": 3,
        "rationale": "Moderate-severe CD with inadequate response to conventional therapy.",
        "basis": "disease_specific",
        "source": "ACG 2021 CD guidelines; GEMINI trial populations",
    },
}

_TA_DEFAULT_FRACTIONS: dict[str, float] = {
    "oncology":       0.15,   # FDA oncology: median initial approval is ~15% of total indication
    "immunology":     0.25,
    "cardiovascular": 0.30,
    "metabolic":      0.35,
    "cns":            0.15,
    "rare_disease":   0.50,   # orphan indications often capture most of the population at once
    "gene_therapy":   0.45,
    "neurology_cns":  0.15,
    "amr_infectious": 0.30,
    "infectious":     0.30,
}

_TA_SPECIALIST_MAP: dict[str, str] = {
    "oncology":       "Medical oncologist / tumor board",
    "immunology":     "Rheumatologist / dermatologist / gastroenterologist",
    "cardiovascular": "Cardiologist / electrophysiologist",
    "metabolic":      "Endocrinologist / primary care physician",
    "cns":            "Neurologist / psychiatrist",
    "neurology_cns":  "Neurologist (stroke / MS / dementia specialist)",
    "rare_disease":   "Metabolic disease specialist / geneticist",
    "gene_therapy":   "Gene therapy centre / haematologist",
    "amr_infectious": "Infectious disease specialist / hospital pharmacist",
    "infectious":     "Infectious disease specialist",
    "ibd":            "Gastroenterologist",
    "hematology":     "Haematologist / BMT specialist",
    "respiratory":    "Pulmonologist / allergist",
    "digital_health": "Chief Medical Information Officer / department head",
}


def specialist_for_ta(ta: str) -> str:
    """Return the prescribing specialist type for a therapeutic area."""
    ta_low = ta.lower()
    for key, specialist in _TA_SPECIALIST_MAP.items():
        if key in ta_low or ta_low in key:
            return specialist
    return "Relevant clinical specialist (consult KOL list)"


def resolve_initial_indication(disease_name: str, therapeutic_area: str) -> dict:
    """
    Return the initial-vs-eventual fraction for a disease at first launch.

    A therapy rarely captures its full addressable market on day one — it launches
    in a narrow sub-indication (a biomarker-defined subgroup, a disease severity tier,
    or a specific treatment line) and expands over subsequent label amendments.

    Returns a dict with keys: fraction, rationale, expansion_years, source, basis
      basis: "disease_specific" | "ta_default" | "global_default"
    """
    name_low = disease_name.lower()

    # Disease-specific lookup
    for disease_key, entry in _DISEASE_INITIAL_FRACTIONS.items():
        if disease_key in name_low or name_low in disease_key:
            return {
                "fraction":        entry["fraction"],
                "rationale":       entry["rationale"],
                "expansion_years": entry["expansion_years"],
                "source":          entry["source"],
                "basis":           entry["basis"],
            }

    # TA-level default
    ta_low = therapeutic_area.lower()
    for ta_key, fraction in _TA_DEFAULT_FRACTIONS.items():
        if ta_key in ta_low or ta_low.startswith(ta_key[:4]):
            return {
                "fraction":        fraction,
                "rationale":       (
                    f"TA default for {therapeutic_area}: first approval typically covers "
                    f"{fraction:.0%} of the eventual addressable indication. "
                    "Disease-specific label criteria narrow the initial patient count; "
                    "label expansions unlock the remaining population over time."
                ),
                "expansion_years": 3,
                "source":          f"FDA median initial approval fraction for {therapeutic_area} (internal calibration)",
                "basis":           "ta_default",
            }

    # Global fallback
    return {
        "fraction":        0.30,
        "rationale":       (
            "No disease- or TA-specific initial indication fraction found. "
            "Global default of 30% applied — this is conservative and should be "
            "validated with a KOL familiar with the indication's approval landscape."
        ),
        "expansion_years": 3,
        "source":          "Global default — REVIEW with clinical KOL before citing",
        "basis":           "global_default",
    }


def segment_initial_indication(segment: dict, approved_population: int) -> dict | None:
    """
    Compute a product-specific launch fraction from a segment funnel definition.

    Uses the first 'absolute' gate in the segment funnel as the base population,
    then expresses approved_population as a fraction of that base.

    Returns None if no absolute gate exists or approved_population <= 0.
    """
    if not approved_population or approved_population <= 0:
        return None

    funnel = segment.get("funnel", [])
    base_pop = None
    for gate in funnel:
        if gate.get("type") == "absolute":
            base_pop = gate.get("value")
            break

    if not base_pop or base_pop <= 0:
        return None

    fraction = approved_population / base_pop
    return {
        "fraction":    round(fraction, 4),
        "basis":       "product_segment",
        "base_pop":    base_pop,
        "approved_pop": approved_population,
        "segment_name": segment.get("segment_name", ""),
        "rationale":   (
            f"Product-specific launch population ({approved_population:,}) as fraction of "
            f"disease base ({base_pop:,}) from segment funnel '{segment.get('segment_name', '')}'. "
            "This is more precise than a disease-level constant."
        ),
        "source": "Segment funnel derivation",
    }


def apply_model_launch_indication(ive: dict, model_output: dict | None) -> dict:
    """
    Patch an initial-vs-eventual (IVE) dict with the model's own launch indication.

    When the LLM identifies a specific launch population fraction (e.g., 2L+ KRAS-G12C
    NSCLC = 5% of all NSCLC), this overrides the disease-prior and becomes the driver.

    Cross-checks: if the model fraction diverges > 50% from the prior, sets
    prior_divergence_flag = True so the report flags the discrepancy for review.

    Returns ive unchanged if applicable=False or model_output is invalid.
    """
    if not ive.get("applicable", True):
        return ive

    if not model_output or not isinstance(model_output, dict):
        return ive

    raw = model_output.get("fraction_of_disease")
    try:
        frac = float(raw)
    except (TypeError, ValueError):
        return ive

    if not (0 < frac < 1.0):
        return ive

    eventual_tam = ive.get("eventual_market", {}).get("tam_usd", 0)
    if not eventual_tam or eventual_tam <= 0:  # H-12: no valid eventual TAM — skip to avoid $0 override
        return ive
    prior_fraction = ive.get("initial_market", {}).get("fraction_of_eventual", None)

    ive = dict(ive)
    ive["initial_market"] = dict(ive.get("initial_market", {}))
    ive["initial_market"]["fraction_of_eventual"] = frac
    ive["initial_market"]["basis"] = "model"
    ive["initial_market"]["tam_usd"] = round(eventual_tam * frac)
    if model_output.get("population"):
        ive["initial_market"]["population"] = model_output["population"]
    ive["driver"] = "model"

    if model_output.get("verify_with"):
        ive["verify_with"] = model_output["verify_with"]

    # Cross-check against prior
    if prior_fraction and prior_fraction > 0:
        divergence = abs(frac - prior_fraction) / prior_fraction
        ive["prior_cross_check"] = {"fraction": prior_fraction, "divergence": round(divergence, 3)}
        if divergence > 0.50:
            ive["prior_divergence_flag"] = True

    return ive
