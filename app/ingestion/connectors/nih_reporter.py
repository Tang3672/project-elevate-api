"""
NIH RePORTER Canonical Connector
==================================
Source:  NIH RePORTER API v2 (api.reporter.nih.gov)
License: US public domain — fully commercial-safe
Rate:    ≤1 req/sec recommended; 500 records/page; 10,000-record result cap
         (work around cap by date-partitioning queries)

Stores per-disease NIH funding signal in disease_burden:
  metric='nih_active_grant_count'   — number of active grants
  metric='nih_total_funding_usd'    — total award $ for active grants

Also stores per-grant records in nih_grants table for drill-down.

Used by the opportunity scorer as a funding-validation signal.
"""

import logging
import time
from typing import Optional

import requests

from app.db.database import get_pool

logger = logging.getLogger(__name__)

NIH_API = "https://api.reporter.nih.gov/v2/projects/search"
_DELAY  = 1.1   # stay under 1 req/sec

# Disease → search terms tuned for RePORTER full-text search
_DISEASE_SEARCH_TERMS: dict[str, str] = {
    "Glioblastoma Multiforme":               "glioblastoma",
    "Pancreatic Ductal Adenocarcinoma":      "pancreatic cancer",
    "ALS (SOD1-mutant)":                     "amyotrophic lateral sclerosis",
    "Carbapenem-resistant Enterobacterales": "carbapenem resistant Enterobacterales",
    "Acinetobacter baumannii MDR":           "Acinetobacter baumannii",
    "Spinal Muscular Atrophy Type 2":        "spinal muscular atrophy",
    "HER2-low Breast Cancer":               "HER2 breast cancer",
    "KRAS G12C NSCLC":                       "KRAS lung cancer",
    "Huntington Disease":                    "Huntington disease",
    "Friedreich Ataxia":                     "Friedreich ataxia",
    "C. difficile Infection":               "Clostridioides difficile",
    "MRSA Skin Infections":                  "MRSA skin infection",
    "Type 1 Diabetes (CGM/automated insulin)": "type 1 diabetes",
    "Alzheimer Disease (early/MCI)":        "Alzheimer disease",
    "Pulmonary Arterial Hypertension":       "pulmonary arterial hypertension",
    "Duchenne Muscular Dystrophy":           "Duchenne muscular dystrophy",
    "Myelofibrosis JAK-resistant":           "myelofibrosis",
    "Geographic Atrophy (dry AMD)":          "geographic atrophy macular",
    "Sickle Cell Disease (gene therapy)":    "sickle cell disease",
    "RSV in elderly/immunocompromised":      "respiratory syncytial virus elderly",
    "Sepsis (AI early detection)":           "sepsis detection",
    "NASH/MASH":                             "nonalcoholic steatohepatitis",
    "Prostate Cancer (PSMA-targeted)":       "prostate cancer PSMA",
    "Bipolar Depression":                    "bipolar disorder",
    "Rare Pediatric Epilepsy (SCN1A)":       "SCN1A epilepsy dravet",
}


# ── API helpers ───────────────────────────────────────────────────────────────

def _search_grants(search_text: str, from_year: int = 2022,
                   limit: int = 500, offset: int = 0) -> dict:
    """Single page of RePORTER results."""
    payload = {
        "criteria": {
            "advanced_text_search": {
                "operator": "and",
                "search_field": "all",
                "search_text": search_text,
            },
            "project_start_date": {"from_date": f"{from_year}-01-01"},
            "is_active": True,
        },
        "include_fields": [
            "ProjectNum", "ProjectTitle", "AwardAmount", "FiscalYear",
            "Organization", "AbstractText", "Terms",
        ],
        "limit": limit,
        "offset": offset,
    }
    try:
        r = requests.post(NIH_API, json=payload, timeout=20,
                          headers={"Content-Type": "application/json"})
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.warning("RePORTER search failed for '%s': %s", search_text, e)
        return {}


