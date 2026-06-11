"""
Regulatory Precedent Service — approved-drug landscape via openFDA
====================================================================
Before pursuing a new indication, a PI/TTO needs to know: what's
already FDA-approved for this condition? How crowded is the standard
of care, and which companies hold the relevant approvals (potential
acquirers, partners, or competitors)? This is the kind of "regulatory
precedent" question PitchBook doesn't answer (it's not a regulatory
database) and that takes a PI hours of manual Drugs@FDA searching.

Source: openFDA Drug Label API (api.fda.gov/drug/label.json) — free,
no API key required.
"""

import logging

import httpx

logger = logging.getLogger(__name__)

OPENFDA_LABEL_URL = "https://api.fda.gov/drug/label.json"


async def get_regulatory_precedent(disease_name: str) -> dict:
    """
    Search FDA drug labels for a given indication.
    Returns: {total_labels, approved_drugs, market_maturity_signal}
    """
    keywords = disease_name.replace("(", "").replace(")", "").strip()
    params = {
        "search": f'indications_and_usage:"{keywords}"',
        "limit": 30,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(OPENFDA_LABEL_URL, params=params)
            if r.status_code != 200:
                return {}
            data = r.json()
            total = data.get("meta", {}).get("results", {}).get("total", 0)

            seen = set()
            drugs = []
            for res in data.get("results", []):
                of = res.get("openfda") or {}
                generic = (of.get("generic_name") or [None])[0]
                if not generic or generic in seen:
                    continue
                seen.add(generic)
                brand = (of.get("brand_name") or [None])[0]
                manufacturer = (of.get("manufacturer_name") or [None])[0]
                route = (of.get("route") or [None])[0]
                drugs.append({
                    "generic_name":  generic.title(),
                    "brand_name":    brand,
                    "manufacturer":  manufacturer or "Unknown",
                    "route":         route or "",
                    "label_updated": res.get("effective_time", ""),
                })
                if len(drugs) >= 8:
                    break

            if total > 200:
                signal = "CROWDED — well-established standard of care; differentiation must be explicit"
            elif total > 30:
                signal = "MODERATE — some approved options exist; positioning vs. these is needed"
            else:
                signal = "OPEN — few/no FDA-approved drugs reference this indication (potential unmet need or novel indication)"

            logger.info("Regulatory precedent: %d FDA labels for '%s', %d distinct approved drugs",
                         total, disease_name, len(drugs))
            return {
                "total_labels":          total,
                "approved_drugs":        drugs,
                "market_maturity_signal": signal,
            }
    except Exception as e:
        logger.warning("Regulatory precedent fetch failed (non-fatal): %s", e)
        return {}


def format_regulatory_precedent(data: dict, disease_name: str) -> str:
    """Format regulatory precedent as a context block for the report."""
    if not data:
        return ""

    lines = [
        "=== REGULATORY PRECEDENT — APPROVED DRUG LANDSCAPE (openFDA, free public data) ===",
        f"FDA drug labels referencing '{disease_name}': {data.get('total_labels', 0)}",
        f"Market maturity signal: {data.get('market_maturity_signal', '')}",
        "",
    ]

    drugs = data.get("approved_drugs", [])
    if drugs:
        lines.append("FDA-APPROVED DRUGS WITH THIS INDICATION (differentiation bar / potential partners):")
        for d in drugs:
            brand = f" ({d['brand_name']})" if d.get("brand_name") and d["brand_name"].lower() != d["generic_name"].lower() else ""
            lines.append(
                f"  • {d['generic_name']}{brand} — {d['manufacturer']}"
                + (f" | {d['route']}" if d.get("route") else "")
                + (f" | label updated {d['label_updated']}" if d.get("label_updated") else "")
            )
        lines.append("")

    lines.append("=== END REGULATORY PRECEDENT ===")
    return "\n".join(lines)
