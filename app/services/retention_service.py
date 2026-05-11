"""
Retention Intelligence Service
================================
Five features that make PIs stay subscribed:

1. Report Staleness Detector  — "your TAM is now off by 40% because X"
2. Grant Deadline Tracker     — NIH R01, SBIR, CARB-X, BARDA deadlines
3. Competitor Milestone Tracker — Phase 3 readouts, approvals, failures
4. Signal Index Delta          — "3 new hospital systems flagged this indication"
5. Report Versioning           — diff between old and new report

All features run as part of the weekly tracker.
"""

import asyncio
import logging
import json
import re
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
HAIKU_MODEL       = "claude-haiku-4-5-20251001"
SONNET_MODEL      = "claude-sonnet-4-6"
TIMEOUT           = 45.0


# ══════════════════════════════════════════════════════════════════════════════
# 1. REPORT STALENESS DETECTOR
# ══════════════════════════════════════════════════════════════════════════════

async def check_report_staleness(saved_report: dict) -> dict:
    """
    Compare a saved report against current data.
    Returns staleness analysis with specific outdated claims.
    
    Triggers recalculation if:
    - TAM changed by >20%
    - New competitor approved in same indication
    - Epidemiology data shifted significantly
    - Regulatory pathway changed (new guidance, new designation)
    """
    report_data = saved_report.get("report_data", {})
    idea        = report_data.get("idea_submitted", "")
    condition   = report_data.get("disease_intelligence", {}).get("condition", "")
    tam_usd     = report_data.get("market_sizing", {}).get("total_addressable_market_usd", 0)
    created_at  = saved_report.get("created_at", "")
    expert_name = report_data.get("expert_name", "")

    if not condition or not idea:
        return {"staleness_score": 0, "outdated_claims": [], "recalculate": False}

    # Run 3 targeted searches
    searches = [
        f"{condition} FDA approval new drug device 2026",
        f"{condition} epidemiology prevalence incidence updated 2026 site:cdc.gov OR site:who.int",
        f"{condition} market size TAM pharmaceutical 2026",
    ]

    results = []
    for i, q in enumerate(searches):
        if i > 0:
            await asyncio.sleep(1.0)
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                r = await client.post(
                    ANTHROPIC_API_URL,
                    headers={
                        "x-api-key": settings.ANTHROPIC_API_KEY,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": HAIKU_MODEL,
                        "max_tokens": 400,
                        "tools": [{"type": "web_search_20250305", "name": "web_search"}],
                        "messages": [{"role": "user", "content": f"Search: {q}\nExtract 3 key facts with dates and sources."}],
                    }
                )
                text = ""
                for block in r.json().get("content", []):
                    if block.get("type") == "text":
                        text += block.get("text", "")
                results.append(text)
        except Exception as e:
            results.append("")

    combined = "\n\n".join(results)

    # Analyze with Claude
    analysis_prompt = f"""You are analyzing whether a PI's saved market research report is now outdated.

ORIGINAL REPORT (saved {created_at[:10] if created_at else 'previously'}):
- Condition: {condition}
- Expert: {expert_name}
- Original TAM: ${tam_usd:,.0f}
- Product idea: {idea[:200]}

ORIGINAL KEY DATA POINTS:
{json.dumps([dp for dp in report_data.get('disease_intelligence', {}).get('data_points', [])[:5]], indent=2)}

CURRENT DATA FROM WEB SEARCH:
{combined[:2000]}

Analyze if the report needs updating. Respond ONLY in JSON:
{{
  "staleness_score": <0-10, where 10 = completely outdated>,
  "recalculate": <true/false>,
  "recalculate_reason": "<one specific sentence with numbers, or null>",
  "outdated_claims": [
    {{
      "original_claim": "<what the old report said>",
      "current_reality": "<what is true now>",
      "impact": "<how this changes the analysis>",
      "severity": "<critical|major|minor>"
    }}
  ],
  "tam_change_percent": <estimated % change in TAM, 0 if unknown>,
  "summary": "<1-2 sentences PI can act on>"
}}"""

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key": settings.ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": HAIKU_MODEL,
                    "max_tokens": 600,
                    "messages": [{"role": "user", "content": analysis_prompt}],
                }
            )
            text = r.json()["content"][0]["text"]
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                return json.loads(match.group())
    except Exception as e:
        logger.error(f"Staleness analysis failed: {e}")

    return {"staleness_score": 0, "outdated_claims": [], "recalculate": False}


