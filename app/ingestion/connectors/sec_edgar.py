"""
SEC EDGAR Pipeline Disclosure Connector
=========================================
Source:  SEC EDGAR Full-Text Search (efts.sec.gov)
License: US public domain — fully commercial safe
Data:    Drug pipeline mentions in 10-K / 10-Q / 8-K filings from pharma companies

Why valuable:
  - 10-K annual reports contain management's view of their pipeline value
  - 8-K filings = real-time clinical trial results and FDA decisions
  - Analyst/management discussion of a disease = financial market validation
  - Rising 8-K count for a disease = active phase of development
  - Phase 3 failures disclosed in 8-K = white space just opened up

We extract per-disease:
  edgar_10k_mention_count   — times disease appears in annual reports
  edgar_8k_mention_count    — real-time event disclosures (trials, FDA)
  edgar_recent_filers       — top companies filing about this disease
"""

import logging
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

EDGAR_FTS = "https://efts.sec.gov/LATEST/search-index"
_DELAY    = 0.5
_TIMEOUT  = 12

_DISEASE_SEARCH_TERMS: dict[str, str] = {
    "Alzheimer Disease (early/MCI)":        "Alzheimer disease lecanemab donanemab amyloid",
    "NASH/MASH":                            "nonalcoholic steatohepatitis NASH MASH resmetirom",
    "Huntington Disease":                   "Huntington disease huntingtin clinical trial",
    "Sickle Cell Disease (gene therapy)":   "sickle cell disease gene therapy Casgevy Lyfgenia",
    "Glioblastoma Multiforme":              "glioblastoma GBM clinical trial immunotherapy",
    "Pancreatic Ductal Adenocarcinoma":     "pancreatic cancer KRAS drug approval",
    "Type 2 Diabetes (GLP-1 resistant)":   "GLP-1 semaglutide tirzepatide diabetes obesity",
    "Obesity (CNS/metabolic)":             "obesity weight loss GLP-1 wegovy drug approval",
    "Carbapenem-resistant Enterobacterales":"carbapenem resistant antibiotic clinical trial FDA",
    "MRSA Skin Infections":                 "MRSA skin infection antibiotic delafloxacin FDA",
    "Geographic Atrophy (dry AMD)":         "geographic atrophy complement AMD Syfovre Izervay",
    "Multiple Myeloma (triple-refractory)": "multiple myeloma bispecific antibody CAR-T FDA",
    "Lung Cancer (NSCLC, IO-resistant)":   "non-small cell lung cancer KRAS PD-L1 resistance",
    "Major Depression (TRD)":             "treatment-resistant depression ketamine psilocybin FDA",
    "Prostate Cancer (PSMA-targeted)":     "PSMA prostate cancer lutetium Pluvicto radioligand",
    "Inflammatory Bowel Disease (UC/CD)":  "Crohn ulcerative colitis IL-23 biologic drug approval",
    "HIV (long-acting ART / cure)":         "HIV long-acting antiretroviral cabotegravir rilpivirine",
    "Parkinson Disease (early stage)":      "Parkinson disease alpha-synuclein clinical trial FDA",
    "Atrial Fibrillation":                  "atrial fibrillation ablation antiarrhythmic drug FDA",
    "Sepsis (AI early detection)":          "sepsis AI detection diagnostic FDA clearance",
}


def _search_edgar(term: str, form_type: str, days_back: int = 365) -> dict:
    """Search EDGAR full-text for a term in a specific form type."""
    from datetime import date, timedelta
    start = (date.today() - timedelta(days=days_back)).isoformat()

    result = {"count": 0, "filers": []}
    try:
        r = requests.get(
            EDGAR_FTS,
            params={
                "q":         f'"{term}"',
                "dateRange": "custom",
                "startdt":   start,
                "forms":     form_type,
                "_source":   "file_date,entity_name,form_type,file_num",
                "hits.hits.total.value": 1,
            },
            timeout=_TIMEOUT,
            headers={"User-Agent": "ProjectElevate/1.0 contact@projectelevate.io"},
        )
        if r.status_code == 200:
            data  = r.json()
            total = data.get("hits", {}).get("total", {}).get("value", 0)
            hits  = data.get("hits", {}).get("hits", [])
            result["count"] = total
            seen_filers: set = set()
            for h in hits[:5]:
                src = h.get("_source", {})
                filer = src.get("entity_name", "")
                if filer and filer not in seen_filers:
                    seen_filers.add(filer)
                    result["filers"].append(filer)
    except Exception as e:
        logger.warning("EDGAR search failed for '%s' (%s): %s", term[:30], form_type, e)
    return result


async def load_edgar_signals(disease_names: list[str] | None = None) -> dict[str, dict]:
    """
    Fetch SEC EDGAR pipeline disclosure signals.
    Returns {disease: {10k_count, 8k_count, filers}}.
    """
    targets = disease_names or list(_DISEASE_SEARCH_TERMS.keys())
    results: dict[str, dict] = {}

    try:
        from app.db.database import get_pool
        pool = await get_pool()
    except Exception:
        pool = None

    for disease in targets:
        term = _DISEASE_SEARCH_TERMS.get(disease)
        if not term:
            continue

        # Use first two words for tighter filing search
        short_term = " ".join(term.split()[:3])

        d10k = _search_edgar(short_term, "10-K")
        time.sleep(_DELAY)
        d8k  = _search_edgar(short_term, "8-K")
        time.sleep(_DELAY)

        data = {
            "10k_count":   d10k["count"],
            "8k_count":    d8k["count"],
            "filers":      list(set(d10k["filers"] + d8k["filers"]))[:5],
        }
        results[disease] = data

        if pool:
            try:
                async with pool.acquire() as conn:
                    mondo_row = await conn.fetchrow(
                        "SELECT mondo_id FROM disease WHERE lower(label)=lower($1) LIMIT 1", disease
                    )
                    mondo_id = mondo_row["mondo_id"] if mondo_row else None
                    for metric, value in [
                        ("edgar_10k_mention_count", float(d10k["count"])),
                        ("edgar_8k_mention_count",  float(d8k["count"])),
                    ]:
                        await conn.execute("""
                            INSERT INTO disease_burden
                                (mondo_id, disease_label, source_name, source_code, commercial_safe,
                                 metric, value, unit, location, year)
                            VALUES ($1,$2,'sec_edgar','sec_efts',TRUE,$3,$4,'filings','United States',2026)
                            ON CONFLICT (mondo_id, source_name, metric, location, year, age_group, sex)
                            DO UPDATE SET value=EXCLUDED.value, fetched_at=NOW()
                        """, mondo_id, disease, metric, value)
            except Exception as e:
                logger.warning("EDGAR DB store failed for %s: %s", disease, e)

        logger.info("SEC EDGAR: %s → 10-K:%d, 8-K:%d filings, filers:%s",
                    disease, d10k["count"], d8k["count"],
                    str(data["filers"][:2])[:60])

    return results
