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
import dataclasses
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
# PTRS — now sourced from ptrs_tables.py (hard published numbers, NOT multipliers)
# BIO/Informa 2011-2020, Wong 2019, FDA CDRH data. See ptrs_tables.py for citations.
# ──────────────────────────────────────────────────────────────────────────────
# Kept for backward compatibility with any code that references these directly.
# The probability_score function now calls ptrs_tables.get_ptrs() instead.
_BASE_LOA_FROM_PHASE = {
    "preclinical": 0.049,   # [BIO2020] all-indication: pre-IND → approval
    "phase1":      0.079,   # [BIO2020] 7.9% all-indication P1→approval
    "phase2":      0.149,   # [BIO2020] derived: P2→approval = 0.307×0.581×0.853
    "phase3":      0.493,   # [BIO2020] P3→submission 57.8% × approval 85.3%
    "filed":       0.853,   # [BIO2020] NDA/BLA → approval 85.3%
    "approved":    1.000,
}

# Legacy multipliers — DEPRECATED. probability_score() now uses ptrs_tables directly.
# Kept only for external code that may import these.
_TA_LOA_MULTIPLIER = {
    "oncology":         0.67,   # 0.079 × 0.67 = 5.3% [BIO2020]
    "hematology":       3.03,   # 0.079 × 3.03 = 23.9% [BIO2020]
    "rare_disease":     2.15,   # 0.079 × 2.15 = 17.0% [BIO2020]
    "cns":              0.75,   # 0.079 × 0.75 = 5.9% [BIO2020]
    "amr_infectious":   1.65,   # 0.079 × 1.65 = 13.0% (12.9% infectious [BIO2020])
    "cardiovascular":   1.11,   # 0.079 × 1.11 = 8.8% [BIO2020]
    "metabolic":        1.34,   # 0.079 × 1.34 = 10.6% [BIO2020]
    "gene_therapy":     1.43,   # 0.079 × 1.43 = 11.3% [ASGCT2024 estimate]
    "immunology":       1.85,   # 0.079 × 1.85 = 14.6% [BIO2020]
    "vaccine":          2.63,   # 0.079 × 2.63 = 20.8% [WHO vaccine estimate]
    "ophthalmology":    1.46,   # 0.079 × 1.46 = 11.5% [BIO2020]
    "device":           6.84,   # Device LOA ~54% from IDE filing (fundamentally different)
    "diagnostic":       9.24,   # IVD LOA ~73% from 510k submission
    "respiratory":      1.09,   # 0.079 × 1.09 = 8.6% [BIO2020]
    "other":            1.00,
}

# Biomarker lever: BIO2020: 25.9% LOA with biomarker vs 8.4% without = 3.08×
# Applied in ptrs_tables.blend_ptrs() with cap at 75%
_BIOMARKER_MULTIPLIER = 2.80   # [BIO2020] conservative application of 3.08×

# Modality nudges: DEPRECATED. Replaced by subcategory-specific PTRS profiles.
_MODALITY_NUDGE = {
    "gene_cell_therapy": 1.00,
    "biologic":          1.00,
    "drug_small_molecule": 1.00,
    "vaccine_immunotherapy": 1.00,
    "medical_device":    1.00,
    "diagnostic":        1.00,
    "digital_health":    1.00,
    "other_platform":    1.00,
}


# ──────────────────────────────────────────────────────────────────────────────
# SUBCATEGORY SCORING PROFILES — Mixture of Experts for market discovery
# Each profile adjusts the four sub-score weights and adds modifiers specific
# to the product vertical. Prevents AMR, gene therapy, SaMD etc. from being
# scored by the same logic as oncology biologics.
# ──────────────────────────────────────────────────────────────────────────────