# ══════════════════════════════════════════════════════════════════════════════
# 2. GRANT DEADLINE TRACKER
# ══════════════════════════════════════════════════════════════════════════════

# Static grant calendar — updated periodically
# Format: name, funder, amount, deadline_pattern, url, relevant_domains
GRANT_CALENDAR = [
    {
        "name": "NIH SBIR Phase I",
        "funder": "NIH",
        "amount": "$305,419",
        "cycle": "3x/year",
        "deadlines": ["April 5", "August 5", "December 5"],
        "url": "https://seed.nih.gov/small-business-funding/sbir-sttr",
        "domains": ["all"],
        "notes": "Fast-track available. No commercial product required.",
    },
    {
        "name": "NIH SBIR Phase II",
        "funder": "NIH",
        "amount": "$2M",
        "cycle": "3x/year",
        "deadlines": ["April 5", "August 5", "December 5"],
        "url": "https://seed.nih.gov/small-business-funding/sbir-sttr",
        "domains": ["all"],
        "notes": "Requires Phase I completion or direct Phase II justification.",
    },
    {
        "name": "NIH R01",
        "funder": "NIH",
        "amount": "$500K/yr (direct costs)",
        "cycle": "3x/year",
        "deadlines": ["February 5", "June 5", "October 5"],
        "url": "https://grants.nih.gov/grants/guide/pa-files/PA-25-303.html",
        "domains": ["all"],
        "notes": "Standard R01. New investigator deadline: February 12, June 12, October 12.",
    },
    {
        "name": "CARB-X Round",
        "funder": "CARB-X",
        "amount": "Up to $4.5M Phase 1 / $12M Phase 2",
        "cycle": "Rolling",
        "deadlines": ["Rolling — check website"],
        "url": "https://carb-x.org/apply/",
        "domains": ["drug_small_molecule", "diagnostic", "drug_amr"],
        "notes": "Novel antibacterial and diagnostic products only. No Phase 3 funding.",
    },
    {
        "name": "BARDA BAA",
        "funder": "BARDA",
        "amount": "$50M-$500M+",
        "cycle": "Periodic",
        "deadlines": ["Check SAM.gov for open BAAs"],
        "url": "https://medicalcountermeasures.gov/barda/funding/",
        "domains": ["drug_small_molecule", "biologic", "diagnostic", "vaccine_immunotherapy"],
        "notes": "CBRN and pandemic preparedness. Requires U.S. company.",
    },
    {
        "name": "FDA Orphan Products Clinical Trials Grant",
        "funder": "FDA OOPD",
        "amount": "Up to $500K/yr × 4 years",
        "cycle": "Annual",
        "deadlines": ["November (check grants.gov)"],
        "url": "https://www.fda.gov/patients/rare-diseases-fda/grants-rare-diseases-and-conditions",
        "domains": ["drug_rare_disease", "biologic_rare_disease", "gene_therapy_rare"],
        "notes": "Must have Orphan Drug Designation. Clinical studies only.",
    },
    {
        "name": "NCI SBIR Phase I",
        "funder": "NCI / NIH",
        "amount": "Up to $2M",
        "cycle": "3x/year",
        "deadlines": ["April 5", "August 5", "December 5"],
        "url": "https://sbir.cancer.gov/",
        "domains": ["drug_oncology", "biologic_oncology", "diagnostic_companion", "gene_therapy_oncology"],
        "notes": "Cancer-specific SBIR. Omnibus solicitation.",
    },
    {
        "name": "NHLBI SBIR/R01",
        "funder": "NHLBI / NIH",
        "amount": "$305K (SBIR) / $500K (R01)",
        "cycle": "3x/year",
        "deadlines": ["April 5", "August 5", "December 5"],
        "url": "https://www.nhlbi.nih.gov/grants-and-training/funding-opportunities",
        "domains": ["drug_cardiology", "biologic_cardiology", "device_cardiovascular"],
        "notes": "Heart, lung, blood focus. Strong cardiovascular portfolio.",
    },
    {
        "name": "NINDS SBIR/R01",
        "funder": "NINDS / NIH",
        "amount": "$305K (SBIR) / $500K (R01)",
        "cycle": "3x/year",
        "deadlines": ["April 5", "August 5", "December 5"],
        "url": "https://www.ninds.nih.gov/funding",
        "domains": ["drug_cns", "gene_therapy_cns", "device_neurology"],
        "notes": "Neurology and stroke focus.",
    },
    {
        "name": "NIDDK SBIR/R01",
        "funder": "NIDDK / NIH",
        "amount": "$305K (SBIR) / $500K (R01)",
        "cycle": "3x/year",
        "deadlines": ["April 5", "August 5", "December 5"],
        "url": "https://www.niddk.nih.gov/research-funding",
        "domains": ["drug_metabolic", "device_metabolic"],
        "notes": "Diabetes, kidney, digestive, liver focus.",
    },
    {
        "name": "CEPI Funding Round",
        "funder": "CEPI",
        "amount": "Up to $100M",
        "cycle": "Periodic",
        "deadlines": ["Check cepi.net for open calls"],
        "url": "https://cepi.net/funding/",
        "domains": ["vaccine_prophylactic", "vaccine_cancer_immuno"],
        "notes": "Pandemic preparedness vaccines. Global health focus.",
    },
    {
        "name": "Wellcome Trust Innovator Awards",
        "funder": "Wellcome Trust",
        "amount": "Up to £500K",
        "cycle": "Rolling",
        "deadlines": ["Rolling"],
        "url": "https://wellcome.org/grant-funding/schemes/innovator-awards-health-innovation",
        "domains": ["all"],
        "notes": "UK focus but international applicants welcome. Early-stage innovation.",
    },
]


