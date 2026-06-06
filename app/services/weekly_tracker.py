"""
Weekly Intelligence Tracker
============================
Runs every Monday 8AM UTC.
For each active watchlist, searches for new developments
and determines if a report recalculation is needed.

Search categories per watchlist:
  1. Recent publications (PubMed, bioRxiv)
  2. FDA approvals / guidance
  3. Clinical trial updates (ClinicalTrials.gov)
  4. Disease epidemiology news (CDC, WHO)
  5. Competitor pipeline news
  6. Funding / deal news

Significance scoring (Claude Haiku):
  8-10: Recalculation strongly recommended
  6-7:  Recalculation suggested
  1-5:  Informational only
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Dict, Optional
import httpx

from app.core.config import settings
from app.db.watchlist_repository import get_all_active_watchlists, create_alert
from app.db.user_repository import get_user_by_id
# Email sent inline via send_weekly_digest_email function below

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
HAIKU_MODEL       = "claude-haiku-4-5-20251001"
SEARCH_TIMEOUT    = 30.0
SEARCH_DELAY      = 1.0  # seconds between searches to avoid 429


# ── Search Templates ──────────────────────────────────────────────────────────

def build_searches(watchlist: dict) -> List[str]:
    """Build 6 targeted search queries for a watchlist."""
    desc     = watchlist.get("product_description", "")[:200]
    keywords = watchlist.get("keywords", [])
    domain   = watchlist.get("disease_domain", "")
    kw_str   = " ".join(keywords[:3]) if keywords else desc[:50]

    return [
        f"{kw_str} new publication research 2026 site:pubmed.ncbi.nlm.nih.gov OR site:biorxiv.org",
        f"{kw_str} FDA approval guidance 2026 site:fda.gov",
        f"{kw_str} clinical trial results Phase 2 3 2026 site:clinicaltrials.gov",
        f"{kw_str} epidemiology prevalence incidence 2026 site:cdc.gov OR site:who.int",
        f"{kw_str} competitor pipeline drug device approval 2026",
        f"{kw_str} funding deal investment acquisition 2026",
    ]


# ── Single Search ─────────────────────────────────────────────────────────────

async def _run_search(query: str) -> str:
    """Run a single web search via Claude and return results."""
    try:
        async with httpx.AsyncClient(timeout=SEARCH_TIMEOUT) as client:
            r = await client.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key":         settings.ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type":      "application/json",
                },
                json={
                    "model":      HAIKU_MODEL,
                    "max_tokens": 600,
                    "tools":      [{"type": "web_search_20250305", "name": "web_search"}],
                    "messages":   [{
                        "role":    "user",
                        "content": (
                            f"Search: {query}\n\n"
                            "Extract the 3-5 most important recent findings. "
                            "For each: TITLE | DATE | KEY FINDING | URL\n"
                            "Only include results from the last 6 months. Be concise."
                        )
                    }],
                }
            )
            r.raise_for_status()
            text = ""
            for block in r.json().get("content", []):
                if block.get("type") == "text":
                    text += block.get("text", "")
            return f"[{query[:60]}]\n{text}\n"
    except Exception as e:
        logger.warning(f"Search failed for '{query[:50]}': {e}")
        return f"[{query[:60]}]\n[Search unavailable]\n"


# ── Significance Analysis ─────────────────────────────────────────────────────

ANALYSIS_SYSTEM = """You are a pharmaceutical intelligence analyst. Given recent news and publications
about a healthcare product area, determine:
1. The most significant developments
2. Whether they require the PI to recalculate their market analysis

Significance triggers (any one warrants recalculation):
- New FDA drug/device approval in same indication
- Phase 3 trial results published for a competitor
- Major epidemiology change (>20% shift in prevalence/incidence)
- New FDA guidance document affecting the regulatory pathway
- Major competitor funding round (>$50M) or acquisition
- New breakthrough therapy designation for a competitor

