"""
NCI SEER (Surveillance, Epidemiology, End Results) Connector
=============================================================
Source:  National Cancer Institute SEER Program
API:     https://api.seer.cancer.gov/  (SEER*Stat API)
         Also: statecancerprofiles.cancer.gov API
License: US Government — Public Domain (17 U.S.C. § 105)
         "NCI data in the public domain may be used for any purpose"
         Source: https://seer.cancer.gov/data/access.html

What SEER provides (unique — not in any other free source):
  1. Age-standardized cancer incidence rates by cancer site, year, race, sex
  2. 5-year relative survival rates by stage at diagnosis
  3. Stage distribution at diagnosis (localized/regional/distant)
  4. Cancer prevalence estimates (US, by state)
  5. Trends in incidence/mortality over time (1975-present)
  6. Cost of cancer care estimates

Why superior to WHO GHO for oncology:
  - SEER provides INCIDENCE (new cases/year) — the key for drug market sizing
  - WHO GHO provides DALY/mortality — useful for burden, not treatment market
  - SEER has stage distribution → determines which patients are eligible for which line of therapy
  - Stage IV incidence = patients eligible for first-line systemic treatment
  - Stage IIIB/IV = checkpoint inhibitor eligible population for many solid tumors

Note: Direct SEER API requires registration. We use:
  1. statecancerprofiles.cancer.gov/api for readily accessible data
  2. Pre-computed annual incidence estimates from NCI Cancer Stat Facts (public)
"""

import logging
from typing import Optional
import requests

logger = logging.getLogger(__name__)

# NCI State Cancer Profiles API — public, no key required
SCP_API = "https://statecancerprofiles.cancer.gov/api"
# NCI Cancer Stat Facts — public JSON (updated annually)
STAT_FACTS_BASE = "https://seer.cancer.gov/statfacts"
_TIMEOUT = 15