@dataclasses.dataclass
class _ScoringProfile:
    """Subcategory-specific scoring parameters."""
    # Weight overrides (must sum to ~1.0; replaces globals for this subcategory)
    w_opp:  float = 0.35
    w_prob: float = 0.28
    w_val:  float = 0.25
    w_inn:  float = 0.12
    # Unmet need adjustment (additive on top of the approved-treatment curve)
    unmet_boost: float = 0.0
    # Value ceiling override (log-normalisation ceiling, default $35B)
    value_ceiling_usd: float = 35_000_000_000
    # PTRS base multiplier (multiplicative on TA-specific LOA)
    ptrs_mult: float = 1.0
    # Whether commercial size dominates (True) vs regulatory burden (False)
    commercial_dominant: bool = True
    # Note shown in UI
    note: str = ""


_SUBCATEGORY_PROFILES: dict[str, _ScoringProfile] = {
    # AMR: unmet need is sky-high (CDC urgent threat) but commercial value is
    # structurally depressed (stewardship programs restrict use). Adjust weights.
    "drug_amr": _ScoringProfile(
        w_opp=0.45, w_prob=0.25, w_val=0.18, w_inn=0.12,
        unmet_boost=25.0, value_ceiling_usd=5_000_000_000,
        note="AMR: high unmet need / constrained commercial (stewardship programs limit use)",
    ),
    "drug_amr_community": _ScoringProfile(
        w_opp=0.40, w_prob=0.30, w_val=0.20, w_inn=0.10,
        unmet_boost=15.0, value_ceiling_usd=3_000_000_000,
        note="Community AMR: broader patient access but generic competition faster",
    ),
    # Gene therapy: value ceiling high (one-time curative pricing) but PTRS low
    # (manufacturing + durable safety risk). Weight probability more conservatively.
    "gene_cell_therapy": _ScoringProfile(
        w_opp=0.30, w_prob=0.35, w_val=0.25, w_inn=0.10,
        ptrs_mult=0.85, value_ceiling_usd=10_000_000_000,
        note="Gene therapy: high value ceiling but elevated PTRS risk (manufacturing, durability)",
    ),
    # Oncology: well-characterized trials, biomarker-driven. Innovation weight high.
    "biologic_oncology": _ScoringProfile(
        w_opp=0.32, w_prob=0.28, w_val=0.28, w_inn=0.12,
        value_ceiling_usd=40_000_000_000,
        note="Oncology biologic: biomarker-gated population reduces size but improves PTRS",
    ),
    "drug_oncology": _ScoringProfile(
        w_opp=0.32, w_prob=0.30, w_val=0.26, w_inn=0.12,
        note="Oncology small molecule: established biomarker-driven precision oncology pathways",
    ),
    # Medical devices: higher PTRS (510(k)/PMA clearer than drug approval), but
    # value is procedure-volume based not patient-prevalence based.
    "medical_device": _ScoringProfile(
        w_opp=0.38, w_prob=0.22, w_val=0.28, w_inn=0.12,
        ptrs_mult=1.40, value_ceiling_usd=20_000_000_000,
        note="Medical device: higher regulatory success rate (510k/PMA vs drug), procedure-volume TAM",
    ),
    # IVD diagnostics: very high PTRS (FDA clearance much faster than drug approval)
    # and test-volume based TAM, not prevalence-based.
    "diagnostic": _ScoringProfile(
        w_opp=0.35, w_prob=0.20, w_val=0.32, w_inn=0.13,
        ptrs_mult=1.55, value_ceiling_usd=15_000_000_000,
        note="IVD: fast 510k/De Novo clearance; TAM = test volume × CLFS rate (not drug pricing)",
    ),
    # SaMD/digital health: FDA clearance is easy but COMMERCIAL REALIZATION is very hard.
    # Key corrections vs drugs:
    #  - TAM unit = hospital sites or health systems, NOT patient population
    #  - CMS coverage rate ~15-20% of cleared AI devices get any reimbursement (Bipartisan Policy)
    #  - Hospital budget cycles 12-18 months, EHR integration 6-18 months
    #  - TTO feedback: AI devices often fail commercially despite clinical validation
    # Adjustments: raise opportunity weight (real unmet need), cut probability (commercial)
    # heavily penalize value (hospital market << patient prevalence implies)
    "digital_health": _ScoringProfile(
        w_opp=0.38, w_prob=0.20, w_val=0.32, w_inn=0.10,
        ptrs_mult=0.70,           # FDA clearance easy; COMMERCIAL adoption is the hard part
        value_ceiling_usd=2_000_000_000,   # Enterprise SaaS: ~$2B ceiling (realistic for hospital AI)
        commercial_dominant=False,
        note="SaMD: easy FDA clearance but CMS coverage ~15-20%, hospital budget cycles, EHR integration 6-18mo",
    ),
    # Vaccines: public health value vs commercial value diverge. ACIP recommendation
    # drives both access and revenue. Probability depends on immunogenicity endpoint.
    "vaccine_immunotherapy": _ScoringProfile(
        w_opp=0.40, w_prob=0.28, w_val=0.22, w_inn=0.10,
        unmet_boost=10.0, value_ceiling_usd=25_000_000_000,
        note="Vaccine: ACIP recommendation is the key commercial gate; population-level TAM",
    ),
    # Rare disease: small populations but premium pricing and FDA incentives.
    "drug_rare_disease": _ScoringProfile(
        w_opp=0.30, w_prob=0.30, w_val=0.30, w_inn=0.10,
        unmet_boost=20.0, value_ceiling_usd=8_000_000_000,
        note="Rare disease: orphan pricing offsets small population; strong FDA incentives",
    ),
    "biologic_rare_disease": _ScoringProfile(
        w_opp=0.28, w_prob=0.30, w_val=0.32, w_inn=0.10,
        unmet_boost=25.0, ptrs_mult=0.95, value_ceiling_usd=12_000_000_000,
        note="Rare disease biologic: enzyme replacement pricing $200-500K/yr; orphan market",
    ),
    # CNS: highest Phase 2 failure rate in all of medicine. Weight probability heavily.
    "drug_cns": _ScoringProfile(
        w_opp=0.30, w_prob=0.40, w_val=0.22, w_inn=0.08,
        ptrs_mult=0.65, value_ceiling_usd=15_000_000_000,
        note="CNS: highest clinical failure rate; Phase 2 attrition ~80% (FDA, 2023)",
    ),
    # Immunology/autoimmune: crowded but validated; biosimilar competition compresses value.
    "drug_immunology": _ScoringProfile(
        w_opp=0.32, w_prob=0.30, w_val=0.26, w_inn=0.12,
        value_ceiling_usd=20_000_000_000,
        note="Immunology: crowded with biosimilars; differentiation via mechanism or convenience critical",
    ),
    "biologic_immunology": _ScoringProfile(
        w_opp=0.30, w_prob=0.30, w_val=0.28, w_inn=0.12,
        value_ceiling_usd=25_000_000_000,
        note="Autoimmune biologic: biosimilar pressure growing; mechanistic differentiation needed",
    ),
}

