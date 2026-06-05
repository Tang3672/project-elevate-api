"""
USASpending.gov Federal Healthcare Contracts Connector
=======================================================
Source:  USASpending.gov — US government federal spending database
API:     https://api.usaspending.gov/api/v2/
License: US Government — Public Domain (17 U.S.C. § 105) — commercial use YES
         "USASpending.gov is a public website from the federal government."
         No rate limits documented. No auth required.

What USASpending adds (unique — not in any other free source):
  1. BARDA contracts and awards — antimicrobial/pandemic contracts with dollar amounts
  2. DoD/DARPA health tech contracts — defense-funded medical innovation
  3. NIH contracts (not grants — different from NIH RePORTER)
  4. CMS IT and analytics contracts — hospital quality, payment model contracts
  5. VA drug formulary contracts — veteran-specific market access signal

Why valuable:
  - BARDA awards ($50M-$200M) are early signals of commercial pull for AMR drugs
  - PASTEUR Act equivalent payouts now visible in USASpending
  - DoD contracts for trauma, field medicine, wearables signal military market
  - Federal contract wins are leading indicators of commercial traction

SBIR.gov API covers early-stage grants; USASpending covers larger awards.
"""

import logging
from typing import Optional
import requests

logger = logging.getLogger(__name__)

USA_SPENDING_API = "https://api.usaspending.gov/api/v2"
_TIMEOUT = 20


def search_healthcare_contracts(
    keywords: list[str],
    award_min_usd: int = 1_000_000,
    agency: str = "HHS",
    limit: int = 10,
) -> list[dict]:
    """
    Search USASpending for federal healthcare contracts.

    Source: USASpending.gov (US public domain) — commercial use YES
    """
    try:
        payload = {
            "filters": {
                "keywords": keywords,
                "agencies": [{"type": "awarding", "tier": "toptier", "name": agency}],
                "award_amounts": [{"lower_bound": award_min_usd}],
                "award_type_codes": ["A", "B", "C", "D"],  # contracts
            },
            "fields": ["Award ID", "Recipient Name", "Award Amount", "Description",
                       "Award Type", "Start Date", "End Date", "awarding_agency_name",
                       "Funding Agency Name", "Place of Performance City Name"],
            "page": 1,
            "limit": limit,
            "sort": "Award Amount",
            "order": "desc",
        }

        r = requests.post(
            f"{USA_SPENDING_API}/search/spending_by_award/",
            json=payload,
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()

        results = []
        for award in data.get("results", []):
            results.append({
                "award_id": award.get("Award ID"),
                "recipient": award.get("Recipient Name"),
                "amount_usd": award.get("Award Amount"),
                "description": award.get("Description", "")[:200],
                "award_type": award.get("Award Type"),
                "start_date": award.get("Start Date"),
                "end_date": award.get("End Date"),
                "agency": award.get("awarding_agency_name"),
                "source": "USASpending.gov (US public domain)",
                "url": f"https://www.usaspending.gov/award/{award.get('Award ID')}",
            })
        return results

    except Exception as e:
        logger.warning("USASpending query failed for %s: %s", keywords, e)
        return []


def get_barda_amr_contracts() -> list[dict]:
    """
    Get BARDA contracts for antimicrobial drug development.
    BARDA awards are the primary commercial pull mechanism for AMR drugs.
    Source: USASpending.gov (US public domain)
    """
    return search_healthcare_contracts(
        keywords=["antimicrobial", "antibiotic", "carbapenem", "CARB-X", "PASTEUR"],
        agency="HHS",
        award_min_usd=5_000_000,
        limit=10,
    )


def get_sbir_healthcare_awards(keyword: str, limit: int = 10) -> list[dict]:
    """
    Search SBIR.gov for healthcare SBIR/STTR awards.
    Source: SBIR.gov API (US public domain) — commercial use YES.
    Complements NIH RePORTER (grants) with early-stage commercial innovation.
    """
    try:
        r = requests.get(
            "https://api.sbir.gov/public/api/awards",
            params={
                "keyword": keyword,
                "agency": "HHS",
                "rows": limit,
                "start": 0,
            },
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()

        results = []
        for award in data.get("docs", []):
            results.append({
                "company": award.get("firm"),
                "title": award.get("title"),
                "amount_usd": award.get("award_amount"),
                "phase": award.get("phase"),
                "year": award.get("award_year"),
                "abstract": (award.get("abstract", "") or "")[:300],
                "program": award.get("program"),
                "source": "SBIR.gov (US public domain)",
                "url": f"https://www.sbir.gov/sbirsearch/detail/award?id={award.get('award_number', '')}",
            })
        return results

    except Exception as e:
        logger.warning("SBIR.gov query failed for '%s': %s", keyword, e)
        return []
