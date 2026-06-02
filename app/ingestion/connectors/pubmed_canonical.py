"""
PubMed Canonical Connector
============================
Source:  NCBI E-utilities (eutils.ncbi.nlm.nih.gov)
License: Free (NLM) — abstracts may carry third-party copyright; cite NLM
Rate:    3 req/sec without key; 10 req/sec with free NCBI API key
Data:    Publication count, top PMIDs, citation signals per disease

Why valuable over OpenAlex:
  - PubMed is the authoritative index for clinical medicine (30M+ papers)
  - MeSH terms give precise disease-specific counts (no noise from unrelated fields)
  - Clinical trial filters let us count RCTs separately from basic research
  - Linkout to full-text PMC for RAG corpus

We store per-disease:
  pubmed_total_count      — all indexed papers (measures academic attention)
  pubmed_rct_count        — randomised controlled trials only (clinical validation)
  pubmed_review_count     — systematic reviews (evidence maturity)
  pubmed_5yr_trend        — growth rate of publications (accelerating or declining field)
"""

import logging
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

ESEARCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
_DELAY  = 0.35   # stay under 3 req/sec
_TIMEOUT = 12

# NCBI recommends including tool + email in all requests
_PARAMS_BASE = {
    "db":      "pubmed",
    "retmode": "json",
    "retmax":  0,           # we only want counts
    "tool":    "project-elevate",
    "email":   "contact@projectelevate.io",
}


# ── Disease → MeSH + free-text queries ───────────────────────────────────────
_DISEASE_QUERIES: dict[str, dict] = {
    "Alzheimer Disease (early/MCI)": {
        "base":   '"Alzheimer Disease"[MeSH] AND ("drug therapy" OR "clinical trial")',
        "rct":    '"Alzheimer Disease"[MeSH] AND "Randomized Controlled Trial"[pt]',
        "review": '"Alzheimer Disease"[MeSH] AND "Systematic Review"[pt]',
    },
    "NASH/MASH": {
        "base":   '"Non-alcoholic Fatty Liver Disease"[MeSH] AND ("drug therapy" OR "clinical trial")',
        "rct":    '"Non-alcoholic Fatty Liver Disease"[MeSH] AND "Randomized Controlled Trial"[pt]',
        "review": '"Non-alcoholic Fatty Liver Disease"[MeSH] AND "Systematic Review"[pt]',
    },
    "Huntington Disease": {
        "base":   '"Huntington Disease"[MeSH]',
        "rct":    '"Huntington Disease"[MeSH] AND "Randomized Controlled Trial"[pt]',
        "review": '"Huntington Disease"[MeSH] AND "Systematic Review"[pt]',
    },
    "Sickle Cell Disease (gene therapy)": {
        "base":   '"Anemia, Sickle Cell"[MeSH] AND ("gene therapy" OR "CRISPR")',
        "rct":    '"Anemia, Sickle Cell"[MeSH] AND "Randomized Controlled Trial"[pt]',
        "review": '"Anemia, Sickle Cell"[MeSH] AND "Systematic Review"[pt]',
    },
    "Glioblastoma Multiforme": {
        "base":   '"Glioblastoma"[MeSH] AND ("drug therapy" OR "immunotherapy")',
        "rct":    '"Glioblastoma"[MeSH] AND "Randomized Controlled Trial"[pt]',
        "review": '"Glioblastoma"[MeSH] AND "Systematic Review"[pt]',
    },
    "Pancreatic Ductal Adenocarcinoma": {
        "base":   '"Carcinoma, Pancreatic Ductal"[MeSH] AND "drug therapy"[sh]',
        "rct":    '"Carcinoma, Pancreatic Ductal"[MeSH] AND "Randomized Controlled Trial"[pt]',
        "review": '"Carcinoma, Pancreatic Ductal"[MeSH] AND "Systematic Review"[pt]',
    },
    "MRSA Skin Infections": {
        "base":   '"Staphylococcal Skin Infections"[MeSH] AND "methicillin-resistant"[tiab]',
        "rct":    '("MRSA" OR "methicillin-resistant Staphylococcus aureus") AND "skin" AND "Randomized Controlled Trial"[pt]',
        "review": '("MRSA" OR "methicillin-resistant Staphylococcus aureus") AND "Systematic Review"[pt]',
    },
    "Carbapenem-resistant Enterobacterales": {
        "base":   '"Enterobacteriaceae Infections"[MeSH] AND carbapenem-resistant[tiab]',
        "rct":    'carbapenem-resistant Enterobacterales AND "Randomized Controlled Trial"[pt]',
        "review": 'carbapenem-resistant Enterobacterales AND "Systematic Review"[pt]',
    },
    "Type 2 Diabetes (GLP-1 resistant)": {
        "base":   '"Diabetes Mellitus, Type 2"[MeSH] AND ("GLP-1" OR glucagon-like peptide)',
        "rct":    '"Diabetes Mellitus, Type 2"[MeSH] AND "Randomized Controlled Trial"[pt]',
        "review": '"Diabetes Mellitus, Type 2"[MeSH] AND "Systematic Review"[pt]',
    },
    "Obesity (CNS/metabolic)": {
        "base":   '"Obesity"[MeSH] AND ("drug therapy" OR "pharmacotherapy")',
        "rct":    '"Obesity"[MeSH] AND "Randomized Controlled Trial"[pt]',
        "review": '"Obesity"[MeSH] AND "Systematic Review"[pt]',
    },
    "Sepsis (AI early detection)": {
        "base":   '"Sepsis"[MeSH] AND ("artificial intelligence" OR "machine learning" OR "early detection")',
        "rct":    '"Sepsis"[MeSH] AND "Randomized Controlled Trial"[pt]',
        "review": '"Sepsis"[MeSH] AND "Systematic Review"[pt]',
    },
    "Idiopathic Pulmonary Fibrosis": {
        "base":   '"Idiopathic Pulmonary Fibrosis"[MeSH] AND "drug therapy"[sh]',
        "rct":    '"Idiopathic Pulmonary Fibrosis"[MeSH] AND "Randomized Controlled Trial"[pt]',
        "review": '"Idiopathic Pulmonary Fibrosis"[MeSH] AND "Systematic Review"[pt]',
    },
    "Systemic Lupus Erythematosus": {
        "base":   '"Lupus Erythematosus, Systemic"[MeSH] AND "drug therapy"[sh]',
        "rct":    '"Lupus Erythematosus, Systemic"[MeSH] AND "Randomized Controlled Trial"[pt]',
        "review": '"Lupus Erythematosus, Systemic"[MeSH] AND "Systematic Review"[pt]',
    },
}


