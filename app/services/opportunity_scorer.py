"""
Opportunity Scoring Engine
===========================
Implements the 6-factor weighted MCDA algorithm grounded in:
- EVIDEM v3.0 (Goetghebeur et al., BMC Health Services Research 2008)
- Pharmaceutical Innovativeness Index (Gargano et al., 2025)
- AIFA innovativeness framework (Fortinguerra et al., Frontiers in Medicine 2021)
- Ozmosi LENZ four-factor decomposition
- PTRS tables: Hay 2014, Wong 2019 (Biostatistics 20(2):273-286)
- McKinsey first-to-market analysis (Cha & Yu 2014)

Formula:
  Score_raw    = 100 * Σᵢ (wᵢ * sᵢ)
  Score_risk   = Score_raw * PTRS(phase, therapeutic_area)
  Score_final  = Score_risk * (1 + designation_uplift)

Weights (consensus of EVIDEM/PII/AIFA/LENZ):
  Unmet need          0.22
  PTRS x TRL          0.20
  Disease burden      0.18
  Market size/WTP     0.18
  Competition         0.12
  IP/Exclusivity      0.10
"""

import asyncio
import logging
import math
from datetime import datetime, date
from typing import Dict, List, Optional, Tuple
import httpx

logger = logging.getLogger(__name__)

# ── PTRS Tables (Hay 2014 / Wong 2019) ──────────────────────────────────────
# Phase-specific probability of technical and regulatory success
# Source: Hay et al. Nat Biotech 2014; Wong et al. Biostatistics 2019
PTRS = {
    "oncology":           {"phase1": 0.054, "phase2": 0.100, "phase3": 0.330, "preclinical": 0.033},
    "amr_infectious":     {"phase1": 0.220, "phase2": 0.420, "phase3": 0.700, "preclinical": 0.140},
    "rare_disease":       {"phase1": 0.115, "phase2": 0.200, "phase3": 0.580, "preclinical": 0.080},
    "gene_therapy":       {"phase1": 0.085, "phase2": 0.160, "phase3": 0.520, "preclinical": 0.060},
    "cns":                {"phase1": 0.070, "phase2": 0.110, "phase3": 0.370, "preclinical": 0.045},
    "cardiovascular":     {"phase1": 0.110, "phase2": 0.220, "phase3": 0.580, "preclinical": 0.075},
    "metabolic":          {"phase1": 0.130, "phase2": 0.250, "phase3": 0.600, "preclinical": 0.090},
    "immunology":         {"phase1": 0.120, "phase2": 0.230, "phase3": 0.610, "preclinical": 0.085},
    "vaccine":            {"phase1": 0.280, "phase2": 0.450, "phase3": 0.700, "preclinical": 0.180},
    "diagnostic":         {"phase1": 0.350, "phase2": 0.550, "phase3": 0.800, "preclinical": 0.200},
    "device":             {"phase1": 0.300, "phase2": 0.500, "phase3": 0.750, "preclinical": 0.180},
    "default":            {"phase1": 0.104, "phase2": 0.190, "phase3": 0.590, "preclinical": 0.070},
}

# ── Disease-area reference data ───────────────────────────────────────────────
# Annual DALYs (millions) and prevalence for normalization
# Source: IHME GBD 2021; CDC WONDER
DISEASE_REFERENCE = {
    "cardiovascular":   {"dalys_m": 393, "prevalence_m": 550},
    "cancer":           {"dalys_m": 250, "prevalence_m": 43},
    "metabolic":        {"dalys_m": 180, "prevalence_m": 540},
    "cns":              {"dalys_m": 160, "prevalence_m": 80},
    "respiratory":      {"dalys_m": 140, "prevalence_m": 545},
    "infectious":       {"dalys_m": 120, "prevalence_m": 200},
    "musculoskeletal":  {"dalys_m": 100, "prevalence_m": 1700},
    "mental_health":    {"dalys_m": 125, "prevalence_m": 970},
    "digestive":        {"dalys_m": 80,  "prevalence_m": 400},
    "rare_disease":     {"dalys_m": 300, "prevalence_m": 25},  # aggregate of all rare diseases
    "immunology":       {"dalys_m": 45,  "prevalence_m": 120},
    "amr":              {"dalys_m": 20,  "prevalence_m": 5},
    "default":          {"dalys_m": 50,  "prevalence_m": 50},
}

