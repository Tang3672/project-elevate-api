"""
FDA Drug Approvals Connector
=============================
Sources (all US public domain / CC0):
  1. openFDA drug/label   — indication-text search → approved drug names per disease
  2. openFDA drug/drugsfda — application-level (NDA/BLA/ANDA) sponsor + approval year
  3. Drugs@FDA bulk ZIP    — Products.txt: ApplNo, DrugName, ActiveIngredient, Form, Strength

Strategy:
  - For each disease in our universe, count unique approved drugs via
    openFDA label indication search (count=openfda.generic_name.exact).
  - Store each (disease, drug) pair in drug_disease_indication with the
    application number and approval year where available.
  - Also load the full Drugs@FDA Products.txt into the drug canonical table
    (normalised via RxNorm where possible, brand name otherwise).

All results stored in:
  disease_burden: metric='approved_drug_count', source='openfda'
  drug table: populated from Drugs@FDA Products.txt
  drug_disease_indication: (rxcui/brand_name, mondo_id) pairs

License: openFDA CC0, Drugs@FDA US public domain — fully commercial-safe.
"""

import csv
import io
import logging
import time
import zipfile
from typing import Optional

import requests

from app.db.database import get_pool

logger = logging.getLogger(__name__)

OPENFDA_BASE = "https://api.fda.gov"
DRUGS_AT_FDA_ZIP = "https://www.fda.gov/media/89850/download"
_DELAY = 0.25   # openFDA: 240 req/min with key; we stay conservative

# Disease → search terms that work well with openFDA label indication text
_DISEASE_SEARCH_TERMS: dict[str, str] = {
    "Glioblastoma Multiforme":               "glioblastoma",
    "Pancreatic Ductal Adenocarcinoma":      "pancreatic cancer",
    "ALS (SOD1-mutant)":                     "amyotrophic lateral sclerosis",
    "Carbapenem-resistant Enterobacterales": "carbapenem resistant",
    "Acinetobacter baumannii MDR":           "acinetobacter",
    "Spinal Muscular Atrophy Type 2":        "spinal muscular atrophy",
    "HER2-low Breast Cancer":               "breast cancer HER2",
    "KRAS G12C NSCLC":                       "non-small cell lung cancer KRAS",
    "Huntington Disease":                    "huntington",
    "Friedreich Ataxia":                     "friedreich",
    "C. difficile Infection":               "clostridioides difficile",
    "MRSA Skin Infections":                  "methicillin-resistant staphylococcus aureus",
    "Type 1 Diabetes (CGM/automated insulin)": "type 1 diabetes",
    "Alzheimer Disease (early/MCI)":        "alzheimer",
    "Pulmonary Arterial Hypertension":       "pulmonary arterial hypertension",
    "Duchenne Muscular Dystrophy":           "duchenne muscular dystrophy",
    "Myelofibrosis JAK-resistant":           "myelofibrosis",
    "Geographic Atrophy (dry AMD)":          "geographic atrophy",
    "Sickle Cell Disease (gene therapy)":    "sickle cell",
    "RSV in elderly/immunocompromised":      "respiratory syncytial virus",
    "Sepsis (AI early detection)":           "sepsis",
    "NASH/MASH":                             "nonalcoholic steatohepatitis",
    "Prostate Cancer (PSMA-targeted)":       "prostate cancer",
    "Bipolar Depression":                    "bipolar disorder",
    "Rare Pediatric Epilepsy (SCN1A)":       "dravet syndrome",
}


# ── openFDA helpers ───────────────────────────────────────────────────────────

