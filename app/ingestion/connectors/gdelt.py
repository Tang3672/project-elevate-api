"""
GDELT 2.0 News Signal Connector
=================================
Source:  GDELT Project DOC 2.0 API (api.gdeltproject.org)
License: Free — commercial use permitted
Data:    News article volume + sentiment per disease/keyword (15-min updates)
         3-month rolling window; 65+ languages machine-translated

Why valuable: Rising news coverage of a disease = rising investor/prescriber
attention. Declining coverage of a failed drug = market signal. Tone shift
after a trial readout = sentiment-driven demand signal.

We extract per-disease:
  - Monthly article volume (news_mention_count) → market buzz signal
  - Average tone score (positive/negative) → sentiment around treatment landscape
  - Peak coverage month → when the story was hottest

Rate: API is free but rate-limits aggressively. We add 2s delay between
requests and cache results for 24h.
"""

import logging
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)

GDELT_BASE = "https://api.gdeltproject.org/api/v2/doc/doc"
_DELAY     = 2.5   # seconds between requests — GDELT rate-limits at ~1/sec
_TIMEOUT   = 15


# ── Disease → news search queries ────────────────────────────────────────────
# Curated for precision: generic disease names produce too much noise.
# More specific = cleaner signal of clinical/investor activity.

_DISEASE_QUERIES: dict[str, str] = {
    "Alzheimer Disease (early/MCI)":    "lecanemab donanemab Alzheimer amyloid FDA approval",
    "NASH/MASH":                        "resmetirom NASH MASH liver fibrosis drug approval",
    "Huntington Disease":               "Huntington disease drug trial FDA",
    "Sickle Cell Disease (gene therapy)":"Casgevy Lyfgenia sickle cell gene therapy",
    "Geographic Atrophy (dry AMD)":     "Syfovre Izervay geographic atrophy AMD treatment",
    "Sepsis (AI early detection)":      "sepsis AI artificial intelligence detection hospital",
    "Multiple Myeloma (triple-refractory)":"multiple myeloma bispecific CAR-T treatment",
    "KRAS G12C NSCLC":                  "KRAS lung cancer sotorasib adagrasib",
    "Pancreatic Ductal Adenocarcinoma": "pancreatic cancer KRAS drug trial",
    "Glioblastoma Multiforme":          "glioblastoma immunotherapy trial FDA",
    "Type 2 Diabetes (GLP-1 resistant)":"GLP-1 diabetes obesity drug Ozempic Wegovy",
    "Obesity (CNS/metabolic)":          "obesity drug treatment GLP-1 weight loss FDA",
    "Atrial Fibrillation":              "atrial fibrillation catheter ablation drug trial",
    "Rheumatoid Arthritis (JAK-refractory)":"JAK inhibitor rheumatoid arthritis biologic",
    "Inflammatory Bowel Disease (UC/CD)":"Crohn ulcerative colitis biologic drug FDA",
    "Schizophrenia":                    "schizophrenia new drug muscarinic dopamine FDA",
    "Major Depression (TRD)":           "treatment-resistant depression ketamine psilocybin",
    "PTSD":                             "PTSD MDMA psilocybin therapy FDA clinical trial",
    "Carbapenem-resistant Enterobacterales":"carbapenem resistant bacteria antibiotic FDA",
    "HIV (long-acting ART / cure)":     "HIV long-acting antiretroviral cure clinical trial",
    "Parkinson Disease (early stage)":  "Parkinson disease drug alpha-synuclein trial FDA",
    "Lung Cancer (NSCLC, IO-resistant)":"lung cancer immunotherapy resistance KRAS PD-1",
    "Breast Cancer (HR+, CDK4/6 resistant)":"CDK4 CDK6 breast cancer resistance PI3K",
    "Prostate Cancer (PSMA-targeted)":  "PSMA prostate cancer Pluvicto radioligand therapy",
}


