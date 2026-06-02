"""
CMS Medicare Part D Drug Spending Connector
============================================
Source:  CMS Medicare Part D Spending by Drug (data.cms.gov — Socrata API)
         Also: CMS Medicare Part B Drug Spending
License: US public domain — fully commercial safe
Data:    Actual realized gross drug cost, beneficiary count, claims count
         per drug per year — the most authoritative US pricing data available

Why valuable:
  - Real WAC → actual realized revenue (before rebates)
  - Total US Medicare spend per drug = proxy for total US market size
  - Year-over-year trend = market growth rate
  - Beneficiary count = addressable patient population validation

Stores per-drug:
  cms_annual_spend_usd   — total gross Medicare spending
  cms_beneficiary_count  — number of Medicare patients on drug
  cms_cost_per_patient   — average annual cost per beneficiary
  cms_claim_count        — number of claims (utilization signal)
"""

import logging
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# CMS Medicare Part D Spending by Drug — Socrata API (public domain)
PART_D_URL  = "https://data.cms.gov/resource/qm9z-4mdc.json"    # 2021 data
PART_D_URL2 = "https://data.cms.gov/resource/2rkh-6was.json"    # provider drug spending
_TIMEOUT    = 15
_DELAY      = 0.5


# ── Disease → branded drug search terms ──────────────────────────────────────
# Map from our disease universe to the drug names that appear in CMS Part D data.
# Only approved branded drugs have CMS spending data (generics aggregated differently).

_DISEASE_DRUG_MAP: dict[str, list[str]] = {
    "Alzheimer Disease (early/MCI)":        ["LEQEMBI", "ADUHELM", "ARICEPT", "NAMENDA"],
    "NASH/MASH":                            ["REZDIFFRA"],
    "Multiple Myeloma (triple-refractory)": ["DARZALEX", "KYPROLIS", "POMALYST", "REVLIMID"],
    "Rheumatoid Arthritis (JAK-refractory)":["HUMIRA", "RINVOQ", "XELJANZ", "KEVZARA"],
    "Psoriasis/PsA (IL-17/23 refractory)": ["SKYRIZI", "TREMFYA", "COSENTYX", "TALTZ"],
    "Inflammatory Bowel Disease (UC/CD)":  ["ENTYVIO", "STELARA", "XELJANZ", "RINVOQ"],
    "Type 2 Diabetes (GLP-1 resistant)":   ["OZEMPIC", "JARDIANCE", "FARXIGA", "TRULICITY"],
    "Obesity (CNS/metabolic)":             ["WEGOVY", "SAXENDA", "QSYMIA"],
    "Atrial Fibrillation":                  ["XARELTO", "ELIQUIS", "PRADAXA", "MULTAQ"],
    "Heart Failure (HFpEF)":               ["JARDIANCE", "ENTRESTO", "CORLANOR"],
    "Chronic Kidney Disease (DKD)":        ["JARDIANCE", "FARXIGA", "KERENDIA"],
    "Pulmonary Arterial Hypertension":     ["OPSUMIT", "UPTRAVI", "ADEMPAS", "VENTAVIS"],
    "Geographic Atrophy (dry AMD)":        ["SYFOVRE", "IZERVAY", "EYLEA", "LUCENTIS"],
    "Prostate Cancer (PSMA-targeted)":     ["PLUVICTO", "NUBEQA", "ERLEADA", "XTANDI"],
    "Lung Cancer (NSCLC, IO-resistant)":   ["KEYTRUDA", "OPDIVO", "TAGRISSO", "LUMAKRAS"],
    "Breast Cancer (HR+, CDK4/6 resistant)":["IBRANCE", "KISQALI", "VERZENIO", "LYNPARZA"],
    "Multiple Sclerosis (progressive)":    ["OCREVUS", "KESIMPTA", "TYSABRI", "MAVENCLAD"],
    "Schizophrenia":                       ["CAPLYTA", "REXULTI", "VRAYLAR", "ABILIFY"],
    "Major Depression (TRD)":             ["SPRAVATO", "AUVELITY", "REXULTI"],
    "HIV (long-acting ART / cure)":        ["BIKTARVY", "CABENUVA", "DOVATO", "DESCOVY"],
    "Sickle Cell Disease (gene therapy)":  ["CASGEVY", "LYFGENIA", "OXBRYTA", "ADAKVEO"],
    "Cystic Fibrosis (F508del homozygous)":["TRIKAFTA", "SYMDEKO", "KALYDECO"],
    "Duchenne Muscular Dystrophy":         ["EXONDYS", "AMONDYS", "VYONDYS", "ELEVIDYS"],
    "Spinal Muscular Atrophy Type 2":      ["ZOLGENSMA", "SPINRAZA", "EVRYSDI"],
    "COPD (advanced emphysema)":           ["TRELEGY", "ANORO", "SYMBICORT", "SPIRIVA"],
    "Asthma (severe eosinophilic)":        ["DUPIXENT", "FASENRA", "NUCALA", "XOLAIR"],
    "Paroxysmal Nocturnal Hemoglobinuria": ["SOLIRIS", "ULTOMIRIS", "EMPAVELI"],
    "IgA Nephropathy":                     ["TARPEYO", "FILSPARI"],
    "Transthyretin Amyloidosis (polyneuropathy)": ["VYNDAQEL", "ONPATTRO", "AMVUTTRA"],
    "KRAS G12C NSCLC":                     ["LUMAKRAS", "KRAZATI"],
    "Myelofibrosis JAK-resistant":         ["JAKAFI", "INREBIC", "VONJO", "OJJAARA"],
}


