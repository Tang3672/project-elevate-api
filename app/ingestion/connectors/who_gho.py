"""
WHO Global Health Observatory (GHO) Burden Connector
=====================================================
Source:  WHO GHO OData API (ghoapi.azureedge.net)
License: WHO Terms of Use — commercial-safe (more permissive than ICTRP)
         Cite: "World Health Organization. Global Health Observatory."
Data:    Disease DALYs, mortality, prevalence via GHE_DALYNUM indicator
         Covers 194 countries; we filter to USA + Global for the scorer.

This is the PRIMARY commercial-safe replacement for IHME GBD data.
Do NOT load GBD data into disease_burden (commercial_use_restricted=true).

GHE cause-code → disease mapping is maintained in _GHE_CAUSE_MAP below.
Extend as needed; keep mapping documented for auditing.
"""

import logging
import time
from typing import Optional

import requests

from app.db.database import get_pool

logger = logging.getLogger(__name__)

GHO_BASE = "https://ghoapi.azureedge.net/api"
_DELAY   = 0.3


# ── GHE cause code → our disease universe mapping ─────────────────────────────
# Format: {our_disease_name: {"ghe_code": "GHECAUSES_GHE###", "gbd_cause": "label"}}
# These codes are from WHO GHE 2019 classification (stable identifiers).

_GHE_CAUSE_MAP: dict[str, dict] = {
    "Glioblastoma Multiforme":               {"ghe_code": "GHECAUSES_GHE079",  "label": "Brain and nervous system cancers"},
    "Pancreatic Ductal Adenocarcinoma":      {"ghe_code": "GHECAUSES_GHE067",  "label": "Pancreas cancer"},
    "ALS (SOD1-mutant)":                     {"ghe_code": "GHECAUSES_GHE101",  "label": "Other neurological conditions"},
    "Carbapenem-resistant Enterobacterales": {"ghe_code": "GHECAUSES_GHE039",  "label": "Lower respiratory infections (proxy)"},
    "Acinetobacter baumannii MDR":           {"ghe_code": "GHECAUSES_GHE039",  "label": "Lower respiratory infections (proxy)"},
    "Spinal Muscular Atrophy Type 2":        {"ghe_code": "GHECAUSES_GHE101",  "label": "Other neurological conditions"},
    "HER2-low Breast Cancer":               {"ghe_code": "GHECAUSES_GHE070",  "label": "Breast cancer"},
    "KRAS G12C NSCLC":                       {"ghe_code": "GHECAUSES_GHE068",  "label": "Trachea, bronchus, lung cancers"},
    "Huntington Disease":                    {"ghe_code": "GHECAUSES_GHE094",  "label": "Neurological conditions"},
    "Friedreich Ataxia":                     {"ghe_code": "GHECAUSES_GHE101",  "label": "Other neurological conditions"},
    "C. difficile Infection":               {"ghe_code": "GHECAUSES_GHE039",  "label": "Lower respiratory infections (proxy)"},
    "MRSA Skin Infections":                  {"ghe_code": "GHECAUSES_GHE002",  "label": "Infectious and parasitic diseases"},
    "Type 1 Diabetes (CGM/automated insulin)": {"ghe_code": "GHECAUSES_GHE080", "label": "Diabetes mellitus"},
    "Alzheimer Disease (early/MCI)":        {"ghe_code": "GHECAUSES_GHE095",  "label": "Alzheimer's disease and other dementias"},
    "Pulmonary Arterial Hypertension":       {"ghe_code": "GHECAUSES_GHE110",  "label": "Cardiovascular diseases"},
    "Duchenne Muscular Dystrophy":           {"ghe_code": "GHECAUSES_GHE101",  "label": "Other neurological conditions"},
    "Myelofibrosis JAK-resistant":           {"ghe_code": "GHECAUSES_GHE077",  "label": "Leukaemia"},
    "Geographic Atrophy (dry AMD)":          {"ghe_code": "GHECAUSES_GHE106",  "label": "Macular degeneration"},
    "Sickle Cell Disease (gene therapy)":    {"ghe_code": "GHECAUSES_GHE050",  "label": "Haemoglobin disorders"},
    "RSV in elderly/immunocompromised":      {"ghe_code": "GHECAUSES_GHE039",  "label": "Lower respiratory infections"},
    "Sepsis (AI early detection)":           {"ghe_code": "GHECAUSES_GHE052",  "label": "Neonatal sepsis and infections (proxy)"},
    "NASH/MASH":                             {"ghe_code": "GHECAUSES_GHE123",  "label": "Cirrhosis of the liver"},
    "Prostate Cancer (PSMA-targeted)":       {"ghe_code": "GHECAUSES_GHE074",  "label": "Prostate cancer"},
    "Bipolar Depression":                    {"ghe_code": "GHECAUSES_GHE084",  "label": "Bipolar disorder"},
    "Rare Pediatric Epilepsy (SCN1A)":       {"ghe_code": "GHECAUSES_GHE097",  "label": "Epilepsy"},
}