def _fetch_gdelt_volume(query: str, timespan: str = "6month") -> dict:
    """
    Fetch monthly article volume for a query from GDELT DOC 2.0.
    Returns {total_articles, monthly_avg, peak_month, tone_avg}.
    """
    result = {
        "total_articles": 0,
        "monthly_avg":    0.0,
        "peak_month":     None,
        "tone_avg":       0.0,
        "raw_timeline":   [],
    }

    # Volume timeline
    try:
        r = requests.get(
            GDELT_BASE,
            params={
                "query":    query,
                "mode":     "timelinevolnorm",
                "format":   "json",
                "timespan": timespan,
            },
            timeout=_TIMEOUT,
        )
        if r.status_code == 200:
            data = r.json()
            timeline = data.get("timeline", [])
            if timeline:
                pts = timeline[0].get("data", [])
                values = [float(p.get("value", 0)) for p in pts]
                result["raw_timeline"]  = pts[-6:]   # last 6 months
                result["total_articles"] = int(sum(values))
                result["monthly_avg"]   = round(sum(values) / max(len(values), 1), 1)
                if pts:
                    peak = max(pts, key=lambda x: float(x.get("value", 0)))
                    result["peak_month"] = peak.get("date", "")[:7]
        elif r.status_code == 429:
            logger.warning("GDELT rate-limited for query '%s...'", query[:30])
            return result
    except Exception as e:
        logger.warning("GDELT volume fetch failed: %s", e)
        return result

    time.sleep(_DELAY)

    # Tone (sentiment) chart
    try:
        r2 = requests.get(
            GDELT_BASE,
            params={
                "query":    query,
                "mode":     "tonechart",
                "format":   "json",
                "timespan": timespan,
            },
            timeout=_TIMEOUT,
        )
        if r2.status_code == 200:
            data2 = r2.json()
            chart = data2.get("tonechart", [])
            if chart:
                tones = [float(b.get("tone", 0)) * float(b.get("value", 0))
                         for b in chart if b.get("value")]
                total_w = sum(float(b.get("value", 0)) for b in chart)
                if total_w > 0:
                    result["tone_avg"] = round(sum(tones) / total_w, 2)
    except Exception as e:
        logger.warning("GDELT tone fetch failed: %s", e)

    return result


async def load_gdelt_signals(disease_names: list[str] | None = None) -> dict[str, dict]:
    """
    Fetch GDELT news signals for diseases in our universe.
    Stores results in disease_burden table as:
      metric='news_mention_count' — total articles in 6 months
      metric='news_tone_score'    — avg sentiment (-100..+100)
    Returns {disease: {total_articles, monthly_avg, tone_avg}}.
    """
    targets = disease_names or list(_DISEASE_QUERIES.keys())
    results: dict[str, dict] = {}

    try:
        from app.db.database import get_pool
        pool = await get_pool()
    except Exception:
        pool = None

    for disease in targets:
        query = _DISEASE_QUERIES.get(disease)
        if not query:
            continue

        data = _fetch_gdelt_volume(query)
        time.sleep(_DELAY)

        results[disease] = data

        if pool and data["total_articles"] > 0:
            try:
                async with pool.acquire() as conn:
                    mondo_row = await conn.fetchrow(
                        "SELECT mondo_id FROM disease WHERE lower(label)=lower($1) LIMIT 1", disease
                    )
                    mondo_id = mondo_row["mondo_id"] if mondo_row else None

                    for metric, value, unit in [
                        ("news_mention_count", float(data["total_articles"]),   "articles/6mo"),
                        ("news_tone_score",    float(data.get("tone_avg", 0)), "sentiment_score"),
                    ]:
                        await conn.execute("""
                            INSERT INTO disease_burden
                                (mondo_id, disease_label, source_name, source_code, commercial_safe,
                                 metric, value, unit, location, year)
                            VALUES ($1,$2,'gdelt','gdelt',TRUE,$3,$4,$5,'Global',2026)
                            ON CONFLICT (mondo_id, source_name, metric, location, year, age_group, sex)
                            DO UPDATE SET value=EXCLUDED.value, fetched_at=NOW()
                        """, mondo_id, disease, metric, value, unit)
            except Exception as e:
                logger.warning("GDELT DB store failed for %s: %s", disease, e)

        logger.info("GDELT: %s → %d articles/6mo, tone=%.1f",
                    disease, data["total_articles"], data.get("tone_avg", 0))

    return results