def _fetch_cms_drug_spend(drug_name: str) -> Optional[dict]:
    """Fetch CMS Part D spending for one drug name."""
    try:
        r = requests.get(
            PART_D_URL,
            params={
                "$where":  f"upper(brnd_name) like '%{drug_name.upper()}%'",
                "$limit":  5,
                "$order":  "tot_spndng DESC",
            },
            timeout=_TIMEOUT,
        )
        if r.status_code == 200:
            rows = r.json()
            if rows:
                # Sum across formulations
                total_spend = sum(float(row.get("tot_spndng", 0) or 0) for row in rows)
                total_claims = sum(int(row.get("tot_clms", 0) or 0) for row in rows)
                total_benes  = sum(int(row.get("tot_benes", 0) or 0) for row in rows)
                year = rows[0].get("year", "2021")
                return {
                    "drug_name":            drug_name,
                    "brand_name":           rows[0].get("brnd_name", drug_name),
                    "cms_annual_spend_usd": total_spend,
                    "cms_claim_count":      total_claims,
                    "cms_beneficiary_count":total_benes,
                    "cms_cost_per_patient": round(total_spend / max(total_benes, 1), 0),
                    "year":                 year,
                }
    except Exception as e:
        logger.warning("CMS spending fetch failed for %s: %s", drug_name, e)
    return None


async def load_cms_drug_spending(disease_names: list[str] | None = None) -> dict[str, dict]:
    """
    Fetch CMS Part D spending for drugs in our universe.
    Picks the highest-spending drug per disease as the benchmark.
    Stores in disease_burden: cms_annual_spend_usd, cms_beneficiary_count.
    Returns {disease: {best_drug, cms_annual_spend_usd, ...}}.
    """
    targets = disease_names or list(_DISEASE_DRUG_MAP.keys())
    results: dict[str, dict] = {}

    try:
        from app.db.database import get_pool
        pool = await get_pool()
    except Exception:
        pool = None

    for disease in targets:
        drug_names = _DISEASE_DRUG_MAP.get(disease, [])
        if not drug_names:
            continue

        best: Optional[dict] = None
        for drug in drug_names[:3]:   # check top 3 drugs
            data = _fetch_cms_drug_spend(drug)
            time.sleep(_DELAY)
            if data and data["cms_annual_spend_usd"] > 0:
                if best is None or data["cms_annual_spend_usd"] > best["cms_annual_spend_usd"]:
                    best = data

        if not best:
            continue

        results[disease] = best

        if pool:
            try:
                async with pool.acquire() as conn:
                    mondo_row = await conn.fetchrow(
                        "SELECT mondo_id FROM disease WHERE lower(label)=lower($1) LIMIT 1", disease
                    )
                    mondo_id = mondo_row["mondo_id"] if mondo_row else None

                    for metric, value, unit in [
                        ("cms_annual_spend_usd",    best["cms_annual_spend_usd"],    "USD"),
                        ("cms_beneficiary_count",   float(best["cms_beneficiary_count"]), "patients"),
                        ("cms_cost_per_patient",    best["cms_cost_per_patient"],    "USD/patient/yr"),
                    ]:
                        await conn.execute("""
                            INSERT INTO disease_burden
                                (mondo_id, disease_label, source_name, source_code, commercial_safe,
                                 metric, value, unit, location, year)
                            VALUES ($1,$2,'cms_part_d',$3,TRUE,$4,$5,$6,'United States',$7)
                            ON CONFLICT (mondo_id, source_name, metric, location, year, age_group, sex)
                            DO UPDATE SET value=EXCLUDED.value, fetched_at=NOW()
                        """, mondo_id, disease, best["drug_name"], metric, value, unit,
                             int(best.get("year", 2021)))
            except Exception as e:
                logger.warning("CMS DB store failed for %s: %s", disease, e)

        logger.info("CMS Part D: %s → %s $%.0fM/yr (%d Medicare patients)",
                    disease, best["brand_name"],
                    best["cms_annual_spend_usd"] / 1e6,
                    best["cms_beneficiary_count"])

    return results
