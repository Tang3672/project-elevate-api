"""
opportunity_scorer_v2.py — Risk-adjusted opportunity scoring engine.

Replaces the v1 weighted-average MCDA with a three-sub-score geometric model:

    Score_raw = Opportunity^0.35 × Probability^0.40 × Value^0.25

This structurally prevents a great market with ~0 success probability (or a
near-certain asset in a worthless market) from scoring high — the core bug
in v1 where large disease burden rescued doomed, crowded markets.

Sub-scores (each 0..100):
  A. OPPORTUNITY — is this disease/market worth anyone's time? (asset-independent)
  B. PROBABILITY — will an asset here actually make it through trials? (PTRS, done right)
  C. VALUE       — if it makes it, how big is the prize? (pathway-dependent)

All PTRS numbers cite: BIO/Informa Clinical Development Success Rates 2006–2015
(Thomas/Hay); Wong, Siah & Lo, Biostatistics 2019 (406k trials); DIA oncology
PoS (Wong 2019); Nature Communications 2025 dynamic ClinSR. rNPV logic per
Stewart 2001 / Alacrita / standard healthcare-IB practice.
"""

from __future__ import annotations
import asyncio as _asyncio
import json as _json
import logging as _logging
import math
import pathlib as _pathlib
import time as _time
from typing import Optional

import requests as _requests

# ── GBD 2021 US DALYs — R&D/prototyping ONLY (non-commercial license) ────────
# LICENSE: IHME Free-of-Charge Non-Commercial User Agreement.
# DO NOT use _GBD_DISEASE_DALYS in production commercial queries.
# Use _get_commercial_safe_dalys() instead (WHO GHO → falls back to GBD dev-only).
_GBD_DATA_PATH = _pathlib.Path(__file__).parent.parent / "data" / "gbd_us_dalys.json"

def _load_gbd() -> tuple[dict[str, int], dict[str, int], bool]:
    """Returns (disease_dalys, ta_dalys, commercial_restricted)."""
    try:
        raw = _json.loads(_GBD_DATA_PATH.read_text())
        restricted = raw.get("_meta", {}).get("commercial_use_restricted", True)
        disease_dalys = {k: v["us_dalys"] for k, v in raw["diseases"].items()}
        ta_dalys = raw["ta_defaults"]
        return disease_dalys, ta_dalys, restricted
    except Exception as e:
        _logging.getLogger(__name__).warning("GBD data file not loaded: %s", e)
        return {}, {}, True

_GBD_DISEASE_DALYS, _GBD_TA_DALYS, _GBD_COMMERCIAL_RESTRICTED = _load_gbd()

# WHO GHO DALY cache — populated lazily from DB (commercial_safe=TRUE)
_WHO_DALY_CACHE: dict[str, float] = {}