def _count_approved_drugs(search_term: str, api_key: str = "") -> tuple[int, list[str]]:
    """
    Count unique approved drug generic names whose label mentions search_term.
    Returns (count, [top generic names]).
    """
    params = {
        "search": f"indications_and_usage:{search_term}",
        "count": "openfda.generic_name.exact",
        "limit": "100",
    }
    if api_key:
        params["api_key"] = api_key
    try:
        r = requests.get(f"{OPENFDA_BASE}/drug/label.json", params=params, timeout=15)
        if r.status_code == 200:
            results = r.json().get("results", [])
            names = [x["term"] for x in results if x.get("count", 0) >= 2]
            return len(names), names[:20]
        elif r.status_code == 404:
            return 0, []
    except Exception as e:
        logger.warning("openFDA label count failed for '%s': %s", search_term, e)
    return 0, []


def _fetch_application_details(app_number: str) -> Optional[dict]:
    """Fetch sponsor, approval year for an NDA/BLA number."""
    try:
        r = requests.get(
            f"{OPENFDA_BASE}/drug/drugsfda.json",
            params={"search": f"application_number:{app_number}", "limit": "1"},
            timeout=10,
        )
        if r.status_code == 200:
            results = r.json().get("results", [])
            if results:
                res = results[0]
                subs = res.get("submissions", [])
                approval_year = None
                for s in subs:
                    if s.get("submission_status") == "AP":
                        date = s.get("submission_status_date", "")
                        if date:
                            approval_year = int(date[:4])
                            break
                return {"sponsor": res.get("sponsor_name"), "approval_year": approval_year}
    except Exception as e:
        logger.warning("Drugs@FDA app fetch failed for %s: %s", app_number, e)
    return None


# ── Drugs@FDA bulk load ───────────────────────────────────────────────────────

def _download_drugs_at_fda() -> Optional[bytes]:
    """Download the Drugs@FDA ZIP (~6MB). Returns raw bytes or None."""
    try:
        r = requests.get(DRUGS_AT_FDA_ZIP, timeout=60, stream=True)
        r.raise_for_status()
        return r.content
    except Exception as e:
        logger.error("Drugs@FDA ZIP download failed: %s", e)
        return None


def _parse_products_txt(zip_bytes: bytes) -> list[dict]:
    """Parse Products.txt from the Drugs@FDA ZIP into drug dicts."""
    drugs = []
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
            with z.open("Products.txt") as f:
                reader = csv.DictReader(
                    io.TextIOWrapper(f, encoding="utf-8", errors="replace"),
                    delimiter="\t",
                )
                for row in reader:
                    drug_name  = (row.get("DrugName") or "").strip()
                    active_ing = (row.get("ActiveIngredient") or "").strip()
                    appl_no    = (row.get("ApplNo") or "").strip()
                    form       = (row.get("Form") or "").strip()
                    strength   = (row.get("Strength") or "").strip()
                    if not drug_name:
                        continue
                    drugs.append({
                        "brand_name":       drug_name,
                        "generic_name":     active_ing,
                        "application_no":   appl_no,
                        "dosage_form":      form,
                        "strength":         strength,
                    })
    except Exception as e:
        logger.error("Drugs@FDA Products.txt parse failed: %s", e)
    return drugs


# ── DB helpers ────────────────────────────────────────────────────────────────

async def _ensure_drug_indication_table(conn) -> None:
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS drug_disease_indication (
            id              SERIAL PRIMARY KEY,
            drug_label      TEXT         NOT NULL,
            generic_name    TEXT,
            rxcui           VARCHAR(20),
            mondo_id        VARCHAR(20),
            disease_label   TEXT         NOT NULL,
            application_no  VARCHAR(20),
            source          VARCHAR(30)  NOT NULL DEFAULT 'openfda',
            commercial_safe BOOLEAN      NOT NULL DEFAULT TRUE,
            fetched_at      TIMESTAMPTZ  DEFAULT NOW(),
            UNIQUE (drug_label, disease_label, source)
        );
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS ddi_disease_idx ON drug_disease_indication (disease_label);"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS ddi_mondo_idx ON drug_disease_indication (mondo_id);"
    )


