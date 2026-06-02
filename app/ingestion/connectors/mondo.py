"""
MONDO Ontology Loader
=====================
Source:  EMBL-EBI OLS4 API (www.ebi.ac.uk/ols4)
License: CC BY 4.0 — commercial safe; cite Monarch Initiative
Data:    Disease entities + ICD-10/MeSH/OMIM/Orphanet/NCIt cross-references

Strategy: targeted lookup by disease name for our OPPORTUNITY_UNIVERSE diseases,
plus bulk page-crawl to seed the broader MONDO backbone. OLS4 returns cross-refs
in annotation.database_cross_reference (e.g. 'ICD10CM:G30', 'MeSH:D000544').

Rate: no documented limit; we add 200ms delay per page to be polite.
"""

import asyncio
import logging
import re
import time
from typing import Optional

import requests

from app.db.database import get_pool

logger = logging.getLogger(__name__)

OLS4_BASE = "https://www.ebi.ac.uk/ols4/api"
_DELAY    = 0.2   # seconds between requests


# ── Therapeutic-area heuristics (MONDO label → our TA key) ────────────────────

_TA_KEYWORDS = {
    "oncology":       ["cancer","carcinoma","glioblastoma","leukemia","lymphoma","melanoma","sarcoma","tumor","myeloma","adenocarcinoma","blastoma"],
    "rare_disease":   ["rare","orphan","ataxia","dystrophy","muscular","spinal muscular","gaucher","fabry","phenylketonuria","sickle cell","huntington","friedreich"],
    "amr_infectious": ["resistant","MRSA","carbapenem","acinetobacter","difficile","staphylococcus","enterobacterales","sepsis","infectious","antimicrobial"],
    "cns":            ["alzheimer","parkinson","huntington","multiple sclerosis","epilepsy","depression","bipolar","schizophrenia","dementia","neurodegen","ALS","amyotrophic"],
    "cardiovascular": ["heart failure","atrial fibrillation","hypertension","coronary","myocardial","stroke","pulmonary arterial","cardiovascular"],
    "metabolic":      ["diabetes","obesity","NASH","MASH","nonalcoholic","fatty liver","metabolic","dyslipidemia"],
    "gene_therapy":   ["gene therapy","AAV","lentiviral","gene editing","CRISPR","monogenic"],
    "immunology":     ["rheumatoid","lupus","psoriasis","inflammatory bowel","Crohn","ulcerative colitis","autoimmune","immunodeficiency"],
    "ophthalmology":  ["macular","glaucoma","retinal","geographic atrophy","AMD","dry eye","optic"],
    "vaccine":        ["RSV","influenza","COVID","SARS","respiratory syncytial","vaccine"],
    "device":         ["sepsis","diagnostic","device","monitor","detection"],
}

def _infer_ta(label: str) -> Optional[str]:
    low = label.lower()
    for ta, keywords in _TA_KEYWORDS.items():
        if any(kw.lower() in low for kw in keywords):
            return ta
    return None


# ── xref parsing ──────────────────────────────────────────────────────────────

def _parse_xrefs(xref_list: list[str]) -> dict:
    icd10, icd11, mesh, omim, orphanet, ncit = [], [], [], [], [], []
    for x in xref_list:
        if x.startswith("ICD10CM:") or x.startswith("ICD10WHO:") or x.startswith("ICD10:"):
            icd10.append(x.split(":", 1)[1])
        elif x.startswith("ICD11:") or x.startswith("ICD-11:"):
            icd11.append(x.split(":", 1)[1])
        elif x.startswith("MeSH:") or x.startswith("MESH:"):
            mesh.append(x.split(":", 1)[1])
        elif x.startswith("OMIM:"):
            omim.append(x.split(":", 1)[1])
        elif x.startswith("Orphanet:") or x.startswith("ORPHA:"):
            orphanet.append(x.split(":", 1)[1])
        elif x.startswith("NCIT:"):
            ncit.append(x.split(":", 1)[1])
    return {"icd10": icd10, "icd11": icd11, "mesh": mesh,
            "omim": omim, "orphanet": orphanet, "ncit": ncit}


# ── Core fetch helpers ────────────────────────────────────────────────────────

def _search_mondo(query: str, exact: bool = False, rows: int = 5) -> list[dict]:
    """OLS4 full-text search within MONDO."""
    try:
        r = requests.get(
            f"{OLS4_BASE}/search",
            params={"q": query, "ontology": "mondo", "exact": str(exact).lower(), "rows": rows},
            timeout=10,
        )
        r.raise_for_status()
        return r.json().get("response", {}).get("docs", [])
    except Exception as e:
        logger.warning("OLS4 search failed for '%s': %s", query, e)
        return []


def _fetch_term_by_iri(iri: str) -> Optional[dict]:
    """Fetch full MONDO term (with annotations) by IRI."""
    try:
        r = requests.get(
            f"{OLS4_BASE}/ontologies/mondo/terms",
            params={"iri": iri},
            timeout=10,
        )
        r.raise_for_status()
        terms = r.json().get("_embedded", {}).get("terms", [])
        return terms[0] if terms else None
    except Exception as e:
        logger.warning("OLS4 term fetch failed for %s: %s", iri, e)
        return None


