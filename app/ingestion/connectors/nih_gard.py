"""
NIH GARD (Genetic and Rare Diseases Information Center) Connector
==================================================================
Source:  NIH National Center for Advancing Translational Sciences (NCATS)
API:     https://rarediseases.info.nih.gov/api/
License: US Public Domain (NIH government work) — commercial use YES
         "GARD content is in the public domain."
         Source: https://rarediseases.info.nih.gov/about

What GARD adds (unique — bridges Orphanet and US regulatory terminology):
  1. US-standard disease naming (NIH/ClinVar/ICD-10 aligned)
     → Orphanet uses European naming; GARD bridges to US regulatory context
  2. Inheritance pattern (AR, AD, XR, XD, mitochondrial, unknown)
     → Required for gene therapy eligibility (carrier screening, family testing)
  3. OMIM/Orphanet/MeSH/NCI Thesaurus cross-references
     → Links our disease names to regulatory submission identifiers
  4. Prevalence category (extremely rare <1:1M, very rare <1:100K, rare <1:2K)
     → Regulatory threshold for Orphan Drug designation eligibility
  5. Related genes list (NCBI Gene ID cross-reference)
     → Directly connects disease to potential gene therapy targets
  6. Research resources: trial registries, natural history studies
     → Intelligence on which academic programs are active

Why this is better than Orphanet for US market:
  - Orphanet prevalence uses EU population and EU regulatory thresholds
  - GARD uses US naming aligned with FDA/NIH regulatory submissions
  - GARD has 6,800+ diseases vs Orphanet's similar scope but with US ICD-10 codes
  - FDA orphan designation applications cite GARD as a primary source

Rate limit: No documented limit; public NIH API
"""

import logging
from typing import Optional
import requests

logger = logging.getLogger(__name__)
GARD_API = "https://rarediseases.info.nih.gov/api"
_TIMEOUT = 15


def search_rare_disease(disease_name: str) -> Optional[dict]:
    """
    Search NIH GARD for a rare disease.
    Returns US-standard naming, inheritance, related genes, prevalence category.

    Source: NIH GARD (US Public Domain) — commercial use YES
    """
    try:
        r = requests.get(
            f"{GARD_API}/diseases",
            params={"name": disease_name, "pageSize": 3, "pageNumber": 1},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        diseases = data.get("diseases", [])
        if not diseases:
            return None

        disease = diseases[0]
        disease_id = disease.get("diseaseId")

        # Get detailed info
        detail_r = requests.get(f"{GARD_API}/diseases/{disease_id}", timeout=_TIMEOUT)
        detail = detail_r.json() if detail_r.ok else {}

        synonyms = [s.get("name") for s in disease.get("synonyms", [])[:3]]
        genes = [g.get("symbol") for g in detail.get("genes", [])[:5]]
        inheritance = [m.get("name") for m in detail.get("inheritanceModes", [])]

        # Map prevalence category to US patient estimate
        prevalence_category = detail.get("prevalenceCategory", {}).get("name", "Unknown")
        _PREVALENCE_US_MAP = {
            "Extremely rare (<1/1 000 000)": 334,
            "Very rare (<1/100 000)": 3_340,
            "Rare (<1/2 000)": 167_000,
            "Uncommon": 500_000,
        }
        us_patient_estimate = _PREVALENCE_US_MAP.get(prevalence_category, None)

        return {
            "found": True,
            "disease_name": disease.get("diseaseName", disease_name),
            "gard_id": disease_id,
            "synonyms": synonyms,
            "inheritance_modes": inheritance,
            "related_genes": genes,
            "prevalence_category": prevalence_category,
            "us_patient_estimate": us_patient_estimate,
            "qualifies_orphan_us": us_patient_estimate is None or us_patient_estimate < 200_000,
            "omim_id": next((x.get("id") for x in detail.get("xrefs", []) if x.get("database") == "OMIM"), None),
            "orphanet_id": next((x.get("id") for x in detail.get("xrefs", []) if x.get("database") == "Orphanet"), None),
            "icd10": next((x.get("id") for x in detail.get("xrefs", []) if x.get("database") == "ICD-10-CM"), None),
            "source": "NIH GARD (US Public Domain)",
            "url": f"https://rarediseases.info.nih.gov/diseases/{disease_id}/",
            "citation": f"NIH GARD. {disease.get('diseaseName', disease_name)}. rarediseases.info.nih.gov. Accessed 2025.",
        }

    except Exception as e:
        logger.warning("NIH GARD query failed for %s: %s", disease_name, e)
        return None


def get_rare_disease_genes(disease_name: str) -> list[str]:
    """
    Get gene list associated with a rare disease from GARD.
    Useful for gene therapy target identification.
    Source: NIH GARD (US Public Domain)
    """
    data = search_rare_disease(disease_name)
    return data.get("related_genes", []) if data else []
