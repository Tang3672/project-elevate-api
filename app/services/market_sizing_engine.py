"""
Market Sizing Engine v2 — Five-Stage Pipeline
==============================================
Implements the frameworks from the Advanced Mathematical Frameworks for Medical
Product Market Sizing and Epidemiological Forecasting document:

  Stage 1  DisMod-inspired Population Cascade
           Prevalent patients → diagnosed → treatment-eligible
           (Barendregt et al.; ISPOR/Mauskopf BIA §6.1)

  Stage 2  Weibull-Parameterized Duration of Therapy (DoT)
           Integrates area under parametric survival curve per patient
           (NICE TSD 14; Poly-Hazard formulation §5.1)

  Stage 3  Bass Diffusion Model for Market Penetration
           F(t) = (1-e^{-(p+q)t}) / (1 + (q/p)e^{-(p+q)t})  §4.1
           t_peak = ln(q/p)/(p+q)
           p, q calibrated by TA from pharmaceutical diffusion literature

  Stage 4  Gross-to-Net Pricing Adjustment
           WAC × (1 − rebate%) = net realized price per patient
           Rebate benchmarks from CMS Medicare Part D / NADAC data §6.2

  Stage 5  BIA Affordability Gate (ISPOR/Mauskopf §6)
           Net annual spend per eligible patient × total eligible:
           if > US payer affordability threshold → flag + dampen revenue

Together these produce a TAM (theoretical ceiling) and a Year-5 Peak Revenue
estimate grounded in commercial realities that the simple penetration formula misses.

The engine operates as a SUPPLEMENT to tam_calculator.py:
  • Diseases with curated parameters in tam_parameters.json keep their expert TAM.
  • The engine enriches all results with Bass/DoT/BIA metadata.
  • For unlisted diseases the engine becomes the primary TAM computation.
"""

from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 1: POPULATION CASCADE (DisMod / ISPOR)
# ══════════════════════════════════════════════════════════════════════════════

# Diagnostic yield: fraction of prevalent patients actively diagnosed.
# Source: published epidemiology; GBD Disease Burden studies; NCI SEER coverage.
_DIAGNOSTIC_YIELD: dict[str, float] = {
    "oncology":        0.85,   # Cancer registry capture; symptomatic presentation
    "hematology":      0.88,   # Blood malignancies: high diagnostic rate
    "rare_disease":    0.38,   # Long diagnostic odyssey; often <50% (NORD surveys)
    "gene_therapy":    0.35,   # Mostly overlaps rare_disease
    "cns":             0.58,   # Neurodegen: estimated ~40% of AD undiagnosed (Alzheimer Assoc 2023)
    "cardiovascular":  0.78,   # Routine ECG / echo screening
    "metabolic":       0.82,   # HbA1c screening programs; obesity BMI-defined
    "amr_infectious":  0.52,   # Many treated empirically without confirmed culture
    "immunology":      0.68,   # Autoimmune: moderate referral rates
    "ophthalmology":   0.72,   # Ophthalmology exam-dependent
    "vaccine":         0.90,   # Population-based; high identification
    "device":          0.88,   # Hospital-based diagnosis
    "diagnostic":      0.90,
    "respiratory":     0.68,   # COPD notoriously underdiagnosed (~50% by spirometry)
    "other":           0.62,
}

