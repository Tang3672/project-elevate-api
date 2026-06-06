"""
CMS Medicare Part D Prescriber-Level Data Connector
=====================================================
Source:  CMS Medicare Part D Prescribers by Provider and Drug
Dataset: https://data.cms.gov/provider-summary-by-type-of-service/medicare-part-d-prescribers/medicare-part-d-prescribers-by-provider-and-drug
License: US Government Public Domain — commercial use YES
         "CMS provides this data as a public service."

What this adds (the most granular prescribing data available for free):
  1. Provider-level drug utilization: how many claims each physician wrote for each drug
  2. Geographic prescribing patterns: which states/cities have highest utilization
  3. Specialty-level penetration: which specialties prescribe the most of a drug
  4. Competitive share: if drug A has 40% of prescriptions vs drug B in a specialty,
     that IS the real-world market share
  5. Prescriber concentration: top 10% of prescribers write 50%+ of claims for most drugs
     → Identifies the exact physicians to target for commercial launch
  6. Total drug cost by provider: prescribing cost signature (low vs high cost prescribers)

Why this is extraordinarily valuable:
  This is real-world market share data at physician level. No competitor provides this.
  EvaluatePharma uses IQVIA MIDAS prescription data (proprietary, $$$).
  We use CMS Part D prescriber data (public domain, free).
  Limitation: Part D covers Medicare patients only (~30% of prescriptions).
  But for specialty drugs targeting Medicare patients (oncology, neurology, CV),
  it captures the majority of the market.

API endpoint: https://data.cms.gov/resource/3z4d-vmhm.json (Socrata)
Rate limit: Free Socrata app token removes rate cap (get at data.cms.gov/developer)
"""

import logging
from typing import Optional
import requests

logger = logging.getLogger(__name__)
PRESCRIBER_API = "https://data.cms.gov/resource/3z4d-vmhm.json"
_TIMEOUT = 20


def get_top_prescribers(
    drug_name: str,
    specialty: str = None,
    state: str = None,
    top_n: int = 10,
) -> list[dict]:
    """
    Get top prescribers (by claim count) for a drug.
    These are the KOLs who are already prescribing this drug or analogues.

    Source: CMS Part D Prescriber Data (US Public Domain)
    """
    try:
        params = {
            "$where": f"UPPER(drug_name) LIKE '%{drug_name.upper()}%'",
            "$order": "tot_clms DESC",
            "$limit": top_n * 2,  # Get more to filter
        }
        if specialty:
            params["$where"] += f" AND UPPER(prscrbr_type) LIKE '%{specialty.upper()}%'"
        if state:
            params["$where"] += f" AND prscrbr_state_abrvtn = '{state.upper()}'"

        r = requests.get(PRESCRIBER_API, params=params, timeout=_TIMEOUT)
        r.raise_for_status()
        records = r.json()[:top_n]

        results = []
        for rec in records:
            results.append({
                "npi": rec.get("prscrbr_npi"),
                "physician_name": f"{rec.get('prscrbr_first_name', '')} {rec.get('prscrbr_last_name', '')}".strip(),
                "specialty": rec.get("prscrbr_type", ""),
                "city": rec.get("prscrbr_city", ""),
                "state": rec.get("prscrbr_state_abrvtn", ""),
                "drug_name": rec.get("drug_name", drug_name),
                "total_claims": rec.get("tot_clms"),
                "total_day_supply": rec.get("tot_day_suply"),
                "total_drug_cost": rec.get("tot_drug_cst"),
                "beneficiary_count": rec.get("tot_benes"),
                "source": "CMS Medicare Part D Prescriber Data (US Public Domain)",
                "url": "https://data.cms.gov/provider-summary-by-type-of-service/medicare-part-d-prescribers/",
            })
        return results

    except Exception as e:
        logger.warning("CMS prescriber query failed for %s: %s", drug_name, e)
        return []


def get_specialty_market_share(drug_name: str, competing_drugs: list[str]) -> dict:
    """
    Estimate market share from CMS Part D prescribing data.
    Compares claim counts across competing drugs in same indication.

    Source: CMS Part D Prescriber Data (US Public Domain)
    """
    try:
        all_drugs = [drug_name] + (competing_drugs or [])[:4]
        drug_claims = {}

        for drug in all_drugs:
            params = {
                "$select": "drug_name, SUM(tot_clms) as total_claims, COUNT(*) as prescriber_count",
                "$where": f"UPPER(drug_name) LIKE '%{drug.upper()}%'",
                "$group": "drug_name",
                "$order": "total_claims DESC",
                "$limit": 1,
            }
            r = requests.get(PRESCRIBER_API, params=params, timeout=_TIMEOUT)
            if r.ok:
                data = r.json()
                if data:
                    drug_claims[drug] = {
                        "total_claims": int(data[0].get("total_claims", 0)),
                        "prescriber_count": int(data[0].get("prescriber_count", 0)),
                    }

        if not drug_claims:
            return {"found": False}

        total_claims = sum(d["total_claims"] for d in drug_claims.values())
        shares = {
            drug: round(data["total_claims"] / max(1, total_claims) * 100, 1)
            for drug, data in drug_claims.items()
        }

        return {
            "found": True,
            "market_shares_pct": shares,
            "total_claims_in_class": total_claims,
            "drug_claims_breakdown": drug_claims,
            "source": "CMS Medicare Part D Prescriber Data (US Public Domain)",
            "url": "https://data.cms.gov/provider-summary-by-type-of-service/medicare-part-d-prescribers/",
            "caveat": "Part D covers Medicare patients (~30% of US prescriptions); skews toward 65+ population",
        }

    except Exception as e:
        logger.warning("CMS market share query failed: %s", e)
        return {"found": False, "error": str(e)}


def get_geographic_prescribing_heatmap(drug_name: str) -> list[dict]:
    """
    Get prescribing volume by state to identify geographic market concentration.
    Source: CMS Part D Prescriber Data (US Public Domain)
    """
    try:
        params = {
            "$select": "prscrbr_state_abrvtn, SUM(tot_clms) as total_claims, COUNT(*) as prescriber_count",
            "$where": f"UPPER(drug_name) LIKE '%{drug_name.upper()}%'",
            "$group": "prscrbr_state_abrvtn",
            "$order": "total_claims DESC",
            "$limit": 15,
        }
        r = requests.get(PRESCRIBER_API, params=params, timeout=_TIMEOUT)
        r.raise_for_status()

        return [
            {
                "state": rec.get("prscrbr_state_abrvtn"),
                "total_claims": int(rec.get("total_claims", 0)),
                "prescriber_count": int(rec.get("prescriber_count", 0)),
                "source": "CMS Part D Prescriber Data (US Public Domain)",
            }
            for rec in r.json()
        ]

    except Exception as e:
        logger.warning("CMS geographic query failed for %s: %s", drug_name, e)
        return []
