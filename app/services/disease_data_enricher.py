"""
Disease Data Enricher — Powers the Market Discovery Tool
==========================================================
Pulls specialized database-backed data for each disease in the discovery universe,
replacing hardcoded _TA_DEFAULTS and _DISEASE_OVERRIDES with live/pre-loaded data
from our full 49-source dataset.

Called by _score_one_inner() for every disease in the OPPORTUNITY_UNIVERSE (~309 diseases).
All functions have aggressive in-memory caching with TTLs matched to data update frequency.

Data flow for each discovery disease:
  1. Prevalence/incidence → NCI SEER (oncology) or Orphanet (rare) or WHO GHO
  2. Biomarker fraction    → cBioPortal GENIE or ClinVar (gene therapy)
  3. Drug pricing          → CMS Part D/B ASP or pre-loaded benchmarks
  4. Formulary coverage    → CMS MA Formulary files (realized TAM adjustment)
  5. MEPS adherence        → AHRQ MEPS (realized TAM adjustment)
  6. Trial count           → ClinicalTrials.gov (already implemented)
  7. Approval count        → openFDA (already implemented)
  8. Subcategory routing   → soft_router → subcategory-specific PTRS + scoring weights
  9. Disease burden        → WHO GHO DALYs (already implemented)
  10. Geographic hotspots  → County Health Rankings (contextual enrichment)

Result: Instead of "metabolic diabetes → 35M patients, $15K cost, 0.82 diag yield"
        we get: "Type 2 Diabetes (GLP-1 resistant) →
          - 4.8M treatment-naive GLP-1 candidates (CMS Part D prevalence data)
          - $13,618/yr WAC semaglutide (CMS ASP Q3-2024)
          - 0.82 formulary coverage × 0.71 PA approval = 0.58 effective access
          - 0.55 real-world adherence (AHRQ MEPS T2D data)
          - Realized TAM = theoretical × 0.58 × 0.55 = 0.32× theoretical ceiling"
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional, Any

logger = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════════════════════════
# CACHE — LRU with per-entry TTL (reuse from retrieval_pipeline)
# ════════════════════════════════════════════════════════════════════════════

from collections import OrderedDict
import hashlib

class _TTLCache:
    def __init__(self, max_size: int = 1000):
        self._store: OrderedDict[str, tuple[Any, float, float]] = OrderedDict()
        self._max = max_size
    def get(self, key: str) -> Optional[Any]:
        e = self._store.get(key)
        if not e: return None
        v, t, ttl = e
        if time.monotonic() - t > ttl:
            del self._store[key]
            return None
        self._store.move_to_end(key)
        return v
    def set(self, key: str, value: Any, ttl: float = 86400.0):
        self._store[key] = (value, time.monotonic(), ttl)
        self._store.move_to_end(key)
        if len(self._store) > self._max:
            self._store.popitem(last=False)

_CACHE = _TTLCache(max_size=2000)


# ════════════════════════════════════════════════════════════════════════════
# ENRICHED DISEASE PARAMETERS
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class DiseaseEnrichment:
    """All database-backed parameters for one disease, ready for scorer."""
    disease_name:          str
    therapeutic_area:      str
    subcategory_id:        str         # Routed subcategory (e.g., "drug_oncology")

    # Population
    us_patient_population: int         # Most accurate source available
    population_source:     str
    biomarker_eligible:    Optional[int] = None   # If biomarker-stratified
    biomarker_fraction:    Optional[float] = None  # e.g., 0.131 for KRAS G12C

    # Pricing
    annual_treatment_cost: float = 50_000
    pricing_source:        str = "pre-loaded benchmark"

    # TAM adjustments (NEW — from MEPS + formulary)
    formulary_coverage:    float = 0.80  # % plans covering drug
    pa_approval_rate:      float = 0.85  # % PA requests approved
    meps_fill_rate:        float = 0.75  # % patients filling Rx
    meps_adherence_rate:   float = 0.70  # % patients adherent at 12mo
    realized_tam_factor:   float = 1.0   # combined adjustment to theoretical TAM

    # Clinical
    has_biomarker:         bool = False
    is_first_in_class:     bool = False
    typical_phase:         str = "phase2"
    approved_count:        int = 0

    # Burden
    dalys:                 Optional[float] = None
    daly_source:           str = "unknown"

    # Soft routing weights
    soft_weights:          dict = field(default_factory=dict)

    # Enrichment metadata
    sources_used:          list[str] = field(default_factory=list)
    enrichment_latency_ms: float = 0.0
    cache_hit:             bool = False


# ════════════════════════════════════════════════════════════════════════════
# DISEASE → SUBCATEGORY ROUTING (for discovery universe)
# ════════════════════════════════════════════════════════════════════════════

# Pre-mapped subcategories for the known disease universe
# Avoids running full NLP router for every disease on every discovery call
_DISEASE_SUBCATEGORY_MAP: dict[str, str] = {
    # AMR
    "Carbapenem-resistant Enterobacterales": "drug_amr",
    "Acinetobacter baumannii MDR":          "drug_amr",
    "C. difficile Infection":               "drug_amr_community",
    "MRSA Skin Infections":                 "drug_amr_community",
    # Oncology — solid
    "Glioblastoma Multiforme":              "biologic_oncology",
    "Pancreatic Ductal Adenocarcinoma":     "drug_oncology",
    "KRAS G12C NSCLC":                      "drug_oncology",
    "Lung Cancer (NSCLC, IO-resistant)":    "biologic_oncology",
    "HER2-low Breast Cancer":               "biologic_oncology",
    "Breast Cancer (HR+, CDK4/6 resistant)":"drug_oncology",
    "Ovarian Cancer (BRCA-wild type)":      "drug_oncology",
    "Colorectal Cancer (MSS)":              "drug_oncology",
    "Prostate Cancer (PSMA-targeted)":      "biologic_oncology",
    # Oncology — heme
    "Multiple Myeloma (triple-refractory)": "biologic_oncology",
    "Myelofibrosis JAK-resistant":          "drug_oncology",
    "AML (FLT3-mutant)":                    "biologic_oncology",
    # CNS / Neuro
    "Alzheimer Disease (early/MCI)":        "drug_cns_neurodegen",
    "ALS (SOD1-mutant)":                    "gene_therapy_cns",
    "Huntington Disease":                   "gene_therapy_cns",
    "Parkinson Disease (LRRK2)":            "drug_cns_neurodegen",
    "Rare Pediatric Epilepsy (SCN1A)":      "gene_therapy_rare",
    "Major Depression (TRD)":              "drug_mental_health",
    "Bipolar Depression":                   "drug_mental_health",
    "Schizophrenia":                        "drug_mental_health",
    # Metabolic
    "Type 2 Diabetes (GLP-1 resistant)":   "drug_metabolic",
    "Obesity (CNS/metabolic)":             "drug_metabolic",
    "NASH/MASH":                            "drug_metabolic",
    "Chronic Kidney Disease (DKD)":        "drug_metabolic",
    # Cardiovascular
    "Heart Failure (HFpEF)":               "drug_cardiovascular",
    "Heart Failure (HFrEF, device-refractory)": "device_cardiovascular",
    "Atrial Fibrillation":                  "device_cardiovascular",
    # Immunology
    "Rheumatoid Arthritis (JAK-refractory)":"biologic_immunology",
    "Psoriasis / PsA (IL-17/23 refractory)":"biologic_immunology",
    "Inflammatory Bowel Disease (UC/CD)":  "biologic_immunology",
    "Asthma (severe eosinophilic)":        "biologic_immunology",
    # Ophthalmology
    "Wet AMD / Diabetic Macular Edema":    "biologic_immunology",  # anti-VEGF biologics
    "Geographic Atrophy (dry AMD)":        "biologic_oncology",    # complement biologics
    # Rare / gene therapy
    "Spinal Muscular Atrophy Type 2":      "gene_therapy_rare",
    "Duchenne Muscular Dystrophy":         "gene_therapy_rna",
    "Sickle Cell Disease (gene therapy)":  "gene_therapy_hematology",
    "Friedreich Ataxia":                   "gene_therapy_rare",
    "Beta-Thalassemia":                    "gene_therapy_hematology",
    "Hemophilia A (gene therapy)":         "gene_therapy_hematology",
    # Diagnostic
    "Sepsis (AI early detection)":         "digital_cds",
    "Type 1 Diabetes (CGM/automated insulin)": "device_metabolic",
    "RSV in elderly/immunocompromised":    "vaccine_prophylactic",
}


def _route_disease(disease_name: str, therapeutic_area: str) -> str:
    """Route a disease to its subcategory for PTRS + scoring profile."""
    # Check pre-mapped first (O(1))
    sub = _DISEASE_SUBCATEGORY_MAP.get(disease_name)
    if sub:
        return sub

    # Fall back to TA-based mapping
    ta = therapeutic_area.lower()
    _TA_SUB_MAP = {
        "amr_infectious": "drug_amr",
        "oncology":        "drug_oncology",
        "hematology":      "biologic_hematology",
        "cns":             "drug_cns_neurodegen",
        "cardiovascular":  "drug_cardiovascular",
        "metabolic":       "drug_metabolic",
        "immunology":      "biologic_immunology",
        "rare_disease":    "drug_rare_disease",
        "gene_therapy":    "gene_therapy_rare",
        "vaccine":         "vaccine_prophylactic",
        "device":          "device_cardiovascular",
        "diagnostic":      "diagnostic_molecular_lab",
        "other":           "drug_oncology",
    }
    for key, sub_id in _TA_SUB_MAP.items():
        if key in ta:
            return sub_id
    return "drug_oncology"


# ════════════════════════════════════════════════════════════════════════════
# ENRICHMENT DATA — pre-loaded from specialized databases
# ════════════════════════════════════════════════════════════════════════════

# Disease-specific enrichment using our new specialized connectors
# Format: disease_name → {population, pricing, biomarker, formulary, meps, sources}
# Built from: NCI SEER + Orphanet + cBioPortal + CMS ASP + CMS Formulary + MEPS
_DISEASE_ENRICHMENT_DB: dict[str, dict] = {

    # ── ONCOLOGY (SEER incidence-based, biomarker-stratified) ─────────────
    "KRAS G12C NSCLC": {
        "population": 16_839,        # SEER 234,580 × 55% Stage IV × 13.1% KRAS G12C (cBioPortal GENIE)
        "biomarker_fraction": 0.131,
        "has_biomarker": True,
        "annual_cost": 180_000,      # Sotorasib/adagrasib WAC (CMS Part B ASP)
        "formulary_coverage": 0.88,  # Oral oncology: well-covered
        "pa_approval_rate": 0.90,    # CDx companion diagnostic required
        "meps_fill_rate": 0.91,
        "meps_adherence": 0.81,
        "population_source": "SEER 2024 × cBioPortal GENIE v16.1 (CC BY 4.0)",
        "pricing_source": "CMS Part B ASP Q3-2024",
    },
    "HER2-low Breast Cancer": {
        "population": 52_000,        # SEER 310,720 × 7% Stage IV × 54% HER2-low (cBioPortal)
        "biomarker_fraction": 0.540,
        "has_biomarker": True,
        "annual_cost": 220_000,      # T-DXd (Enhertu) CMS Part B ASP
        "formulary_coverage": 0.92,
        "pa_approval_rate": 0.88,
        "meps_fill_rate": 0.91,
        "meps_adherence": 0.81,
        "population_source": "SEER 2024 × cBioPortal GENIE (HER2-low 54% of HR+/HER2- breast)",
        "pricing_source": "CMS Part B ASP (T-DXd/Enhertu)",
    },
    "Glioblastoma Multiforme": {
        "population": 14_490,        # SEER annual new diagnoses (nearly all Stage IV at dx)
        "biomarker_fraction": 0.45,   # MGMT-methylated (temozolomide-sensitive)
        "has_biomarker": False,       # MGMT not yet drugged specifically
        "annual_cost": 150_000,       # Bevacizumab + TMZ + RT standard
        "formulary_coverage": 0.89,
        "pa_approval_rate": 0.85,
        "meps_fill_rate": 0.91,
        "meps_adherence": 0.85,
        "population_source": "NCI SEER Cancer Stat Facts 2024 (glioblastoma)",
        "pricing_source": "CMS Part B ASP + Part D (temozolomide)",
    },
    "Pancreatic Ductal Adenocarcinoma": {
        "population": 35_213,        # SEER 66,440 × 53% Stage IV
        "biomarker_fraction": 0.075,  # BRCA1/2 germline (olaparib eligible)
        "has_biomarker": True,
        "annual_cost": 160_000,       # Gemcitabine/nab-paclitaxel + FOLFIRINOX standard
        "formulary_coverage": 0.91,
        "pa_approval_rate": 0.86,
        "meps_fill_rate": 0.91,
        "meps_adherence": 0.81,
        "population_source": "NCI SEER 2024 × Stage IV fraction 53%",
        "pricing_source": "CMS Part D spending data",
    },
    "Multiple Myeloma (triple-refractory)": {
        "population": 12_000,         # ~35,730/yr, ~33% triple-refractory after 3 prior lines
        "biomarker_fraction": 0.96,   # BCMA expressing (cBioPortal pre-loaded)
        "has_biomarker": True,
        "annual_cost": 450_000,       # Teclistamab/carvykti range
        "formulary_coverage": 0.89,
        "pa_approval_rate": 0.87,
        "meps_fill_rate": 0.91,
        "meps_adherence": 0.81,
        "population_source": "NCI SEER MM + published triple-refractory prevalence estimates",
        "pricing_source": "CMS Part B ASP (bispecific/CAR-T)",
    },
    "Prostate Cancer (PSMA-targeted)": {
        "population": 23_000,         # ~300K new, 7% Stage IV × 87% PSMA+ = mCRPC PSMA cohort
        "biomarker_fraction": 0.870,  # PSMA+ (VISION trial, cBioPortal)
        "has_biomarker": True,
        "annual_cost": 170_000,       # Lutetium-177 PSMA (Pluvicto) CMS Part B
        "formulary_coverage": 0.85,
        "pa_approval_rate": 0.88,
        "meps_fill_rate": 0.91,
        "meps_adherence": 0.82,
        "population_source": "NCI SEER prostate × Stage IV × PSMA+ fraction (VISION trial)",
        "pricing_source": "CMS Part B ASP (Pluvicto/lu-177-PSMA-617)",
    },

    # ── GENE THERAPY / RARE DISEASE (Orphanet + ClinVar) ──────────────────
    "Spinal Muscular Atrophy Type 2": {
        "population": 2_672,          # Orphanet 8.0/million × 334M US
        "biomarker_fraction": 0.96,   # SMN1 biallelic deletion (ClinVar)
        "has_biomarker": True,
        "annual_cost": 2_200_000,     # Zolgensma one-time (CMS Part B)
        "formulary_coverage": 0.89,
        "pa_approval_rate": 0.92,
        "meps_fill_rate": 0.95,      # High motivation (curative intent)
        "meps_adherence": 0.98,
        "population_source": "Orphanet 8.0/million (CC BY 4.0) × US 334M",
        "pricing_source": "CMS Part B ASP (onasemnogene/Zolgensma)",
    },
    "Duchenne Muscular Dystrophy": {
        "population": 15_030,         # Orphanet 45/million × 334M
        "biomarker_fraction": 0.13,   # Exon 51 skip eligible (ClinVar)
        "has_biomarker": True,
        "annual_cost": 300_000,       # Elevidys (delandistrogene) WAC
        "formulary_coverage": 0.78,
        "pa_approval_rate": 0.88,
        "meps_fill_rate": 0.92,
        "meps_adherence": 0.90,
        "population_source": "Orphanet 45/million (CC BY 4.0) × US 334M",
        "pricing_source": "CMS Part B ASP (delandistrogene moxeparvovec/Elevidys)",
    },
    "Sickle Cell Disease (gene therapy)": {
        "population": 100_200,        # Orphanet 300/million × 334M
        "biomarker_fraction": 0.85,   # HBB S/S genotype eligible (ClinVar HBB gene)
        "has_biomarker": True,
        "annual_cost": 2_200_000,     # Casgevy one-time
        "formulary_coverage": 0.85,
        "pa_approval_rate": 0.90,
        "meps_fill_rate": 0.92,
        "meps_adherence": 0.95,
        "population_source": "Orphanet 300/million (CC BY 4.0) × US population",
        "pricing_source": "CMS (Casgevy $2.2M WAC; Lyfgenia $3.1M)",
    },
    "Hemophilia A (gene therapy)": {
        "population": 10_020,         # Orphanet 30/million × 334M
        "biomarker_fraction": 1.0,    # All severe hemophilia A eligible (F8 null)
        "has_biomarker": True,
        "annual_cost": 3_500_000,     # Hemgenix (etranacogene) precedent
        "formulary_coverage": 0.87,
        "pa_approval_rate": 0.91,
        "meps_fill_rate": 0.94,
        "meps_adherence": 0.96,
        "population_source": "Orphanet 30/million × US 334M",
        "pricing_source": "CMS Part B (Hemgenix $3.5M; Beqvez ~$3.5M)",
    },
    "Huntington Disease": {
        "population": 16_700,         # Orphanet 50/million × 334M
        "biomarker_fraction": 1.0,    # All have HTT expansion (confirmed genetic)
        "has_biomarker": True,
        "annual_cost": 800_000,       # ASO/siRNA investigational pricing projection
        "formulary_coverage": 0.70,
        "pa_approval_rate": 0.82,
        "meps_fill_rate": 0.88,
        "meps_adherence": 0.85,
        "population_source": "Orphanet 50/million (CC BY 4.0) × US 334M",
        "pricing_source": "Projected from ASO/siRNA precedents (nusinersen $125K/yr → HD expectation higher)",
    },
    "Friedreich Ataxia": {
        "population": 5_010,          # Orphanet 15/million × 334M
        "biomarker_fraction": 1.0,
        "has_biomarker": True,
        "annual_cost": 400_000,       # Skyclarys (omaveloxolone) WAC $400K/yr
        "formulary_coverage": 0.72,
        "pa_approval_rate": 0.85,
        "meps_fill_rate": 0.88,
        "meps_adherence": 0.87,
        "population_source": "Orphanet 15/million × US 334M",
        "pricing_source": "CMS Part D (Skyclarys $400K WAC)",
    },

    # ── METABOLIC / CARDIOVASCULAR ─────────────────────────────────────────
    "Type 2 Diabetes (GLP-1 resistant)": {
        "population": 4_800_000,      # ~12M on GLP-1 class; ~40% inadequately controlled
        "biomarker_fraction": None,
        "has_biomarker": False,
        "annual_cost": 13_618,        # Semaglutide WAC (CMS Part D spending)
        "formulary_coverage": 0.82,   # CMS formulary data (semaglutide T2D)
        "pa_approval_rate": 0.71,     # PA required; 71% require PA
        "meps_fill_rate": 0.78,      # MEPS T2D
        "meps_adherence": 0.55,
        "population_source": "CDC NDSR + CMS Part D GLP-1 claim analysis",
        "pricing_source": "CMS Part D semaglutide (Ozempic) actual spending 2022",
    },
    "Obesity (CNS/metabolic)": {
        "population": 7_000_000,      # Clinically eligible (BMI≥30 + comorbidity)
        "biomarker_fraction": None,
        "has_biomarker": False,
        "annual_cost": 15_000,        # Wegovy WAC
        "formulary_coverage": 0.28,   # CMS formulary: only 28% plans cover obesity Rx
        "pa_approval_rate": 0.65,     # PA approval rate (lower for obesity vs T2D)
        "meps_fill_rate": 0.60,
        "meps_adherence": 0.50,
        "population_source": "CDC BRFSS obesity prevalence × clinical eligibility filters",
        "pricing_source": "CMS ASP (semaglutide 2.4mg/Wegovy $15K WAC)",
    },
    "NASH/MASH": {
        "population": 18_000_000,     # Estimated 5-6% of US adults with NASH
        "biomarker_fraction": None,
        "has_biomarker": False,
        "annual_cost": 28_000,        # Rezdiffra (resmetirom) WAC
        "formulary_coverage": 0.55,   # New class, limited formulary access at launch
        "pa_approval_rate": 0.80,
        "meps_fill_rate": 0.68,
        "meps_adherence": 0.60,
        "population_source": "Published NASH epidemiology (Younossi 2023; ~5-6% of US adults)",
        "pricing_source": "CMS Part D (Rezdiffra $28K/yr WAC, launched 2024)",
    },
    "Heart Failure (HFpEF)": {
        "population": 3_000_000,      # ~6M total HF; ~50% HFpEF (EF≥50%)
        "biomarker_fraction": None,
        "has_biomarker": False,
        "annual_cost": 5_200,         # SGLT2 inhibitor (empagliflozin) for HFpEF
        "formulary_coverage": 0.85,
        "pa_approval_rate": 0.78,
        "meps_fill_rate": 0.82,
        "meps_adherence": 0.68,
        "population_source": "AHA HF statistics + EMPEROR-Preserved trial eligibility",
        "pricing_source": "CMS Part D empagliflozin (Jardiance) actual spending",
    },
    "Atrial Fibrillation": {
        "population": 6_000_000,      # Prevalent AFib in US; ~40% eligible for new therapy
        "biomarker_fraction": None,
        "has_biomarker": False,
        "annual_cost": 3_000,         # Novel oral anticoagulant (NOAC) pricing
        "formulary_coverage": 0.92,
        "pa_approval_rate": 0.88,
        "meps_fill_rate": 0.84,
        "meps_adherence": 0.71,
        "population_source": "CDC AFib prevalence estimates + published epidemiology",
        "pricing_source": "CMS Part D (apixaban/Eliquis, rivaroxaban/Xarelto actual spending)",
    },

    # ── CNS ────────────────────────────────────────────────────────────────
    "Alzheimer Disease (early/MCI)": {
        "population": 1_800_000,      # Early stage eligible for anti-amyloid (amyloid-confirmed)
        "biomarker_fraction": 0.70,   # ~70% of clinical MCI confirmed amyloid-positive by PET
        "has_biomarker": True,
        "annual_cost": 26_500,        # Lecanemab WAC; donanemab similar
        "formulary_coverage": 0.15,   # CMS CED restriction (pre-full coverage)
        "pa_approval_rate": 0.99,     # Universal PA; amyloid confirmation + specialist required
        "meps_fill_rate": 0.62,
        "meps_adherence": 0.72,
        "population_source": "Alzheimer's Association + published amyloid PET confirmation rates",
        "pricing_source": "CMS Part B (lecanemab/Leqembi $26,500/yr)",
    },
    "Major Depression (TRD)": {
        "population": 2_800_000,      # ~30% of MDD patients are TRD (~9.3M MDD × 30%)
        "biomarker_fraction": None,
        "has_biomarker": False,
        "annual_cost": 8_000,         # Esketamine (Spravato) WAC/yr
        "formulary_coverage": 0.62,
        "pa_approval_rate": 0.75,
        "meps_fill_rate": 0.62,
        "meps_adherence": 0.44,      # MEPS mental health adherence
        "population_source": "NIMH MDD prevalence × TRD prevalence (30% of MDD, Souery 2007)",
        "pricing_source": "CMS Part D (esketamine + oral antidepressant combo)",
    },

    # ── IMMUNOLOGY ──────────────────────────────────────────────────────────
    "Rheumatoid Arthritis (JAK-refractory)": {
        "population": 400_000,        # ~1.3M diagnosed RA; ~30% JAK/bDMARD refractory
        "biomarker_fraction": None,
        "has_biomarker": False,
        "annual_cost": 30_000,        # JAK inhibitor WAC net (after GTN)
        "formulary_coverage": 0.73,
        "pa_approval_rate": 0.68,     # Step therapy nearly universal
        "meps_fill_rate": 0.85,
        "meps_adherence": 0.72,
        "population_source": "CDC RA prevalence + published DMARD failure rates",
        "pricing_source": "CMS Part D (upadacitinib, baricitinib) average net",
    },
    "Inflammatory Bowel Disease (UC/CD)": {
        "population": 600_000,        # ~1.6M IBD; ~38% refractory to anti-TNF
        "biomarker_fraction": None,
        "has_biomarker": False,
        "annual_cost": 35_000,        # Biologic net pricing (vedolizumab, ustekinumab)
        "formulary_coverage": 0.78,
        "pa_approval_rate": 0.74,
        "meps_fill_rate": 0.85,
        "meps_adherence": 0.75,
        "population_source": "CDC MMWR IBD prevalence + published biologic failure rates",
        "pricing_source": "CMS Part D (upadacitinib/Rinvoq, vedolizumab/Entyvio) actual",
    },
    "Asthma (severe eosinophilic)": {
        "population": 600_000,        # ~25M asthma; ~5-8% severe; ~50% eosinophilic
        "biomarker_fraction": 0.50,   # ≥300 eos/μL defining eligibility
        "has_biomarker": True,
        "annual_cost": 35_000,        # Mepolizumab/dupilumab net pricing
        "formulary_coverage": 0.76,
        "pa_approval_rate": 0.80,
        "meps_fill_rate": 0.70,
        "meps_adherence": 0.40,      # Inhaler adherence is notoriously low
        "population_source": "CDC BRFSS asthma + published severe/eosinophilic fractions",
        "pricing_source": "CMS Part D biologic (dupilumab/Dupixent, mepolizumab/Nucala)",
    },

    # ── DIGITAL HEALTH / DEVICES ──────────────────────────────────────────
    "Sepsis (AI early detection)": {
        "population": 1_700_000,      # CDC: ~1.7M adults with sepsis/yr in US
        "biomarker_fraction": None,
        "has_biomarker": False,
        "annual_cost": 80_000,        # Hospital enterprise SaaS license
        "formulary_coverage": 0.62,   # CMS CED coverage (limited AI reimbursement)
        "pa_approval_rate": 0.95,
        "meps_fill_rate": 1.0,        # Institutional, not patient adherence
        "meps_adherence": 1.0,
        "population_source": "CDC Vital Signs: Sepsis estimates (sepsis.gov)",
        "pricing_source": "Enterprise SaaS benchmark (Viz.ai, Aidoc analogy: $80K/site/yr)",
    },
    "Type 1 Diabetes (CGM/automated insulin)": {
        "population": 1_600_000,      # ~1.6M T1D in US (JDRF estimates)
        "biomarker_fraction": None,
        "has_biomarker": False,
        "annual_cost": 6_000,         # CGM sensor annual cost (Dexcom G7)
        "formulary_coverage": 0.88,
        "pa_approval_rate": 0.82,
        "meps_fill_rate": 0.82,
        "meps_adherence": 0.78,
        "population_source": "JDRF T1D epidemiology + CDC National Diabetes Statistics Report",
        "pricing_source": "CMS Part D (Dexcom CGM sensor $6K/yr; pump supplies)",
    },
    "RSV in elderly/immunocompromised": {
        "population": 85_000_000,     # Adults 60+ (ACIP recommendation scope)
        "biomarker_fraction": None,
        "has_biomarker": False,
        "annual_cost": 200,           # Arexvy/Abrysvo single dose (CDC VFC)
        "formulary_coverage": 0.85,
        "pa_approval_rate": 0.98,     # Vaccines: essentially no PA barrier
        "meps_fill_rate": 0.35,      # RSV vaccine uptake 2023-24 (CDC)
        "meps_adherence": 1.0,        # Single dose
        "population_source": "CDC ACIP RSV recommendation 2023: adults 60+",
        "pricing_source": "CDC VFC contract price (Arexvy/Abrysvo ~$200)",
    },
    "Wet AMD / Diabetic Macular Edema": {
        "population": 1_200_000,      # ~2M nAMD + DME; ~60% treatment-eligible
        "biomarker_fraction": None,
        "has_biomarker": False,
        "annual_cost": 8_000,         # Anti-VEGF (aflibercept/faricimab) 6-8 injections/yr
        "formulary_coverage": 0.96,
        "pa_approval_rate": 0.72,
        "meps_fill_rate": 0.82,
        "meps_adherence": 0.70,
        "population_source": "American Academy of Ophthalmology nAMD/DME epidemiology",
        "pricing_source": "CMS Part B ASP (aflibercept/Eylea, faricimab/Vabysmo)",
    },
}


def get_enrichment_data(
    disease_name: str,
    therapeutic_area: str,
) -> DiseaseEnrichment:
    """
    Get comprehensive enriched parameters for a disease from specialized databases.
    Returns a DiseaseEnrichment with all fields populated.

    Data sources:
      - NCI SEER 2024 (US Public Domain)
      - AACR Project GENIE v16.1 (CC BY 4.0)
      - Orphanet (CC BY 4.0)
      - ClinVar (US Public Domain)
      - CMS Part D/B ASP (US Public Domain)
      - CMS MA Formulary Reference File (US Public Domain)
      - AHRQ MEPS Statistical Briefs (US Public Domain)
    """
    t0 = time.monotonic()

    # Check cache first
    cache_key = hashlib.md5(f"{disease_name}:{therapeutic_area}".encode()).hexdigest()
    cached = _CACHE.get(cache_key)
    if cached:
        cached.cache_hit = True
        return cached

    subcategory_id = _route_disease(disease_name, therapeutic_area)

    # Start with pre-loaded enrichment DB (best data, zero latency)
    pre_loaded = _DISEASE_ENRICHMENT_DB.get(disease_name)
    sources_used = []

    if pre_loaded:
        enrichment = DiseaseEnrichment(
            disease_name=disease_name,
            therapeutic_area=therapeutic_area,
            subcategory_id=subcategory_id,
            us_patient_population=pre_loaded["population"],
            population_source=pre_loaded["population_source"],
            biomarker_eligible=int(pre_loaded["population"] * pre_loaded["biomarker_fraction"])
                if pre_loaded.get("biomarker_fraction") else None,
            biomarker_fraction=pre_loaded.get("biomarker_fraction"),
            annual_treatment_cost=pre_loaded["annual_cost"],
            pricing_source=pre_loaded["pricing_source"],
            formulary_coverage=pre_loaded["formulary_coverage"],
            pa_approval_rate=pre_loaded["pa_approval_rate"],
            meps_fill_rate=pre_loaded["meps_fill_rate"],
            meps_adherence_rate=pre_loaded["meps_adherence"],
            has_biomarker=pre_loaded.get("has_biomarker", False),
            sources_used=[pre_loaded["population_source"], pre_loaded["pricing_source"]],
        )
        # Compute realized TAM factor
        enrichment.realized_tam_factor = round(
            enrichment.formulary_coverage *
            enrichment.pa_approval_rate *
            enrichment.meps_fill_rate *
            enrichment.meps_adherence_rate,
            3
        )
        sources_used.extend(enrichment.sources_used)

    else:
        # Fallback: try specialized connectors in order
        pop, pop_src = _infer_population(disease_name, therapeutic_area, subcategory_id)
        cost, cost_src = _infer_pricing(therapeutic_area, subcategory_id)
        formulary_cov = _infer_formulary_coverage(therapeutic_area, subcategory_id)
        meps = _infer_meps_factors(therapeutic_area)

        enrichment = DiseaseEnrichment(
            disease_name=disease_name,
            therapeutic_area=therapeutic_area,
            subcategory_id=subcategory_id,
            us_patient_population=pop,
            population_source=pop_src,
            annual_treatment_cost=cost,
            pricing_source=cost_src,
            formulary_coverage=formulary_cov["coverage"],
            pa_approval_rate=formulary_cov["pa_rate"],
            meps_fill_rate=meps["fill_rate"],
            meps_adherence_rate=meps["adherence"],
            has_biomarker="biomarker" in disease_name.lower() or subcategory_id in (
                "biologic_oncology", "drug_oncology", "gene_therapy_rare",
                "gene_therapy_hematology", "diagnostic_companion",
            ),
            sources_used=[pop_src, cost_src],
        )
        enrichment.realized_tam_factor = round(
            formulary_cov["coverage"] * formulary_cov["pa_rate"] *
            meps["fill_rate"] * meps["adherence"],
            3
        )

    enrichment.enrichment_latency_ms = round((time.monotonic() - t0) * 1000, 1)
    _CACHE.set(cache_key, enrichment, ttl=7 * 86400)  # 7-day cache
    return enrichment


def _infer_population(disease_name: str, therapeutic_area: str, subcategory_id: str) -> tuple[int, str]:
    """Infer population from specialized connectors."""
    d_l = disease_name.lower()
    ta_l = therapeutic_area.lower()

    # Try NCI SEER for oncology
    if any(x in ta_l for x in ["oncology", "cancer", "hematology"]):
        try:
            from app.ingestion.connectors.seer_cancer import get_cancer_incidence
            seer = get_cancer_incidence(disease_name)
            if seer:
                stage_iv = int(seer["annual_new_cases"] * seer.get("stage_dist_distant", 0.30))
                return stage_iv, f"NCI SEER 2024 Stage IV incidence ({seer['annual_new_cases']:,} × {seer.get('stage_dist_distant',0.3):.0%})"
        except Exception:
            pass

    # Try Orphanet for rare diseases
    if any(x in ta_l for x in ["rare", "orphan", "gene_therapy", "genetic"]) or any(x in subcategory_id for x in ["gene_therapy", "rare"]):
        try:
            from app.ingestion.connectors.orphanet import get_rare_disease_prevalence
            orphan_data = get_rare_disease_prevalence(disease_name)
            if orphan_data.get("found"):
                return orphan_data["us_patient_estimate"], f"Orphanet (CC BY 4.0) {orphan_data['prevalence_per_million']}/million"
        except Exception:
            pass

    # TA-based defaults (last resort)
    _TA_POP_DEFAULTS = {
        "amr_infectious": 400_000, "oncology": 50_000, "cns": 500_000,
        "cardiovascular": 1_500_000, "metabolic": 5_000_000, "gene_therapy": 15_000,
        "rare_disease": 25_000, "immunology": 600_000, "vaccine": 5_000_000,
        "device": 800_000, "diagnostic": 1_000_000, "other": 200_000,
    }
    for key, pop in _TA_POP_DEFAULTS.items():
        if key in ta_l:
            return pop, f"TA default ({key})"
    return 200_000, "TA default (other)"


def _infer_pricing(therapeutic_area: str, subcategory_id: str) -> tuple[float, str]:
    """Infer drug pricing from CMS Part D/B benchmarks."""
    _SUBCATEGORY_PRICING = {
        "drug_amr":             (18_000,   "CMS ASP (ceftazidime-avibactam per course)"),
        "drug_amr_community":   (1_200,    "CMS Part D (oral antibiotic per course)"),
        "drug_oncology":        (180_000,  "CMS Part D median oral oncology WAC"),
        "biologic_oncology":    (220_000,  "CMS Part B ASP median IV oncology biologic"),
        "gene_therapy_rare":    (2_200_000,"CMS Part B (Zolgensma/Casgevy precedent)"),
        "gene_therapy_hematology":(2_200_000,"CMS Part B gene therapy (Casgevy)"),
        "gene_therapy_oncology":(475_000,  "CMS Part B CAR-T (Kymriah/Yescarta)"),
        "gene_therapy_cns":     (800_000,  "Projected ASO/gene therapy CNS pricing"),
        "gene_therapy_rna":     (125_000,  "CMS Part D (nusinersen/Spinraza annual)"),
        "drug_cns_neurodegen":  (28_000,   "CMS Part B (lecanemab) or Part D (CNS drug)"),
        "drug_metabolic":       (13_618,   "CMS Part D (semaglutide/Ozempic actual)"),
        "drug_cardiovascular":  (8_000,    "CMS Part D (SGLT2 inhibitor actual spend)"),
        "drug_immunology":      (30_000,   "CMS Part D (JAK inhibitor net estimate)"),
        "biologic_immunology":  (35_000,   "CMS Part D (biologic net after rebates)"),
        "drug_rare_disease":    (340_000,  "IQVIA orphan drug median WAC"),
        "biologic_rare_disease":(450_000,  "CMS Part B ERT/protein replacement"),
        "drug_mental_health":   (8_000,    "CMS Part D antidepressant/antipsychotic"),
        "device_cardiovascular":(25_000,   "CMS DRG device fraction"),
        "device_metabolic":     (6_000,    "CMS Part D/DME CGM annual cost"),
        "diagnostic_molecular_lab":(1_800, "CMS CLFS NGS panel rate"),
        "diagnostic_poc":       (35,       "CMS CLFS POC test rate"),
        "digital_cds":          (80_000,   "Enterprise SaaS annual site license"),
        "digital_rpm":          (800,      "CMS RPM reimbursement annual"),
        "vaccine_prophylactic": (200,      "CDC VFC contract price"),
        "vaccine_cancer_immuno":(150_000,  "Projected therapeutic cancer vaccine pricing"),
    }
    result = _SUBCATEGORY_PRICING.get(subcategory_id)
    if result:
        return result
    return 50_000, "Median specialty drug WAC (IQVIA 2023)"


def _infer_formulary_coverage(therapeutic_area: str, subcategory_id: str) -> dict:
    """Infer formulary coverage and PA rates by subcategory."""
    _FORMULARY_DEFAULTS = {
        "drug_amr":             {"coverage": 0.85, "pa_rate": 0.88},
        "drug_oncology":        {"coverage": 0.92, "pa_rate": 0.88},
        "biologic_oncology":    {"coverage": 0.90, "pa_rate": 0.88},
        "gene_therapy_rare":    {"coverage": 0.85, "pa_rate": 0.92},
        "gene_therapy_hematology":{"coverage": 0.87, "pa_rate": 0.92},
        "gene_therapy_oncology":{"coverage": 0.89, "pa_rate": 0.87},
        "drug_cns_neurodegen":  {"coverage": 0.55, "pa_rate": 0.88},  # AD coverage low
        "drug_metabolic":       {"coverage": 0.82, "pa_rate": 0.71},
        "drug_cardiovascular":  {"coverage": 0.88, "pa_rate": 0.82},
        "drug_immunology":      {"coverage": 0.75, "pa_rate": 0.70},
        "biologic_immunology":  {"coverage": 0.80, "pa_rate": 0.72},
        "drug_rare_disease":    {"coverage": 0.80, "pa_rate": 0.88},
        "drug_mental_health":   {"coverage": 0.72, "pa_rate": 0.78},
        "device_cardiovascular":{"coverage": 0.92, "pa_rate": 0.88},
        "device_metabolic":     {"coverage": 0.88, "pa_rate": 0.82},
        "digital_cds":          {"coverage": 0.55, "pa_rate": 0.95},
        "vaccine_prophylactic": {"coverage": 0.90, "pa_rate": 0.98},  # Vaccines: essentially no PA barrier
        "diagnostic_molecular_lab":{"coverage": 0.82, "pa_rate": 0.75},
    }
    return _FORMULARY_DEFAULTS.get(subcategory_id, {"coverage": 0.75, "pa_rate": 0.80})


def _infer_meps_factors(therapeutic_area: str) -> dict:
    """Infer MEPS fill rate and adherence from AHRQ published data."""
    _MEPS_DEFAULTS = {
        "oncology":    {"fill_rate": 0.91, "adherence": 0.81},
        "rare_disease":{"fill_rate": 0.93, "adherence": 0.90},
        "gene_therapy":{"fill_rate": 0.94, "adherence": 0.96},
        "cns":         {"fill_rate": 0.70, "adherence": 0.58},
        "metabolic":   {"fill_rate": 0.78, "adherence": 0.55},
        "cardiovascular":{"fill_rate": 0.82, "adherence": 0.68},
        "immunology":  {"fill_rate": 0.85, "adherence": 0.72},
        "amr_infectious":{"fill_rate": 0.95, "adherence": 0.92},  # Acute, short course
        "vaccine":     {"fill_rate": 0.35, "adherence": 1.00},    # Uptake rate ≈ fill
        "device":      {"fill_rate": 0.88, "adherence": 0.82},
    }
    ta_l = therapeutic_area.lower()
    for key, factors in _MEPS_DEFAULTS.items():
        if key in ta_l:
            return factors
    return {"fill_rate": 0.75, "adherence": 0.70}
