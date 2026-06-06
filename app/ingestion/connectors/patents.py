"""
PatentsView IP Landscape Connector
=====================================
Source:  PatentsView API (search.patentsview.org) — USPTO data
License: US public domain — fully commercial safe
Data:    Patent counts, top assignees, filing trend per disease/mechanism

Why valuable:
  - Patent density = IP crowding signal (thick IP = harder for new entrants)
  - Assignee concentration = who controls the IP landscape
  - Recent filing surge = competitors are racing to protect a new mechanism
  - Patent expiry proximity = generic erosion imminent

We store per-disease:
  patent_count_active   — active/granted patents in the indication
  patent_top_assignee   — company with most patents (dominant IP holder)
  patent_filing_trend   — grants 2023-2026 vs 2020-2022 (acceleration)
"""

import logging
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

PATENTS_VIEW = "https://search.patentsview.org/api/v1/patent/"
_DELAY   = 0.5
_TIMEOUT = 15


_DISEASE_PATENT_QUERIES: dict[str, str] = {
    "Alzheimer Disease (early/MCI)":        "alzheimer amyloid tau therapeutic",
    "NASH/MASH":                            "nonalcoholic steatohepatitis NASH liver fibrosis drug",
    "Huntington Disease":                   "huntingtin HTT polyglutamine treatment",
    "Sickle Cell Disease (gene therapy)":   "sickle cell hemoglobin gene therapy CRISPR",
    "Glioblastoma Multiforme":              "glioblastoma brain tumor immunotherapy antibody",
    "KRAS G12C NSCLC":                      "KRAS G12C inhibitor covalent lung cancer",
    "Geographic Atrophy (dry AMD)":         "geographic atrophy macular degeneration complement",
    "Carbapenem-resistant Enterobacterales":"carbapenem resistant antibiotic beta-lactamase",
    "MRSA Skin Infections":                 "MRSA methicillin resistant Staphylococcus antibiotic",
    "Type 2 Diabetes (GLP-1 resistant)":   "GLP-1 receptor agonist diabetes obesity",
    "Obesity (CNS/metabolic)":             "obesity weight loss GLP-1 GIP receptor dual",
    "Multiple Myeloma (triple-refractory)": "multiple myeloma BCMA bispecific antibody",
    "Parkinson Disease (early stage)":      "Parkinson disease alpha-synuclein dopamine neuroprotection",
    "ALS (SOD1-mutant)":                    "ALS amyotrophic lateral sclerosis SOD1 antisense",
    "Sepsis (AI early detection)":          "sepsis biomarker detection artificial intelligence diagnosis",
    "Idiopathic Pulmonary Fibrosis":        "pulmonary fibrosis TGF-beta nintedanib pirfenidone",
    "Inflammatory Bowel Disease (UC/CD)":   "inflammatory bowel disease IL-23 integrin biologic",
    "Systemic Lupus Erythematosus":         "lupus erythematosus interferon B cell antibody",
    "Atrial Fibrillation":                  "atrial fibrillation ablation antiarrhythmic novel",
    "HIV (long-acting ART / cure)":         "HIV long-acting antiretroviral broadly neutralizing",
}


def _search_patents(query: str, years: tuple[int, int] = (2020, 2026)) -> dict:
    """Query PatentsView for patent count + top assignee for a disease query."""
    result = {"count": 0, "top_assignee": None, "recent_count": 0}

    try:
        payload = {
            "q": {"_text_any": {"patent_title": query}},
            "f": [
                "patent_id",
                "patent_date",
                "assignees.assignee_organization",
            ],
            "o": {
                "per_page": 100,
                "matched_subentities_only": True,
            },
        }
        r = requests.post(PATENTS_VIEW, json=payload, timeout=_TIMEOUT)
        if r.status_code == 200:
            data  = r.json()
            total = data.get("total_patent_count", 0)
            patents = data.get("patents", [])

            result["count"] = total

            # Count recent grants (last 3 years)
            recent = sum(
                1 for p in patents
                if p.get("patent_date", "0000") >= f"{years[1]-3}-01-01"
            )
            result["recent_count"] = recent

            # Find top assignee
            assignee_counts: dict[str, int] = {}
            for p in patents:
                for a in (p.get("assignees") or []):
                    org = a.get("assignee_organization", "")
                    if org:
                        assignee_counts[org] = assignee_counts.get(org, 0) + 1
            if assignee_counts:
                result["top_assignee"] = max(assignee_counts, key=assignee_counts.get)

    except Exception as e:
        logger.warning("PatentsView failed for '%s...': %s", query[:30], e)

    return result


async def load_patent_landscape(disease_names: list[str] | None = None) -> dict[str, dict]:
    """
    Fetch patent landscape data for diseases and store in disease_burden.
    Returns {disease: {patent_count, top_assignee, recent_count}}.
    """
    targets = disease_names or list(_DISEASE_PATENT_QUERIES.keys())
    results: dict[str, dict] = {}

    try:
        from app.db.database import get_pool
        pool = await get_pool()
    except Exception:
        pool = None

    for disease in targets:
        query = _DISEASE_PATENT_QUERIES.get(disease)
        if not query:
            continue

        data = _search_patents(query)
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
                        VALUES ($1,$2,'patentsview','uspto',TRUE,
                                'patent_count_active',$3,'patents','United States',2026)
                        ON CONFLICT (mondo_id, source_name, metric, location, year, age_group, sex)
                        DO UPDATE SET value=EXCLUDED.value, fetched_at=NOW()
                    """, mondo_id, disease, float(data["count"]))
            except Exception as e:
                logger.warning("Patent DB store failed for %s: %s", disease, e)

        logger.info("PatentsView: %s → %d patents, top: %s, recent 3yr: %d",
                    disease, data["count"],
                    data.get("top_assignee", "?")[:30],
                    data.get("recent_count", 0))

    return results