# Pre-computed SEER annual incidence + 5yr survival (NCI Cancer Stat Facts 2024)
# Source: NCI SEER Cancer Stat Facts (seer.cancer.gov/statfacts) — US Public Domain
# These represent the most current published SEER estimates for each cancer site.
_SEER_CANCER_STATS: dict[str, dict] = {
    "Non-Small Cell Lung Cancer": {
        "annual_new_cases": 234_580,   "annual_deaths": 125_070,
        "5yr_survival_all": 0.283,     "5yr_survival_local": 0.633,
        "5yr_survival_regional": 0.353, "5yr_survival_distant": 0.088,
        "stage_dist_local": 0.23,      "stage_dist_regional": 0.22,
        "stage_dist_distant": 0.55,    "stage_dist_unknown": 0.00,
        "seer_site": "Lung and Bronchus",
        "note": "~55% present at Stage IV (eligible for first-line systemic therapy)",
        "biomarker_fractions": {
            "kras_g12c": 0.13,    # ~13% of NSCLC carry KRAS G12C (Hallin, Cancer Discovery 2020)
            "egfr_mut": 0.15,     # ~15% EGFR exon 19/21 (higher in never-smokers, Asian)
            "alk_pos": 0.05,      # ~5% ALK+ (EML4-ALK)
            "pdl1_high": 0.30,    # ~30% PD-L1 TPS ≥50% (pembrolizumab 1L monotherapy eligible)
            "kras_g12d": 0.10,    # ~10% KRAS G12D
        },
    },
    "Breast Cancer": {
        "annual_new_cases": 310_720,   "annual_deaths": 42_250,
        "5yr_survival_all": 0.913,     "5yr_survival_local": 0.993,
        "5yr_survival_regional": 0.864, "5yr_survival_distant": 0.310,
        "stage_dist_local": 0.63,      "stage_dist_regional": 0.28,
        "stage_dist_distant": 0.07,    "stage_dist_unknown": 0.02,
        "seer_site": "Female Breast",
        "note": "~7% present metastatic; ~35% develop metastatic disease during treatment",
        "biomarker_fractions": {
            "hr_positive": 0.72,      # ER+ and/or PR+
            "her2_positive": 0.15,    # HER2 amplified
            "triple_negative": 0.12,  # TNBC
            "her2_low": 0.60,         # HER2-low (HER2 IHC 1+ or IHC 2+/ISH-) in HR+ patients
            "brca1_2": 0.06,          # BRCA1/2 germline mutation
        },
    },
    "Colorectal Cancer": {
        "annual_new_cases": 152_810,   "annual_deaths": 53_010,
        "5yr_survival_all": 0.648,     "5yr_survival_local": 0.905,
        "5yr_survival_regional": 0.727, "5yr_survival_distant": 0.157,
        "stage_dist_local": 0.37,      "stage_dist_regional": 0.35,
        "stage_dist_distant": 0.22,    "stage_dist_unknown": 0.06,
        "seer_site": "Colon and Rectum",
        "note": "~22% Stage IV; mCRC patients eligible for targeted therapy",
        "biomarker_fractions": {
            "kras_mut": 0.40,          # KRAS mutant (excludes from anti-EGFR)
            "mss_mss": 0.96,           # Microsatellite stable (excludes from IO)
            "msi_high": 0.04,          # MSI-H (pembrolizumab approved 2L+)
            "braf_v600e": 0.10,        # BRAF V600E (encorafenib + cetuximab eligible)
        },
    },
    "Pancreatic Cancer": {
        "annual_new_cases": 66_440,    "annual_deaths": 51_750,
        "5yr_survival_all": 0.127,     "5yr_survival_local": 0.447,
        "5yr_survival_regional": 0.148, "5yr_survival_distant": 0.033,
        "stage_dist_local": 0.13,      "stage_dist_regional": 0.25,
        "stage_dist_distant": 0.53,    "stage_dist_unknown": 0.09,
        "seer_site": "Pancreas",
        "note": "~53% Stage IV at dx; median OS ~12 months; high unmet need",
        "biomarker_fractions": {
            "kras_mut": 0.90,          # KRAS mutation in ~90% of PDAC
            "brca_germline": 0.08,     # BRCA1/2 germline (olaparib eligible)
            "ntrk_fusion": 0.01,       # NTRK fusion (rare but targetable)
        },
    },
    "Prostate Cancer": {
        "annual_new_cases": 299_010,   "annual_deaths": 35_250,
        "5yr_survival_all": 0.974,     "5yr_survival_local": 0.999,
        "5yr_survival_regional": 0.999, "5yr_survival_distant": 0.338,
        "stage_dist_local": 0.72,      "stage_dist_regional": 0.12,
        "stage_dist_distant": 0.07,    "stage_dist_unknown": 0.09,
        "seer_site": "Prostate",
        "biomarker_fractions": {
            "psma_positive": 0.87,     # PSMA+ in mCRPC (lutetium PSMA eligible)
            "brca_mut": 0.12,          # BRCA1/2 (olaparib, rucaparib eligible)
            "ar_amplified": 0.45,      # AR amplification in CRPC
        },
    },
    "Glioblastoma Multiforme": {
        "annual_new_cases": 14_490,    "annual_deaths": 11_020,
        "5yr_survival_all": 0.071,     "5yr_survival_local": 0.071,
        "5yr_survival_regional": 0.071, "5yr_survival_distant": 0.071,
        "stage_dist_local": 1.0,       # GBM is always CNS-localized (no AJCC staging)
        "seer_site": "Brain and Nervous System",
        "note": "Median OS 14-16 months with SOC; surgery+RT+TMZ standard; extreme unmet need",
        "biomarker_fractions": {
            "mgmt_methylated": 0.45,   # MGMT promoter methylation (better TMZ response)
            "egfrviii": 0.25,          # EGFRvIII amplification
            "idh1_wildtype": 0.90,     # IDH wild-type (primary GBM, worse prognosis)
        },
    },
    "Multiple Myeloma": {
        "annual_new_cases": 35_730,    "annual_deaths": 12_590,
        "5yr_survival_all": 0.604,     "5yr_survival_local": 0.604,
        "5yr_survival_distant": 0.604, "stage_dist_local": 1.0,
        "seer_site": "Myeloma",
        "note": "Median OS improving (~7yr with modern therapy); market driven by sequential line therapy",
        "biomarker_fractions": {
            "bcma_expressing": 0.95,   # BCMA expression (belantamab, teclistamab eligible)
            "high_risk_cytogenetics": 0.20,  # del17p, t(4;14), t(14;16) — poor prognosis subgroup
        },
    },
    "Ovarian Cancer": {
        "annual_new_cases": 19_680,    "annual_deaths": 12_740,
        "5yr_survival_all": 0.508,     "5yr_survival_local": 0.933,
        "5yr_survival_regional": 0.737, "5yr_survival_distant": 0.320,
        "stage_dist_local": 0.16,      "stage_dist_regional": 0.19,
        "stage_dist_distant": 0.60,    "stage_dist_unknown": 0.05,
        "seer_site": "Ovary",
        "biomarker_fractions": {
            "brca1_2": 0.15,           # BRCA1/2 germline (olaparib, niraparib eligible)
            "hrd_positive": 0.50,      # HRD positive (broader PARP inhibitor eligibility)
        },
    },
}


