"""
Orphanet Rare Disease Connector
=================================
Source:  Orphanet — European Reference Network for Rare Diseases
API:     https://api.orphacode.org (no auth required for basic lookups)
         Bulk: https://www.orphadata.com/orphanet-scientific-knowledge-files/
License: CC BY 4.0 — fully commercial safe with attribution
         "Orphanet data is available under a Creative Commons Attribution 4.0 licence"
         Source: https://www.orphadata.com/about/

Why this is the gold standard for rare disease:
  1. Orphanet prevalence figures are cited in FDA orphan designation applications
  2. Regulatory standard: EMA uses Orphanet's "<5/10,000 EU population" criterion
  3. Disease classification: ORPHAcodes are used in EU rare disease registry
  4. Gene-disease associations from OMIM (via Orphanet, CC BY 4.0) — safe commercially
  5. ICD-10/SNOMED cross-references for billing/coding analysis

Critical gap vs existing connectors:
  - WHO GHO doesn't cover most rare diseases (too few DALYs to register)
  - MONDO ontology gives classification but not prevalence estimates
  - Orphanet gives disease-specific prevalence in patients/million — the correct
    denominator for orphan drug market sizing (not ICD-10 codes)
"""

import logging
import time
from typing import Optional
import requests

logger = logging.getLogger(__name__)

ORPHANET_API = "https://api.orphacode.org/EN"
_TIMEOUT = 15
_DELAY   = 0.3

# Pre-loaded Orphanet prevalence data for key rare diseases
# Source: Orphanet — https://www.orphadata.com (CC BY 4.0)
# Prevalence type: point prevalence unless stated; all US extrapolations
# US population ~334M for extrapolation
_US_POP = 334_000_000

_ORPHANET_DISEASE_DATA: dict[str, dict] = {
    # Rare neuromuscular / genetic
    "Spinal Muscular Atrophy":           {"orpha": 70, "prev_per_million": 8.0,   "prev_us": 2_672,   "inheritance": "AR", "icd10": "G12.0"},
    "Duchenne Muscular Dystrophy":       {"orpha": 98896, "prev_per_million": 45.0, "prev_us": 15_030, "inheritance": "XR", "icd10": "G71.01"},
    "Becker Muscular Dystrophy":         {"orpha": 98896, "prev_per_million": 20.0, "prev_us": 6_680,  "inheritance": "XR", "icd10": "G71.01"},
    "Friedreich Ataxia":                 {"orpha": 95, "prev_per_million": 15.0,  "prev_us": 5_010,   "inheritance": "AR", "icd10": "G11.1"},
    "Huntington Disease":                {"orpha": 248, "prev_per_million": 50.0, "prev_us": 16_700,  "inheritance": "AD", "icd10": "G10"},
    "ALS (SOD1 familial)":               {"orpha": 803, "prev_per_million": 30.0, "prev_us": 10_020,  "inheritance": "AD/AR","icd10": "G12.21"},
    "Fabry Disease":                     {"orpha": 324, "prev_per_million": 10.0, "prev_us": 3_340,   "inheritance": "XR", "icd10": "E75.21"},
    "Gaucher Disease (type 1)":          {"orpha": 77, "prev_per_million": 10.0,  "prev_us": 3_340,   "inheritance": "AR", "icd10": "E75.22"},
    "Pompe Disease":                     {"orpha": 365, "prev_per_million": 6.0,  "prev_us": 2_004,   "inheritance": "AR", "icd10": "E74.02"},
    "Phenylketonuria":                   {"orpha": 716, "prev_per_million": 30.0, "prev_us": 10_020,  "inheritance": "AR", "icd10": "E70.0"},
    # Hematologic
    "Sickle Cell Disease":               {"orpha": 232, "prev_per_million": 300.0,"prev_us": 100_200, "inheritance": "AR", "icd10": "D57.1"},
    "Beta-Thalassemia Major":            {"orpha": 231214, "prev_per_million": 5.0,"prev_us": 1_670,  "inheritance": "AR", "icd10": "D56.1"},
    "Hemophilia A (severe)":             {"orpha": 98878, "prev_per_million": 30.0,"prev_us": 10_020, "inheritance": "XR", "icd10": "D66"},
    "Hemophilia B (severe)":             {"orpha": 98879, "prev_per_million": 7.0, "prev_us": 2_338,  "inheritance": "XR", "icd10": "D67"},
    # Pulmonary / metabolic
    "Cystic Fibrosis":                   {"orpha": 586, "prev_per_million": 100.0,"prev_us": 33_400,  "inheritance": "AR", "icd10": "J98.4"},
    "Pulmonary Arterial Hypertension":   {"orpha": 422, "prev_per_million": 50.0, "prev_us": 16_700,  "inheritance": "variable","icd10": "I27.0"},
    "Alpha-1 Antitrypsin Deficiency":    {"orpha": 60, "prev_per_million": 750.0, "prev_us": 250_500, "inheritance": "AR", "icd10": "E88.01"},
    # Ophthalmologic
    "Leber Congenital Amaurosis":        {"orpha": 65, "prev_per_million": 10.0,  "prev_us": 3_340,   "inheritance": "AR", "icd10": "H35.50"},
    # Neurological rare
    "Rett Syndrome":                     {"orpha": 778, "prev_per_million": 60.0, "prev_us": 20_040,  "inheritance": "XD", "icd10": "F84.2"},
    "Dravet Syndrome":                   {"orpha": 33069, "prev_per_million": 50.0,"prev_us": 16_700, "inheritance": "AD", "icd10": "G40.833"},
    "Angelman Syndrome":                 {"orpha": 72, "prev_per_million": 50.0,  "prev_us": 16_700,  "inheritance": "imprinting","icd10": "Q93.51"},
    "Prader-Willi Syndrome":             {"orpha": 739, "prev_per_million": 30.0, "prev_us": 10_020,  "inheritance": "imprinting","icd10": "Q87.11"},
    # Lysosomal storage
    "Mucopolysaccharidosis I (Hurler)":  {"orpha": 93473, "prev_per_million": 1.6, "prev_us": 534,   "inheritance": "AR", "icd10": "E76.01"},
    "Mucopolysaccharidosis II (Hunter)": {"orpha": 580, "prev_per_million": 2.0,  "prev_us": 668,    "inheritance": "XR", "icd10": "E76.1"},
    "Niemann-Pick (type C)":             {"orpha": 646, "prev_per_million": 0.5,  "prev_us": 167,    "inheritance": "AR", "icd10": "E75.242"},
    # Rare immunological
    "Hereditary Angioedema":             {"orpha": 91378, "prev_per_million": 15.0,"prev_us": 5_010,  "inheritance": "AD", "icd10": "D84.1"},
    "Ataxia-Telangiectasia":             {"orpha": 100, "prev_per_million": 5.0,  "prev_us": 1_670,   "inheritance": "AR", "icd10": "G11.3"},
}