async def _get_commercial_safe_dalys(disease: str, ta: str) -> tuple[float | None, str]:
    """
    Return (daly_value, source_label) using only commercially-safe sources.
    Priority: WHO GHO (DB cache) → WHO GHO (live API) → GBD (dev-only, flagged).
    Never returns GBD data without a warning in production.
    """
    # 1. Check in-memory WHO GHO cache first
    if disease in _WHO_DALY_CACHE:
        return _WHO_DALY_CACHE[disease], "who_gho"

    # 2. Try DB (disease_burden table, commercial_safe=TRUE)
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT value FROM disease_burden
                WHERE disease_label  = $1
                  AND source_name    = 'who_gho'
                  AND metric         = 'dalys_absolute'
                  AND location       = 'United States'
                  AND commercial_safe = TRUE
                ORDER BY year DESC LIMIT 1
            """, disease)
            if row:
                val = float(row["value"])
                _WHO_DALY_CACHE[disease] = val
                return val, "who_gho"
    except Exception:
        pass  # DB not available in test environments

    # 3. Live WHO GHO fetch (commercial-safe)
    try:
        from app.ingestion.connectors.who_gho import get_us_dalys
        val = await get_us_dalys(disease)
        if val is not None:
            _WHO_DALY_CACHE[disease] = val
            return val, "who_gho"
    except Exception:
        pass

    # 4. GBD fallback — R&D/prototyping only; log warning so it's visible
    gbd_val = _GBD_DISEASE_DALYS.get(disease) or _GBD_TA_DALYS.get(ta)
    if gbd_val:
        if _GBD_COMMERCIAL_RESTRICTED:
            _logging.getLogger(__name__).warning(
                "DALY source: GBD (NON-COMMERCIAL) for '%s' — replace with WHO GHO before monetizing",
                disease
            )
        return float(gbd_val), "gbd_rdonly"

    return None, "none"

# ── US Prevalence — loaded once at import ────────────────────────────────────
_PREVALENCE_DATA_PATH = _pathlib.Path(__file__).parent.parent / "data" / "us_prevalence.json"

def _load_prevalence() -> tuple[dict[str, int], dict[str, int]]:
    try:
        raw = _json.loads(_PREVALENCE_DATA_PATH.read_text())
        disease_pop = {k: v["us_population"] for k, v in raw["diseases"].items()}
        ta_pop = raw["ta_defaults"]
        return disease_pop, ta_pop
    except Exception as e:
        _logging.getLogger(__name__).warning("Prevalence data file not loaded: %s", e)
        return {}, {}

_PREVALENCE_DISEASE, _PREVALENCE_TA = _load_prevalence()


# ──────────────────────────────────────────────────────────────────────────────
# PTRS TABLES — phase transition probabilities by therapeutic area
# Cumulative phase→approval. Source: BIO 2006-2015 + Wong 2019 + DIA oncology.
# Values are cumulative LOA (likelihood of approval) FROM the given phase.
# ──────────────────────────────────────────────────────────────────────────────
# All-indication baseline transitions (BIO 2006-2015):
#   P1→2 .632 | P2→3 .307 | P3→sub .581 | sub→appr .853
#   cumulative P1→approval ≈ .096
_BASE_LOA_FROM_PHASE = {
    "preclinical": 0.062,   # ~0.65 × P1 cumulative (pre-IND attrition)
    "phase1":      0.096,   # canonical BIO cumulative
    "phase2":      0.152,   # 0.307 × 0.581 × 0.853 ≈ 0.152
    "phase3":      0.495,   # 0.581 × 0.853 ≈ 0.495
    "filed":       0.853,   # submission → approval
    "approved":    1.000,
}

# Therapeutic-area multipliers applied to the all-indication base.
# Anchored so oncology ≈ 3.3-5.1% and hematology ≈ 26% cumulative P1 LOA.
_TA_LOA_MULTIPLIER = {
    "oncology":         0.45,   # 0.096*0.45 ≈ 4.3% — matches 3.3-5.1% range
    "hematology":       2.50,   # 0.096*2.50 ≈ 24% — matches 26.1%
    "rare_disease":     0.95,   # near baseline; cleaner trials offset biology
    "cns":              0.55,   # neuro notoriously hard (Phase 2 valley)
    "amr_infectious":   1.35,   # higher PTRS: clear endpoints, GAIN/LPAD support
    "cardiovascular":   0.85,
    "metabolic":        1.10,   # GLP-1 era; reasonably tractable
    "gene_therapy":     0.80,   # durable but manufacturing/safety risk
    "immunology":       1.05,
    "vaccine":          1.20,
    "ophthalmology":    1.15,
    "device":           1.50,   # 510(k)/PMA generally higher success than drugs
    "diagnostic":       1.60,
    "respiratory":      0.90,
    "other":            1.00,
}

# Biomarker lever — the single biggest PTRS multiplier we add in v2.
# BIO: 25.9% with selection biomarker vs 8.4% without (≈3.08x).
# We cap the realized multiplier so cumulative LOA never exceeds sane bounds.
_BIOMARKER_MULTIPLIER = 2.1     # applied when patient-selection biomarker present

# Modality risk nudges (small; PTRS already partly captures via TA)
_MODALITY_NUDGE = {
    "gene_cell_therapy": 0.92,
    "biologic":          1.05,
    "drug_small_molecule": 1.00,
    "vaccine_immunotherapy": 1.10,
    "medical_device":    1.20,
    "diagnostic":        1.25,
    "digital_health":    1.30,
    "other_platform":    0.95,
}


def _clamp(x: float, lo: float = 1.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _normalize_log(value: float, max_value: float) -> float:
    """Log-normalize a heavy-tailed quantity to 0..100, hard-capped at 100."""
    if value <= 0:
        return 0.0
    return min(100.0, 100.0 * math.log(value + 1) / math.log(max_value + 1))


# ──────────────────────────────────────────────────────────────────────────────
# SUB-SCORE A: OPPORTUNITY  (asset-independent: is this market worth it?)
# ──────────────────────────────────────────────────────────────────────────────
def _competition_curve(competitor_count: int) -> float:
    """
    Bivalent: 0 = unvalidated (risky), 5-7 = validated sweet spot, 20+ = commoditized.
    Floors at 10 (a proven market never scores 0). Carried over from v1 (validated).
    """
    if competitor_count <= 0:
        return 20.0
    elif competitor_count <= 7:
        p = competitor_count / 7.0
        return 20.0 + 80.0 * (2 * p - p * p)
    elif competitor_count <= 15:
        return max(15.0, 100.0 - (competitor_count - 7) * 10.5)
    else:
        return max(10.0, 15.0 - (competitor_count - 15) * 0.3)


def opportunity_score(
    *,
    approved_treatments_count: int,
    competitor_trial_count: int,
    us_patient_population: int,
    therapeutic_area: str,
    dalys: Optional[float] = None,
) -> tuple[float, dict]:
    """Disease/market attractiveness, independent of any specific asset."""
    ta = therapeutic_area.lower()

    # Unmet need — inverse of approved-therapy adequacy
    if approved_treatments_count == 0:
        unmet = 100.0
    elif approved_treatments_count == 1:
        unmet = 80.0
    elif approved_treatments_count <= 3:
        unmet = 60.0
    elif approved_treatments_count <= 6:
        unmet = 40.0
    else:
        unmet = 20.0
    # AMR boost: existing antibiotics are last-resort/toxic; CDC urgent-threat framing
    if ta in ("amr_infectious", "amr", "drug_amr"):
        unmet = min(100.0, unmet + 20.0)

    # Disease burden — DALYs if provided, else proxy from population
    if dalys and dalys > 0:
        burden = _normalize_log(dalys, 50_000_000)   # 50M DALYs ~ ceiling (top GBD causes)
    else:
        burden = _normalize_log(us_patient_population, 50_000_000)

    # Competition / white-space
    competition = _competition_curve(competitor_trial_count)

    # Saturation dampener: large but well-served + crowded disease = smaller net opportunity
    if approved_treatments_count >= 4 and competitor_trial_count >= 20:
        burden *= 0.55
        unmet  *= 0.75

    # Opportunity = weighted blend (within sub-score, arithmetic is fine)
    opp = 0.42 * unmet + 0.33 * burden + 0.25 * competition
    return _clamp(opp), {
        "unmet_need": round(unmet, 1),
        "burden": round(burden, 1),
        "competition": round(competition, 1),
    }


# ──────────────────────────────────────────────────────────────────────────────
# SUB-SCORE B: PROBABILITY  (PTRS done right — cumulative LOA from current phase)
# ──────────────────────────────────────────────────────────────────────────────
def probability_score(
    *,
    development_phase: str,
    therapeutic_area: str,
    has_biomarker: bool = False,
    modality: str = "drug_small_molecule",
    competitor_trial_count: int = 5,
) -> tuple[float, dict]:
    """Honest cumulative probability of technical & regulatory success → 0..100."""
    phase = development_phase.lower()
    ta = therapeutic_area.lower()

    base = _BASE_LOA_FROM_PHASE.get(phase, 0.096)
    ta_mult = _TA_LOA_MULTIPLIER.get(ta, 1.00)
    mod_mult = _MODALITY_NUDGE.get(modality, 1.00)

    loa = base * ta_mult * mod_mult
    if has_biomarker:
        loa *= _BIOMARKER_MULTIPLIER

    # Crowding drag: saturated races raise differentiation/enrollment/endpoint risk.
    # Continuous decay above 15 trials, floored at 0.55.
    if competitor_trial_count > 15:
        drag = max(0.55, 1.0 - (competitor_trial_count - 15) * 0.006)
        loa *= drag

    loa = min(loa, 0.78)   # nothing is certain; cap stacked multipliers
    ptrs_pct = round(loa * 100, 1)

    # Log-scaled curve: spreads the 6–78% LOA range across the full 0-100 band.
    # k=99 chosen so targets hit: 0.07→42, 0.15→60, 0.30→75, 0.50→85, 0.78→95.
    # Normalization denominator is log1p(1.0 * 99) so loa=1.0 would → 100.
    _LOG_K = 99.0
    score = min(100.0, 100.0 * math.log1p(loa * _LOG_K) / math.log1p(_LOG_K))
    return _clamp(score), {"ptrs_pct": ptrs_pct, "loa": round(loa, 4)}


# ──────────────────────────────────────────────────────────────────────────────
# SUB-SCORE C: VALUE  (pathway-dependent prize size, risk-adjusted)
# ──────────────────────────────────────────────────────────────────────────────
_EXCLUSIVITY_PREMIUM = {
    "orphan drug": 0.12,
    "orphan": 0.12,
    "breakthrough": 0.08,
    "fast track": 0.05,
    "qidp": 0.13,            # GAIN Act +5yr
    "rmat": 0.10,
    "priority review": 0.06,
    "accelerated approval": 0.07,
}


def value_score(
    *,
    annual_treatment_cost_usd: float,
    us_patient_population: int,
    designations: Optional[list] = None,
    funding_pathway: str = "commercial",
    modality: str = "drug_small_molecule",
    nih_funding_density: Optional[float] = None,
    overlapping_grants: Optional[int] = None,
    competitor_trial_count: int = 5,
    approved_treatments_count: int = 0,
    tam_peak_revenue: Optional[float] = None,
) -> tuple[float, dict]:
    """
    Commercial pathway: epidemiology-anchored peak-sales proxy.
    Basic-science pathway: NIH funding density + grant white-space (NOT market size).
    """
    designations = [d.lower() for d in (designations or [])]

    if funding_pathway == "basic_science":
        # Value redefined: research fundability, not market.
        fund = _normalize_log((nih_funding_density or 0) * 1_000_000, 2_000_000_000)
        # white-space: fewer overlapping grants = more novel = higher value, but
        # some overlap proves the area is fundable. Bivalent-lite.
        og = overlapping_grants if overlapping_grants is not None else 8
        if og <= 0:
            whitespace = 45.0    # totally novel = unproven fundability
        elif og <= 10:
            whitespace = 90.0    # active but not saturated = ideal
        else:
            whitespace = max(30.0, 90.0 - (og - 10) * 2.0)
        val = 0.55 * fund + 0.45 * whitespace
        breakdown = {"nih_fund": round(fund, 1), "whitespace": round(whitespace, 1)}
        return _clamp(val), breakdown

    # Commercial / SBIR: use disease-specific TAM calculator output when available;
    # fall back to generic penetration formula for unlisted diseases.
    if tam_peak_revenue and tam_peak_revenue > 0:
        peak_sales = tam_peak_revenue
    else:
        penetration = 0.10 if us_patient_population < 200_000 else 0.03
        net_price_factor = 0.55
        peak_sales = us_patient_population * penetration * annual_treatment_cost_usd * net_price_factor

    # LOE decay by modality affects durable value (biologics hold value better)
    durability = 1.10 if modality in ("biologic", "gene_cell_therapy", "vaccine_immunotherapy") else 1.0

    market = _normalize_log(peak_sales * durability, 35_000_000_000)  # $35B peak ~ ceiling (Keytruda-scale)

    # Market captureability haircut — only approvals matter here; trial count
    # competition is already captured in opportunity_score (don't double-penalize).
    # Many trials = validated market; fewer approvals = more room to capture share.
    appr_factor = max(0.40, 1.0 - approved_treatments_count * 0.08)  # 8 approved → 0.40
    crowd = appr_factor
    market = market * crowd

    # Exclusivity premium
    premium = sum(_EXCLUSIVITY_PREMIUM.get(d, 0.0) for d in designations)
    premium = min(premium, 0.25)
    val = market * (1 + premium)

    breakdown = {
        "peak_sales_est": round(peak_sales / 1e6, 1),   # $M
        "market": round(market, 1),
        "exclusivity_premium": round(premium, 3),
    }
    return _clamp(val), breakdown


# ──────────────────────────────────────────────────────────────────────────────
# SUB-SCORE D: INNOVATION  (first-in-class / biomarker / regulatory designation)
# ──────────────────────────────────────────────────────────────────────────────
def innovation_score(
    *,
    is_first_in_class: bool = False,
    has_biomarker: bool = False,
    designations: Optional[list] = None,
) -> tuple[float, dict]:
    """
    0..100 innovation premium.
    - First-in-class / novel unvalidated target: +40 pts (BIO: FIC drugs have ~2× LOA)
    - Patient-selection biomarker present: +25 pts (BIO: 3× LOA improvement)
    - Regulatory designation uplift: +10 pts each (Orphan, Breakthrough, QIDP, Fast Track), capped at 30
    """
    designations_raw = [d.lower() for d in (designations or [])]
    # Normalize designation strings to canonical tokens
    _DESIG_MAP = {
        "breakthrough therapy": "breakthrough", "breakthrough designation": "breakthrough",
        "fast track designation": "fast track", "fast-track": "fast track",
        "orphan drug designation": "orphan", "orphan drug": "orphan",
        "accelerated approval": "accelerated", "priority review designation": "priority review",
        "qualified infectious disease product": "qidp",
        "regenerative medicine advanced therapy": "rmat",
    }
    designations = [_DESIG_MAP.get(d, d) for d in designations_raw]
    _COUNTED_DESIGNATIONS = {"orphan", "breakthrough", "qidp", "fast track", "rmat",
                              "accelerated", "priority review"}

    pts = 0.0
    if is_first_in_class:
        pts += 40.0
    if has_biomarker:
        pts += 25.0
    desig_count = sum(1 for d in designations if d in _COUNTED_DESIGNATIONS)
    pts += min(30.0, desig_count * 10.0)

    score = _clamp(min(pts, 100.0))
    return score, {
        "first_in_class": is_first_in_class,
        "biomarker_uplift": has_biomarker,
        "designation_count": desig_count,
    }


# ──────────────────────────────────────────────────────────────────────────────
# MAIN ENTRY — geometric combination
# ──────────────────────────────────────────────────────────────────────────────
# Weights: Opportunity^0.35 × Probability^0.28 × Value^0.25 × Innovation^0.12
# Probability weight reduced from 0.40 → 0.28 to avoid dragging all scores down
# at realistic LOA of 6.7-15%.  Innovation added as the 4th factor.
_W_OPP, _W_PROB, _W_VAL, _W_INN = 0.35, 0.28, 0.25, 0.12


def _tier(score: float) -> tuple[str, str]:
    # Thresholds calibrated to the geometric formula's natural output range.
    if score >= 68:  return "EXCEPTIONAL", "#059669"
    if score >= 52:  return "HIGH", "#0891b2"
    if score >= 36:  return "MODERATE", "#d97706"
    if score >= 20:  return "LOW", "#dc2626"
    return "VERY LOW", "#991b1b"


async def score_opportunity_v2(
    *,
    disease_name: str,
    therapeutic_area: str = "other",
    development_phase: str = "phase2",
    approved_treatments_count: int = 0,
    competitor_trial_count: int = 5,
    annual_treatment_cost_usd: float = 50_000,
    us_patient_population: int = 100_000,
    designations: Optional[list] = None,
    has_biomarker: bool = False,
    modality: str = "drug_small_molecule",
    funding_pathway: str = "commercial",
    dalys: Optional[float] = None,
    nih_funding_density: Optional[float] = None,
    overlapping_grants: Optional[int] = None,
    tam_peak_revenue: Optional[float] = None,
    is_first_in_class: bool = False,
) -> dict:
    opp, opp_b = opportunity_score(
        approved_treatments_count=approved_treatments_count,
        competitor_trial_count=competitor_trial_count,
        us_patient_population=us_patient_population,
        therapeutic_area=therapeutic_area,
        dalys=dalys,
    )
    prob, prob_b = probability_score(
        development_phase=development_phase,
        therapeutic_area=therapeutic_area,
        has_biomarker=has_biomarker,
        modality=modality,
        competitor_trial_count=competitor_trial_count,
    )
    val, val_b = value_score(
        annual_treatment_cost_usd=annual_treatment_cost_usd,
        us_patient_population=us_patient_population,
        designations=designations,
        funding_pathway=funding_pathway,
        modality=modality,
        nih_funding_density=nih_funding_density,
        overlapping_grants=overlapping_grants,
        competitor_trial_count=competitor_trial_count,
        approved_treatments_count=approved_treatments_count,
        tam_peak_revenue=tam_peak_revenue,
    )
    inn, inn_b = innovation_score(
        is_first_in_class=is_first_in_class,
        has_biomarker=has_biomarker,
        designations=designations,
    )

    # Geometric combination — a near-zero in any factor crushes the score.
    # Innovation floored at 1 so diseases with no innovation signal don't zero out.
    score_raw = (opp ** _W_OPP) * (prob ** _W_PROB) * (val ** _W_VAL) * (max(inn, 1.0) ** _W_INN)
    score_display = _clamp(score_raw)

    tier, color = _tier(score_display)

    band = 0.18 + (0.05 if dalys is None else 0.0)
    lo = round(max(1, score_display * (1 - band)), 1)
    hi = round(min(99, score_display * (1 + band)), 1)

    return {
        "disease": disease_name,
        "therapeutic_area": therapeutic_area,
        "score": round(score_display, 1),
        "tier": tier,
        "tier_color": color,
        "score_raw": round(score_raw, 2),
        "ptrs": prob_b["ptrs_pct"],
        "confidence_low": lo,
        "confidence_high": hi,
        "funding_pathway": funding_pathway,
        "us_patient_population": us_patient_population,
        "annual_cost_usd": annual_treatment_cost_usd,
        "subscores": {
            "opportunity": round(opp, 1),
            "probability": round(prob, 1),
            "value": round(val, 1),
            "innovation": round(inn, 1),
        },
        "components": {**opp_b, **prob_b, **val_b, **inn_b},
        "weights": {
            "opportunity": _W_OPP,
            "probability": _W_PROB,
            "value": _W_VAL,
            "innovation": _W_INN,
        },
    }


# ──────────────────────────────────────────────────────────────────────────────
# DISCOVERY ENGINE v2 — scores the curated OPPORTUNITY_UNIVERSE through v2
# ──────────────────────────────────────────────────────────────────────────────
import asyncio as _asyncio

# Per-disease enrichment: fields the v1 universe tuple doesn't carry.
# (competitor_trial_count, us_patient_population, has_biomarker, modality, dalys)
# Curated from public epidemiology + ClinicalTrials.gov density. Defaults applied
# by therapeutic area where a specific disease isn't listed.
_TA_DEFAULTS = {
    # ta: (trials, population, biomarker, modality, dalys)
    "oncology":        (40, 250_000, True,  "biologic", 2_000_000),
    "rare_disease":    (8,  25_000,  True,  "gene_cell_therapy", 150_000),
    "amr_infectious":  (10, 400_000, False, "drug_small_molecule", 800_000),
    "cns":             (15, 500_000, False, "drug_small_molecule", 3_000_000),
    "cardiovascular":  (30, 1_500_000, False, "drug_small_molecule", 5_000_000),
    "metabolic":       (35, 5_000_000, False, "drug_small_molecule", 4_000_000),
    "gene_therapy":    (6,  20_000,  True,  "gene_cell_therapy", 120_000),
    "immunology":      (20, 800_000, True,  "biologic", 1_500_000),
    "vaccine":         (12, 2_000_000, False, "vaccine_immunotherapy", 1_000_000),
    "ophthalmology":   (14, 600_000, True,  "biologic", 700_000),
    "device":          (10, 800_000, False, "medical_device", 900_000),
    "diagnostic":      (8,  1_000_000, True, "diagnostic", 0),
    "other":           (15, 300_000, False, "drug_small_molecule", 500_000),
}

# Specific-disease overrides (more accurate than TA defaults where known)
_DISEASE_OVERRIDES = {
    "Glioblastoma Multiforme":               (35, 12_000, False, "biologic", 250_000),
    "Pancreatic Ductal Adenocarcinoma":      (45, 60_000, True,  "biologic", 400_000),
    "Huntington Disease":                    (6,  30_000, True,  "drug_small_molecule", 200_000),
    "Carbapenem-resistant Enterobacterales": (8,  500_000, False, "drug_small_molecule", 900_000),
    "Spinal Muscular Atrophy Type 2":        (5,  15_000, True,  "gene_cell_therapy", 120_000),
    "Alzheimer Disease (early/MCI)":         (90, 6_000_000, True, "biologic", 8_000_000),
    "HER2-low Breast Cancer":                (60, 250_000, True,  "biologic", 600_000),
    "KRAS G12C NSCLC":                       (50, 80_000, True,  "biologic", 500_000),
}


def _phase_default_designations(ta, approved):
    """Infer likely designations from TA + approval landscape."""
    desig = []
    if ta in ("rare_disease", "gene_therapy") or approved <= 1:
        desig.append("Orphan Drug")
    if ta == "amr_infectious":
        desig.append("QIDP")
    if approved == 0:
        desig.append("Fast Track")
    return desig


# ──────────────────────────────────────────────────────────────────────────────
# LIVE TRIAL COUNT — ClinicalTrials.gov v2 with 24h in-memory cache
# ──────────────────────────────────────────────────────────────────────────────

_TRIAL_COUNT_CACHE: dict[str, tuple[int, float]] = {}  # disease → (count, fetched_at)
_CACHE_TTL = 86_400  # 24 hours
_logger = _logging.getLogger(__name__)

# Disease names in OPPORTUNITY_UNIVERSE that don't match CT.gov search well —
# map to a cleaner search term for the API query.
_CT_SEARCH_ALIASES: dict[str, str] = {
    # Original 25
    "ALS (SOD1-mutant)":                    "amyotrophic lateral sclerosis",
    "NASH/MASH":                            "nonalcoholic steatohepatitis",
    "Alzheimer Disease (early/MCI)":        "Alzheimer Disease",
    "C. difficile Infection":               "Clostridioides difficile",
    "Sickle Cell Disease (gene therapy)":   "Sickle Cell Disease",
    "Sepsis (AI early detection)":          "Sepsis",
    "Geographic Atrophy (dry AMD)":         "geographic atrophy",
    "KRAS G12C NSCLC":                      "KRAS non-small cell lung",
    "MRSA Skin Infections":                 "MRSA",
    "Type 1 Diabetes (CGM/automated insulin)": "Type 1 Diabetes",
    "Carbapenem-resistant Enterobacterales": "carbapenem resistant Enterobacterales",
    "Acinetobacter baumannii MDR":          "Acinetobacter baumannii",
    "RSV in elderly/immunocompromised":     "respiratory syncytial virus",
    "Prostate Cancer (PSMA-targeted)":      "Prostate Cancer",
    "Myelofibrosis JAK-resistant":          "myelofibrosis",
    "Bipolar Depression":                   "bipolar disorder",
    "Rare Pediatric Epilepsy (SCN1A)":      "Dravet syndrome",
    "HER2-low Breast Cancer":              "HER2 breast cancer",
    # New 26
    "Heart Failure (HFpEF)":               "heart failure preserved ejection fraction",
    "Type 2 Diabetes (GLP-1 resistant)":   "Type 2 Diabetes",
    "Obesity (CNS/metabolic)":             "obesity",
    "Lung Cancer (NSCLC, IO-resistant)":   "non-small cell lung cancer",
    "Colorectal Cancer (MSS)":             "colorectal cancer",
    "Multiple Myeloma (triple-refractory)": "multiple myeloma",
    "Chronic Kidney Disease (DKD)":        "diabetic kidney disease",
    "Atrial Fibrillation":                 "atrial fibrillation",
    "Major Depression (TRD)":              "treatment-resistant depression",
    "Schizophrenia":                       "schizophrenia",
    "COPD (advanced emphysema)":           "COPD emphysema",
    "Rheumatoid Arthritis (JAK-refractory)": "rheumatoid arthritis",
    "Psoriasis / PsA (IL-17/23 refractory)": "psoriasis",
    "Inflammatory Bowel Disease (UC/CD)":  "inflammatory bowel disease",
    "Breast Cancer (HR+, CDK4/6 resistant)": "breast cancer CDK4",
    "Ovarian Cancer (BRCA-wild type)":     "ovarian cancer",
    "Wet AMD / Diabetic Macular Edema":    "macular degeneration",
    "Asthma (severe eosinophilic)":        "severe asthma eosinophilic",
    "Heart Failure (HFrEF, device-refractory)": "heart failure reduced ejection",
    "Stroke (acute ischemic, neuroprotection)": "ischemic stroke",
    "Parkinson Disease (early stage)":     "Parkinson disease",
    "Multiple Sclerosis (progressive)":    "progressive multiple sclerosis",
    "Influenza (universal vaccine)":       "influenza universal vaccine",
    "HIV (long-acting ART / cure)":        "HIV long-acting",
    "PTSD":                                "post-traumatic stress disorder",
    "Opioid Use Disorder":                 "opioid use disorder",
}


async def _fetch_live_trial_count(disease: str, ta: str) -> int:
    """
    Query ClinicalTrials.gov v2 for active trial count.
    Read order: L1 in-process cache → L2 DB disease_aggregate → live CT.gov API.
    Results cached for 24h. Falls back to static value on error.
    """
    now = _time.monotonic()

    # L1: in-process cache
    cached = _TRIAL_COUNT_CACHE.get(disease)
    if cached and (now - cached[1]) < _CACHE_TTL:
        return cached[0]

    fallback = _DISEASE_OVERRIDES.get(disease, _TA_DEFAULTS.get(ta, _TA_DEFAULTS["other"]))[0]

    # L2: DB disease_aggregate (populated by cache_warmer on startup)
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT competitor_trial_count FROM disease_aggregate "
                "WHERE lower(disease_label)=lower($1) "
                "  AND competitor_trial_count IS NOT NULL LIMIT 1",
                disease,
            )
            if row and row["competitor_trial_count"] is not None:
                count = int(row["competitor_trial_count"])
                _TRIAL_COUNT_CACHE[disease] = (count, now)
                return count
    except Exception:
        pass   # DB unavailable in test environments — fall through to live API

    # L3: Live CT.gov API
    search_term = _CT_SEARCH_ALIASES.get(disease, disease)

    def _sync_fetch() -> int:
        r = _requests.get(
            "https://clinicaltrials.gov/api/v2/studies",
            params={
                "query.cond": search_term,
                "filter.overallStatus": "RECRUITING,NOT_YET_RECRUITING,ACTIVE_NOT_RECRUITING",
                "countTotal": "true",
                "pageSize": "1",
                "format": "json",
            },
            timeout=8.0,
        )
        r.raise_for_status()
        return int(r.json().get("totalCount", fallback))

    try:
        loop = _asyncio.get_event_loop()
        count = await loop.run_in_executor(None, _sync_fetch)
        _TRIAL_COUNT_CACHE[disease] = (count, now)
        _logger.debug("CT.gov '%s' → %d trials", disease, count)
        return count
    except Exception as e:
        _logger.warning("CT.gov fetch failed for '%s', using static fallback: %s", disease, e)

    _TRIAL_COUNT_CACHE[disease] = (fallback, now)
    return fallback


# ──────────────────────────────────────────────────────────────────────────────
# LIVE APPROVAL COUNT — openFDA drug label API with 24h in-memory cache
# ──────────────────────────────────────────────────────────────────────────────

_APPROVAL_COUNT_CACHE: dict[str, tuple[int, float]] = {}

# For these diseases the indication text is too broad (all NSCLC drugs get counted
# for a KRAS G12C-specific opportunity, etc.). Keep the curated static value.
_FDA_USE_STATIC: frozenset[str] = frozenset({
    "KRAS G12C NSCLC",                        # "non-small cell lung cancer" → 64 drugs (all NSCLC)
    "HER2-low Breast Cancer",                 # "HER2" → 40 drugs (all HER2+ drugs)
    "Prostate Cancer (PSMA-targeted)",        # "prostate cancer" → 41 drugs
    "Type 1 Diabetes (CGM/automated insulin)", # "type 1 diabetes" → 37 (all insulins)
    "Bipolar Depression",                      # "bipolar" → 36 (all mood stabilizers)
    "Sepsis (AI early detection)",             # device/diagnostic; drug count irrelevant
    "Carbapenem-resistant Enterobacterales",  # FDA labels lack phrase; newer drugs absent
    "Acinetobacter baumannii MDR",            # "acinetobacter" → 35 (old broad-spectrum ABx)
})

# Map disease names to the indication phrase used in FDA drug labels.
_FDA_INDICATION_ALIASES: dict[str, str] = {
    "Huntington Disease":                    "chorea",
    "Alzheimer Disease (early/MCI)":         "Alzheimer's",
    "Friedreich Ataxia":                     "friedreich's",
    "ALS (SOD1-mutant)":                     "amyotrophic lateral sclerosis",
    "Spinal Muscular Atrophy Type 2":        "spinal muscular atrophy",
    "Duchenne Muscular Dystrophy":           "duchenne",
    "Sickle Cell Disease (gene therapy)":   "sickle cell",
    "Glioblastoma Multiforme":              "glioblastoma",
    "Pancreatic Ductal Adenocarcinoma":     "pancreatic cancer",
    "Myelofibrosis JAK-resistant":          "myelofibrosis",
    "Carbapenem-resistant Enterobacterales": "carbapenem-resistant Enterobacteriaceae",
    "Acinetobacter baumannii MDR":          "acinetobacter baumannii",
    "C. difficile Infection":               "Clostridioides difficile",
    "MRSA Skin Infections":                 "MRSA",
    "Geographic Atrophy (dry AMD)":         "geographic atrophy",
    "NASH/MASH":                            "nonalcoholic steatohepatitis",
    "Pulmonary Arterial Hypertension":      "pulmonary arterial hypertension",
    "RSV in elderly/immunocompromised":     "respiratory syncytial virus",
    "Rare Pediatric Epilepsy (SCN1A)":      "Dravet syndrome",
    "Prostate Cancer (PSMA-targeted)":      "prostate cancer",
}


async def _fetch_live_approval_count(disease: str, static_fallback: int) -> int:
    """
    Count distinct approved drugs for this indication via the openFDA drug label API.
    Skips diseases where the indication text is too broad for meaningful counting.
    Caches results 24h. Falls back to static_fallback on error or skip.
    """
    if disease in _FDA_USE_STATIC:
        return static_fallback

    now = _time.monotonic()
    cached = _APPROVAL_COUNT_CACHE.get(disease)
    if cached and (now - cached[1]) < _CACHE_TTL:
        return cached[0]

    indication = _FDA_INDICATION_ALIASES.get(disease, disease)

    def _sync_fetch() -> int:
        r = _requests.get(
            "https://api.fda.gov/drug/label.json",
            params={
                "search": f'indications_and_usage:"{indication}"',
                "count": "openfda.generic_name.exact",
                "limit": "100",
            },
            timeout=8.0,
        )
        r.raise_for_status()
        results = r.json().get("results", [])
        # Cap at 20 — scoring model only distinguishes 0/1/2-3/4-6/7+ tiers
        return min(len(results), 20)

    try:
        loop = _asyncio.get_event_loop()
        count = await loop.run_in_executor(None, _sync_fetch)
        # If FDA returns 0 it usually means the search term needs refinement — keep static
        if count == 0:
            count = static_fallback
        _APPROVAL_COUNT_CACHE[disease] = (count, now)
        _logger.debug("FDA approvals '%s' → %d", disease, count)
        return count
    except Exception as e:
        _logger.warning("FDA approval fetch failed for '%s', using static: %s", disease, e)

    _APPROVAL_COUNT_CACHE[disease] = (static_fallback, now)
    return static_fallback


async def run_discovery_engine_v2(top_n: int = 25, funding_pathway: str = "commercial"):
    """
    Score the full disease universe through the v2 engine.
    Universe comes from universe_builder (500+ diseases); falls back to the v1
    OPPORTUNITY_UNIVERSE if the builder import fails (backward compatibility).
    Returns the same dict shape the frontend expects, with v2 subscores in components.
    """
    try:
        from app.services.universe_builder import get_universe
        OPPORTUNITY_UNIVERSE = get_universe()
    except Exception:
        from app.services.opportunity_scorer import OPPORTUNITY_UNIVERSE

    async def score_one(opp):
        disease, ta, phase, approved, cost, notes = opp
        _, pop, biomarker, modality, _old_dalys = _DISEASE_OVERRIDES.get(
            disease, _TA_DEFAULTS.get(ta, _TA_DEFAULTS["other"])
        )
        # DALYs — commercial-safe first (WHO GHO/DB), GBD only as R&D fallback
        dalys, daly_source = await _get_commercial_safe_dalys(disease, ta)
        if dalys is None:
            dalys = _old_dalys  # last resort: hardcoded estimate from _DISEASE_OVERRIDES
            daly_source = "hardcoded"
        # Real US prevalence: universe_builder per-disease dict → static file → TA default
        try:
            from app.services.universe_builder import get_disease_population
            known_pop = get_disease_population(disease)
        except Exception:
            known_pop = None
        pop = known_pop or _PREVALENCE_DISEASE.get(disease) or _PREVALENCE_TA.get(ta) or pop
        # ── Market Sizing: 5-stage engine (Bass + BIA + DoT + Gross-to-Net) ──────
        # 1. Try curated expert TAM first (tam_calculator.py)
        from app.services.tam_calculator import calculate_tam, format_tam
        expert_tam = calculate_tam(disease, fallback_population=pop, fallback_price=cost)

        # Fetch live data in parallel
        trials, approved = await _asyncio.gather(
            _fetch_live_trial_count(disease, ta),
            _fetch_live_approval_count(disease, approved),
        )
        first_in_class = (approved == 0 and phase in ("preclinical", "phase1", "phase2"))
        desig = _phase_default_designations(ta, approved)

        # 2. Always run the new engine — it enriches with Bass/DoT/BIA metadata
        from app.services.market_sizing_engine import compute_market_size
        engine_tam = compute_market_size(
            disease_name=disease,
            therapeutic_area=ta,
            prevalent_patients=pop,
            wac_annual_usd=cost,
            approved_treatments_count=approved,
            modality=modality,
            designations=desig,
            is_first_in_class=first_in_class,
            has_biomarker=biomarker,
            development_phase=phase,
        )

        # Expert TAM takes precedence for curated diseases; engine fills gaps
        tam = expert_tam if expert_tam and expert_tam.get("formula") != "generic_fallback" else engine_tam

        try:
            r = await score_opportunity_v2(
                disease_name=disease,
                therapeutic_area=ta,
                development_phase=phase,
                approved_treatments_count=approved,
                competitor_trial_count=trials,
                annual_treatment_cost_usd=cost,
                us_patient_population=pop,
                designations=desig,
                has_biomarker=biomarker,
                modality=modality,
                funding_pathway=funding_pathway,
                dalys=dalys if dalys and dalys > 0 else None,
                tam_peak_revenue=tam["peak_revenue_usd"] if tam else None,
                is_first_in_class=first_in_class,
            )
            r["daly_source"] = daly_source
            # TAM fields for the frontend
            if tam:
                r["us_tam_usd"]        = round(tam["us_tam_usd"])
                r["peak_revenue_usd"]  = round(tam["peak_revenue_usd"])
                r["us_tam_fmt"]        = tam.get("us_tam_fmt") or format_tam(tam["us_tam_usd"])
                r["peak_revenue_fmt"]  = tam.get("peak_revenue_fmt") or format_tam(tam["peak_revenue_usd"])
                r["tam_formula"]       = tam["formula"]
                r["pricing_rationale"] = tam.get("pricing_rationale", "")
                # Engine-specific enrichment (always from new engine)
                r["market_sizing"]     = {
                    "dot_years":         engine_tam["dot"]["years"],
                    "dot_category":      engine_tam["dot"]["category"],
                    "bass_penetration_y5": engine_tam["bass"]["capturable_y5"],
                    "peak_adoption_year":engine_tam["bass"]["peak_adoption_year"],
                    "diagnostic_yield":  engine_tam["cascade"]["diagnostic_yield"],
                    "eligible_patients": engine_tam["cascade"]["eligible"],
                    "net_price_pct_wac": engine_tam["pricing"]["gross_to_net_pct"],
                    "bia_concern":       engine_tam["bia"]["affordability_concern"],
                    "bia_dampening":     engine_tam["bia"]["revenue_dampening"],
                }
            # Flatten subscores into components for the existing frontend bars
            r["notes"] = notes
            r["phase"] = phase
            s = r["subscores"]
            r["components"] = {
                "opportunity": s["opportunity"],
                "probability": s["probability"],
                "value": s["value"],
                "innovation": s.get("innovation", 0),
            }
            return r
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"v2 score failed for {disease}: {e}")
            return None

    results = await _asyncio.gather(*[score_one(o) for o in OPPORTUNITY_UNIVERSE])
    scored = [r for r in results if r is not None]

    # Market-size scaling: prevent ultra-rare diseases from dominating the
    # leaderboard on innovation+unmet-need alone. Tiered penalty by patient count:
    #   >500k: 1.00×  (large markets, no penalty)
    #   100k-500k: 0.92×  (mid markets, slight haircut)
    #   30k-100k: 0.78×
    #   10k-30k: 0.60×
    #   3k-10k: 0.45×
    #   <3k: 0.32×   (ultra-orphan, still visible but ranked realistically)
    def _pop_scale(pop: int) -> float:
        if pop >= 500_000: return 1.00
        if pop >= 100_000: return 0.92
        if pop >=  30_000: return 0.78
        if pop >=  10_000: return 0.60
        if pop >=   3_000: return 0.45
        return 0.32

    for r in scored:
        pop_val = r.get("us_patient_population") or 0
        scale = _pop_scale(pop_val)
        if scale < 1.0:
            r["score"]     = round(r["score"] * scale, 1)
            r["score_raw"] = round(r.get("score_raw", r["score"]) * scale, 2)
            r["rare_disease_penalty"] = True
        # Re-tier after scaling
        r["tier"], r["tier_color"] = _tier(r["score"])

    scored.sort(key=lambda x: x["score"], reverse=True)
    # Add rank field
    for i, r in enumerate(scored, 1):
        r["rank"] = i
    return scored[:top_n]