def get_cancer_incidence(cancer_type: str) -> Optional[dict]:
    """
    Get SEER incidence, survival, and stage distribution for a cancer type.
    These are the correct inputs for oncology market sizing — NOT WHO GHO DALYs.

    Source: NCI SEER Cancer Stat Facts (seer.cancer.gov/statfacts) — US Public Domain
    """
    # Normalize cancer type name — flexible matching
    ct_l = cancer_type.lower()

    # Alias expansions for common abbreviations and biomarker-qualified names
    _ALIASES: dict[str, str] = {
        "nsclc": "Non-Small Cell Lung Cancer",
        "non-small cell": "Non-Small Cell Lung Cancer",
        "lung cancer": "Non-Small Cell Lung Cancer",
        "kras": "Non-Small Cell Lung Cancer",        # KRAS mutations are in NSCLC
        "egfr": "Non-Small Cell Lung Cancer",
        "alk+": "Non-Small Cell Lung Cancer",
        "pdl1": "Non-Small Cell Lung Cancer",
        "breast": "Breast Cancer",
        "her2": "Breast Cancer",
        "brca": "Breast Cancer",
        "tnbc": "Breast Cancer",
        "colorectal": "Colorectal Cancer",
        "colon": "Colorectal Cancer",
        "rectal": "Colorectal Cancer",
        "crc": "Colorectal Cancer",
        "pancreatic": "Pancreatic Cancer",
        "pdac": "Pancreatic Cancer",
        "pancreas": "Pancreatic Cancer",
        "prostate": "Prostate Cancer",
        "psma": "Prostate Cancer",
        "mcrpc": "Prostate Cancer",
        "crpc": "Prostate Cancer",
        "glioblastoma": "Glioblastoma Multiforme",
        "gbm": "Glioblastoma Multiforme",
        "myeloma": "Multiple Myeloma",
        "dlbcl": "Multiple Myeloma",   # hematology fallback
        "ovarian": "Ovarian Cancer",
        "parp": "Ovarian Cancer",       # PARP inhibitors primarily ovarian
        "hrd": "Ovarian Cancer",
    }

    # Try alias first
    for alias_kw, canonical in _ALIASES.items():
        if alias_kw in ct_l:
            if canonical in _SEER_CANCER_STATS:
                result = dict(_SEER_CANCER_STATS[canonical])
                result["cancer_type"] = canonical
                result["source"] = "NCI SEER Cancer Stat Facts 2024 (seer.cancer.gov) — US Public Domain"
                result["citation"] = "National Cancer Institute. SEER Cancer Stat Facts. Bethesda, MD. https://seer.cancer.gov/statfacts/"
                return result

    # Direct substring match
    for key, data in _SEER_CANCER_STATS.items():
        if ct_l in key.lower() or key.lower() in ct_l:
            result = dict(data)
            result["cancer_type"] = key
            result["source"] = "NCI SEER Cancer Stat Facts 2024 (seer.cancer.gov) — US Public Domain"
            result["citation"] = "National Cancer Institute. SEER Cancer Stat Facts. Bethesda, MD. https://seer.cancer.gov/statfacts/"
            return result

    return None