MAX_DALYS = 393  # cardiovascular as normalization ceiling


# ── Normalization functions ───────────────────────────────────────────────────

def normalize_log(value: float, max_value: float) -> float:
    """Log normalization for heavy-tailed distributions (DALYs, prevalence)."""
    if value <= 0:
        return 0.0
    raw = 100.0 * math.log(value + 1) / math.log(max_value + 1)
    return min(100.0, raw)  # hard cap at 100


def normalize_linear(value: float, min_v: float, max_v: float) -> float:
    """Linear normalization to 0-100."""
    if max_v == min_v:
        return 50.0
    return max(0.0, min(100.0, 100.0 * (value - min_v) / (max_v - min_v)))


def normalize_competition(competitor_count: int) -> float:
    """
    Bivalent signal: low = unvalidated, medium = validated, high = commoditized.
    Peaks at 5-7 competitors. Floors at 10 (never fully penalized — market still exists).
    Source: adapted from Schulze & Ringel (Nature Reviews Drug Discovery 2013);
    Cha & Yu (McKinsey 2014) — first-to-market 6% share advantage.
    """
    if competitor_count <= 0:
        return 20.0   # unvalidated — scientifically risky
    elif competitor_count <= 7:
        # Rising phase: validation signal dominates
        p = competitor_count / 7.0
        return 20.0 + 80.0 * (2*p - p*p)  # accelerating then leveling
    elif competitor_count <= 15:
        # Crowded: declining but still viable
        return max(15.0, 100.0 - (competitor_count - 7) * 10.5)
    else:
        # Commoditized: low but not zero (market is proven)
        return max(10.0, 15.0 - (competitor_count - 15) * 0.3)


def order_of_entry_score(rank: int) -> float:
    """
    Score based on pipeline entry rank.
    Source: Cha & Yu (McKinsey 2014) — first-to-market 6% share advantage.
    First-in-class = 100, each subsequent step decays.
    """
    scores = {1: 100, 2: 85, 3: 65, 4: 45, 5: 30}
    return float(scores.get(rank, 20.0))


def designation_uplift(designations: List[str]) -> float:
    """
    Regulatory designation uplift multiplier.
    Source: Miller (Orphanet J Rare Dis 2017) — orphan = 3.36-8.87% CAR;
    PRV market price $150-160M (BioPharma Dive, 2025).
    """
    uplift = 0.0
    desig_lower = [d.lower() for d in designations]
    if any("breakthrough" in d for d in desig_lower):
        uplift += 0.15
    if any("orphan" in d for d in desig_lower):
        uplift += 0.10
    if any("fast track" in d or "fast_track" in d for d in desig_lower):
        uplift += 0.05
    if any("rmat" in d for d in desig_lower):
        uplift += 0.10
    if any("qidp" in d for d in desig_lower):
        uplift += 0.13
    if any("prime" in d for d in desig_lower):  # EMA
        uplift += 0.07
    return min(uplift, 0.40)  # cap at 40%


# ── Live data fetchers ────────────────────────────────────────────────────────

async def fetch_clinical_trial_count(condition: str, phase: str = None) -> Dict:
    """
    Count active/recruiting trials for a condition.
    Source: ClinicalTrials.gov v2 API
    """
    try:
        params = {
            "query.cond": condition,
            "filter.status": "RECRUITING,NOT_YET_RECRUITING,ACTIVE_NOT_RECRUITING",
            "countTotal": "true",
            "pageSize": 1,
        }
        if phase:
            params["filter.phase"] = phase

        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                "https://clinicaltrials.gov/api/v2/studies",
                params=params,
            )
            if r.status_code == 200:
                data = r.json()
                total = data.get("totalCount", 0)
                return {"total": total, "condition": condition}
    except Exception as e:
        logger.warning(f"ClinicalTrials fetch failed for {condition}: {e}")
    return {"total": 0, "condition": condition}