def get_relevant_grants(sub_expert_id: str, disease_keywords: List[str]) -> List[dict]:
    """Return grants relevant to a specific sub-expert and disease."""
    relevant = []
    for grant in GRANT_CALENDAR:
        domains = grant.get("domains", [])
        if "all" in domains or sub_expert_id in domains:
            # Check if any disease keyword matches
            grant_text = f"{grant['name']} {grant['notes']} {grant['funder']}".lower()
            kw_match = any(kw.lower() in grant_text for kw in disease_keywords) if disease_keywords else True
            if kw_match or "all" in domains:
                relevant.append(grant)
    return relevant[:5]  # Return top 5


async def check_grant_deadlines(sub_expert_id: str, keywords: List[str]) -> List[dict]:
    """Check for upcoming grant deadlines relevant to this watchlist."""
    grants = get_relevant_grants(sub_expert_id, keywords)
    now = datetime.now(timezone.utc)

    upcoming = []
    for grant in grants:
        # Check if any deadline is within 60 days
        for deadline_str in grant.get("deadlines", []):
            if "rolling" in deadline_str.lower() or "check" in deadline_str.lower():
                upcoming.append({**grant, "days_until": None, "urgency": "check_website"})
                break
            else:
                try:
                    # Try to parse deadline like "April 5"
                    for year in [now.year, now.year + 1]:
                        try:
                            deadline = datetime.strptime(f"{deadline_str} {year}", "%B %d %Y")
                            deadline = deadline.replace(tzinfo=timezone.utc)
                            days_until = (deadline - now).days
                            if 0 <= days_until <= 90:
                                upcoming.append({
                                    **grant,
                                    "days_until": days_until,
                                    "deadline_date": deadline.strftime("%B %d, %Y"),
                                    "urgency": "urgent" if days_until <= 14 else "upcoming",
                                })
                                break
                        except ValueError:
                            pass
                except Exception:
                    pass

    return upcoming


