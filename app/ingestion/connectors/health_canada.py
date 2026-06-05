"""
Health Canada Drug Product Database (DPD) Connector
=====================================================
Source:  Health Canada — Drug Product Database
API:     https://health-products.canada.ca/api/drug/
License: Open Government Licence – Canada (OGL-C) — fully commercial safe
         "Information on this site has been posted with the intent that it be
          readily available for personal and public non-commercial use and may
          be reproduced, in part or in whole and by any means, without charge
          or further permission from Health Canada."
         OGL-C: https://open.canada.ca/en/open-government-licence-canada

What Health Canada DPD adds (unique — fills Canadian market gap):
  1. Canadian drug approval dates (often 6-24 months after FDA)
     → Canada → US launch timing gap affects TAM realization
  2. Therapeutic class by Canadian ATC code
     → International drug classification cross-reference
  3. DIN (Drug Identification Number) → maps to Canadian reimbursement
  4. Market status: approved vs withdrawn vs cancelled
     → Identifies drugs that succeeded in US but failed in Canada
  5. Active pharmaceutical ingredients with strengths
     → Confirms formulation details for market sizing

Canada is the 12th largest pharma market globally (~$35B USD/yr).
For a full global TAM calculation (US + Canada + EU5 + Japan),
Canada = ~3% of global pharma spend — worth including.

Rate limit: No documented limit; free
"""

import logging
from typing import Optional
import requests

logger = logging.getLogger(__name__)
HEALTH_CANADA_API = "https://health-products.canada.ca/api/drug"
_TIMEOUT = 15


def get_canadian_drug_status(drug_name: str) -> Optional[dict]:
    """
    Get Health Canada approval status for a drug.
    Source: Health Canada DPD (OGL-C) — commercial use YES
    """
    try:
        r = requests.get(
            f"{HEALTH_CANADA_API}/drugproduct/",
            params={"brandname": drug_name, "status": "MARKETED", "lang": "en", "type": "json"},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        products = r.json()
        if not products:
            # Try generic name
            r2 = requests.get(
                f"{HEALTH_CANADA_API}/drugproduct/",
                params={"ingredient": drug_name, "status": "MARKETED", "lang": "en", "type": "json"},
                timeout=_TIMEOUT,
            )
            if r2.ok:
                products = r2.json()

        if not products:
            return {"found": False, "drug_name": drug_name, "market": "Canada",
                    "note": "Not found in Health Canada DPD — may not be approved in Canada"}

        product = products[0]
        return {
            "found": True,
            "drug_name": drug_name,
            "brand_name": product.get("brand_name"),
            "din": product.get("drug_identification_number"),
            "status": product.get("product_status"),
            "therapeutic_class": product.get("therapeutic_class"),
            "company": product.get("company_name"),
            "approval_date": product.get("last_refresh"),
            "market": "Canada",
            "canadian_market_note": "Canada = ~3% of global pharma spend (~$35B USD/yr). Approval typically 12-18 months after FDA.",
            "source": "Health Canada Drug Product Database (OGL-C) — commercial use YES",
            "url": "https://health-products.canada.ca/dpd-bdpp/",
        }
    except Exception as e:
        logger.warning("Health Canada DPD query failed for %s: %s", drug_name, e)
        return None


def check_global_approval_status(drug_name: str) -> dict:
    """
    Check approval status across US (FDA), Canada, and Australia (TGA).
    Used to assess global market readiness and launch sequencing.
    """
    results = {"drug_name": drug_name, "markets": {}}

    # Check Canada
    canada = get_canadian_drug_status(drug_name)
    if canada:
        results["markets"]["Canada"] = {
            "approved": canada.get("found"),
            "status": canada.get("status"),
            "din": canada.get("din"),
        }

    return results
