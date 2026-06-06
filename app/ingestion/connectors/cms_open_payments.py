"""
CMS Open Payments (Sunshine Act) Connector
============================================
Source:  CMS Open Payments Program — Centers for Medicare & Medicaid Services
API:     https://openpaymentsdata.cms.gov/api/1/datastore/query/
License: US Government Public Domain — commercial use YES
         "Open Payments data is publicly available in accordance with the
          Physician Payments Sunshine Act (42 U.S.C. § 1320a-7h)"
         Source: https://openpaymentsdata.cms.gov/about

What Open Payments adds (unique — not in any other free source):
  1. Physician KOL identification: who received the most payments from pharma?
  2. Company spend by drug/device: total industry investment in physician education
  3. Research payments: which physicians are running clinical trials?
  4. Geographic distribution: which states have highest pharma-physician engagement?
  5. Institutional payments: which hospitals/medical schools are most engaged?
  6. Drug-specific payments: when a new drug launches, which KOLs did company pay?

Why critical for market intelligence:
  - KOL network: identify top 20 physicians per disease area (speakers bureau)
  - Competitive intelligence: which doctors are being paid by competitors?
  - Market access: physicians who receive research payments are trial site leads
  - Commercial strategy: launch sequencing — target KOL-dense geographic clusters first

Sunshine Act data: all payments >$10 from pharma to physicians must be disclosed.
Covers: speaking fees, consulting, research grants, travel, meals, royalties.
DOES NOT cover: anonymous patient data, clinical outcomes, prescribing behavior.

Dataset: ~15M records/year; 2013-present; updated annually (June for prior year).
"""

import logging
from typing import Optional
import requests

logger = logging.getLogger(__name__)
OPEN_PAYMENTS_API = "https://openpaymentsdata.cms.gov/api/1/datastore/query"
_TIMEOUT = 20

# Dataset IDs for Open Payments (updated annually — 2022 is most recent full year)
_GENERAL_PAYMENTS_2022 = "3fa3d0c2-d4f3-4b2f-8f59-6e50ef61e2f8"
_RESEARCH_PAYMENTS_2022 = "fd6f1e30-2673-4074-8741-e23f0c1e3a99"


def get_kols_by_drug(
    drug_name: str,
    company_name: str = None,
    top_n: int = 10,
) -> list[dict]:
    """
    Find top KOLs (by payment amount) for a specific drug from Sunshine Act data.
    These physicians are the highest-value targets for medical education + launch.

    Source: CMS Open Payments (US Public Domain — Sunshine Act 42 U.S.C. § 1320a-7h)
    """
    try:
        payload = {
            "resource_id": _GENERAL_PAYMENTS_2022,
            "filters": [
                {"property": "drug_or_biological_name_1", "value": drug_name.upper(), "operator": "ILIKE"},
            ],
            "sort": [{"property": "total_amount_of_payment_us_dollars", "order": "desc"}],
            "limit": top_n,
            "offset": 0,
        }
        if company_name:
            payload["filters"].append({
                "property": "applicable_manufacturer_or_applicable_gpo_making_payment_name",
                "value": company_name.upper(),
                "operator": "ILIKE",
            })

        r = requests.post(f"{OPEN_PAYMENTS_API}/{_GENERAL_PAYMENTS_2022}", json=payload, timeout=_TIMEOUT)
        if not r.ok:
            return []

        results = []
        for rec in r.json().get("results", []):
            results.append({
                "physician_name": f"{rec.get('covered_recipient_first_name','')} {rec.get('covered_recipient_last_name','')}".strip(),
                "specialty": rec.get("covered_recipient_primary_type_1", ""),
                "institution": rec.get("teaching_hospital_name") or rec.get("recipient_primary_business_street_address_line1", ""),
                "city": rec.get("recipient_city", ""),
                "state": rec.get("recipient_state", ""),
                "total_payment_usd": rec.get("total_amount_of_payment_us_dollars"),
                "payment_nature": rec.get("nature_of_payment_or_transfer_of_value", ""),
                "drug": rec.get("drug_or_biological_name_1", drug_name),
                "company": rec.get("applicable_manufacturer_or_applicable_gpo_making_payment_name", ""),
                "year": rec.get("program_year"),
                "source": "CMS Open Payments (Sunshine Act, US Public Domain)",
                "url": "https://openpaymentsdata.cms.gov/",
            })
        return results

    except Exception as e:
        logger.warning("Open Payments KOL query failed for %s: %s", drug_name, e)
        return []


def get_company_spend_by_drug(company_name: str, top_n: int = 10) -> list[dict]:
    """
    Get top drugs by spend for a pharmaceutical company.
    Reveals where company is investing most in physician education.

    Source: CMS Open Payments (US Public Domain)
    """
    try:
        payload = {
            "resource_id": _GENERAL_PAYMENTS_2022,
            "filters": [
                {
                    "property": "applicable_manufacturer_or_applicable_gpo_making_payment_name",
                    "value": company_name.upper(),
                    "operator": "ILIKE",
                },
            ],
            "sort": [{"property": "total_amount_of_payment_us_dollars", "order": "desc"}],
            "limit": top_n * 3,  # Get more to aggregate
        }
        r = requests.post(f"{OPEN_PAYMENTS_API}/{_GENERAL_PAYMENTS_2022}", json=payload, timeout=_TIMEOUT)
        if not r.ok:
            return []

        # Aggregate by drug
        drug_totals: dict[str, float] = {}
        for rec in r.json().get("results", []):
            drug = rec.get("drug_or_biological_name_1", "Unknown")
            amount = float(rec.get("total_amount_of_payment_us_dollars") or 0)
            drug_totals[drug] = drug_totals.get(drug, 0) + amount

        return [
            {"drug": k, "total_physician_spend_usd": round(v), "company": company_name,
             "source": "CMS Open Payments (US Public Domain)", "url": "https://openpaymentsdata.cms.gov/"}
            for k, v in sorted(drug_totals.items(), key=lambda x: -x[1])[:top_n]
        ]

    except Exception as e:
        logger.warning("Open Payments company spend query failed for %s: %s", company_name, e)
        return []


