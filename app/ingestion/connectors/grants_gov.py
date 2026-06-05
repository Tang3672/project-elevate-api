"""
Grants.gov Federal Funding Opportunities Connector
====================================================
Source:  Grants.gov — US Department of Health and Human Services
API:     https://apply07.grants.gov/grantsws/rest/opportunities/search/
License: US Government Public Domain — commercial use YES
         "Content on Grants.gov is in the public domain."
         Source: https://www.grants.gov/web/grants/learn-grants/grants-101/introduction-to-grants.html

What Grants.gov adds (unique vs NIH Reporter + SBIR.gov):
  1. BARDA Broad Agency Announcements (BAAs) — before awards are made
     → Prospective intelligence: what is government planning to fund?
  2. DARPA/ARPA-H health technology solicitations
  3. DoD CDMRP (Congressionally Directed Medical Research Programs)
     — cancer, ALS, autism, Gulf War illness, Parkinson's — disease-specific DoD funding
  4. VA research opportunities
  5. AHRQ research grants
  6. CDC cooperative agreements
  7. ACF/SAMHSA mental health and substance use programs

NIH Reporter shows AWARDED grants (what already got funded).
SBIR.gov shows small business awards.
Grants.gov shows OPEN SOLICITATIONS — what will get funded next.
This is the forward-looking intelligence signal.

Rate limit: No documented rate limit; no auth required
"""

import logging
from typing import Optional
import requests

logger = logging.getLogger(__name__)
GRANTS_API = "https://apply07.grants.gov/grantsws/rest/opportunities/search/"
_TIMEOUT = 20

# Agency codes for healthcare-relevant agencies
_HEALTHCARE_AGENCIES = {
    "HHS":   "Department of Health and Human Services (NIH, FDA, BARDA, HRSA, CDC, CMS)",
    "DOD":   "Department of Defense (CDMRP disease programs)",
    "VA":    "Department of Veterans Affairs (veterans health research)",
    "AHRQ":  "Agency for Healthcare Research and Quality",
    "ARPA-H":"Advanced Research Projects Agency for Health (ARPA-H)",
}