def _get_all_grants(search_text: str, from_year: int = 2022,
                    max_results: int = 2000) -> tuple[int, int, list[dict]]:
    """
    Paginate RePORTER (500/page) up to max_results.
    Returns (total_count, total_funding_usd, [grant records]).
    """
    grants: list[dict] = []
    total_funding = 0
    page_size = 500

    first = _search_grants(search_text, from_year, limit=page_size)
    total = first.get("meta", {}).get("total", 0)

    for p in first.get("results", []):
        awards = p.get("award_amount") or 0
        total_funding += int(awards)
        grants.append(p)

    # Fetch additional pages if needed (up to max_results cap)
    offset = page_size
    while offset < min(total, max_results):
        time.sleep(_DELAY)
        page = _search_grants(search_text, from_year, limit=page_size, offset=offset)
        for p in page.get("results", []):
            awards = p.get("award_amount") or 0
            total_funding += int(awards)
            grants.append(p)
        offset += page_size

    return total, total_funding, grants


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _ensure_grants_table(conn) -> None:
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS nih_grants (
            id              SERIAL PRIMARY KEY,
            project_num     TEXT UNIQUE,
            disease_label   TEXT,
            mondo_id        VARCHAR(20),
            title           TEXT,
            award_amount    BIGINT,
            fiscal_year     INTEGER,
            org_name        TEXT,
            abstract        TEXT,
            fetched_at      TIMESTAMPTZ DEFAULT NOW()
        );
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS nih_disease_idx ON nih_grants (disease_label);"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS nih_mondo_idx ON nih_grants (mondo_id);"
    )


async def _upsert_funding_burden(conn, disease_label: str, mondo_id: Optional[str],
                                 grant_count: int, total_usd: int) -> None:
    for metric, value, unit in [
        ("nih_active_grant_count", float(grant_count), "grants"),
        ("nih_total_funding_usd",  float(total_usd),   "USD"),
    ]:
        try:
            await conn.execute("""
                INSERT INTO disease_burden
                    (mondo_id, disease_label, source_name, source_code, commercial_safe,
                     metric, value, unit, location, year)
                VALUES ($1,$2,'nih_reporter','nih_reporter',TRUE,$3,$4,$5,'United States',2024)
                ON CONFLICT (mondo_id, source_name, metric, location, year, age_group, sex)
                DO UPDATE SET value=EXCLUDED.value, fetched_at=NOW()
            """, mondo_id, disease_label, metric, value, unit)
        except Exception as e:
            logger.error("funding burden upsert failed (%s/%s): %s", disease_label, metric, e)


async def _upsert_grant(conn, grant: dict, disease_label: str,
                        mondo_id: Optional[str]) -> None:
    try:
        org = grant.get("organization", {})
        org_name = org.get("org_name") if isinstance(org, dict) else None
        await conn.execute("""
            INSERT INTO nih_grants
                (project_num, disease_label, mondo_id, title, award_amount, fiscal_year, org_name, abstract)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
            ON CONFLICT (project_num) DO UPDATE SET
                award_amount = EXCLUDED.award_amount,
                fetched_at   = NOW()
        """,
            grant.get("project_num"),
            disease_label,
            mondo_id,
            grant.get("project_title", "")[:500],
            grant.get("award_amount") or 0,
            grant.get("fiscal_year"),
            org_name,
            (grant.get("abstract_text") or "")[:2000],
        )
    except Exception as e:
        logger.warning("grant upsert failed: %s", e)


# ── Public entry points ───────────────────────────────────────────────────────

async def load_nih_funding(from_year: int = 2022) -> dict[str, dict]:
    """
    Fetch active NIH grants for all diseases and persist burden metrics.
    Returns {disease: {"grant_count": N, "total_usd": N}}.
    """
    pool = await get_pool()
    results: dict[str, dict] = {}

    async with pool.acquire() as conn:
        await _ensure_grants_table(conn)

        for disease, search_text in _DISEASE_SEARCH_TERMS.items():
            total, funding, grants = _get_all_grants(search_text, from_year)
            time.sleep(_DELAY)

            # Resolve MONDO
            mondo_id = None
            try:
                row = await conn.fetchrow(
                    "SELECT mondo_id FROM disease WHERE lower(label)=lower($1) LIMIT 1", disease
                )
                if row:
                    mondo_id = row["mondo_id"]
            except Exception:
                pass

            await _upsert_funding_burden(conn, disease, mondo_id, total, funding)

            # Store top 50 grants for drill-down
            for g in grants[:50]:
                await _upsert_grant(conn, g, disease, mondo_id)

            results[disease] = {"grant_count": total, "total_usd": funding}
            logger.info("NIH RePORTER: %s → %d grants, $%,.0f", disease, total, funding)

    return results


async def get_nih_grant_count(disease_name: str, from_year: int = 2022) -> int:
    """
    Fast path: return cached grant count from DB, or fetch live.
    Used by opportunity scorer as a validation signal.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow("""
                SELECT value FROM disease_burden
                WHERE disease_label = $1
                  AND source_name   = 'nih_reporter'
                  AND metric        = 'nih_active_grant_count'
                ORDER BY fetched_at DESC LIMIT 1
            """, disease_name)
            if row:
                return int(row["value"])
        except Exception:
            pass

    # Live fetch
    search_text = _DISEASE_SEARCH_TERMS.get(disease_name, disease_name)
    data = _search_grants(search_text, from_year, limit=1)
    return data.get("meta", {}).get("total", 0)