def _term_to_row(term: dict) -> Optional[dict]:
    """Convert an OLS4 term dict to a DB row dict."""
    obo_id = term.get("obo_id", "")
    if not obo_id.startswith("MONDO:"):
        return None
    label = term.get("label", "")
    desc  = term.get("description") or []
    anno  = term.get("annotation", {})
    xrefs = _parse_xrefs(anno.get("database_cross_reference", []))
    synonyms = term.get("synonyms", [])
    is_rare = any("rare" in s.lower() or "orphan" in s.lower()
                  for s in ([label] + (anno.get("comment", []) or [])))
    return {
        "mondo_id":    obo_id,
        "label":       label,
        "synonyms":    synonyms,
        "definition":  desc[0] if desc else None,
        "icd10_ids":   xrefs["icd10"],
        "icd11_ids":   xrefs["icd11"],
        "mesh_ids":    xrefs["mesh"],
        "omim_ids":    xrefs["omim"],
        "orphanet_ids": xrefs["orphanet"],
        "ncit_ids":    xrefs["ncit"],
        "therapeutic_area": _infer_ta(label),
        "is_rare":     is_rare,
    }


async def _upsert_disease(conn, row: dict) -> bool:
    """Idempotent upsert into the disease table. Returns True if new/updated."""
    try:
        await conn.execute("""
            INSERT INTO disease (
                mondo_id, label, synonyms, definition,
                icd10_ids, icd11_ids, mesh_ids, omim_ids, orphanet_ids, ncit_ids,
                therapeutic_area, is_rare, updated_at
            ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,NOW())
            ON CONFLICT (mondo_id) DO UPDATE SET
                label           = EXCLUDED.label,
                synonyms        = EXCLUDED.synonyms,
                definition      = EXCLUDED.definition,
                icd10_ids       = EXCLUDED.icd10_ids,
                icd11_ids       = EXCLUDED.icd11_ids,
                mesh_ids        = EXCLUDED.mesh_ids,
                omim_ids        = EXCLUDED.omim_ids,
                orphanet_ids    = EXCLUDED.orphanet_ids,
                ncit_ids        = EXCLUDED.ncit_ids,
                therapeutic_area = COALESCE(EXCLUDED.therapeutic_area, disease.therapeutic_area),
                is_rare         = EXCLUDED.is_rare,
                updated_at      = NOW()
        """,
            row["mondo_id"], row["label"], row["synonyms"], row["definition"],
            row["icd10_ids"], row["icd11_ids"], row["mesh_ids"],
            row["omim_ids"], row["orphanet_ids"], row["ncit_ids"],
            row["therapeutic_area"], row["is_rare"],
        )
        return True
    except Exception as e:
        logger.error("Upsert failed for %s: %s", row.get("mondo_id"), e)
        return False


# ── Public entry points ───────────────────────────────────────────────────────

async def load_mondo_for_diseases(disease_names: list[str]) -> dict[str, str]:
    """
    Resolve a list of disease names to MONDO IDs and load them into the DB.
    Returns {disease_name: mondo_id} for resolved diseases.
    """
    pool = await get_pool()
    resolved: dict[str, str] = {}

    async with pool.acquire() as conn:
        for name in disease_names:
            # 1. Try exact match first
            docs = _search_mondo(name, exact=True, rows=3)
            if not docs:
                # 2. Fall back to fuzzy search
                docs = _search_mondo(name, exact=False, rows=5)
            if not docs:
                logger.warning("MONDO: no match for '%s'", name)
                continue

            # Pick the best match (first result, prefer exact label match)
            best = next((d for d in docs if d.get("label", "").lower() == name.lower()), docs[0])
            iri  = best.get("iri") or f"http://purl.obolibrary.org/obo/{best['obo_id'].replace(':','_')}"

            time.sleep(_DELAY)
            term = _fetch_term_by_iri(iri)
            if not term:
                continue

            row = _term_to_row(term)
            if not row:
                continue

            if await _upsert_disease(conn, row):
                resolved[name] = row["mondo_id"]
                logger.info("MONDO loaded: %s → %s", name, row["mondo_id"])

            time.sleep(_DELAY)

    return resolved


async def bulk_load_mondo(page_size: int = 500, max_pages: int = 20) -> int:
    """
    Bulk-seed the disease table by crawling MONDO pages.
    Loads up to max_pages × page_size terms (default 10,000 terms).
    Run once to bootstrap the ontology backbone; refresh monthly.
    """
    pool = await get_pool()
    total = 0

    async with pool.acquire() as conn:
        for page in range(max_pages):
            try:
                r = requests.get(
                    f"{OLS4_BASE}/ontologies/mondo/terms",
                    params={"size": page_size, "page": page},
                    timeout=30,
                )
                r.raise_for_status()
                data = r.json()
                terms = data.get("_embedded", {}).get("terms", [])
                if not terms:
                    break

                for term in terms:
                    row = _term_to_row(term)
                    if row:
                        await _upsert_disease(conn, row)
                        total += 1

                # Check if more pages
                links = data.get("_links", {})
                if "next" not in links:
                    break

                logger.info("MONDO bulk: page %d, %d terms loaded so far", page, total)
                time.sleep(_DELAY)

            except Exception as e:
                logger.error("MONDO bulk page %d failed: %s", page, e)
                break

    logger.info("MONDO bulk load complete: %d diseases", total)
    return total
