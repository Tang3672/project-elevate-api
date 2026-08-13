#!/usr/bin/env python3
"""
G.14 — Build the EDGAR forecast-to-outcome calibration artifact.

Offline batch script.  Run periodically (weekly/monthly) to refresh the
calibration factors used by app/db/edgar_calibration_repository.py.

What it does
------------
1. Searches EDGAR EFTS full-text search for S-1 filings that mention
   "total addressable market" in the 2018–2023 window.
2. For each hit, fetches the submission metadata to get the company CIK
   and classify the product category.
3. Retrieves actual revenue from the EDGAR company facts API
   (us-gaap Revenues / RevenueFromContractWithCustomerExcludingAssessedTax)
   for the 3 years following the S-1 date.
4. Extracts the stated TAM claim from the filing text via regex.
5. Computes the overestimate ratio: stated_tam / peak_realized_revenue_3yr.
6. Groups pairs by archetype and writes the median ratio per archetype to
   app/data/edgar_calibration.json.

Output JSON shape
-----------------
{
  "built_at": "2026-08-12T00:00:00Z",
  "n_pairs": 142,
  "edgar_source": "https://efts.sec.gov/LATEST/search-index",
  "calibration_factors": {
    "research_tool_non_clinical": {"factor": 2.4, "n": 18, "p25": 1.8, "p75": 4.1},
    "pharma_small_molecule": {"factor": 3.1, "n": 31, ...},
    ...
  },
  "pairs": [
    {
      "cik": "0001234567", "company": "Acme Labs",
      "s1_date": "2020-03-15", "claimed_tam_usd": 50000000,
      "realized_revenue_peak_usd": 2000000,
      "ratio": 25.0, "archetype": "research_tool_non_clinical"
    }, ...
  ]
}

EDGAR API notes
---------------
- Full-text search: https://efts.sec.gov/LATEST/search-index (no auth required)
- Company facts: https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json
- SEC rate limit: 10 requests/second max
- User-Agent header required: "ProjectElevate/1.0 oneonesie100@gmail.com"

Usage
-----
  python scripts/build_edgar_calibration.py [--max-hits 500] [--start 2018] [--end 2023]
  python scripts/build_edgar_calibration.py --dry-run   # print stats, don't write
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import pathlib
import re
import statistics
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("build_edgar_calibration")

_PROJECT_ROOT = pathlib.Path(__file__).parent.parent
_DEFAULT_OUT  = _PROJECT_ROOT / "app" / "data" / "edgar_calibration.json"

_USER_AGENT = "ProjectElevate/1.0 oneonesie100@gmail.com"
_SEC_RATE_LIMIT_RPS = 8   # Stay safely under SEC's 10 req/s limit
_THROTTLE_DELAY = 1.0 / _SEC_RATE_LIMIT_RPS

_EFTS_URL         = "https://efts.sec.gov/LATEST/search-index"
_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"

# Revenue concept names in XBRL/EDGAR, in preference order
_REVENUE_CONCEPTS = [
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
    "RevenueFromContractWithCustomerIncludingAssessedTax",
]

# Regex to find dollar amounts near "total addressable market" in filing text.
# Matches: $1B, $500M, $1.5 billion, $500 million
_TAM_PATTERN = re.compile(
    r"total\s+addressable\s+market[^.]{0,200}?"
    r"\$\s*([\d,]+(?:\.\d+)?)\s*"
    r"(billion|million|B|M|bn|mm)?",
    re.IGNORECASE,
)

# Broad archetype classification by SIC code and keyword
_SIC_ARCHETYPE: dict[str, str] = {
    "7372": "software_samd",        # Prepackaged software
    "7371": "software_samd",        # Computer programming
    "7374": "software_samd",        # Data processing
    "8099": "research_tool_non_clinical",
    "3826": "in_vitro_diagnostic",  # Lab instruments
    "3841": "medical_device_surgical",
    "3845": "medical_device_capital",
    "2836": "pharma_biologic",      # Biologics
    "2835": "in_vitro_diagnostic",  # Diagnostic substances
    "2830": "pharma_small_molecule",
    "2833": "pharma_small_molecule",
    "8731": "research_tool_non_clinical",  # Commercial physical/biological research
    "0100": "research_tool_non_clinical",  # Agriculture (USDA-funded)
}


def _classify_by_description(description: str, sic: str) -> str:
    """Best-effort archetype from SIC + entity description."""
    arch = _SIC_ARCHETYPE.get(str(sic), "")
    if arch:
        return arch
    desc = (description or "").lower()
    if any(kw in desc for kw in ["gene therapy", "cell therapy", "car-t", "aav", "crispr"]):
        return "gene_cell_therapy"
    if any(kw in desc for kw in ["vaccine", "immunization", "mrna"]):
        return "vaccine"
    if any(kw in desc for kw in ["research", "laboratory", "instrument", "sensor", "agronomy"]):
        return "research_tool_non_clinical"
    if any(kw in desc for kw in ["software", "saas", "platform", "digital", "analytics"]):
        return "software_samd"
    if any(kw in desc for kw in ["diagnostic", "assay", "sequencing", "pcr", "ivd"]):
        return "in_vitro_diagnostic"
    if any(kw in desc for kw in ["device", "implant", "catheter", "stent"]):
        return "medical_device_surgical"
    if any(kw in desc for kw in ["biologic", "antibody", "monoclonal", "protein"]):
        return "pharma_biologic"
    if any(kw in desc for kw in ["drug", "molecule", "compound", "inhibitor"]):
        return "pharma_small_molecule"
    return "pharma_small_molecule"  # default


def _extract_tam_from_text(text: str) -> Optional[float]:
    """Extract the first stated TAM dollar amount from filing text."""
    m = _TAM_PATTERN.search(text)
    if not m:
        return None
    amount_str = m.group(1).replace(",", "")
    suffix     = (m.group(2) or "").lower()
    try:
        amount = float(amount_str)
    except ValueError:
        return None
    if suffix in ("billion", "b", "bn"):
        return amount * 1e9
    if suffix in ("million", "m", "mm"):
        return amount * 1e6
    # No suffix — if > 1000, treat as raw USD; else probably millions
    return amount * 1e6 if amount < 10_000 else amount


def _get_peak_revenue(facts: dict, s1_year: int, window_years: int = 3) -> Optional[float]:
    """
    Extract peak annual revenue from XBRL company facts in the
    `window_years` years after the S-1 year.
    """
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    for concept in _REVENUE_CONCEPTS:
        data = us_gaap.get(concept, {})
        usd_entries = data.get("units", {}).get("USD", [])
        annual = [
            e for e in usd_entries
            if e.get("form") in ("10-K", "10-K/A")
            and e.get("end", "")[:4].isdigit()
            and s1_year < int(e["end"][:4]) <= s1_year + window_years
        ]
        if annual:
            return max(e["val"] for e in annual)
    return None


async def _fetch_json(client: httpx.AsyncClient, url: str, params: dict = None) -> dict:
    """Fetch JSON from SEC with rate-limit throttling and User-Agent."""
    await asyncio.sleep(_THROTTLE_DELAY)
    resp = await client.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


async def _fetch_hits(client: httpx.AsyncClient, start: str, end: str, max_hits: int) -> list[dict]:
    """Page through EDGAR EFTS results for S-1 filings mentioning TAM."""
    hits  = []
    from_ = 0
    size  = min(50, max_hits)

    while len(hits) < max_hits:
        params = {
            "q":          '"total addressable market"',
            "forms":      "S-1",
            "dateRange":  "custom",
            "startdt":    start,
            "enddt":      end,
            "from":       from_,
            "size":       size,
        }
        try:
            data   = await _fetch_json(client, _EFTS_URL, params)
            batch  = data.get("hits", {}).get("hits", [])
        except Exception as exc:
            logger.warning("EFTS page error (from=%d): %s", from_, exc)
            break
        if not batch:
            break
        hits  += batch
        from_ += len(batch)
        logger.info("Fetched %d / %d hits", len(hits), max_hits)
        if len(batch) < size:
            break

    return hits[:max_hits]


async def _build(max_hits: int, start: str, end: str, dry_run: bool, out_path: pathlib.Path) -> None:
    headers = {"User-Agent": _USER_AGENT}
    pairs: list[dict] = []

    async with httpx.AsyncClient(headers=headers) as client:
        hits = await _fetch_hits(client, start, end, max_hits)
        logger.info("Processing %d S-1 filing hits", len(hits))

        for hit in hits:
            src      = hit.get("_source", {})
            cik_raw  = src.get("cik", "")
            entity   = src.get("entity_name", "")
            period   = src.get("period_of_report", "")[:10]
            sic      = src.get("sic", "")
            s1_year  = int(period[:4]) if period and period[:4].isdigit() else None
            if not cik_raw or not s1_year:
                continue
            cik = str(cik_raw).zfill(10)

            # Extract TAM from the filing's excerpt text
            excerpt  = hit.get("_source", {}).get("file_date", "") + " " + entity
            text     = hit.get("_source", {}).get("display_names", "") or ""
            tam      = _extract_tam_from_text(text)

            if tam is None:
                # Try fetching the actual filing document for TAM extraction
                try:
                    accession = src.get("accession_no", "").replace("-", "")
                    if accession:
                        doc_url = (
                            f"https://www.sec.gov/Archives/edgar/full-index/"
                            f"{s1_year}/{accession[:4]}/"
                            f"{cik}/{accession}/{accession}-index.json"
                        )
                        idx = await _fetch_json(client, doc_url)
                        filing_url = None
                        for doc in idx.get("directory", {}).get("item", []):
                            if doc.get("type") == "S-1" and doc.get("name", "").endswith(".htm"):
                                filing_url = f"https://www.sec.gov/Archives/edgar/full-index/{s1_year}/{accession[:4]}/{cik}/{accession}/{doc['name']}"
                                break
                        if filing_url:
                            await asyncio.sleep(_THROTTLE_DELAY)
                            resp = await client.get(filing_url, timeout=60)
                            tam  = _extract_tam_from_text(resp.text)
                except Exception as exc:
                    logger.debug("Filing text fetch failed for CIK %s: %s", cik, exc)

            if tam is None or tam <= 0:
                continue

            # Fetch company facts for revenue
            try:
                facts_url = _COMPANY_FACTS_URL.format(cik=cik)
                facts     = await _fetch_json(client, facts_url)
                revenue   = _get_peak_revenue(facts, s1_year)
            except Exception as exc:
                logger.debug("Company facts fetch failed for CIK %s: %s", cik, exc)
                revenue = None

            if not revenue or revenue <= 0:
                continue

            ratio    = tam / revenue
            archetype = _classify_by_description(entity, sic)

            pairs.append({
                "cik":                       cik,
                "company":                   entity,
                "s1_date":                   period,
                "claimed_tam_usd":           tam,
                "realized_revenue_peak_usd": revenue,
                "ratio":                     ratio,
                "archetype":                 archetype,
            })
            logger.info(
                "Pair: %s | TAM=$%.0fM | revenue=$%.0fM | ratio=%.1f | arch=%s",
                entity, tam / 1e6, revenue / 1e6, ratio, archetype,
            )

    # Aggregate calibration factors per archetype (median ratio, count, quartiles)
    arch_ratios: dict[str, list[float]] = {}
    for p in pairs:
        arch_ratios.setdefault(p["archetype"], []).append(p["ratio"])

    calibration_factors: dict[str, dict] = {}
    for arch, ratios in arch_ratios.items():
        ratios_sorted = sorted(ratios)
        n = len(ratios_sorted)
        median = statistics.median(ratios_sorted)
        p25    = ratios_sorted[n // 4] if n >= 4 else ratios_sorted[0]
        p75    = ratios_sorted[3 * n // 4] if n >= 4 else ratios_sorted[-1]
        calibration_factors[arch] = {
            "factor": round(median, 4),
            "n":      n,
            "p25":    round(p25, 4),
            "p75":    round(p75, 4),
        }

    artifact = {
        "built_at":            datetime.now(timezone.utc).isoformat(),
        "n_pairs":             len(pairs),
        "edgar_source":        _EFTS_URL,
        "calibration_factors": calibration_factors,
        "pairs":               pairs,
    }

    logger.info(
        "Calibration artifact: %d pairs across %d archetypes",
        len(pairs), len(calibration_factors),
    )
    for arch, cf in calibration_factors.items():
        logger.info("  %-35s  factor=%.2f  n=%d", arch, cf["factor"], cf["n"])

    if dry_run:
        logger.info("--dry-run: not writing artifact")
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(artifact, f, indent=2)
    logger.info("Wrote artifact to %s", out_path)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--max-hits", type=int, default=500,
                   help="Maximum S-1 hits to process (default: 500)")
    p.add_argument("--start", default="2018-01-01", help="S-1 filing start date (YYYY-MM-DD)")
    p.add_argument("--end",   default="2023-12-31", help="S-1 filing end date (YYYY-MM-DD)")
    p.add_argument("--out",   default=str(_DEFAULT_OUT), help="Output JSON path")
    p.add_argument("--dry-run", action="store_true", help="Print stats but don't write artifact")
    args = p.parse_args()

    asyncio.run(_build(
        max_hits = args.max_hits,
        start    = args.start,
        end      = args.end,
        dry_run  = args.dry_run,
        out_path = pathlib.Path(args.out),
    ))


if __name__ == "__main__":
    main()