def search_funding_opportunities(
    keywords: str,
    agency_code: str = "HHS",
    opportunity_status: str = "forecasted,posted",
    limit: int = 10,
) -> list[dict]:
    """
    Search for open federal funding opportunities.
    Source: Grants.gov (US Public Domain) — commercial use YES
    """
    try:
        payload = {
            "keyword": keywords,
            "agency": agency_code,
            "oppStatuses": opportunity_status,
            "rows": limit,
            "start": 0,
        }
        r = requests.post(GRANTS_API, json=payload, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()

        results = []
        for opp in data.get("oppHits", [])[:limit]:
            results.append({
                "title": opp.get("title", "")[:150],
                "agency": opp.get("agencyName", ""),
                "agency_code": opp.get("agency", ""),
                "number": opp.get("number", ""),
                "status": opp.get("oppStatus", ""),
                "category": opp.get("oppCategory", ""),
                "posted_date": opp.get("postedDate"),
                "close_date": opp.get("closeDate"),
                "estimated_total_funding": opp.get("estimatedTotalProgramFunding"),
                "award_count": opp.get("expectedNumberOfAwards"),
                "description": (opp.get("synopsis", "") or "")[:300],
                "cfda_number": opp.get("cfdaNumbers", [None])[0] if opp.get("cfdaNumbers") else None,
                "source": "Grants.gov (US Public Domain)",
                "url": f"https://www.grants.gov/search-results-detail/{opp.get('id', '')}",
            })
        return results

    except Exception as e:
        logger.warning("Grants.gov search failed for '%s': %s", keywords, e)
        return []


def get_barda_opportunities(disease_keywords: str) -> list[dict]:
    """Search for BARDA (Biomedical Advanced Research and Development Authority) opportunities."""
    return search_funding_opportunities(
        keywords=f"BARDA {disease_keywords}",
        agency_code="HHS",
        opportunity_status="forecasted,posted",
        limit=5,
    )


def get_dod_cdmrp_opportunities(disease: str) -> list[dict]:
    """
    Search for DoD CDMRP (Congressionally Directed Medical Research Programs).
    DoD funds cancer, ALS, autism, Parkinson's, lupus, epilepsy, etc.
    Often overlooked non-dilutive funding source for these diseases.
    """
    return search_funding_opportunities(
        keywords=disease,
        agency_code="DOD",
        opportunity_status="forecasted,posted",
        limit=5,
    )


def get_arpa_h_opportunities() -> list[dict]:
    """
    Get ARPA-H (Advanced Research Projects Agency for Health) open opportunities.
    ARPA-H funds transformative health technology — highest dollar, lowest chance.
    Source: Grants.gov ARPA-H solicitations (US Public Domain)
    """
    return search_funding_opportunities(
        keywords="ARPA-H health technology",
        agency_code="HHS",
        opportunity_status="forecasted,posted",
        limit=5,
    )


# Pre-loaded CDMRP disease programs (from DoD CDMRP website — US public domain)
# Source: https://cdmrp.health.mil/about/overview — US Public Domain
_CDMRP_PROGRAMS: dict[str, dict] = {
    "breast_cancer": {
        "program": "Breast Cancer Research Program (BCRP)",
        "annual_funding_m": 120,
        "congress_authorization": "Enacted annually in National Defense Authorization Act",
        "priority_areas": ["metastatic disease", "triple-negative breast cancer", "prevention"],
        "award_types": ["Idea Award ($300K)", "Breakthrough Award ($2.5M)", "Era of Hope Scholar ($1.25M)"],
        "url": "https://cdmrp.health.mil/bcrp/",
    },
    "prostate_cancer": {
        "program": "Prostate Cancer Research Program (PCRP)",
        "annual_funding_m": 100,
        "congress_authorization": "FY2024 NDAA",
        "priority_areas": ["castration-resistant disease", "metastasis", "health disparities"],
        "award_types": ["Idea Award ($200K)", "Transformative Award ($1.5M)", "Clinical Trial Award ($4M)"],
        "url": "https://cdmrp.health.mil/pcrp/",
    },
    "als": {
        "program": "Amyotrophic Lateral Sclerosis Research Program (ALSRP)",
        "annual_funding_m": 30,
        "congress_authorization": "FY2024 NDAA (veteran ALS mortality twice civilian rate)",
        "priority_areas": ["biomarkers", "novel therapeutics", "veteran-specific ALS"],
        "award_types": ["Investigator-Initiated Research Award ($800K)", "Clinical Trial Planning Award ($200K)"],
        "url": "https://cdmrp.health.mil/alsrp/",
    },
    "alzheimers": {
        "program": "Alzheimer's Research Program (ARP)",
        "annual_funding_m": 50,
        "congress_authorization": "FY2024 NDAA (traumatic brain injury connection)",
        "priority_areas": ["TBI-related AD", "biomarkers", "early detection"],
        "award_types": ["Idea Award ($500K)", "Clinical Trial Award ($4M)"],
        "url": "https://cdmrp.health.mil/arp/",
    },
    "epilepsy": {
        "program": "Epilepsy Research Program (ERP)",
        "annual_funding_m": 20,
        "congress_authorization": "FY2024 NDAA",
        "priority_areas": ["refractory epilepsy", "veterans with TBI-related seizures"],
        "award_types": ["Idea Award ($250K)", "Clinical Development Award ($1M)"],
        "url": "https://cdmrp.health.mil/erp/",
    },
    "lupus": {
        "program": "Lupus Research Program (LRP)",
        "annual_funding_m": 15,
        "congress_authorization": "FY2024 NDAA",
        "priority_areas": ["biomarkers", "novel therapeutics", "racial disparities"],
        "award_types": ["Idea Award ($200K)", "Clinical Trial Award ($2M)"],
        "url": "https://cdmrp.health.mil/lrp/",
    },
}


def get_cdmrp_program(disease_name: str) -> Optional[dict]:
    """Return DoD CDMRP program info if one exists for this disease."""
    d = disease_name.lower()
    for key, program in _CDMRP_PROGRAMS.items():
        if any(w in d for w in key.split("_")):
            return {
                **program,
                "note": f"DoD CDMRP {program['program']}: ${program['annual_funding_m']}M/year — often overlooked non-dilutive funding",
                "source": "DoD CDMRP (cdmrp.health.mil) — US Public Domain",
            }
    return None