# ══════════════════════════════════════════════════════════════════════════════
# 3. COMPETITOR MILESTONE TRACKER
# ══════════════════════════════════════════════════════════════════════════════

async def track_competitor_milestones(condition: str, product_desc: str) -> List[dict]:
    """
    Search for competitor milestones in the same indication.
    Returns list of significant events: approvals, Phase 3 readouts, failures, BTDs.
    """
    queries = [
        f"{condition} FDA approval new drug 2026",
        f"{condition} Phase 3 trial results readout 2026",
        f"{condition} breakthrough therapy designation FDA 2026",
        f"{condition} clinical trial failure discontinued 2026",
        f"{condition} drug acquisition partnership deal 2026",
    ]

    all_results = ""
    for i, q in enumerate(queries[:3]):  # Limit to 3 for rate limiting
        if i > 0:
            await asyncio.sleep(1.0)
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                r = await client.post(
                    ANTHROPIC_API_URL,
                    headers={
                        "x-api-key": settings.ANTHROPIC_API_KEY,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json={
                        "model": HAIKU_MODEL,
                        "max_tokens": 400,
                        "tools": [{"type": "web_search_20250305", "name": "web_search"}],
                        "messages": [{"role": "user", "content": f"Search: {q}\nList recent events with dates. Format: EVENT | DATE | COMPANY | URL"}],
                    }
                )
                for block in r.json().get("content", []):
                    if block.get("type") == "text":
                        all_results += block.get("text", "") + "\n"
        except Exception as e:
            logger.warning(f"Competitor search failed: {e}")

    if not all_results.strip():
        return []

    # Extract milestones with Claude
    extract_prompt = f"""Extract competitor milestones from this text for {condition}.
Focus on: FDA approvals, Phase 3 results, BTD designations, trial failures, acquisitions.

TEXT:
{all_results[:2000]}

Respond ONLY in JSON array:
[
  {{
    "event_type": "<approval|phase3_success|phase3_failure|btd|acquisition|other>",
    "company": "<company name>",
    "product": "<drug/device name>",
    "description": "<one sentence>",
    "date": "<month year or 'recent'>",
    "impact_on_pi": "<one sentence on how this affects the PI's strategy>",
    "url": "<url or null>"
  }}
]"""

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            r = await client.post(
                ANTHROPIC_API_URL,
                headers={
                    "x-api-key": settings.ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": HAIKU_MODEL,
                    "max_tokens": 600,
                    "messages": [{"role": "user", "content": extract_prompt}],
                }
            )
            text = r.json()["content"][0]["text"]
            match = re.search(r'\[.*\]', text, re.DOTALL)
            if match:
                milestones = json.loads(match.group())
                return milestones[:5]
    except Exception as e:
        logger.error(f"Milestone extraction failed: {e}")

    return []


# ══════════════════════════════════════════════════════════════════════════════
# 4. SIGNAL INDEX DELTA
# ══════════════════════════════════════════════════════════════════════════════

async def compute_signal_delta(watchlist: dict, days_back: int = 30) -> dict:
    """
    Compare current demand signals against signals from N days ago.
    Shows how the hospital/federal demand picture has changed.
    """
    try:
        from app.db.demand_repository import search_similar_signals
        from app.services.embedding_service import embed_text
    except ImportError as e:
        return {"new_in_30_days": 0, "delta_summary": f"Service unavailable: {e}"}

    desc = watchlist.get("product_description", "")
    if not desc:
        return {"new_signals": 0, "delta_summary": "No product description"}

    try:
        embedding = await embed_text(desc)
        current_signals = await search_similar_signals(
            query_embedding=embedding, top_k=50, min_similarity=0.55
        )

        # Signals added in last 30 days
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
        new_signals = []
        for sig in current_signals:
            fetched_at = sig.get("fetched_at")
            if fetched_at:
                try:
                    if isinstance(fetched_at, str):
                        fetched_dt = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
                    else:
                        fetched_dt = fetched_at
                    if fetched_dt.replace(tzinfo=timezone.utc) > cutoff:
                        new_signals.append(sig)
                except Exception:
                    pass

        # Summarize new signals by source
        by_source = {}
        for sig in new_signals:
            src = sig.get("source", "unknown")
            by_source[src] = by_source.get(src, 0) + 1

        source_summary = ", ".join(f"{count} from {src}" for src, count in by_source.items())

        return {
            "total_current": len(current_signals),
            "new_in_30_days": len(new_signals),
            "by_source": by_source,
            "source_summary": source_summary or "No new signals",
            "top_new_signals": [
                {
                    "title": s.get("title", ""),
                    "source": s.get("source", ""),
                    "signal_type": s.get("signal_type", ""),
                    "location": s.get("location_name", ""),
                }
                for s in new_signals[:3]
            ],
        }
    except Exception as e:
        logger.error(f"Signal delta failed: {e}")
        return {"new_signals": 0, "delta_summary": str(e)}


# ══════════════════════════════════════════════════════════════════════════════
# 5. REPORT VERSIONING
# ══════════════════════════════════════════════════════════════════════════════

def diff_reports(old_report: dict, new_report: dict) -> dict:
    """
    Compare two PIReport dicts and return a structured diff.
    Shows what changed between the PI's old report and a fresh analysis.
    """
    changes = []

    # Compare TAM
    old_tam = old_report.get("market_sizing", {}).get("total_addressable_market_usd", 0)
    new_tam = new_report.get("market_sizing", {}).get("total_addressable_market_usd", 0)
    if old_tam and new_tam and abs(new_tam - old_tam) / old_tam > 0.1:
        pct = ((new_tam - old_tam) / old_tam) * 100
        changes.append({
            "field": "Total Addressable Market",
            "old_value": f"${old_tam/1e6:.0f}M",
            "new_value": f"${new_tam/1e6:.0f}M",
            "change": f"{pct:+.0f}%",
            "significance": "high" if abs(pct) > 25 else "medium",
        })

    # Compare regulatory pathway
    old_path = old_report.get("regulatory_pathway", {}).get("recommended_pathway", "")
    new_path = new_report.get("regulatory_pathway", {}).get("recommended_pathway", "")
    if old_path and new_path and old_path != new_path:
        changes.append({
            "field": "Recommended Regulatory Pathway",
            "old_value": old_path,
            "new_value": new_path,
            "change": "Changed",
            "significance": "high",
        })

    # Compare designations count
    old_desig = len(old_report.get("regulatory_pathway", {}).get("designations", []))
    new_desig = len(new_report.get("regulatory_pathway", {}).get("designations", []))
    if new_desig > old_desig:
        changes.append({
            "field": "Regulatory Designations Available",
            "old_value": f"{old_desig} designations",
            "new_value": f"{new_desig} designations",
            "change": f"+{new_desig - old_desig} new designations identified",
            "significance": "medium",
        })

    # Compare disease data points
    old_dp = {dp.get("metric", ""): dp.get("value", "") for dp in old_report.get("disease_intelligence", {}).get("data_points", [])}
    new_dp = {dp.get("metric", ""): dp.get("value", "") for dp in new_report.get("disease_intelligence", {}).get("data_points", [])}

    for metric in set(old_dp.keys()) & set(new_dp.keys()):
        if old_dp[metric] != new_dp[metric] and old_dp[metric] and new_dp[metric]:
            changes.append({
                "field": f"Disease Data: {metric}",
                "old_value": old_dp[metric],
                "new_value": new_dp[metric],
                "change": "Updated",
                "significance": "medium",
            })

    high_changes = [c for c in changes if c["significance"] == "high"]
    
    return {
        "total_changes": len(changes),
        "high_significance_changes": len(high_changes),
        "changes": changes[:10],
        "summary": f"{len(changes)} things changed since your last report" if changes else "No significant changes detected",
        "needs_regeneration": len(high_changes) >= 2 or any(c["field"] == "Total Addressable Market" for c in high_changes),
    }


# ══════════════════════════════════════════════════════════════════════════════
# UNIFIED RETENTION CHECK — runs as part of weekly tracker
# ══════════════════════════════════════════════════════════════════════════════

async def run_retention_checks(watchlist: dict, saved_reports: List[dict]) -> dict:
    """
    Run all retention checks for a watchlist.
    Called by the weekly tracker for each active watchlist.
    """
    desc     = watchlist.get("product_description", "")
    keywords = watchlist.get("keywords", [])

    # Get condition from most recent saved report
    latest_report = saved_reports[0] if saved_reports else {}
    report_data   = latest_report.get("report_data", {}) if latest_report else {}
    condition     = report_data.get("disease_intelligence", {}).get("condition", desc[:50])
    sub_expert_id = report_data.get("expert_domain", "drug_amr")

    results = {}

    # 1. Staleness check (if there's a saved report)
    if latest_report:
        try:
            staleness = await check_report_staleness(latest_report)
            results["staleness"] = staleness
        except Exception as e:
            logger.error(f"Staleness check failed: {e}")
            results["staleness"] = {}

    # 2. Grant deadlines
    try:
        grants = await check_grant_deadlines(sub_expert_id, keywords)
        results["grant_deadlines"] = grants
    except Exception as e:
        logger.error(f"Grant deadline check failed: {e}")
        results["grant_deadlines"] = []

    # 3. Competitor milestones
    try:
        await asyncio.sleep(1.0)  # Rate limit buffer
        milestones = await track_competitor_milestones(condition, desc)
        results["competitor_milestones"] = milestones
    except Exception as e:
        logger.error(f"Competitor milestone check failed: {e}")
        results["competitor_milestones"] = []

    # 4. Signal delta
    try:
        delta = await compute_signal_delta(watchlist)
        results["signal_delta"] = delta
    except Exception as e:
        logger.error(f"Signal delta failed: {e}")
        results["signal_delta"] = {}

    return results


def format_retention_alert_body(retention_results: dict, watchlist_name: str) -> str:
    """Format retention check results into a readable alert body."""
    parts = [f"**Retention Intelligence Report — {watchlist_name}**\n"]

    # Staleness
    staleness = retention_results.get("staleness", {})
    if staleness.get("recalculate"):
        parts.append(f"\n🔴 **Report may be outdated:** {staleness.get('recalculation_reason', '')}")
        for claim in staleness.get("outdated_claims", [])[:3]:
            parts.append(f"\n  • {claim.get('field', '')}: {claim.get('old_value', '')} → {claim.get('new_value', '')}")

    # Grant deadlines
    grants = retention_results.get("grant_deadlines", [])
    if grants:
        parts.append("\n\n💰 **Upcoming Grant Deadlines:**")
        for g in grants[:3]:
            days = g.get("days_until")
            deadline_str = f" ({days} days)" if days else ""
            parts.append(f"\n  • {g['name']} — {g['amount']}{deadline_str}")

    # Competitor milestones
    milestones = retention_results.get("competitor_milestones", [])
    if milestones:
        parts.append("\n\n🎯 **Competitor Milestones:**")
        for m in milestones[:3]:
            emoji = {"approval": "✅", "phase3_success": "📈", "phase3_failure": "❌", "btd": "⭐", "acquisition": "💼"}.get(m.get("event_type", ""), "•")
            parts.append(f"\n  {emoji} {m.get('company', '')} — {m.get('description', '')}")

    # Signal delta
    delta = retention_results.get("signal_delta", {})
    new_count = delta.get("new_in_30_days", 0)
    if new_count > 0:
        parts.append(f"\n\n📊 **Signal Index:** {new_count} new demand signals in the last 30 days ({delta.get('source_summary', '')})")

    return "\n".join(parts)