_SUBCATEGORY_PROFILE_MAP: dict[str, str] = {
    # Maps TA strings and modality strings to profile keys
    "amr_infectious": "drug_amr",
    "gene_therapy": "gene_cell_therapy",
    "gene_cell_therapy": "gene_cell_therapy",
    "rare_disease": "drug_rare_disease",
    "biologic_rare": "biologic_rare_disease",
    "cns": "drug_cns",
    "oncology": "drug_oncology",
    "biologic": "biologic_oncology",
    "biologic_oncology": "biologic_oncology",
    "device": "medical_device",
    "medical_device": "medical_device",
    "diagnostic": "diagnostic",
    "digital_health": "digital_health",
    "software_samd": "digital_health",
    "vaccine": "vaccine_immunotherapy",
    "vaccine_immunotherapy": "vaccine_immunotherapy",
    "immunology": "drug_immunology",
    "biologic_immunology": "biologic_immunology",
    "drug_rare_disease": "drug_rare_disease",
    "drug_amr": "drug_amr",
}


def _get_scoring_profile(therapeutic_area: str, modality: str) -> _ScoringProfile:
    """
    Return subcategory scoring profile. TA takes priority over modality for
    TAs with dominant clinical characteristics (CNS failure rate, AMR stewardship,
    rare disease pricing), but modality wins for oncology (biologic vs small mol differs).
    """
    ta = therapeutic_area.lower()
    mod = modality.lower()

    # TA-dominant: the TA characteristic overrides modality classification
    _TA_DOMINANT = {"cns", "amr_infectious", "amr", "gene_therapy", "rare_disease",
                    "vaccine", "digital_health", "diagnostic"}
    if any(t in ta for t in _TA_DOMINANT):
        key = _SUBCATEGORY_PROFILE_MAP.get(ta) or _SUBCATEGORY_PROFILE_MAP.get(mod)
    else:
        # Modality-dominant for oncology and immunology (biologic vs small mol matters a lot)
        key = _SUBCATEGORY_PROFILE_MAP.get(mod) or _SUBCATEGORY_PROFILE_MAP.get(ta)

    return _SUBCATEGORY_PROFILES.get(key, _ScoringProfile())


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
    subcategory_weights: Optional[dict] = None,
) -> tuple[float, dict]:
    """
    Cumulative probability of technical + regulatory success → 0..100.

    Now uses hard published LOA numbers from ptrs_tables.py (BIO2020, Wong2019,
    FDA CDRH data) — NOT arbitrary multipliers applied to a generic baseline.

    If subcategory_weights is provided (soft routing), blends PTRS across
    multiple subcategories proportionally. Otherwise infers subcategory from
    therapeutic_area + modality.
    """
    try:
        from app.services.ptrs_tables import get_ptrs, blend_ptrs, PTRS_REGISTRY
    except ImportError:
        # Fallback to legacy multiplier method if ptrs_tables unavailable
        phase = development_phase.lower()
        ta = therapeutic_area.lower()
        base = _BASE_LOA_FROM_PHASE.get(phase, 0.079)
        ta_mult = _TA_LOA_MULTIPLIER.get(ta, 1.00)
        loa = base * ta_mult
        if has_biomarker:
            loa = min(loa * _BIOMARKER_MULTIPLIER, 0.75)
        ptrs_pct = round(loa * 100, 1)
        _LOG_K = 99.0
        score = min(100.0, 100.0 * math.log1p(loa * _LOG_K) / math.log1p(_LOG_K))
        return _clamp(score), {"ptrs_pct": ptrs_pct, "loa": round(loa, 4), "source": "legacy_fallback"}

    # Determine subcategory from TA + modality if no soft weights provided
    if subcategory_weights:
        loa, ptrs_pct, citation = blend_ptrs(subcategory_weights, development_phase, has_biomarker)
        blend_source = "soft_routing_blend"
    else:
        # Map TA + modality to most likely subcategory
        sub_id = _ta_modality_to_subcategory(therapeutic_area, modality)
        loa, ptrs_pct, citation = get_ptrs(sub_id, development_phase, has_biomarker)
        blend_source = sub_id

    # Crowding drag: saturated competitive race raises enrollment/endpoint risk
    # Applies beyond 15 active trials; floored at 0.60 (some LOA always remains)
    # Source: FDA PDUFA performance reports — NDA receipt-to-approval not affected
    # by competitor count, but clinical development success is.
    if competitor_trial_count > 15:
        drag = max(0.60, 1.0 - (competitor_trial_count - 15) * 0.005)
        loa = loa * drag

    loa = min(loa, 0.85)   # cap: even favored programs have residual uncertainty
    ptrs_pct = round(loa * 100, 2)

    # Log-scaled 0-100 score:
    # Spreads the realistic LOA range (3%-85%) across full 0-100 band.
    # k=99: 0.05→35, 0.08→47, 0.15→63, 0.24→73, 0.40→83, 0.70→93
    _LOG_K = 99.0
    score = min(100.0, 100.0 * math.log1p(loa * _LOG_K) / math.log1p(_LOG_K))

    return _clamp(score), {
        "ptrs_pct": ptrs_pct,
        "loa": round(loa, 4),
        "subcategory": blend_source,
        "biomarker_applied": has_biomarker,
        "citation": citation[:80] if citation else "",
        "source": "ptrs_tables_bio2020",
    }