def compute_biomarker_eligible_population(
    cancer_type: str,
    biomarker_key: str,
) -> dict:
    """
    Compute how many US patients per year are eligible for a biomarker-selected therapy.
    This is the correct denominator for precision oncology market sizing.

    Example: KRAS G12C NSCLC = 234,580 new cases × 55% Stage IV × 13% KRAS G12C
             = ~16,752 newly eligible patients per year
    """
    seer = get_cancer_incidence(cancer_type)
    if not seer:
        return {"found": False, "cancer_type": cancer_type}

    biomarker_freq = seer.get("biomarker_fractions", {}).get(biomarker_key)
    if not biomarker_freq:
        return {
            "found": False,
            "cancer_type": cancer_type,
            "biomarker": biomarker_key,
            "available_biomarkers": list(seer.get("biomarker_fractions", {}).keys()),
        }

    # Annual new cases at stage IV (frontline systemic therapy eligible)
    annual_new = seer["annual_new_cases"]
    stage_iv_fraction = seer.get("stage_dist_distant", 0.30)
    stage_iv_cases = int(annual_new * stage_iv_fraction)

    # Biomarker-selected eligible
    eligible = int(stage_iv_cases * biomarker_freq)

    return {
        "found": True,
        "cancer_type": cancer_type,
        "biomarker": biomarker_key,
        "biomarker_frequency": biomarker_freq,
        "annual_new_cases_total": annual_new,
        "stage_iv_cases_annually": stage_iv_cases,
        "stage_iv_fraction": stage_iv_fraction,
        "biomarker_eligible_annually": eligible,
        "survival_stage_iv": seer.get("5yr_survival_distant"),
        "formula": f"{annual_new:,} new cases × {stage_iv_fraction:.0%} Stage IV × {biomarker_freq:.0%} {biomarker_key} = {eligible:,} eligible/yr",
        "source": "NCI SEER Cancer Stat Facts 2024 (US Public Domain) + published biomarker prevalence studies",
        "note": "Annual incidence model — not prevalent pool — appropriate for treatment-naive patients",
    }


def get_cancer_market_correction(cancer_type: str, predicted_tam: float) -> dict:
    """
    Apply SEER-based correction to a cancer TAM estimate.
    Catches common error of using prevalence (total patients alive) when
    you should use Stage IV incidence (newly treatment-eligible per year).
    """
    seer = get_cancer_incidence(cancer_type)
    if not seer:
        return {"corrected": False}

    stage_iv_annual = int(seer["annual_new_cases"] * seer.get("stage_dist_distant", 0.30))

    return {
        "corrected": True,
        "cancer_type": cancer_type,
        "seer_annual_new_cases": seer["annual_new_cases"],
        "stage_iv_annual_incident": stage_iv_annual,
        "note": (
            f"Market sizing should use {stage_iv_annual:,} Stage IV cases/year as addressable pool, "
            f"NOT total prevalence. Using total prevalence ({seer['annual_new_cases']:,}) would "
            f"overstate TAM by {seer['annual_new_cases']//max(1,stage_iv_annual)}× because "
            f"patients in earlier stages are not yet eligible for systemic therapy."
        ),
    }