def _count_pubmed(term: str) -> int:
    """Return the total count for a PubMed search term."""
    try:
        r = requests.get(
            ESEARCH,
            params={**_PARAMS_BASE, "term": term},
            timeout=_TIMEOUT,
        )
        if r.status_code == 200:
            data = r.json()
            return int(data.get("esearchresult", {}).get("count", 0))
    except Exception as e:
        logger.warning("PubMed count failed for '%s...': %s", term[:40], e)
    return 0


def _compute_5yr_trend(base_query: str) -> float:
    """
    Compare publication count in last 2 years vs 3-5 years ago.
    Returns growth rate: >1 = growing field, <1 = declining.
    """
    recent    = _count_pubmed(f"({base_query}) AND (\"2024\"[dp] OR \"2025\"[dp] OR \"2026\"[dp])")
    time.sleep(_DELAY)
    prior     = _count_pubmed(f"({base_query}) AND (\"2021\"[dp] OR \"2022\"[dp] OR \"2023\"[dp])")
    if prior == 0:
        return 1.0
    return round((recent / max(prior, 1)) * (5 / 3), 2)   # normalise for different time windows


async def load_pubmed_signals(disease_names: list[str] | None = None) -> dict[str, dict]:
    """
    Fetch PubMed publication counts for diseases and store in disease_burden.
    Returns {disease: {total, rct_count, review_count, trend}}.
    """
    targets = disease_names or list(_DISEASE_QUERIES.keys())
    results: dict[str, dict] = {}

    try:
        from app.db.database import get_pool
        pool = await get_pool()
    except Exception:
        pool = None

    for disease in targets:
        cfg = _DISEASE_QUERIES.get(disease)
        if not cfg:
            continue

        total  = _count_pubmed(cfg["base"])
        time.sleep(_DELAY)
        rct    = _count_pubmed(cfg["rct"])
        time.sleep(_DELAY)
        review = _count_pubmed(cfg["review"])
        time.sleep(_DELAY)
        trend  = _compute_5yr_trend(cfg["base"])
        time.sleep(_DELAY)

        data = {
            "total":        total,
            "rct_count":    rct,
            "review_count": review,
            "trend_5yr":    trend,
        }
        results[disease] = data

        if pool:
            try:
                async with pool.acquire() as conn:
                    mondo_row = await conn.fetchrow(
                        "SELECT mondo_id FROM disease WHERE lower(label)=lower($1) LIMIT 1", disease
                    )
                    mondo_id = mondo_row["mondo_id"] if mondo_row else None
                    for metric, value, unit in [
                        ("pubmed_total_count",  float(total),  "papers"),
                        ("pubmed_rct_count",    float(rct),    "rcts"),
                        ("pubmed_review_count", float(review), "reviews"),
                        ("pubmed_5yr_trend",    float(trend),  "ratio"),
                    ]:
                        await conn.execute("""
                            INSERT INTO disease_burden
                                (mondo_id, disease_label, source_name, source_code, commercial_safe,
                                 metric, value, unit, location, year)
                            VALUES ($1,$2,'pubmed','ncbi_eutils',TRUE,$3,$4,$5,'Global',2026)
                            ON CONFLICT (mondo_id, source_name, metric, location, year, age_group, sex)
                            DO UPDATE SET value=EXCLUDED.value, fetched_at=NOW()
                        """, mondo_id, disease, metric, value, unit)
            except Exception as e:
                logger.warning("PubMed DB store failed for %s: %s", disease, e)

        logger.info("PubMed: %s → %d total, %d RCTs, %d reviews, trend=%.2f",
                    disease, total, rct, review, trend)

    return results