# Spatial dimension codes
_USA_CODE    = "USA"
_GLOBAL_CODE = "GLOBAL"


# ── API helpers ───────────────────────────────────────────────────────────────

def _fetch_ghe_dalys(ghe_code: str, spatial_dim: str = "USA",
                     year: int = 2019, sex: str = "SEX_BTSX") -> Optional[float]:
    """
    Fetch total DALYs for a cause code + location + year from WHO GHE_DALYNUM.
    Returns absolute DALY count (thousands) or None.
    sex options: SEX_BTSX (both), SEX_MLE (male), SEX_FMLE (female)
    """
    try:
        # Filter: country, all ages, both sexes, specific year and cause
        url = (
            f"{GHO_BASE}/GHE_DALYNUM"
            f"?$filter=SpatialDim eq '{spatial_dim}'"
            f" and TimeDim eq {year}"
            f" and Dim1 eq '{sex}'"
            f" and Dim2 eq 'AGEGROUP_AGEAll'"
            f" and Dim3 eq '{ghe_code}'"
            f"&$select=NumericValue,TimeDim,Dim3"
            f"&$top=5"
        )
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            vals = r.json().get("value", [])
            if vals:
                return float(vals[0].get("NumericValue") or 0)
    except Exception as e:
        logger.warning("WHO GHO fetch failed (cause=%s, loc=%s): %s", ghe_code, spatial_dim, e)
    return None


def _fetch_mortality_rate(ghe_code: str, spatial_dim: str = "USA",
                          year: int = 2019) -> Optional[float]:
    """Fetch mortality rate per 100k for a cause code."""
    try:
        url = (
            f"{GHO_BASE}/GHE_DEATHS_NUMERIC"
            f"?$filter=SpatialDim eq '{spatial_dim}'"
            f" and TimeDim eq {year}"
            f" and Dim1 eq 'SEX_BTSX'"
            f" and Dim2 eq 'AGEGROUP_AGEAll'"
            f" and Dim3 eq '{ghe_code}'"
            f"&$top=5"
        )
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            vals = r.json().get("value", [])
            if vals:
                return float(vals[0].get("NumericValue") or 0)
    except Exception as e:
        logger.warning("WHO GHO mortality failed (cause=%s): %s", ghe_code, e)
    return None


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _upsert_burden(conn, mondo_id: Optional[str], disease_label: str,
                         source_code: str, metric: str, value: float,
                         unit: str, location: str, year: int, raw: dict) -> None:
    try:
        await conn.execute("""
            INSERT INTO disease_burden (
                mondo_id, disease_label, source_name, source_code,
                commercial_safe, metric, value, unit, location, year,
                age_group, sex, raw_data, fetched_at
            ) VALUES ($1,$2,'who_gho',$3,TRUE,$4,$5,$6,$7,$8,'All ages','Both sexes',$9,NOW())
            ON CONFLICT (mondo_id, source_name, metric, location, year, age_group, sex)
            DO UPDATE SET
                value      = EXCLUDED.value,
                raw_data   = EXCLUDED.raw_data,
                fetched_at = NOW()
        """,
            mondo_id, disease_label, source_code, metric, value, unit, location, year,
            __import__("json").dumps(raw),
        )
    except Exception as e:
        logger.error("Burden upsert failed for %s/%s: %s", disease_label, metric, e)