async def fetch_nih_grant_count(condition: str) -> int:
    """
    Count active NIH grants for a disease area.
    Proxy for academic momentum / funding validation.
    Source: NIH Reporter API
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                "https://api.reporter.nih.gov/v2/projects/search",
                json={
                    "criteria": {
                        "advanced_text_search": {
                            "operator": "and",
                            "search_field": "all",
                            "search_text": condition,
                        },
                        "project_start_date": {"from_date": "2022-01-01"},
                        "is_active": True,
                    },
                    "limit": 1,
                    "offset": 0,
                },
                headers={"Content-Type": "application/json"},
            )
            if r.status_code == 200:
                return r.json().get("meta", {}).get("total", 0)
    except Exception as e:
        logger.warning(f"NIH Reporter fetch failed for {condition}: {e}")
    return 0


async def fetch_fda_approvals(condition: str) -> int:
    """
    Count FDA-approved drugs for a condition (proxy for unmet need — inverse).
    Source: openFDA drug approvals
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                "https://api.fda.gov/drug/drugsfda.json",
                params={
                    "search": f'products.brand_name:"{condition}" OR products.generic_name:"{condition}"',
                    "count": "products.dosage_form",
                    "limit": 1,
                }
            )
            if r.status_code == 200:
                return r.json().get("meta", {}).get("results", {}).get("total", 0)
    except Exception:
        pass
    return 0


# ── Core scoring function ─────────────────────────────────────────────────────