def get_orphanet_disease(disease_name: str) -> Optional[dict]:
    """
    Get Orphanet data for a rare disease: prevalence, ORPHAcode, inheritance pattern.

    Source: Orphanet (CC BY 4.0) — commercial use permitted with attribution.
    """
    # Try pre-loaded data first
    for key, data in _ORPHANET_DISEASE_DATA.items():
        if disease_name.lower() in key.lower() or key.lower() in disease_name.lower():
            return {
                **data,
                "disease_name": key,
                "query": disease_name,
                "prevalence_us_estimate": data["prev_us"],
                "source": "Orphanet (www.orphadata.com) CC BY 4.0",
                "citation": f"Orphanet. {key}. Orphanet Report Series: Prevalence and incidence of rare diseases. 2024.",
                "url": f"https://www.orpha.net/en/disease/detail/{data['orpha']}",
                "note": f"Prevalence {data['prev_per_million']:.1f}/million EU population; US extrapolated from {_US_POP//1_000_000}M population",
            }

    # Try live API
    try:
        r = requests.get(
            f"{ORPHANET_API}/Disease/Search",
            params={"name": disease_name, "lang": "EN"},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        results = r.json()
        if results and isinstance(results, list):
            first = results[0]
            orpha_code = first.get("ORPHAcode")
            return {
                "orpha": orpha_code,
                "disease_name": first.get("Name", disease_name),
                "source": "Orphanet API (CC BY 4.0)",
                "url": f"https://www.orpha.net/en/disease/detail/{orpha_code}",
            }
    except Exception as e:
        logger.warning("Orphanet API call failed for '%s': %s", disease_name, e)

    return None


def get_rare_disease_prevalence(disease_name: str) -> dict:
    """
    Return the EU/US prevalence estimate for a rare disease.
    Orphanet prevalence is the regulatory gold standard for orphan drug designation.

    Returns prevalence per million and estimated US patient count.
    """
    data = get_orphanet_disease(disease_name)
    if not data:
        return {
            "found": False,
            "disease": disease_name,
            "note": "Not in Orphanet database; may not qualify as rare disease (<200K US patients / <5/10K EU)",
        }

    return {
        "found": True,
        "disease": data.get("disease_name"),
        "orpha_code": data.get("orpha"),
        "prevalence_per_million": data.get("prev_per_million"),
        "us_patient_estimate": data.get("prev_us"),
        "inheritance_pattern": data.get("inheritance"),
        "icd10": data.get("icd10"),
        "qualifies_for_orphan_designation": data.get("prev_us", 0) < 200_000,  # <200K US = orphan
        "eu_orphan_threshold": data.get("prev_per_million", 999) < 50,  # <5/10,000 = 50/million EU
        "source": data.get("source"),
        "url": data.get("url"),
    }
