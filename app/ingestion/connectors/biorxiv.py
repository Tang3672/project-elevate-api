"""
bioRxiv / medRxiv Preprint Pipeline Connector
===============================================
Source:  bioRxiv/medRxiv API (api.biorxiv.org)
License: Open — content individual articles CC-BY/CC0; API free
Data:    Preprint papers posted in the last 6-12 months by disease topic

Why valuable: Preprints appear 6-12 months before journal publication.
  A surge in preprints for a disease mechanism signals that academic labs
  are converging on a new therapeutic hypothesis — the earliest public
  signal of where drug development is headed next.

We extract per-disease:
  preprint_count_90d   — papers in last 90 days (pipeline heat)
  preprint_count_12mo  — papers in last 12 months (trend)
  top_preprints        — 5 most recent titles + DOIs (for RAG injection)
"""

import logging
import time
from datetime import date, timedelta
from typing import Optional

import requests

logger = logging.getLogger(__name__)

BIORXIV_API = "https://api.biorxiv.org/details"
_DELAY      = 0.3
_TIMEOUT    = 12


# ── Disease → search terms for bioRxiv/medRxiv ───────────────────────────────
_DISEASE_SEARCH_TERMS: dict[str, tuple[str, str]] = {
    # (biorxiv_query_term, server)  — server: 'biorxiv' | 'medrxiv'
    "Alzheimer Disease (early/MCI)":        ("alzheimer amyloid tau", "medrxiv"),
    "NASH/MASH":                            ("NASH MASH nonalcoholic steatohepatitis", "medrxiv"),
    "Huntington Disease":                   ("huntingtin HTT aggregation", "biorxiv"),
    "Sickle Cell Disease (gene therapy)":   ("sickle cell gene therapy CRISPR", "medrxiv"),
    "Glioblastoma Multiforme":              ("glioblastoma immunotherapy treatment", "medrxiv"),
    "Pancreatic Ductal Adenocarcinoma":     ("pancreatic cancer KRAS treatment", "medrxiv"),
    "KRAS G12C NSCLC":                      ("KRAS G12C lung cancer resistance", "biorxiv"),
    "Type 2 Diabetes (GLP-1 resistant)":   ("GLP-1 diabetes beta cell resistance", "medrxiv"),
    "Obesity (CNS/metabolic)":             ("obesity GLP-1 adipose metabolism", "medrxiv"),
    "Atrial Fibrillation":                  ("atrial fibrillation ablation mechanism", "medrxiv"),
    "Major Depression (TRD)":              ("treatment-resistant depression ketamine mechanism", "medrxiv"),
    "PTSD":                                 ("PTSD MDMA psilocybin therapy", "medrxiv"),
    "Schizophrenia":                        ("schizophrenia muscarinic dopamine mechanism", "biorxiv"),
    "Carbapenem-resistant Enterobacterales":("carbapenem resistant Klebsiella mechanism", "biorxiv"),
    "HIV (long-acting ART / cure)":         ("HIV cure reservoir latency", "medrxiv"),
    "Geographic Atrophy (dry AMD)":         ("geographic atrophy complement drusen", "medrxiv"),
    "Idiopathic Pulmonary Fibrosis":        ("IPF fibrosis TGF beta mechanism", "medrxiv"),
    "Multiple Sclerosis (progressive)":     ("progressive multiple sclerosis neuroprotection", "medrxiv"),
    "Parkinson Disease (early stage)":      ("Parkinson alpha-synuclein dopamine neurodegeneration", "medrxiv"),
    "ALS (SOD1-mutant)":                    ("ALS SOD1 TDP-43 motor neuron", "medrxiv"),
    "Inflammatory Bowel Disease (UC/CD)":   ("Crohn colitis IL-23 microbiome treatment", "medrxiv"),
    "Systemic Lupus Erythematosus":         ("lupus SLE B cell interferon mechanism", "medrxiv"),
    "Rheumatoid Arthritis (JAK-refractory)":("rheumatoid arthritis JAK cytokine synovial", "medrxiv"),
    "Sepsis (AI early detection)":          ("sepsis machine learning biomarker prediction", "medrxiv"),
    "Acute Myeloid Leukemia (FLT3-ITD)":   ("AML FLT3 resistance venetoclax mechanism", "medrxiv"),
}