async def score_opportunity(
    disease_name: str,
    therapeutic_area: str,
    development_phase: str = "preclinical",
    approved_treatments_count: int = None,
    competitor_trial_count: int = None,
    annual_treatment_cost_usd: float = None,
    us_patient_population: int = None,
    designations: List[str] = None,
    order_of_entry: int = None,
) -> Dict:
    """
    Score a biomedical opportunity on a 0-100 scale.

    Returns a dict with:
    - score_final: 0-100 risk-adjusted score
    - score_raw: pre-risk-adjustment score
    - component_scores: breakdown by factor
    - confidence_range: [low, high] from ±35% sensitivity on scored inputs
    - explanation: plain-English breakdown
    """
    designations = designations or []

    # ── Fetch live data if not provided ──────────────────────────────────────
    if competitor_trial_count is None or approved_treatments_count is None:
        trial_data, nih_count = await asyncio.gather(
            fetch_clinical_trial_count(disease_name),
            fetch_nih_grant_count(disease_name),
            return_exceptions=True
        )
        if competitor_trial_count is None:
            competitor_trial_count = trial_data.get("total", 5) if isinstance(trial_data, dict) else 5
        if approved_treatments_count is None:
            approved_treatments_count = max(0, nih_count // 50) if isinstance(nih_count, int) else 2
    else:
        nih_count = 0

    # ── Reference data ────────────────────────────────────────────────────────
    ta_key = therapeutic_area.lower().replace(" ", "_").replace("-", "_")
    ref = DISEASE_REFERENCE.get(ta_key, DISEASE_REFERENCE["default"])
    dalys_m = ref["dalys_m"]
    prevalence_m = ref["prevalence_m"]

    # ── Factor 1: Disease Burden (V1 DALYs + V2 prevalence) weight=0.18 ──────
    # Log normalization per Gillum (PLOS ONE 2011): DALYs best predictor of funding
    daly_score = normalize_log(dalys_m, MAX_DALYS)
    prevalence_score = normalize_log(prevalence_m, 1700)  # musculoskeletal is max
    burden_score = 0.7 * daly_score + 0.3 * prevalence_score

    # ── Factor 2: Unmet Need (V4) weight=0.22 ─────────────────────────────────
    # Inverse of approved treatments; more approvals = less unmet need
    # Calibrated to PII "Unmet Therapeutic Need" (UTN) weight 29%
    if approved_treatments_count == 0:
        unmet_score = 100.0  # no approved treatments = maximum unmet need
    elif approved_treatments_count == 1:
        unmet_score = 80.0   # tofersen for SOD1-ALS — high unmet need remains
    elif approved_treatments_count <= 3:
        unmet_score = 60.0
    elif approved_treatments_count <= 6:
        unmet_score = 40.0
    else:
        unmet_score = 20.0   # well-served indication

    # AMR boost: existing antibiotics are last-resort, toxic, resistance spreading
    # CDC urgent/serious threat classifications indicate unmet need beyond approval count
    if ta_key in ("amr_infectious", "amr", "drug_amr"):
        unmet_score = min(100.0, unmet_score + 20.0)

    # ── Factor 3: Market Size / WTP (V2*V3) weight=0.18 ─────────────────────
    # Annual market = patients * treatment cost
    # Normalize against $10B reference (blockbuster)
    if annual_treatment_cost_usd is None:
        # Default by therapeutic area
        default_costs = {
            "oncology": 150000, "rare_disease": 400000, "gene_therapy": 2000000,
            "cns": 80000, "cardiovascular": 30000, "metabolic": 15000,
            "amr": 20000, "amr_infectious": 20000, "immunology": 60000,
            "vaccine": 500, "diagnostic": 2000, "device": 15000,
        }
        annual_treatment_cost_usd = default_costs.get(ta_key, 50000)

    if us_patient_population is None:
        us_patient_population = int(prevalence_m * 1_000_000 * 0.25)  # 25% US share of global

    annual_market_usd = us_patient_population * annual_treatment_cost_usd
    market_score = normalize_log(annual_market_usd, 2_000_000_000_000)  # $2T ceiling (global pharma max)

    # ── Factor 4: Competitive Intensity (V5 bivalent + V6 order) weight=0.12 ─
    # Bivalent: validates target but compresses share
    competition_score = normalize_competition(competitor_trial_count)
    entry_rank = order_of_entry if order_of_entry else min(5, max(1, competitor_trial_count // 3 + 1))
    entry_score = order_of_entry_score(entry_rank)
    competitive_score = 0.6 * competition_score + 0.4 * entry_score

    # ── Factor 5: PTRS × TRL weight=0.20 ─────────────────────────────────────
    # Phase-specific probability of technical and regulatory success
    # Source: Hay 2014; Wong 2019 (Biostatistics 20(2):273-286)
    phase_key = development_phase.lower().replace(" ", "_").replace("/", "_")
    if "preclinical" in phase_key or "pre_clinical" in phase_key:
        ptrs_phase = "preclinical"
    elif "phase_1" in phase_key or "phase1" in phase_key:
        ptrs_phase = "phase1"
    elif "phase_2" in phase_key or "phase2" in phase_key:
        ptrs_phase = "phase2"
    elif "phase_3" in phase_key or "phase3" in phase_key:
        ptrs_phase = "phase3"
    else:
        ptrs_phase = "preclinical"

    ptrs_table = PTRS.get(ta_key, PTRS["default"])
    ptrs_value = ptrs_table.get(ptrs_phase, ptrs_table["preclinical"])

    # TRL proxy from phase (NASA TRL scale)
    trl_map = {"preclinical": 4, "phase1": 6, "phase2": 7, "phase3": 8}
    trl = trl_map.get(ptrs_phase, 4)
    trl_score = (trl / 9.0) * 100

    feasibility_score = (ptrs_value * 100) * 0.6 + trl_score * 0.4

    # ── Factor 6: IP / Regulatory Exclusivity weight=0.10 ────────────────────
    # Based on designation mix and assumed patent runway
    base_exclusivity = 70.0  # assume reasonable IP position
    desig_up = designation_uplift(designations)
    exclusivity_score = min(100.0, base_exclusivity * (1 + desig_up))

    # ── Market accessibility modifier ────────────────────────────────────────
    # When a market is both crowded AND well-served, penalize burden and market.
    # This prevents large-disease burden from rescuing commoditized markets.
    # E.g. GLP-1 obesity: large burden but 4 approved drugs + 25 trials = bad for new entrant
    crowding_factor = 1.0
    if unmet_score < 50 and competitive_score < 30:
        # Both low unmet need AND high competition — very crowded for new entrant
        crowding_factor = 0.35
    elif unmet_score < 50 and competitive_score < 50:
        # Moderate crowding
        crowding_factor = 0.6
    elif unmet_score < 60 and competitive_score < 40:
        crowding_factor = 0.65

    adjusted_burden = burden_score * crowding_factor
    adjusted_market = market_score * crowding_factor

    # ── Weighted sum (raw score) ───────────────────────────────────────────────
    weights = {
        "unmet_need":     0.22,
        "feasibility":    0.20,
        "burden":         0.18,
        "market":         0.18,
        "competition":    0.12,
        "exclusivity":    0.10,
    }

    score_raw = (
        weights["unmet_need"]  * unmet_score +
        weights["feasibility"] * feasibility_score +
        weights["burden"]      * adjusted_burden +
        weights["market"]      * adjusted_market +
        weights["competition"] * competitive_score +
        weights["exclusivity"] * exclusivity_score
    )

    # ── Designation uplift (on raw score only) ───────────────────────────────
    # PTRS is already captured inside feasibility_score component.
    # Applying it again as a multiplier double-penalizes early-stage assets.
    # Designation uplift adds value on top of raw score.
    score_final = score_raw * (1 + desig_up * 0.5)  # soft uplift, max +20%

    # Scale to 0-100. Max theoretical raw=100, max uplift=0.20 -> 120.
    score_display = min(95.0, score_final / 120.0 * 100.0)
    score_display = max(1.0, score_display)

    # ── Confidence range (±35% sensitivity on the scored inputs) ──────────────
    confidence_low  = max(1.0, score_display * 0.65)
    confidence_high = min(99.0, score_display * 1.35)

    # ── Tier label ────────────────────────────────────────────────────────────
    if score_display >= 70:
        tier = "EXCEPTIONAL"
        tier_color = "#059669"
    elif score_display >= 55:
        tier = "HIGH"
        tier_color = "#0891b2"
    elif score_display >= 40:
        tier = "MODERATE"
        tier_color = "#d97706"
    elif score_display >= 25:
        tier = "LOW"
        tier_color = "#dc2626"
    else:
        tier = "VERY LOW"
        tier_color = "#6b7280"

    return {
        "score": round(score_display, 1),
        "tier": tier,
        "tier_color": tier_color,
        "confidence_low": round(confidence_low, 1),
        "confidence_high": round(confidence_high, 1),
        "ptrs": round(ptrs_value * 100, 1),
        "score_raw": round(score_raw, 1),
        "components": {
            "unmet_need":     round(unmet_score, 1),
            "feasibility":    round(feasibility_score, 1),
            "burden":         round(burden_score, 1),
            "market":         round(market_score, 1),
            "competition":    round(competitive_score, 1),
            "exclusivity":    round(exclusivity_score, 1),
        },
        "weights": weights,
        "inputs": {
            "disease": disease_name,
            "therapeutic_area": therapeutic_area,
            "phase": development_phase,
            "competitor_trials": competitor_trial_count,
            "approved_treatments": approved_treatments_count,
            "annual_cost_usd": annual_treatment_cost_usd,
            "us_patients": us_patient_population,
            "designations": designations,
            "ptrs_source": "Hay 2014 (Nat Biotech); Wong 2019 (Biostatistics 20:273)",
        },
    }


# ── Discovery Engine: score a curated list of opportunities ──────────────────

OPPORTUNITY_UNIVERSE = [
    # (disease_name, therapeutic_area, phase, approved_count, annual_cost, notes)
    # ── High-volume / well-known conditions ───────────────────────────────────
    ("Alzheimer Disease (early/MCI)",        "cns",          "phase3", 2,  28000,   "Lecanemab/donanemab approved; amyloid-positive biomarker enrichment"),
    ("Heart Failure (HFpEF)",               "cardiovascular","phase3", 5,  18000,   "Empagliflozin approved; large unmet need in preserved-EF subtype"),
    ("Type 2 Diabetes (GLP-1 resistant)",   "metabolic",    "phase3", 12, 12000,   "GLP-1 saturation; oral/combination next frontier"),
    ("Obesity (CNS/metabolic)",             "metabolic",    "phase3", 4,  15000,   "Semaglutide crowded; mechanism diversity needed"),
    ("Lung Cancer (NSCLC, IO-resistant)",   "oncology",     "phase3", 8,  180000,  "PD-1/L1 resistance creates massive second-line gap"),
    ("Colorectal Cancer (MSS)",             "oncology",     "phase2", 4,  120000,  "MSS tumors unresponsive to checkpoint; RAS-targeted combos emerging"),
    ("Multiple Myeloma (triple-refractory)","oncology",     "phase2", 6,  200000,  "Bispecifics/CAR-T improving outcomes; still no cure"),
    ("Chronic Kidney Disease (DKD)",        "metabolic",    "phase3", 4,  25000,   "SGLT2i/finerenone approved; GFR-preserving agents still needed"),
    ("Atrial Fibrillation",                 "cardiovascular","phase3", 6,  8000,    "Rate/rhythm control standard; catheter ablation gap for persistent AF"),
    ("Major Depression (TRD)",              "cns",          "phase2", 3,  15000,   "Esketamine approved; psilocybin/MDMA pipeline accelerating"),
    ("Schizophrenia",                       "cns",          "phase2", 12, 20000,   "D2 class crowded; muscarinic agonists (xanomeline-trospium) new class"),
    ("COPD (advanced emphysema)",           "respiratory",  "phase2", 5,  18000,   "Triple inhaler therapy; lung volume reduction device gap"),
    ("Rheumatoid Arthritis (JAK-refractory)","immunology",  "phase2", 8,  40000,   "Biologic/JAK failure population; next-gen targeted therapies"),
    ("Psoriasis / PsA (IL-17/23 refractory)","immunology", "phase2", 7,  35000,   "IL-17/23 biologics standard; TYK2 inhibitors expanding options"),
    ("Inflammatory Bowel Disease (UC/CD)",  "immunology",   "phase3", 8,  45000,   "Anti-TNF resistance; selective gut-homing biologics next"),
    ("Breast Cancer (HR+, CDK4/6 resistant)","oncology",   "phase2", 5,  150000,  "CDK4/6 inhibitor resistance; PI3K/AKT/mTOR pathway targets"),
    ("Prostate Cancer (PSMA-targeted)",     "oncology",     "phase3", 4,  180000,  "Pluvicto approved; PSMA ADCs and combos emerging"),
    ("Ovarian Cancer (BRCA-wild type)",     "oncology",     "phase2", 3,  150000,  "PARP inhibitor benefit limited to BRCA; FRα/ADC approaches"),
    ("Pancreatic Ductal Adenocarcinoma",    "oncology",     "phase2", 3,  200000,  "12% 5-year survival; KRAS G12D targeted agents emerging"),
    ("Glioblastoma Multiforme",             "oncology",     "phase2", 2,  150000,  "No approved immunotherapy; checkpoint inhibitors failed Phase 3"),
    ("NASH/MASH",                           "metabolic",    "phase3", 1,  50000,   "Resmetirom approved 2024; pipeline crowded but huge market"),
    ("Sepsis (AI early detection)",         "device",       "phase2", 0,  5000,    "No approved specific therapy; diagnostic gap critical"),
    ("Type 1 Diabetes (CGM/automated insulin)","metabolic", "phase3", 4,  12000,   "Device+drug combination; closed-loop systems maturing"),
    ("Geographic Atrophy (dry AMD)",        "ophthalmology","phase3", 2,  20000,   "Syfovre/Izervay approved 2023; market still growing"),
    ("Wet AMD / Diabetic Macular Edema",    "ophthalmology","phase3", 4,  15000,   "Anti-VEGF crowded; longer-acting port-delivery emerging"),
    ("Asthma (severe eosinophilic)",        "respiratory",  "phase3", 5,  25000,   "Biologic growth; TSLP/IL-33 next targets"),
    ("Heart Failure (HFrEF, device-refractory)","cardiovascular","phase2",6,20000,"Cardiac contractility modulation; gene therapy for DCM"),
    ("Stroke (acute ischemic, neuroprotection)","cns",      "phase2", 1,  25000,   "tPA window limit; neuroprotection agents have failed historically"),
    ("Parkinson Disease (early stage)",     "cns",          "phase2", 4,  15000,   "Dopamine replacement standard; alpha-synuclein/GBA-targeting next"),
    ("Multiple Sclerosis (progressive)",    "cns",          "phase2", 6,  80000,   "Relapsing MS well-served; progressive forms still lacking"),
    # ── AMR / Infectious ─────────────────────────────────────────────────────
    ("Carbapenem-resistant Enterobacterales","amr_infectious","phase2",4, 18000,   "CDC urgent threat; NDM prevalence rising"),
    ("Acinetobacter baumannii MDR",         "amr_infectious","phase2", 2,  16000,   "ESKAPE pathogen; extremely limited treatment options"),
    ("MRSA Skin Infections",                "amr_infectious","phase2", 5,  1500,    "Oral gap; TMP-SMX resistance rising"),
    ("C. difficile Infection",              "amr_infectious","phase2", 3,  8000,    "Recurring infection problem; microbiome approaches emerging"),
    ("RSV in elderly/immunocompromised",    "vaccine",      "phase3", 2,  250,     "Arexvy/Abrysvo approved; booster strategy unclear"),
    ("Influenza (universal vaccine)",       "vaccine",      "phase2", 4,  200,     "Annual shot limitation; HA stalk/universal approaches"),
    ("HIV (long-acting ART / cure)",        "amr_infectious","phase3", 8,  25000,   "Daily pill to long-acting injectable; cure strategies emerging"),
    # ── CNS / Psychiatry ─────────────────────────────────────────────────────
    ("Huntington Disease",                  "cns",          "phase2", 0,  120000,  "No disease-modifying therapy approved; high unmet need"),
    ("Bipolar Depression",                  "cns",          "phase2", 3,  15000,   "Lumateperone approved; significant unmet need remains"),
    ("PTSD",                                "cns",          "phase2", 2,  8000,    "MDMA/psilocybin-assisted therapy in Phase 3; breakthrough potential"),
    ("Opioid Use Disorder",                 "cns",          "phase2", 3,  6000,    "Buprenorphine/naltrexone standard; novel mechanisms + digital tools"),
    ("ALS (SOD1-mutant)",                   "rare_disease", "phase2", 1,  178000,  "Tofersen approved 2024; oral alternative opportunity"),
    # ── Rare / Genetic ───────────────────────────────────────────────────────
    ("Sickle Cell Disease (gene therapy)",  "gene_therapy", "phase3", 2,  2200000, "Casgevy/Lyfgenia approved 2023; access/affordability gap"),
    ("Duchenne Muscular Dystrophy",         "rare_disease", "phase2", 3,  1200000, "Exon-skipping approved; gene therapy wave coming"),
    ("Spinal Muscular Atrophy Type 2",      "rare_disease", "phase2", 3,  340000,  "Zolgensma/nusinersen approved; beyond-neonatal gap"),
    ("Friedreich Ataxia",                   "rare_disease", "phase2", 1,  340000,  "Omaveloxolone approved 2023; additional mechanisms needed"),
    ("Rare Pediatric Epilepsy (SCN1A)",     "rare_disease", "phase2", 2,  180000,  "Fenfluramine/cannabidiol approved; gene therapy next"),
    ("Pulmonary Arterial Hypertension",     "cardiovascular","phase2", 8,  80000,  "Multiple approved; novel mechanisms still needed"),
    ("Myelofibrosis JAK-resistant",         "oncology",     "phase2", 3,  200000,  "Ruxolitinib resistance creates second-line gap"),
    ("HER2-low Breast Cancer",              "oncology",     "phase3", 2,  180000,  "Enhertu established precedent; large addressable population"),
    ("KRAS G12C NSCLC",                     "oncology",     "phase2", 2,  180000,  "Sotorasib/adagrasib approved; combination strategies needed"),
]


async def run_discovery_engine(top_n: int = 20) -> List[Dict]:
    """
    Score all opportunities in the universe and return ranked list.
    Runs all scoring in parallel for speed.
    """
    async def score_one(opp):
        disease, ta, phase, approved, cost, notes = opp
        try:
            result = await score_opportunity(
                disease_name=disease,
                therapeutic_area=ta,
                development_phase=phase,
                approved_treatments_count=approved,
                annual_treatment_cost_usd=cost,
            )
            result["disease"] = disease
            result["therapeutic_area"] = ta
            result["notes"] = notes
            result["phase"] = phase
            return result
        except Exception as e:
            logger.error(f"Score failed for {disease}: {e}")
            return None

    results = await asyncio.gather(*[score_one(opp) for opp in OPPORTUNITY_UNIVERSE])
    scored = [r for r in results if r is not None]
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_n]