# Treatment eligibility: fraction of diagnosed patients who meet criteria for
# a novel (non-generic first-line) therapy.
# Captures biomarker gating, prior therapy requirements, line-of-therapy rules.
_TREATMENT_ELIGIBLE: dict[str, float] = {
    "oncology":        0.38,   # Biomarker selection + prior-therapy requirement
    "hematology":      0.55,   # Broader eligibility; BTK/BCL2 targets large fractions
    "rare_disease":    0.88,   # Genetic confirmation suffices; few alternatives
    "gene_therapy":    0.92,   # High eligibility: often only option
    "cns":             0.52,   # AD: amyloid-positive + functional impairment criteria
    "cardiovascular":  0.40,   # Guideline-directed therapy exhaustion required
    "metabolic":       0.28,   # GLP-1/insulin first; novel only in refractory
    "amr_infectious":  0.72,   # Resistant organisms: broad eligibility
    "immunology":      0.32,   # Biologic/JAK failure required before novel agents
    "ophthalmology":   0.65,
    "vaccine":         0.85,   # Population-based immunisation programs
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
    """
    Stage 1: DisMod-inspired population cascade.

    Returns:
      (eligible_patients, diagnostic_yield, treatment_eligible_pct, cascade_summary)
    """
    ta = therapeutic_area.lower()
    diag_yield = _DIAGNOSTIC_YIELD.get(ta, 0.62)
    treat_elig  = _TREATMENT_ELIGIBLE.get(ta, 0.52)

    # Biomarker selection narrows eligibility but improves LOA; net effect on TAM
    # depends on whether biomarker defines indication (smaller pop) or enrichment.
    # Conservative: biomarker narrows eligibility to the responsive fraction.
    if is_biomarker_selected and ta not in ("rare_disease", "gene_therapy"):
        treat_elig *= 0.65   # Biomarker-selected subset is typically ~35-65% of diagnosed

    # First-in-class: no prior-therapy gating; broader eligibility
    if is_first_in_class:
        treat_elig = min(treat_elig * 1.25, 0.95)

    diagnosed = int(prevalent_patients * diag_yield)
    eligible  = int(diagnosed * treat_elig)

    summary = (
        f"Prevalence {prevalent_patients:,} → "
        f"Diagnosed {diagnosed:,} ({diag_yield:.0%} yield) → "
        f"Treatment-eligible {eligible:,} ({treat_elig:.0%})"
    )
    return eligible, diag_yield, treat_elig, summary


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 2: DURATION OF THERAPY (Weibull-parameterized, NICE TSD 14)
# ══════════════════════════════════════════════════════════════════════════════
# DoT (years) = E[T | Weibull(k, λ)] = λ·Γ(1 + 1/k)
# We supply pre-solved TA × modality medians anchored to clinical precedents.
# For oncology the Weibull mean aligns with Phase-III PFS medians.

_DOT_YEARS: dict[str, float] = {
    # (therapeutic_area, modality) → years
    # Gene/cell therapy: single administration, lifetime benefit
    ("gene_therapy",    "gene_cell_therapy"):   20.0,
    ("rare_disease",    "gene_cell_therapy"):   18.0,
    # Curative antibiotics: short course
    ("amr_infectious",  "drug_small_molecule"):  0.038,  # 14 days
    ("amr_infectious",  "biologic"):             0.055,  # 20-day IV course
    # Vaccines: booster intervals
    ("vaccine",         "vaccine_immunotherapy"): 4.0,
    # Oncology: Weibull(k=1.5, median PFS ~18mo) → mean ~22mo
    ("oncology",        "drug_small_molecule"):  1.8,
    ("oncology",        "biologic"):             2.4,
    ("oncology",        "gene_cell_therapy"):    4.0,   # CAR-T durable remissions
    # Hematology: longer PFS with biologics
    ("hematology",      "drug_small_molecule"):  2.5,
    ("hematology",      "biologic"):             3.5,
    # Chronic CNS / neurodegenerative
    ("cns",             "drug_small_molecule"):  7.0,
    ("cns",             "biologic"):             6.0,
    # Cardiovascular chronic maintenance
    ("cardiovascular",  "drug_small_molecule"): 10.0,
    ("cardiovascular",  "device"):              10.0,
    # Metabolic: lifelong management
    ("metabolic",       "drug_small_molecule"): 10.0,
    ("metabolic",       "biologic"):             8.0,
    # Immunology: chronic with possible remission
    ("immunology",      "drug_small_molecule"):  5.0,
    ("immunology",      "biologic"):             6.5,
    # Ophthalmology: chronic injections or device
    ("ophthalmology",   "biologic"):             9.0,
    ("ophthalmology",   "medical_device"):       8.0,
    # Rare disease drugs (non-gene therapy)
    ("rare_disease",    "drug_small_molecule"): 12.0,
    ("rare_disease",    "biologic"):            10.0,
    # Respiratory
    ("respiratory",     "drug_small_molecule"):  7.0,
    ("respiratory",     "biologic"):             6.0,
    # Devices / diagnostics
    ("device",          "medical_device"):       9.0,
    ("device",          "digital_health"):       5.0,
    ("diagnostic",      "diagnostic"):           0.02,   # single test
}

_TA_DOT_DEFAULTS: dict[str, float] = {
    "oncology": 2.0, "hematology": 3.0, "rare_disease": 11.0,
    "gene_therapy": 18.0, "cns": 7.0, "cardiovascular": 9.0,
    "metabolic": 9.0, "amr_infectious": 0.04, "immunology": 6.0,
    "vaccine": 4.0, "ophthalmology": 8.0, "device": 8.0,
    "diagnostic": 0.02, "respiratory": 6.5, "other": 5.0,
}


def compute_dot(therapeutic_area: str, modality: str = "drug_small_molecule") -> float:
    """
    Stage 2: Weibull-based Duration of Therapy in years.
    Returns expected years on therapy per patient.
    """
    key = (therapeutic_area.lower(), modality.lower())
    if key in _DOT_YEARS:
        return _DOT_YEARS[key]
    # Fallback: TA-level default
    return _TA_DOT_DEFAULTS.get(therapeutic_area.lower(), 5.0)


def dot_revenue_multiplier(dot_years: float, annual_cost: float) -> float:
    """
    Total revenue per patient = annual_cost × DoT.
    Discounted at standard pharma WACC of 10% using annuity formula.
    PV = annual_cost × (1 - (1+r)^-n) / r
    """
    r = 0.10
    n = dot_years
    if n <= 0:
        return annual_cost * 0.02   # < 1 month: just the course cost
    if r == 0 or n > 40:
        return annual_cost * min(n, 30)
    pv = annual_cost * (1 - (1 + r) ** -n) / r
    return pv


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 3: BASS DIFFUSION MODEL  §4.1
# F(t) = (1 − e^{−(p+q)t}) / (1 + (q/p)e^{−(p+q)t})
# ══════════════════════════════════════════════════════════════════════════════

# Pharmaceutical Bass parameters calibrated from published diffusion studies.
# Guseo & Guidolin (Ann. Appl. Stat. 2015); Infosys Life Sciences pharma review.
# p = innovation coefficient (KOL-driven early adoption)
# q = imitation coefficient (word-of-mouth / guideline uptake)
_BASS_PARAMS: dict[str, tuple[float, float]] = {
    # (p, q) — typical ranges from pharma diffusion literature
    "oncology":        (0.030, 0.350),  # Aggressive KOL/trial-driven adoption
    "hematology":      (0.025, 0.380),  # Hemato-oncology specialist adoption
    "rare_disease":    (0.018, 0.150),  # Small KOL community; slow but sticky
    "gene_therapy":    (0.015, 0.120),  # Novel modality; reimbursement delays
    "cns":             (0.020, 0.220),  # Neurologists conservative prescribers
    "cardiovascular":  (0.015, 0.280),  # Cardiology guidelines-driven
    "metabolic":       (0.028, 0.400),  # DTC + primary care; fast imitation
    "amr_infectious":  (0.010, 0.080),  # Stewardship constrains adoption
    "immunology":      (0.022, 0.320),  # Rheum/derm biologics well-established path
    "vaccine":         (0.020, 0.300),  # Population campaigns
    "ophthalmology":   (0.018, 0.250),  # Retina specialist-driven
    "device":          (0.012, 0.200),  # Capital purchase; procurement cycles
    "diagnostic":      (0.025, 0.350),  # Lab adoption relatively fast
    "respiratory":     (0.018, 0.260),
    "other":           (0.020, 0.250),
}


def bass_cumulative(t: float, p: float, q: float) -> float:
    """
    Bass Model: F(t) = cumulative fraction of addressable market adopted at time t.
    Returns value in [0, 1].
    """
    if p + q <= 0 or t <= 0:
        return 0.0
    exp_t = math.exp(-(p + q) * t)
    return (1.0 - exp_t) / (1.0 + (q / p) * exp_t)


def bass_peak_time(p: float, q: float) -> float:
    """t_peak = ln(q/p) / (p+q) — time of maximum adoption rate."""
    if p <= 0 or q <= 0:
        return 5.0
    return math.log(q / p) / (p + q)


def compute_bass_penetration(
    therapeutic_area: str,
    years: float = 5.0,
    is_first_in_class: bool = False,
    order_of_entry: int = 1,
) -> tuple[float, float, dict]:
    """
    Stage 3: Bass Model penetration at `years` post-launch.

    Order-of-entry adjustment: late entrants capture a share of the remaining
    unpenetrated market (not the full Bass F(t)).  Approximates BLP market
    share fragmentation without the full random-coefficients model.

    Returns:
      (penetration_fraction, peak_time_years, metadata)
    """
    ta = therapeutic_area.lower()
    p, q = _BASS_PARAMS.get(ta, (0.020, 0.250))

    # First-in-class education effect: higher innovation coefficient
    if is_first_in_class:
        p *= 1.30

    total_penetration = bass_cumulative(years, p, q)
    t_peak = bass_peak_time(p, q)

    # Order-of-entry share fraction: BLP-inspired fragment
    # 1st: captures full market; 2nd: ~60%; 3rd: ~45%; 4th+: diminishing
    _ENTRY_SHARE = {1: 1.0, 2: 0.60, 3: 0.45, 4: 0.33, 5: 0.25}
    entry_share = _ENTRY_SHARE.get(min(order_of_entry, 5), 0.20)

    capturable = total_penetration * entry_share

    return capturable, t_peak, {
        "bass_p": round(p, 4), "bass_q": round(q, 4),
        "total_market_penetration_y5": round(total_penetration, 3),
        "entry_share": round(entry_share, 2),
        "capturable_y5": round(capturable, 3),
        "peak_adoption_year": round(t_peak, 1),
    }


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 4: GROSS-TO-NET PRICING  §6.2
# ══════════════════════════════════════════════════════════════════════════════
# Source: CMS Medicare Part D Drug Spending Dashboard; NADAC; IQVIA net pricing.
# Net price = WAC × (1 − rebate_rate) × (1 − copay/coinsurance_adjustment)

_GROSS_TO_NET: dict[str, float] = {
    # Fraction of WAC retained as net realized price
    "gene_therapy":    0.88,   # One-time; outcomes-based; minimal rebate
    "rare_disease":    0.78,   # Orphan pricing; limited payer negotiation
    "oncology":        0.72,   # High unmet need; branded premium maintained
    "hematology":      0.70,
    "amr_infectious":  0.80,   # QIDP exclusivity; antimicrobial stewardship exceptions
    "vaccine":         0.82,   # Government VFC + commercial blend
    "diagnostic":      0.85,
    "device":          0.75,
    "cns":             0.68,   # CNS drugs face significant rebate pressure
    "cardiovascular":  0.58,   # Large formulary; high rebate competition
    "metabolic":       0.55,   # GLP-1/insulin benchmark rebates 45-50%
    "immunology":      0.60,   # Biologic class competition = high rebates
    "ophthalmology":   0.70,
    "respiratory":     0.62,
    "other":           0.65,
}


def gross_to_net_price(wac_usd: float, therapeutic_area: str,
                        has_orphan: bool = False) -> tuple[float, float]:
    """
    Stage 4: Convert WAC to net realized price.
    Returns (net_price_usd, net_pct_of_wac).
    """
    ta  = therapeutic_area.lower()
    pct = _GROSS_TO_NET.get(ta, 0.65)
    if has_orphan:
        pct = min(pct + 0.08, 0.92)   # Orphan designation → less rebate leverage
    net = wac_usd * pct
    return net, pct


# ══════════════════════════════════════════════════════════════════════════════
# STAGE 5: BIA AFFORDABILITY GATE (ISPOR/Mauskopf §6)
# ══════════════════════════════════════════════════════════════════════════════
# ICER US cost-effectiveness threshold: $150,000/QALY
# BIA absolute budget threshold: ~$500M annual national spend signals access risk
# (typical US payer concern threshold; Mauskopf 2012 BIA good-practice report)

_BIA_ANNUAL_PER_PATIENT_THRESHOLD = 300_000   # USD — triggers access concern flag
_BIA_TOTAL_BUDGET_THRESHOLD       = 500_000_000  # $500M total US annual spend


def bia_affordability(
    net_price_per_year: float,
    eligible_patients: int,
    therapeutic_area: str,
    dot_years: float,
) -> tuple[bool, float, str]:
    """
    Stage 5: ISPOR/Mauskopf BIA affordability check.

    Returns:
      (affordability_concern: bool, revenue_dampening: float, reason: str)
      revenue_dampening: multiplier applied to peak revenue (1.0 = no dampening)
    """
    # Annual net cost per patient (acute: cost per course, not per year)
    annual_cost = net_price_per_year if dot_years >= 1.0 else net_price_per_year * dot_years

    total_annual_spend = annual_cost * eligible_patients

    concern = False
    dampening = 1.0
    reason = "Within payer affordability thresholds"

    if annual_cost > _BIA_ANNUAL_PER_PATIENT_THRESHOLD:
        concern = True
        # Per-patient excess: how much above threshold
        excess_ratio = annual_cost / _BIA_ANNUAL_PER_PATIENT_THRESHOLD
        # Dampen revenue: diminishing returns above threshold
        # Formula: dampening = 1 / (1 + ln(excess_ratio)) — logarithmic dampening
        dampening = max(0.45, 1.0 / (1.0 + math.log(excess_ratio)))
        reason = (
            f"Per-patient annual cost ${annual_cost:,.0f} "
            f"exceeds ICER affordability threshold ${_BIA_ANNUAL_PER_PATIENT_THRESHOLD:,}; "
            f"payer access expected to be restricted"
        )

    if total_annual_spend > _BIA_TOTAL_BUDGET_THRESHOLD and not concern:
        concern = True
        excess_b = total_annual_spend / _BIA_TOTAL_BUDGET_THRESHOLD
        dampening = max(0.55, 1.0 / (1.0 + 0.5 * math.log(excess_b)))
        reason = (
            f"Total US annual spend ${total_annual_spend / 1e6:.0f}M "
            f"exceeds BIA budget threshold ${_BIA_TOTAL_BUDGET_THRESHOLD / 1e6:.0f}M; "
            f"step edits / PA likely to limit market access"
        )

    return concern, dampening, reason


# ══════════════════════════════════════════════════════════════════════════════
# UNIFIED ENGINE
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

    Returns a dict compatible with the existing TAM calculator output, plus
    rich metadata from each stage for display/debugging.
    """
    designations = [d.lower() for d in (designations or [])]
    has_orphan = any("orphan" in d for d in designations)
    ta = therapeutic_area.lower()

    # Infer order of entry from approved count (proxy for competitive position)
    order_of_entry = max(1, approved_treatments_count + 1)

    # ── Stage 1: Population Cascade ──────────────────────────────────────────
    eligible, diag_yield, treat_elig, cascade_summary = apply_population_cascade(
        prevalent_patients, ta,
        is_biomarker_selected=has_biomarker,
        is_first_in_class=is_first_in_class,
    )

    # ── Stage 2: Duration of Therapy ─────────────────────────────────────────
    dot = compute_dot(ta, modality)
    dot_multiplier = min(dot, 25.0)   # cap at 25yr for scoring (gene therapy ceiling)

    # ── Stage 3: Bass Diffusion ───────────────────────────────────────────────
    penetration_y5, t_peak, bass_meta = compute_bass_penetration(
        ta, years=years_to_peak,
        is_first_in_class=is_first_in_class,
        order_of_entry=order_of_entry,
    )

    # ── Stage 4: Gross-to-Net ─────────────────────────────────────────────────
    net_price, gtn_pct = gross_to_net_price(wac_annual_usd, ta, has_orphan)

    # ── Revenue calculation ───────────────────────────────────────────────────
    # Three cases mirror real-world pharmaceutical revenue economics:
    #
    #  Gene/cell therapy (one-time):
    #    Revenue = annual new eligible cohort × one-time net price
    #    Annual cohort ≈ eligible_prevalent / DoT  (steady-state incidence proxy)
    #    This correctly sizes the *flow* market, not the *stock* market.
    #
    #  Acute (DoT < 1yr, e.g. AMR antibiotics):
    #    Revenue per patient-episode = net_price × DoT
    #    TAM = annual episodes × per-episode revenue
    #
    #  Chronic (DoT ≥ 1yr):
    #    TAM = eligible patients × annual net price

    if modality.lower() in ("gene_cell_therapy",) or dot >= 15.0:
        # One-time treatment: size by annual new eligible patients
        # Steady-state: new patients per year ≈ prevalent / avg DoT years
        annual_cohort = max(1, eligible / max(1.0, dot))
        annual_per_patient = net_price
        us_tam_usd = annual_cohort * annual_per_patient
    elif dot < 1.0:
        # Acute/episodic: per-episode cost
        annual_per_patient = net_price * dot
        us_tam_usd = eligible * annual_per_patient
    else:
        # Chronic maintenance: annual revenue stream
        annual_per_patient = net_price
        us_tam_usd = eligible * annual_per_patient

    # Year-5 peak revenue = TAM × Bass penetration (capturable share)
    peak_revenue_raw = us_tam_usd * penetration_y5

    # ── Stage 5: BIA Affordability ────────────────────────────────────────────
    bia_flag, dampening, bia_reason = bia_affordability(
        net_price, eligible, ta, dot
    )
    peak_revenue_usd = peak_revenue_raw * dampening

    # ── Pricing rationale string ──────────────────────────────────────────────
    net_fmt = f"${net_price:,.0f}"
    gtn_fmt = f"{gtn_pct:.0%} of WAC"
    dot_fmt = f"{dot:.1f} yr" if dot >= 1 else f"{dot * 365:.0f}-day course"
    pricing_rationale = (
        f"Net price {net_fmt} ({gtn_fmt}); "
        f"DoT {dot_fmt}; "
        f"Bass Y5 penetration {penetration_y5:.1%}; "
        f"Eligible patients {eligible:,} ({diag_yield:.0%} diagnosed × {treat_elig:.0%} eligible)"
    )
    if bia_flag:
        pricing_rationale += f"; ⚠ BIA: {bia_reason}"

    return {
        # Core outputs (compatible with tam_calculator.py schema)
        "us_tam_usd":        round(us_tam_usd),
        "peak_revenue_usd":  round(peak_revenue_usd),
        "formula":           "market_sizing_engine_v2",
        "pricing_rationale": pricing_rationale,

        # Stage metadata
        "cascade": {
            "prevalent_patients":    prevalent_patients,
            "diagnosed":             int(prevalent_patients * diag_yield),
            "eligible":              eligible,
            "diagnostic_yield":      round(diag_yield, 3),
            "treatment_eligible":    round(treat_elig, 3),
            "summary":               cascade_summary,
        },
        "dot": {
            "years":                 round(dot, 2),
            "multiplier_capped":     round(dot_multiplier, 2),
            "category":              "acute" if dot < 1 else "chronic" if dot < 5 else "lifelong",
        },
        "bass": bass_meta,
        "pricing": {
            "wac_annual_usd":        round(wac_annual_usd),
            "net_annual_usd":        round(net_price),
            "gross_to_net_pct":      round(gtn_pct, 3),
            "has_orphan_premium":    has_orphan,
        },
        "bia": {
            "affordability_concern": bia_flag,
            "revenue_dampening":     round(dampening, 3),
            "reason":                bia_reason,
        },

        # Convenience formats
        "us_tam_fmt":        _fmt(us_tam_usd),
        "peak_revenue_fmt":  _fmt(peak_revenue_usd),
        "peak_penetration":  round(penetration_y5, 3),
    }


def _fmt(usd: float) -> str:
    if usd >= 1e9:  return f"${usd / 1e9:.1f}B"
    if usd >= 1e6:  return f"${usd / 1e6:.0f}M"
    return f"${usd / 1e3:.0f}K"
