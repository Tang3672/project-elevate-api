"""
RSS Feed Connector
===================
Sources:  FDA press releases, NEJM/Lancet/JAMA table-of-contents,
          ClinicalTrials.gov new studies feed, WHO news, NIH news
License:  Open/public — commercial safe for news monitoring
Data:     Recent articles and announcements mentioning diseases

Why valuable:
  - FDA approvals appear in FDA RSS before any database update (real-time)
  - Journal TOC feeds = newest clinical evidence the moment it publishes
  - WHO/NIH news = global disease burden and funding priority signals
  - Company press releases (via PR Newswire) = pipeline readouts

We store items in the disease_burden table as 'rss_recent_mention_count'
and also write raw items to raw_ingest for downstream RAG pipeline use.
"""

import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Optional
import re

import requests

logger = logging.getLogger(__name__)

_TIMEOUT = 10
_DELAY   = 0.3

# ── Feed registry ─────────────────────────────────────────────────────────────
RSS_FEEDS: dict[str, str] = {
    "fda_drug_approvals":    "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds-updates/ucm2005274.htm",
    "fda_press_releases":    "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds-updates/ucm2007798.htm",
    "fda_medical_devices":   "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds-updates/ucm2009831.htm",
    "nih_news":              "https://www.nih.gov/rss/news.rss",
    "nejm_toc":              "https://www.nejm.org/action/showFeed?type=etoc&feed=rss&jc=nejm",
    "lancet_toc":            "https://www.thelancet.com/rssfeed/lancet_current.xml",
    "nature_medicine":       "https://www.nature.com/nm.rss",
    "jama_toc":              "https://jamanetwork.com/rss/site_3/67.xml",
    "clinicaltrials_new":    "https://clinicaltrials.gov/ct2/results/rss.xml?rcv_d=14&lup_d=14&sel_rss=new14",
    "stat_news":             "https://www.statnews.com/feed/",
    "biopharmadive":         "https://www.biopharmadive.com/feeds/news/",
    "fierce_pharma":         "https://www.fiercepharma.com/rss/xml",
    "who_news":              "https://www.who.int/rss-feeds/news-english.xml",
}

# Disease keyword sets for matching feed items
_DISEASE_KEYWORDS: dict[str, list[str]] = {
    "Alzheimer Disease (early/MCI)":        ["alzheimer", "lecanemab", "donanemab", "aduhelm", "leqembi"],
    "NASH/MASH":                            ["nash", "mash", "steatohepatitis", "resmetirom", "rezdiffra"],
    "Huntington Disease":                   ["huntington", "huntingtin"],
    "Sickle Cell Disease (gene therapy)":   ["sickle cell", "casgevy", "lyfgenia"],
    "Glioblastoma Multiforme":              ["glioblastoma", "gbm"],
    "KRAS G12C NSCLC":                      ["kras g12c", "sotorasib", "adagrasib", "lumakras", "krazati"],
    "Type 2 Diabetes (GLP-1 resistant)":   ["glp-1", "semaglutide", "ozempic", "tirzepatide", "mounjaro"],
    "Obesity (CNS/metabolic)":             ["wegovy", "obesity drug", "weight loss drug"],
    "Carbapenem-resistant Enterobacterales":["carbapenem", "cre ", "klebsiella resistant"],
    "MRSA Skin Infections":                 ["mrsa", "methicillin-resistant"],
    "Geographic Atrophy (dry AMD)":         ["geographic atrophy", "syfovre", "izervay", "dry amd"],
    "Multiple Myeloma (triple-refractory)": ["multiple myeloma", "elranatamab", "teclistamab", "talvey"],
    "Lung Cancer (NSCLC, IO-resistant)":   ["non-small cell lung", "nsclc", "tagrisso", "keytruda lung"],
    "Major Depression (TRD)":             ["treatment-resistant depression", "ketamine", "spravato", "psilocybin fda"],
    "Sepsis (AI early detection)":          ["sepsis detection", "sepsis ai", "sepsis diagnosis"],
    "HIV (long-acting ART / cure)":         ["hiv cure", "long-acting hiv", "cabenuva"],
    "Prostate Cancer (PSMA-targeted)":     ["psma", "pluvicto", "lutetium prostate"],
    "Inflammatory Bowel Disease (UC/CD)":  ["crohn", "ulcerative colitis", "vedolizumab", "ustekinumab"],
    "Parkinson Disease (early stage)":      ["parkinson", "alpha-synuclein", "prasinezumab"],
    "Atrial Fibrillation":                  ["atrial fibrillation", "ablation fda", "afib drug"],
}