def _fetch_preprints(term: str, server: str, days_back: int = 90) -> dict:
    """
    Fetch preprints from bioRxiv or medRxiv for a search term.
    Uses the date-range endpoint and filters by abstract content client-side.
    Returns {count, papers: [{title, doi, date, authors}]}.
    """
    end_date   = date.today()
    start_date = end_date - timedelta(days=days_back)

    result: dict = {"count": 0, "papers": []}

    try:
        # bioRxiv date-range endpoint: /details/{server}/{start}/{end}/{cursor}/json
        cursor = 0
        papers_found = []
        term_lower   = term.lower()

        while cursor < 100:   # max 100 results
            url = f"{BIORXIV_API}/{server}/{start_date.isoformat()}/{end_date.isoformat()}/{cursor}/json"
            r   = requests.get(url, timeout=_TIMEOUT)
            if r.status_code != 200:
                break

            data     = r.json()
            messages = data.get("messages", [{}])
            status   = messages[0].get("status", "")
            if status != "ok":
                break

            collection = data.get("collection", [])
            if not collection:
                break

            for paper in collection:
                title    = (paper.get("title", "") or "").lower()
                abstract = (paper.get("abstract", "") or "").lower()
                # Simple relevance filter — does the abstract mention our terms?
                keywords = term_lower.split()[:3]
                if sum(1 for kw in keywords if kw in title or kw in abstract) >= 2:
                    papers_found.append({
                        "title":   paper.get("title", "")[:200],
                        "doi":     paper.get("doi", ""),
                        "date":    paper.get("date", ""),
                        "authors": paper.get("authors", "")[:100],
                        "server":  server,
                    })

            cursor += len(collection)
            if cursor >= int(messages[0].get("total", 0)):
                break

            time.sleep(_DELAY)

        result["count"]  = len(papers_found)
        result["papers"] = sorted(papers_found, key=lambda x: x["date"], reverse=True)[:5]

    except Exception as e:
        logger.warning("bioRxiv fetch failed for '%s': %s", term[:30], e)

    return result


async def load_preprint_signals(disease_names: list[str] | None = None) -> dict[str, dict]:
    """
    Fetch preprint pipeline signals for disease universe.
    Returns {disease: {count_90d, papers}}.
    """
    targets = disease_names or list(_DISEASE_SEARCH_TERMS.keys())
    results: dict[str, dict] = {}

    try:
        from app.db.database import get_pool
        pool = await get_pool()
    except Exception:
        pool = None

    for disease in targets:
        config = _DISEASE_SEARCH_TERMS.get(disease)
        if not config:
            continue

        term, server = config
        data = _fetch_preprints(term, server, days_back=90)
        time.sleep(_DELAY)
        results[disease] = data

        if pool and data["count"] >= 0:
            try:
                async with pool.acquire() as conn:
                    mondo_row = await conn.fetchrow(
                        "SELECT mondo_id FROM disease WHERE lower(label)=lower($1) LIMIT 1", disease
                    )
                    mondo_id = mondo_row["mondo_id"] if mondo_row else None
                    await conn.execute("""
                        INSERT INTO disease_burden
                            (mondo_id, disease_label, source_name, source_code, commercial_safe,
                             metric, value, unit, location, year)
                        VALUES ($1,$2,'biorxiv','biorxiv_medrxiv',TRUE,
                                'preprint_count_90d',$3,'preprints','Global',2026)
                        ON CONFLICT (mondo_id, source_name, metric, location, year, age_group, sex)
                        DO UPDATE SET value=EXCLUDED.value, fetched_at=NOW()
                    """, mondo_id, disease, float(data["count"]))
            except Exception as e:
                logger.warning("bioRxiv DB store failed for %s: %s", disease, e)

        logger.info("bioRxiv/medRxiv: %s → %d preprints (90d)", disease, data["count"])

    return results