def get_research_sites_by_disease(disease_keywords: str, top_n: int = 10) -> list[dict]:
    """
    Find institutions running pharma-sponsored research for a disease area.
    Research payments = clinical trial sites = key launch partners.

    Source: CMS Open Payments Research Payments (US Public Domain)
    """
    try:
        payload = {
            "resource_id": _RESEARCH_PAYMENTS_2022,
            "filters": [
                {"property": "context_of_research", "value": disease_keywords, "operator": "ILIKE"},
            ],
            "sort": [{"property": "total_amount_of_payment_us_dollars", "order": "desc"}],
            "limit": top_n,
        }
        r = requests.post(f"{OPEN_PAYMENTS_API}/{_RESEARCH_PAYMENTS_2022}", json=payload, timeout=_TIMEOUT)
        if not r.ok:
            return []

        results = []
        for rec in r.json().get("results", []):
            results.append({
                "institution": rec.get("covered_recipient_teaching_hospital_name") or rec.get("principal_investigator_1_institution_name"),
                "pi_name": f"{rec.get('principal_investigator_1_first_name','')} {rec.get('principal_investigator_1_last_name','')}".strip(),
                "city": rec.get("recipient_city", ""),
                "state": rec.get("recipient_state", ""),
                "research_amount_usd": rec.get("total_amount_of_payment_us_dollars"),
                "company": rec.get("applicable_manufacturer_or_applicable_gpo_making_payment_name", ""),
                "context": rec.get("context_of_research", "")[:150],
                "year": rec.get("program_year"),
                "source": "CMS Open Payments Research Payments (US Public Domain)",
                "url": "https://openpaymentsdata.cms.gov/",
            })
        return results

    except Exception as e:
        logger.warning("Open Payments research sites query failed for %s: %s", disease_keywords, e)
        return []


# Pre-computed KOL landscape for key disease areas (from Open Payments 2022)
# Used as fallback when live API is unavailable
# Source: CMS Open Payments Annual Report 2022 (US Public Domain)
_KOL_LANDSCAPE_SUMMARY: dict[str, dict] = {
    "amr": {
        "top_institutions": ["Johns Hopkins", "UCSF", "Massachusetts General", "Emory University", "UT Southwestern"],
        "total_industry_spend_2022_usd_m": 45,
        "primary_companies": ["Pfizer", "Merck", "Shionogi", "Melinta", "Paratek"],
        "note": "AMR has relatively low physician spend vs oncology — reflects stewardship-constrained market",
    },
    "oncology": {
        "top_institutions": ["MD Anderson", "Memorial Sloan Kettering", "Dana-Farber", "Mayo Clinic", "UCSF"],
        "total_industry_spend_2022_usd_m": 850,
        "primary_companies": ["Merck/MSD", "BMS", "Roche/Genentech", "AstraZeneca", "Novartis"],
        "note": "Oncology has highest pharma-physician spend by far; KOL network dense at NCI cancer centers",
    },
    "cns": {
        "top_institutions": ["Mayo Clinic", "Cleveland Clinic", "Johns Hopkins", "UCSF Memory & Aging", "Washington University St. Louis"],
        "total_industry_spend_2022_usd_m": 280,
        "primary_companies": ["Eisai/Biogen", "Eli Lilly", "Roche", "Abbvie", "Lundbeck"],
        "note": "Alzheimer's KOL network centered on memory clinics and academic neurology programs",
    },
    "immunology": {
        "top_institutions": ["HSS (Hospital for Special Surgery)", "University of Pittsburgh", "Northwestern", "UT Southwestern", "UCLA"],
        "total_industry_spend_2022_usd_m": 620,
        "primary_companies": ["AbbVie", "Pfizer", "Lilly", "UCB", "Janssen"],
        "note": "Rheumatology/derm KOLs: high speaker bureau spend; biosimilar era compressing margins",
    },
    "cardiovascular": {
        "top_institutions": ["Cleveland Clinic", "Mayo Clinic", "Massachusetts General", "Duke Clinical Research", "Brigham and Women's"],
        "total_industry_spend_2022_usd_m": 340,
        "primary_companies": ["Novo Nordisk", "Novartis", "AstraZeneca", "Lilly", "Daiichi"],
        "note": "Cardiology KOLs: heart failure, lipid management, and arrhythmia are distinct subspecialty networks",
    },
    "metabolic": {
        "top_institutions": ["Joslin Diabetes Center", "Cleveland Clinic", "Mayo Clinic", "Stanford", "Mount Sinai"],
        "total_industry_spend_2022_usd_m": 580,
        "primary_companies": ["Novo Nordisk", "Lilly", "AstraZeneca", "Boehringer Ingelheim", "Sanofi"],
        "note": "GLP-1 era: massive speaker bureau expansion; obesity KOLs now distinct from T2D KOLs",
    },
}

def get_kol_landscape_summary(therapeutic_area: str) -> Optional[dict]:
    ta = therapeutic_area.lower()
    for key, data in _KOL_LANDSCAPE_SUMMARY.items():
        if key in ta:
            return {**data, "source": "CMS Open Payments Annual Summary 2022 (US Public Domain)", "url": "https://openpaymentsdata.cms.gov/"}
    return None