def _parse_rss(url: str, max_items: int = 30) -> list[dict]:
    """Parse an RSS feed and return recent items as dicts."""
    items = []
    try:
        r = requests.get(url, timeout=_TIMEOUT,
                         headers={"User-Agent": "Medlevate/1.0 contact@projectelevate.io"})
        if r.status_code != 200:
            return items

        root = ET.fromstring(r.content)
        ns   = {"atom": "http://www.w3.org/2005/Atom"}

        # Try RSS 2.0 format
        for item in root.findall(".//item")[:max_items]:
            title   = (item.findtext("title") or "").strip()
            link    = (item.findtext("link")  or "").strip()
            pubdate = (item.findtext("pubDate") or "").strip()
            desc    = (item.findtext("description") or "").strip()
            if title:
                items.append({"title": title, "link": link,
                               "date": pubdate, "description": desc[:300]})

        # Try Atom format
        if not items:
            for entry in root.findall("atom:entry", ns)[:max_items]:
                title = (entry.findtext("atom:title", namespaces=ns) or "").strip()
                link  = entry.find("atom:link", ns)
                href  = link.attrib.get("href", "") if link is not None else ""
                date  = (entry.findtext("atom:published", namespaces=ns) or "").strip()
                if title:
                    items.append({"title": title, "link": href, "date": date, "description": ""})

    except Exception as e:
        logger.warning("RSS parse failed for %s: %s", url[:50], e)
    return items


def _match_disease(text: str, disease: str) -> bool:
    """Check if a text contains keywords for a given disease."""
    text_lower = text.lower()
    keywords   = _DISEASE_KEYWORDS.get(disease, [])
    return any(kw in text_lower for kw in keywords)


async def load_rss_signals(disease_names: list[str] | None = None) -> dict[str, dict]:
    """
    Scan all RSS feeds and count recent mentions per disease.
    Returns {disease: {mention_count, recent_items}}.
    Stores in disease_burden as rss_recent_mention_count.
    """
    # Fetch all feeds
    all_items: list[dict] = []
    for feed_name, url in RSS_FEEDS.items():
        items = _parse_rss(url)
        for item in items:
            item["feed"] = feed_name
        all_items.extend(items)
        time.sleep(_DELAY)

    logger.info("RSS: fetched %d total items from %d feeds", len(all_items), len(RSS_FEEDS))

    targets = disease_names or list(_DISEASE_KEYWORDS.keys())
    results: dict[str, dict] = {}

    try:
        from app.db.database import get_pool
        pool = await get_pool()
    except Exception:
        pool = None

    for disease in targets:
        matched = []
        for item in all_items:
            text = (item.get("title", "") + " " + item.get("description", "")).lower()
            if _match_disease(text, disease):
                matched.append(item)

        data = {
            "mention_count": len(matched),
            "recent_items":  matched[:5],
        }
        results[disease] = data

        if pool and len(matched) > 0:
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
                        VALUES ($1,$2,'rss_feeds','multi_feed',TRUE,
                                'rss_recent_mention_count',$3,'mentions','Global',2026)
                        ON CONFLICT (mondo_id, source_name, metric, location, year, age_group, sex)
                        DO UPDATE SET value=EXCLUDED.value, fetched_at=NOW()
                    """, mondo_id, disease, float(len(matched)))
            except Exception as e:
                logger.warning("RSS DB store failed for %s: %s", disease, e)

    return results