def _ta_modality_to_subcategory(therapeutic_area: str, modality: str) -> str:
    """Map TA + modality to the most specific subcategory for PTRS lookup."""
    ta = therapeutic_area.lower()
    mod = modality.lower()

    # Modality-specific mappings (take priority for clear modalities)
    if "gene_cell" in mod or "gene therapy" in mod:
        if "cns" in ta:                 return "gene_therapy_cns"
        if "hematol" in ta or "blood" in ta or "sickle" in ta: return "gene_therapy_hematology"
        if "oncol" in ta or "cancer" in ta: return "gene_therapy_oncology"
        return "gene_therapy_rare"
    if "diagnostic" in mod:
        return "diagnostic_molecular_lab"
    if "digital" in mod or "samd" in mod or "software" in mod:
        return "digital_cds"
    if "vaccine" in mod:
        if "cancer" in ta or "oncol" in ta: return "vaccine_cancer_immuno"
        return "vaccine_prophylactic"
    if "medical_device" in mod:
        if "cardio" in ta or "cardiac" in ta: return "device_cardiovascular"
        return "device_surgical_orthopedic"
    if "biologic" in mod:
        if "oncol" in ta or "cancer" in ta: return "biologic_oncology"
        if "immun" in ta or "autoimmune" in ta: return "biologic_immunology"
        if "hematol" in ta:              return "biologic_hematology"
        if "rare" in ta or "orphan" in ta: return "biologic_rare_disease"
        return "biologic_oncology"

    # TA-specific for small molecules
    _TA_MAP = {
        "amr_infectious":  "drug_amr",
        "amr":             "drug_amr",
        "oncology":        "drug_oncology",
        "cns":             "drug_cns_neurodegen",
        "cardiovascular":  "drug_cardiovascular",
        "metabolic":       "drug_metabolic",
        "immunology":      "drug_immunology",
        "rare_disease":    "drug_rare_disease",
        "gene_therapy":    "gene_therapy_rare",
        "hematology":      "biologic_hematology",
        "vaccine":         "vaccine_prophylactic",
        "device":          "device_cardiovascular",
        "diagnostic":      "diagnostic_molecular_lab",
        "respiratory":     "drug_cns_acute",   # respiratory LOA similar to CNS acute
        "ophthalmology":   "biologic_immunology",  # retinal biologics similar LOA to immunology
    }
    for key, sub in _TA_MAP.items():
        if key in ta:
            return sub
    return "drug_oncology"  # conservative default


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
    idea_text: Optional[str] = None,        # If provided, enables soft routing
    soft_weights: Optional[dict] = None,    # Pre-computed soft routing weights
) -> dict:
    # ── Soft routing: load idea-specific weight vector ─────────────────────────
    # If idea_text is provided, compute signal-based weights for blended scoring.
    # If soft_weights are pre-computed (from the report pipeline), use those.
    # Otherwise fall back to hard TA/modality profile lookup.
    _soft_weights = None
    _blend_note = None
    if soft_weights:
        _soft_weights = soft_weights
    elif idea_text:
        try:
            from app.services.soft_router import soft_route, blend_scoring_profile
            routing = soft_route(idea_text)
            _soft_weights = routing.weights
            _blend_note = routing.blend_note
        except Exception:
            _soft_weights = None

    if _soft_weights:
        try:
            from app.services.soft_router import blend_scoring_profile
            blended = blend_scoring_profile(_soft_weights)
            w_opp  = blended["w_opp"]
            w_prob = blended["w_prob"]
            w_val  = blended["w_val"]
            w_inn  = blended["w_inn"]
            _unmet_boost  = blended["unmet_boost"]
            _ptrs_mult    = blended["ptrs_mult"]
        except Exception:
            # Fallback to hard profile
            profile = _get_scoring_profile(therapeutic_area, modality)
            w_opp, w_prob, w_val, w_inn = profile.w_opp, profile.w_prob, profile.w_val, profile.w_inn
            _unmet_boost, _ptrs_mult = profile.unmet_boost, profile.ptrs_mult
    else:
        # Hard subcategory-specific scoring profile (MoE for discovery)
        profile = _get_scoring_profile(therapeutic_area, modality)
        w_opp  = profile.w_opp
        w_prob = profile.w_prob
        w_val  = profile.w_val
        w_inn  = profile.w_inn
        _unmet_boost = profile.unmet_boost
        _ptrs_mult   = profile.ptrs_mult

    opp, opp_b = opportunity_score(
        approved_treatments_count=approved_treatments_count,
        competitor_trial_count=competitor_trial_count,
        us_patient_population=us_patient_population,
        therapeutic_area=therapeutic_area,
        dalys=dalys,
    )
    # Apply subcategory unmet need boost (diminishing returns near ceiling)
    if _unmet_boost > 0:
        opp = _clamp(opp + _unmet_boost * (1 - opp / 100))
        opp_b["subcategory_unmet_boost"] = round(_unmet_boost, 1)

    # Probability: now uses hard published PTRS from ptrs_tables.py
    # Pass subcategory_weights for soft-blended LOA if available
    prob, prob_b = probability_score(
        development_phase=development_phase,
        therapeutic_area=therapeutic_area,
        has_biomarker=has_biomarker,
        modality=modality,
        competitor_trial_count=competitor_trial_count,
        subcategory_weights=_soft_weights,
    )
    # Apply subcategory PTRS multiplier only if it differs from 1.0
    if _ptrs_mult != 1.0:
        prob = _clamp(prob * _ptrs_mult)
        prob_b["subcategory_ptrs_mult"] = round(_ptrs_mult, 3)

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

    # Geometric combination with subcategory-specific weights
    score_raw = (opp ** w_opp) * (prob ** w_prob) * (val ** w_val) * (max(inn, 1.0) ** w_inn)
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
        "subcategory_note": _blend_note or (profile.note if not _soft_weights else None),
        "soft_routing": dict(sorted((_soft_weights or {}).items(), key=lambda x: -x[1])[:3]) if _soft_weights else None,
        "subscores": {
            "opportunity": round(opp, 1),
            "probability": round(prob, 1),
            "value": round(val, 1),
            "innovation": round(inn, 1),
        },
        "components": {**opp_b, **prob_b, **val_b, **inn_b},
        "weights": {
            "opportunity": w_opp,
            "probability": w_prob,
            "value": w_val,
            "innovation": w_inn,
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
        # Outer try catches any error outside the inner v2-scoring try block
        # (e.g. compute_market_size failing) so one disease never crashes all 309.
        try:
          return await _score_one_inner(opp, funding_pathway)
        except Exception as e:
          _logger.error("score_one outer failed for %s: %s", opp[0] if opp else "?", e)
          return None

    async def _score_one_inner(opp, funding_pathway):
        disease, ta, phase, approved, cost, notes = opp

        # ── Database-backed enrichment (replaces hardcoded _TA_DEFAULTS) ──────────
        # Uses: NCI SEER, cBioPortal GENIE, Orphanet, CMS Part D/B, AHRQ MEPS,
        #       CMS MA Formulary files — all pre-loaded, zero API latency
        from app.services.disease_data_enricher import get_enrichment_data
        enrichment = get_enrichment_data(disease, ta)

        # Override TA defaults with enriched data from specialized sources
        pop      = enrichment.us_patient_population
        cost     = enrichment.annual_treatment_cost   # CMS-grounded pricing
        biomarker = enrichment.has_biomarker
        # Subcategory-aware modality (from soft routing)
        sub_id   = enrichment.subcategory_id
        modality = (
            "gene_cell_therapy" if "gene_therapy" in sub_id
            else "biologic"     if "biologic" in sub_id
            else "diagnostic"   if "diagnostic" in sub_id
            else "digital_health" if "digital" in sub_id
            else "medical_device" if "device" in sub_id
            else "vaccine_immunotherapy" if "vaccine" in sub_id
            else "drug_small_molecule"
        )

        # Realized TAM factor from formulary + MEPS (new — key differentiator)
        realized_tam_factor = enrichment.realized_tam_factor

        # Legacy fallback for any field that enricher didn't fill
        _, _legacy_pop, _legacy_biomarker, _legacy_modality, _old_dalys = _DISEASE_OVERRIDES.get(
            disease, _TA_DEFAULTS.get(ta, _TA_DEFAULTS["other"])
        )
        if pop <= 0:
            pop = _legacy_pop
        if not biomarker:
            biomarker = _legacy_biomarker

        # DALYs — commercial-safe first (WHO GHO/DB), GBD only as R&D fallback
        dalys, daly_source = await _get_commercial_safe_dalys(disease, ta)
        if dalys is None:
            dalys = _old_dalys
            daly_source = "hardcoded"

        # Real US prevalence: universe_builder → enricher → static file → TA default
        try:
            from app.services.universe_builder import get_disease_population
            known_pop = get_disease_population(disease)
            if known_pop and known_pop > 0:
                pop = known_pop
        except Exception:
            pass
        pop = pop or _PREVALENCE_DISEASE.get(disease) or _PREVALENCE_TA.get(ta) or _legacy_pop
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
                # Apply formulary + MEPS realized TAM adjustment
                tam_peak_revenue=(tam["peak_revenue_usd"] * realized_tam_factor) if tam else None,
                is_first_in_class=first_in_class,
                soft_weights={sub_id: 1.0},   # Use enrichment-derived subcategory
            )
            r["daly_source"] = daly_source
            # Surface enrichment data for the frontend
            r["enrichment"] = {
                "subcategory_id":      enrichment.subcategory_id,
                "population_source":   enrichment.population_source,
                "pricing_source":      enrichment.pricing_source,
                "formulary_coverage":  enrichment.formulary_coverage,
                "pa_approval_rate":    enrichment.pa_approval_rate,
                "meps_fill_rate":      enrichment.meps_fill_rate,
                "meps_adherence":      enrichment.meps_adherence_rate,
                "realized_tam_factor": realized_tam_factor,
                "biomarker_eligible":  enrichment.biomarker_eligible,
                "biomarker_fraction":  enrichment.biomarker_fraction,
                "cache_hit":           enrichment.cache_hit,
            }
            # TAM fields for the frontend
            if tam:
                r["us_tam_usd"]        = round(tam["us_tam_usd"])
                r["peak_revenue_usd"]  = round(tam["peak_revenue_usd"])
                r["us_tam_fmt"]        = tam.get("us_tam_fmt") or format_tam(tam["us_tam_usd"])
                r["peak_revenue_fmt"]  = tam.get("peak_revenue_fmt") or format_tam(tam["peak_revenue_usd"])
                r["tam_formula"]       = tam["formula"]
                r["pricing_rationale"] = tam.get("pricing_rationale", "")
                # Engine-specific enrichment (always from new engine)
                bass_meta = engine_tam.get("bass", {})
                r["market_sizing"] = {
                    "dot_years":         engine_tam.get("dot", {}).get("years", 5.0),
                    "dot_category":      engine_tam.get("dot", {}).get("category", "chronic"),
                    "bass_penetration_y5": (
                        bass_meta.get("capturable_y5")
                        or engine_tam.get("combined_penetration")
                        or bass_meta.get("total_market_penetration_y5", 0.1)
                    ),
                    "peak_adoption_year":bass_meta.get("peak_adoption_year", 5.0),
                    "diagnostic_yield":  engine_tam.get("cascade", {}).get("diagnostic_yield", 0.65),
                    "eligible_patients": engine_tam.get("cascade", {}).get("eligible", pop),
                    "net_price_pct_wac": engine_tam.get("pricing", {}).get("gross_to_net_pct", 0.65),
                    "bia_concern":       engine_tam.get("bia", {}).get("affordability_concern", False),
                    "bia_dampening":     engine_tam.get("bia", {}).get("revenue_dampening", 1.0),
                }
            # Store trial + approval counts so tractability computation can read them
            # (score_opportunity_v2 doesn't return these — must add explicitly)
            r["competitor_trial_count"]    = trials
            r["approved_treatments_count"] = approved
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

    results = await _asyncio.gather(*[score_one(o) for o in OPPORTUNITY_UNIVERSE],
                                    return_exceptions=True)
    scored = [r for r in results if r is not None and not isinstance(r, Exception)]

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
        # Read actual live-fetched values (stored by _score_one_inner above)
        trials_count = int(r.get("competitor_trial_count", 5) or 5)
        approved_val = int(r.get("approved_treatments_count", 0) or 0)

        # Population scale: small markets get penalized to prevent ultra-rare dominating
        scale = _pop_scale(pop_val)

        # Commercial tractability penalty — the most important new check.
        # Diseases with 0 approved therapies AND very few active trials have NO
        # validated clinical/commercial path. High unmet need + no trials =
        # scientifically interesting but commercially speculative.
        # Source: McKinsey drug development analysis — 95%+ of diseases with
        # 0 approvals and <3 trials never reach commercial stage.
        # Examples: 22q11.2 deletion (no validated DMT path), AKI (complex endpoint
        # validation failures). These should rank behind diseases with proven paths.
        tractability_scale = 1.0
        if approved_val == 0 and trials_count < 5:
            # No approved therapy + very thin pipeline = speculative opportunity
            tractability_scale = 0.55
            r["commercial_tractability"] = "SPECULATIVE"
            r["tractability_note"] = f"0 approved therapies + {trials_count} active trials — no validated clinical path yet"
        elif approved_val == 0 and trials_count < 15:
            # Emerging but unproven
            tractability_scale = 0.78
            r["commercial_tractability"] = "EMERGING"
            r["tractability_note"] = f"0 approved therapies; {trials_count} trials show emerging interest"
        elif approved_val >= 3 and trials_count >= 20:
            # Crowded but commercially validated
            r["commercial_tractability"] = "VALIDATED_CROWDED"
        else:
            r["commercial_tractability"] = "VIABLE"

        combined_scale = scale * tractability_scale
        if combined_scale < 1.0:
            r["score"]     = round(r["score"] * combined_scale, 1)
            r["score_raw"] = round(r.get("score_raw", r["score"]) * combined_scale, 2)
            if scale < 1.0:
                r["rare_disease_penalty"] = True
        # Re-tier after scaling
        r["tier"], r["tier_color"] = _tier(r["score"])

        # Compute SAM explicitly for frontend display
        # SAM = peak_revenue_usd (already risk-adjusted via Bass + BIA + formulary + MEPS)
        peak = r.get("peak_revenue_usd") or 0
        r["sam_usd"] = round(peak)
        r["sam_fmt"] = (f"${peak/1e9:.1f}B" if peak >= 1e9 else
                        f"${peak/1e6:.0f}M" if peak >= 1e6 else
                        f"${peak/1e3:.0f}K")

    # SORT BY SAM (risk-adjusted commercial value) not composite score.
    # Rationale: SAM already incorporates PTRS, Bass diffusion, formulary coverage,
    # MEPS adherence, and BIA affordability — it IS the risk-adjusted expected value.
    # Ranking by SAM ensures commercially viable diseases (large + tractable + accessible)
    # surface above academically interesting but commercially speculative diseases.
    scored.sort(key=lambda x: x.get("sam_usd", 0), reverse=True)

    # Add rank field
    for i, r in enumerate(scored, 1):
        r["rank"] = i
    return scored[:top_n]
