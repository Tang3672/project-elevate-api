"""
News Article Connector
======================
Pulls fresh articles from biomedical RSS feeds and stores each article as
a DemandSignal so the demand_signals count grows every week as new papers
and news items publish.

Sources (all open/public):
  - FDA press releases & drug approvals
  - NIH news
  - NEJM, Lancet, Nature Medicine, JAMA tables of contents
  - ClinicalTrials.gov new-study feed
  - STAT News, BioPharma Dive, Fierce Pharma
  - WHO news

Each article gets source_record_id = URL (unique per article), so
ON CONFLICT DO NOTHING correctly skips already-stored articles while
adding new ones every run.
"""

import hashlib
import logging
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import AsyncIterator, List

import httpx

from app.ingestion.connectors.base import BaseConnector
from app.models.demand_signal import DemandSignal, SignalSource, SignalType, GeographicScope

logger = logging.getLogger(__name__)

_TIMEOUT = 15
_DELAY   = 0.5   # seconds between feed fetches

RSS_FEEDS: dict[str, str] = {
    "fda_drug_approvals":  "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds-updates/ucm2005274.htm",
    "fda_press_releases":  "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds-updates/ucm2007798.htm",
    "fda_medical_devices": "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds-updates/ucm2009831.htm",
    "nih_news":            "https://www.nih.gov/rss/news.rss",
    "nejm_toc":            "https://www.nejm.org/action/showFeed?type=etoc&feed=rss&jc=nejm",
    "lancet_toc":          "https://www.thelancet.com/rssfeed/lancet_current.xml",
    "nature_medicine":     "https://www.nature.com/nm.rss",
    "jama_toc":            "https://jamanetwork.com/rss/site_3/67.xml",
    "clinicaltrials_new":  "https://clinicaltrials.gov/ct2/results/rss.xml?rcv_d=14&lup_d=14&sel_rss=new14",
    "stat_news":           "https://www.statnews.com/feed/",
    "biopharmadive":       "https://www.biopharmadive.com/feeds/news/",
    "fierce_pharma":       "https://www.fiercepharma.com/rss/xml",
    "who_news":            "https://www.who.int/rss-feeds/news-english.xml",
}

# Map feed name → hint for routing (determines which reports this signal is relevant to)
_FEED_CATEGORY: dict[str, str] = {
    "fda_drug_approvals":  "drug",
    "fda_press_releases":  "drug",
    "fda_medical_devices": "device",
    "nih_news":            "research",
    "nejm_toc":            "drug",
    "lancet_toc":          "drug",
    "nature_medicine":     "drug",
    "jama_toc":            "drug",
    "clinicaltrials_new":  "clinical_trial",
    "stat_news":           "drug",
    "biopharmadive":       "drug",
    "fierce_pharma":       "drug",
    "who_news":            "disease_burden",
}


def _parse_feed(url: str, max_items: int = 30) -> list[dict]:
    """Fetch and parse one RSS/Atom feed. Returns list of article dicts."""
    items = []
    try:
        r = httpx.get(
            url, timeout=_TIMEOUT,
            headers={"User-Agent": "ProjectElevate/1.0 contact@projectelevate.io"},
        )
        if r.status_code != 200:
            return items
        root = ET.fromstring(r.content)
        ns   = {"atom": "http://www.w3.org/2005/Atom"}

        for item in root.findall(".//item")[:max_items]:
            title  = (item.findtext("title") or "").strip()
            link   = (item.findtext("link")  or "").strip()
            pubdate= (item.findtext("pubDate") or "").strip()
            desc   = (item.findtext("description") or "").strip()
            if title:
                items.append({"title": title, "link": link,
                               "date": pubdate, "description": desc[:400]})

        if not items:
            for entry in root.findall("atom:entry", ns)[:max_items]:
                title = (entry.findtext("atom:title", namespaces=ns) or "").strip()
                lnk   = entry.find("atom:link", ns)
                href  = lnk.attrib.get("href", "") if lnk is not None else ""
                date  = (entry.findtext("atom:published", namespaces=ns) or "").strip()
                summ  = (entry.findtext("atom:summary", namespaces=ns) or "").strip()
                if title:
                    items.append({"title": title, "link": href,
                                   "date": date, "description": summ[:400]})
    except Exception as e:
        logger.warning("Feed parse failed for %s: %s", url[:60], e)
    return items


def _url_to_id(url: str) -> str:
    """Stable 64-char identifier from URL — used as source_record_id."""
    if not url:
        return ""
    # Use the URL directly if short enough, otherwise hash it
    if len(url) <= 200:
        return url
    return hashlib.sha256(url.encode()).hexdigest()[:64]


class NewsArticleConnector(BaseConnector):
    """
    Produces one DemandSignal per RSS article.
    Each article's URL is its source_record_id → new articles add new
    signals every run; already-stored articles are skipped.
    """
    source_name             = "rss_news"
    description             = "Biomedical news and journal RSS feeds"
    update_frequency_hours  = 24
    batch_size              = 50

    async def fetch(self) -> AsyncIterator[List[DemandSignal]]:
        batch: List[DemandSignal] = []
        seen_ids: set[str] = set()

        for feed_name, url in RSS_FEEDS.items():
            category = _FEED_CATEGORY.get(feed_name, "drug")
            articles = _parse_feed(url)
            logger.info("NewsArticleConnector: %s → %d articles", feed_name, len(articles))

            for art in articles:
                link = art.get("link", "")
                rid  = _url_to_id(link or art.get("title", ""))
                if not rid or rid in seen_ids:
                    continue
                seen_ids.add(rid)

                title = art.get("title", "")[:400]
                desc  = art.get("description", "")
                if not title:
                    continue

                sig = DemandSignal(
                    source               = SignalSource.RSS_NEWS,
                    source_record_id     = rid,
                    signal_type          = SignalType.RESEARCH_TREND,
                    fetched_at           = datetime.now(timezone.utc),
                    title                = title,
                    description          = (desc or title)[:800],
                    condition_or_topic   = feed_name,
                    innovation_category_hint = category,
                    geographic_scope     = GeographicScope.GLOBAL,
                    country              = "US",
                    source_url           = link[:512] if link else None,
                    keywords             = [feed_name, category],
                    confidence_score     = 0.7,
                )
                batch.append(sig)
                if len(batch) >= self.batch_size:
                    yield batch
                    batch = []

            time.sleep(_DELAY)   # avoid hammering feeds

        if batch:
            yield batch