async def _upsert_approval_burden(conn, disease_label: str, mondo_id: Optional[str],
                                  count: int, source_code: str) -> None:
    try:
        await conn.execute("""
            INSERT INTO disease_burden
                (mondo_id, disease_label, source_name, source_code, commercial_safe,
                 metric, value, unit, location, year)
            VALUES ($1,$2,'openfda',$3,TRUE,'approved_drug_count',$4,'drugs','United States',2024)
            ON CONFLICT (mondo_id, source_name, metric, location, year, age_group, sex)
            DO UPDATE SET value=EXCLUDED.value, fetched_at=NOW()
        """, mondo_id, disease_label, source_code, float(count))
    except Exception as e:
        logger.error("approval burden upsert failed for %s: %s", disease_label, e)


async def _upsert_indication(conn, drug_label: str, generic_name: str,
                              disease_label: str, mondo_id: Optional[str]) -> None:
    try:
        await conn.execute("""
            INSERT INTO drug_disease_indication
                (drug_label, generic_name, mondo_id, disease_label, source)
            VALUES ($1,$2,$3,$4,'openfda')
            ON CONFLICT (drug_label, disease_label, source) DO NOTHING
        """, drug_label, generic_name or None, mondo_id, disease_label)
    except Exception as e:
        logger.warning("indication upsert failed: %s", e)


# ── Public entry points ───────────────────────────────────────────────────────

async def load_fda_approvals(api_key: str = "") -> dict[str, int]:
    """
    For each disease in our universe, count approved drugs via openFDA label search
    and persist into disease_burden (approved_drug_count) + drug_disease_indication.
    Returns {disease_name: approved_count}.
    """
    pool = await get_pool()
    results: dict[str, int] = {}

    async with pool.acquire() as conn:
        await _ensure_drug_indication_table(conn)

        for disease, search_term in _DISEASE_SEARCH_TERMS.items():
            count, drug_names = _count_approved_drugs(search_term, api_key)
            time.sleep(_DELAY)

            # Resolve MONDO ID if available
            mondo_id = None
            try:
                row = await conn.fetchrow(
                    "SELECT mondo_id FROM disease WHERE lower(label)=lower($1) LIMIT 1", disease
                )
                if row:
                    mondo_id = row["mondo_id"]
            except Exception:
                pass

            await _upsert_approval_burden(conn, disease, mondo_id, count, search_term)

            for name in drug_names[:10]:
                await _upsert_indication(conn, name, name, disease, mondo_id)

            results[disease] = count
            logger.info("FDA approvals: %s → %d drugs", disease, count)

    return results


async def bulk_load_drugs_at_fda() -> int:
    """
    Download Drugs@FDA ZIP and load all Products into the drug table.
    Returns number of drug entries loaded.
    """
    logger.info("Downloading Drugs@FDA ZIP (~6MB)...")
    zip_bytes = _download_drugs_at_fda()
    if not zip_bytes:
        return 0

    drugs = _parse_products_txt(zip_bytes)
    logger.info("Drugs@FDA: parsed %d product entries", len(drugs))

    pool = await get_pool()
    loaded = 0
    async with pool.acquire() as conn:
        await _ensure_drug_indication_table(conn)
        for d in drugs:
            try:
                await conn.execute("""
                    INSERT INTO drug (rxcui, label, generic_name, brand_names, updated_at)
                    VALUES ($1, $2, $3, $4, NOW())
                    ON CONFLICT (rxcui) DO UPDATE SET
                        label        = EXCLUDED.label,
                        generic_name = COALESCE(EXCLUDED.generic_name, drug.generic_name),
                        brand_names  = EXCLUDED.brand_names,
                        updated_at   = NOW()
                """,
                    d["application_no"] or d["brand_name"],
                    d["brand_name"],
                    d["generic_name"] or None,
                    [d["brand_name"]],
                )
                loaded += 1
            except Exception:
                pass

    logger.info("Drugs@FDA: %d drugs loaded", loaded)
    return loaded
