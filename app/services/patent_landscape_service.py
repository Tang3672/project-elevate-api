"""
Patent Landscape Service — IP whitespace & competitive intelligence
=====================================================================
A TTO evaluating a new technology needs to know: who else is patenting
in this space right now? Is there freedom-to-operate risk? Which
universities/companies are the natural licensing partners or
competitors? A PI using ChatGPT cannot answer this — it requires a
live patent database search, and PitchBook does not cover patents at
all (it's a financial database, not an IP database).

Source: Google Patents' public search endpoint
(patents.google.com/xhr/query) — the same JSON API that powers the
patents.google.com search UI. Free, no API key, no registration.
(USPTO's PatentsView API is mid-transition to a key-gated Open Data
Portal as of June 2026, so we use Google Patents instead.)
"""

import logging
from collections import Counter
from datetime import datetime, timedelta

import httpx

logger = logging.getLogger(__name__)

GOOGLE_PATENTS_URL = "https://patents.google.com/xhr/query"


async def get_patent_landscape(
    disease_name: str,
    technology_keywords: str = "",
    years_back: int = 3,
) -> dict:
    """
    Search recent US patent filings related to a disease/technology area.
    Returns: {total_results, recent_patents, top_assignees, activity_signal}
    """
    keywords = disease_name.replace("(", "").replace(")", "").strip()
    inner_query = f'q="{keywords}"'
    if technology_keywords:
        inner_query += f" {technology_keywords}"

    after_date = (datetime.now() - timedelta(days=years_back * 365)).strftime("%Y%m%d")
    inner = f"{inner_query}&country=US&after=priority:{after_date}&sort=new"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                GOOGLE_PATENTS_URL,
                params={"url": inner, "exp": ""},
                headers={"User-Agent": "Mozilla/5.0 (compatible; ProjectElevate research tool)"},
            )
            if r.status_code != 200:
                return {}
            data = r.json()
            res = data.get("results") or {}
            total = res.get("total_num_results", 0) or 0

            patents = []
            assignees: Counter = Counter()
            for cluster in (res.get("cluster") or [])[:1]:
                for item in (cluster.get("result") or [])[:15]:
                    p = item.get("patent") or {}
                    title = (p.get("title") or "").replace("&hellip;", "...").strip()
                    if not title:
                        continue
                    assignee = (p.get("assignee") or "").strip()
                    if assignee:
                        assignees[assignee] += 1
                    pub_no = p.get("publication_number") or ""
                    patents.append({
                        "title":              title[:120],
                        "assignee":           assignee or "Unknown",
                        "priority_date":      p.get("priority_date") or "",
                        "publication_number": pub_no,
                        "url":                f"https://patents.google.com/patent/{pub_no}" if pub_no else "",
                    })

            if total > 150:
                signal = "CROWDED — established IP landscape, FTO analysis recommended before filing"
            elif total > 30:
                signal = "ACTIVE — moderate patent activity, differentiation matters"
            else:
                signal = "OPEN — limited patent activity, potential white space"

            logger.info("Patent landscape: %d total US filings for '%s' (last %dy)",
                         total, disease_name, years_back)
            return {
                "total_results":   total,
                "recent_patents":  patents,
                "top_assignees":   assignees.most_common(6),
                "activity_signal": signal,
                "years_back":      years_back,
            }
    except Exception as e:
        logger.warning("Patent landscape fetch failed (non-fatal): %s", e)
        return {}


def format_patent_landscape(data: dict, disease_name: str) -> str:
    """Format patent landscape as a context block for the report."""
    if not data:
        return ""

    lines = [
        "=== PATENT LANDSCAPE (Google Patents — US filings, free public search) ===",
        f"Recent US patent filings related to '{disease_name}' "
        f"(last {data.get('years_back', 3)} years): {data.get('total_results', 0)}",
        f"IP landscape signal: {data.get('activity_signal', '')}",
        "",
    ]

    assignees = data.get("top_assignees", [])
    if assignees:
        lines.append("TOP PATENT HOLDERS IN THIS SPACE (potential licensing partners or competitors):")
        for name, count in assignees:
            lines.append(f"  • {name} — {count} recent filing(s)")
        lines.append("")

    patents = data.get("recent_patents", [])
    if patents:
        lines.append("MOST RECENT FILINGS:")
        for p in patents[:6]:
            lines.append(f"  • {p['title']} — {p['assignee']} (priority {p['priority_date']})")
            if p.get("url"):
                lines.append(f"    {p['url']}")
        lines.append("")

    lines.append("=== END PATENT LANDSCAPE ===")
    return "\n".join(lines)