async def _lookup_mondo_id(conn, disease_label: str) -> Optional[str]:
    row = await conn.fetchrow(
        "SELECT mondo_id FROM disease WHERE lower(label) = lower($1) LIMIT 1",
        disease_label
    )
    if row:
        return row["mondo_id"]
    # Try xref_map
    row = await conn.fetchrow(
        "SELECT canonical_id FROM xref_map WHERE canonical_type='disease' AND lower(source_id)=lower($1) LIMIT 1",
        disease_label
    )
    return row["canonical_id"] if row else None


# ── Public entry points ───────────────────────────────────────────────────────

async def load_burden_for_diseases(
    disease_names: list[str] | None = None,
    year: int = 2019,
) -> dict[str, float]:
    """
    Fetch WHO GHO DALY counts for the given disease names (or all mapped diseases)
    and persist them into disease_burden (commercial_safe=TRUE).

    Returns {disease_name: us_dalys} for successfully fetched diseases.
    """
    targets = disease_names or list(_GHE_CAUSE_MAP.keys())
    pool    = await get_pool()
    results: dict[str, float] = {}

    async with pool.acquire() as conn:
        for disease in targets:
            mapping = _GHE_CAUSE_MAP.get(disease)
            if not mapping:
                logger.warning("WHO GHO: no cause-code mapping for '%s'", disease)
                continue

            ghe_code = mapping["ghe_code"]
            mondo_id = await _lookup_mondo_id(conn, disease)

            # Fetch US DALYs
            dalys_raw = _fetch_ghe_dalys(ghe_code, spatial_dim=_USA_CODE, year=year)
            time.sleep(_DELAY)

            if dalys_raw is not None:
                # WHO GHE_DALYNUM is in thousands
                dalys = dalys_raw * 1000
                await _upsert_burden(
                    conn, mondo_id, disease, ghe_code,
                    "dalys_absolute", dalys, "DALYs",
                    "United States", year,
                    {"ghe_code": ghe_code, "raw_thousands": dalys_raw},
                )
                results[disease] = dalys
                logger.info("WHO GHO: %s US DALYs=%,.0f (year=%d)", disease, dalys, year)
            else:
                logger.warning("WHO GHO: no DALY data for '%s' (code=%s)", disease, ghe_code)

            # Also fetch mortality for richer burden picture
            deaths_raw = _fetch_mortality_rate(ghe_code, spatial_dim=_USA_CODE, year=year)
            time.sleep(_DELAY)
            if deaths_raw is not None:
                await _upsert_burden(
                    conn, mondo_id, disease, ghe_code,
                    "deaths_absolute", deaths_raw * 1000, "deaths",
                    "United States", year,
                    {"ghe_code": ghe_code, "raw_thousands": deaths_raw},
                )

    logger.info("WHO GHO burden load complete: %d/%d diseases fetched", len(results), len(targets))
    return results


async def get_us_dalys(disease_name: str, year: int = 2019) -> Optional[float]:
    """
    Fast read path: return US DALYs for a disease from the DB.
    Falls back to WHO GHO API if not in DB. Returns None if unavailable.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT value FROM disease_burden
            WHERE disease_label = $1
              AND source_name   = 'who_gho'
              AND metric        = 'dalys_absolute'
              AND location      = 'United States'
              AND year          = $2
              AND commercial_safe = TRUE
            LIMIT 1
        """, disease_name, year)
        if row:
            return float(row["value"])

    # Not in DB yet — fetch live and cache
    mapping = _GHE_CAUSE_MAP.get(disease_name)
    if not mapping:
        return None
    dalys_raw = _fetch_ghe_dalys(mapping["ghe_code"], spatial_dim=_USA_CODE, year=year)
    if dalys_raw is None:
        return None
    dalys = dalys_raw * 1000
    # Cache it
    async with pool.acquire() as conn:
        mondo_id = await _lookup_mondo_id(conn, disease_name)
        await _upsert_burden(conn, mondo_id, disease_name, mapping["ghe_code"],
                             "dalys_absolute", dalys, "DALYs", "United States", year,
                             {"ghe_code": mapping["ghe_code"], "raw_thousands": dalys_raw})
    return dalys