Respond ONLY in JSON:
{
  "significance_score": <1-10>,
  "recalculation_needed": <true/false>,
  "recalculation_reason": "<one sentence why, or null>",
  "top_findings": [
    {"title": "...", "category": "...", "impact": "...", "url": "..."},
    ...
  ],
  "summary": "<2-3 sentence summary of the week's developments>"
}"""


async def _analyze_findings(watchlist: dict, search_results: str) -> dict:
    """Use Claude Haiku to analyze search results and score significance."""
    desc = watchlist.get("product_description", "")[:300]
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            r = await client.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key":         settings.ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type":      "application/json",
                },
                json={
                    "model":      HAIKU_MODEL,
                    "max_tokens": 800,
                    "system":     ANALYSIS_SYSTEM,
                    "messages":   [{
                        "role":    "user",
                        "content": f"Product: {desc}\n\nRecent findings:\n{search_results[:3000]}"
                    }],
                }
            )
            r.raise_for_status()
            import json, re
            text = r.json()["content"][0]["text"]
            # Extract JSON
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group())
    except Exception as e:
        logger.error(f"Analysis failed: {e}")

    return {
        "significance_score":  3,
        "recalculation_needed": False,
        "recalculation_reason": None,
        "top_findings":         [],
        "summary":              "Weekly scan completed. No major developments detected.",
    }


# ── Process One Watchlist ─────────────────────────────────────────────────────

async def process_watchlist(watchlist: dict) -> dict:
    """Run full weekly intelligence scan for one watchlist."""
    wl_id   = watchlist["watchlist_id"]
    wl_name = watchlist.get("name", "Watchlist")
    user_id = watchlist["user_id"]

    logger.info(f"Processing watchlist {wl_id}: {wl_name}")

    # Run searches sequentially with delay to avoid rate limiting
    queries = build_searches(watchlist)
    results = []
    for i, query in enumerate(queries):
        if i > 0:
            await asyncio.sleep(SEARCH_DELAY)
        result = await _run_search(query)
        results.append(result)

    combined = "\n\n".join(results)

    # Run retention intelligence checks (staleness, grants, competitors, signals)
    try:
        from app.services.retention_service import run_retention_checks, format_retention_alert_body
        from app.db.user_repository import get_user_by_id
        # Get saved reports for this user
        try:
            from app.db.user_repository import get_pool
            pool = await get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM saved_reports WHERE user_id = $1 ORDER BY created_at DESC LIMIT 3",
                    watchlist["user_id"]
                )
                saved_reports = [dict(r) for r in rows]
        except Exception:
            saved_reports = []

        retention_results = await run_retention_checks(watchlist, saved_reports)
        retention_body    = format_retention_alert_body(retention_results, watchlist.get("name", ""))
    except Exception as e:
        logger.error(f"Retention checks failed: {e}")
        retention_results = {}
        retention_body    = ""

    # Analyze findings
    analysis = await _analyze_findings(watchlist, combined)

    score       = analysis.get("significance_score", 1)
    needs_recalc = analysis.get("recalculation_needed", False)
    reason      = analysis.get("recalculation_reason")
    summary     = analysis.get("summary", "")
    findings    = analysis.get("top_findings", [])

    # Determine alert severity
    if score >= 8:
        severity = "high"
    elif score >= 6:
        severity = "medium"
    else:
        severity = "low"

    # Build alert title
    if needs_recalc:
        title = f"⚠️ Recalculation recommended: {wl_name}"
    elif score >= 5:
        title = f"📊 Notable developments: {wl_name}"
    else:
        title = f"📋 Weekly scan: {wl_name}"

    # Build alert body
    body_parts = [f"**Weekly Intelligence Report — {wl_name}**\n"]
    body_parts.append(f"Significance score: {score}/10\n")
    body_parts.append(f"\n{summary}\n")

    if needs_recalc and reason:
        body_parts.append(f"\n🔴 **Recalculation needed:** {reason}\n")

    if findings:
        body_parts.append("\n**Top findings this week:**")
        for f in findings[:5]:
            body_parts.append(
                f"\n• [{f.get('category','General')}] {f.get('title','')} — {f.get('impact','')}"
            )

    body = "\n".join(body_parts)

    # Save alert to DB
    alert = await create_alert(
        watchlist_id = wl_id,
        user_id      = user_id,
        title        = title,
        body         = body,
        severity     = severity,
        source       = "weekly_tracker",
        recalculation_needed = needs_recalc,
        significance_score   = score,
    )

    return {
        "watchlist_id":       wl_id,
        "watchlist_name":     wl_name,
        "user_id":            user_id,
        "significance_score": score,
        "recalculation_needed": needs_recalc,
        "recalculation_reason": reason,
        "summary":            summary,
        "findings_count":     len(findings),
        "alert_id":           alert.get("id") if alert else None,
    }


# ── Main Weekly Job ───────────────────────────────────────────────────────────

async def run_weekly_tracker():
    """
    Main entry point — called by APScheduler every Monday 8AM UTC.
    Processes all active watchlists and sends email digests.
    """
    start = datetime.now(timezone.utc)
    logger.info(f"Weekly tracker started at {start.isoformat()}")

    try:
        watchlists = await get_all_active_watchlists()
    except Exception as e:
        logger.error(f"Failed to fetch watchlists: {e}")
        # Table may not exist yet — return gracefully
        return []

    if not watchlists:
        logger.info("No active watchlists to process")
        return

    logger.info(f"Processing {len(watchlists)} watchlists")

    # Process watchlists with 2s delay between to avoid API rate limits
    results = []
    for i, wl in enumerate(watchlists):
        if i > 0:
            await asyncio.sleep(2.0)
        try:
            result = await process_watchlist(wl)
            results.append(result)
        except Exception as e:
            logger.error(f"Failed to process watchlist {wl.get('id')}: {e}")

    # Group results by user and send email digest
    from collections import defaultdict
    by_user = defaultdict(list)
    for r in results:
        by_user[r["user_id"]].append(r)

    for user_id, user_results in by_user.items():
        try:
            user = await get_user_by_id(user_id)
            if user and user.get("email"):
                await send_weekly_digest_email(user, user_results)
        except Exception as e:
            logger.error(f"Failed to send digest to user {user_id}: {e}")

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info(f"Weekly tracker complete: {len(results)} watchlists in {elapsed:.1f}s")
    return results


async def send_weekly_digest_email(user: dict, results: List[dict]):
    """Send weekly intelligence digest email to a user."""
    email     = user.get("email")
    name      = user.get("name", "there")
    needs_recalc = [r for r in results if r.get("recalculation_needed")]
    high_sig     = [r for r in results if r.get("significance_score", 0) >= 6]

    subject = (
        f"⚠️ {len(needs_recalc)} report(s) need updating — Project Elevate Weekly"
        if needs_recalc else
        f"📊 Your weekly intelligence digest — Project Elevate"
    )

    # Build email HTML
    rows = ""
    for r in results:
        score = r.get("significance_score", 0)
        color = "#DC2626" if score >= 8 else "#D97706" if score >= 6 else "#059669"
        badge = "🔴 Recalculate" if r.get("recalculation_needed") else f"Score {score}/10"
        rows += f"""
        <tr>
          <td style="padding:12px 0;border-bottom:1px solid #e2e8f0">
            <div style="font-weight:700;color:#0a1628">{r['watchlist_name']}</div>
            <div style="font-size:12px;color:#718096;margin-top:4px">{r.get('summary','')[:150]}...</div>
          </td>
          <td style="padding:12px 0;border-bottom:1px solid #e2e8f0;text-align:right;white-space:nowrap">
            <span style="background:{color};color:#fff;padding:3px 10px;font-size:11px;font-weight:700">
              {badge}
            </span>
          </td>
        </tr>"""

    html = f"""
    <div style="font-family:sans-serif;max-width:600px;margin:0 auto;padding:32px">
      <div style="background:#0a1628;padding:20px 24px;margin-bottom:24px">
        <span style="color:#fff;font-weight:700;font-size:16px">PE</span>
        <span style="color:#a0aec0;font-size:14px;margin-left:8px">Project Elevate — Weekly Intelligence</span>
      </div>

      <h2 style="color:#0a1628;margin-bottom:4px">Your weekly scan is ready</h2>
      <p style="color:#718096;font-size:13px">Hi {name}, here's what changed in your research areas this week.</p>

      {"<div style='background:#FEF3C7;border:1px solid #F59E0B;padding:16px;margin-bottom:20px'><strong>⚠️ " + str(len(needs_recalc)) + " report(s) may need recalculation</strong> based on new developments.</div>" if needs_recalc else ""}

      <table style="width:100%;border-collapse:collapse">
        {rows}
      </table>

      <div style="margin-top:24px;text-align:center">
        <a href="https://preeminent-zuccutto-bd1f9d.netlify.app"
           style="background:#1A4FD6;color:#fff;padding:12px 28px;text-decoration:none;font-weight:700;display:inline-block">
          View Full Reports →
        </a>
      </div>

      <p style="color:#a0aec0;font-size:11px;margin-top:24px;text-align:center">
        Project Elevate · Weekly intelligence digest · <a href="#" style="color:#a0aec0">Unsubscribe</a>
      </p>
    </div>
    """

    try:
        from app.services.email_service import send_email
        await send_email(to=email, subject=subject, html=html)
        logger.info(f"Weekly digest sent to {email}")
    except Exception as e:
        logger.error(f"Failed to send digest to {email}: {e}")


# ── Manual trigger for testing ────────────────────────────────────────────────

async def run_tracker_for_user(user_id: int):
    """Manually trigger tracker for a single user (for testing)."""
    from app.db.watchlist_repository import get_watchlists_for_user
    try:
        watchlists = await get_watchlists_for_user(user_id)
    except Exception as e:
        logger.error(f"Failed to fetch watchlists for user {user_id}: {e}")
        return []
    results = []
    for wl in watchlists:
        result = await process_watchlist(wl)
        results.append(result)
    return results
