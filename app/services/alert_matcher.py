"""
Alert Matcher
=============
Compares newly ingested demand signals against all user watchlists
and creates alerts when matches are found.

Matching strategy (two-pass):
  1. Keyword match — fast, catches obvious domain matches
  2. Semantic similarity — embedding cosine similarity >= 0.65

Alert types and severity:
  - fda_recall:      HIGH   (active safety failure in their area)
  - fda_adverse:     MEDIUM (safety signal trending up)
  - clinical_trial:  MEDIUM (new competitor or validation trial)
  - disease_burden:  LOW    (new epidemiological data)
  - hrsa_shortage:   MEDIUM (new care access gap)
  - funding:         HIGH   (new funding opportunity — time-sensitive)
  - competitor:      HIGH   (competitor drug approved or failed)
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Tuple

from app.db.database import get_pool
from app.db.watchlist_repository import (
    get_all_watchlists_for_matching, create_alert,
    alert_already_exists, update_last_checked
)
from app.services.embedding_service import embed_text
from app.services.expert_profiles import EXPERT_REGISTRY

logger = logging.getLogger(__name__)

# Minimum similarity score to trigger an alert
MIN_SIMILARITY = 0.65

# Signal type → alert type + severity mapping
SIGNAL_ALERT_MAP = {
    "fda_recalls":          ("fda_recall",     "high"),
    "fda_adverse_events":   ("fda_adverse",    "medium"),
    "fda_device_events":    ("fda_adverse",    "medium"),
    "clinical_trials":      ("clinical_trial", "medium"),
    "cdc_places":           ("disease_burden", "low"),
    "cdc_fluview":          ("disease_burden", "low"),
    "cdc_wastewater":       ("disease_burden", "medium"),
    "census_sahie":         ("disease_burden", "low"),
    "cms_hospital_quality": ("disease_burden", "low"),
    "hrsa_shortage":        ("hrsa_shortage",  "medium"),
}

# Alert type display labels for email/UI
ALERT_TYPE_LABELS = {
    "fda_recall":      "⚠ FDA Recall",
    "fda_adverse":     "🔴 Safety Signal",
    "clinical_trial":  "🧪 New Trial",
    "disease_burden":  "📊 Burden Update",
    "hrsa_shortage":   "🏥 Shortage Area",
    "funding":         "💰 Funding Opportunity",
    "competitor":      "⚡ Competitor Activity",
}


async def run_weekly_match() -> Dict:
    """
    Main entry point for the weekly alert job.
    Fetches signals from the past 7 days and matches against all watchlists.
    Returns a summary of alerts created.
    """
    logger.info("Starting weekly alert matching run...")
    cutoff = datetime.utcnow() - timedelta(days=7)

    # Get all signals from the past 7 days
    new_signals = await _get_recent_signals(cutoff)
    logger.info(f"Found {len(new_signals)} new signals in past 7 days")

    # Get all watchlists
    watchlists = await get_all_watchlists_for_matching()
    logger.info(f"Matching against {len(watchlists)} watchlists")

    total_alerts = 0
    skipped      = 0

    for watchlist in watchlists:
        wid    = watchlist['id']
        uid    = watchlist['user_id']
        desc   = watchlist['product_description']
        domain = watchlist['disease_domain']
        kws    = [k.lower() for k in (watchlist['keywords'] or [])]

        # Get expert keywords for this domain
        expert_kws = []
        if domain in EXPERT_REGISTRY:
            expert_kws = [k.lower() for k in EXPERT_REGISTRY[domain].router_keywords]

        # Embed the watchlist description (for semantic matching)
        try:
            desc_embedding = await embed_text(desc)
        except Exception as e:
            logger.warning(f"Embedding failed for watchlist {wid}: {e}")
            desc_embedding = None

        # Filter out irrelevant signal types for this domain
        filtered_signals = new_signals
        if domain == "antibiotic_amr":
            # CDC PLACES (county chronic disease) is not relevant to antibiotics
            filtered_signals = [s for s in new_signals
                                if s.get('source') not in ('cdc_places', 'census_sahie', 'cms_hospital_quality')]

        for signal in filtered_signals:
            # Skip if already alerted for this signal
            if await alert_already_exists(wid, signal['id']):
                skipped += 1
                continue

            # Check relevance
            match, reason = _is_relevant(
                signal, desc, kws, expert_kws, desc_embedding
            )
            if not match:
                continue

            # Create alert
            source       = signal.get('source', '')
            alert_type, severity = SIGNAL_ALERT_MAP.get(source, ('disease_burden', 'low'))

            # Upgrade severity for high-value signals
            if signal.get('signal_type') == 'safety_failure':
                severity = 'high'

            title   = _build_alert_title(signal, alert_type)
            summary = _build_alert_summary(signal, reason, watchlist['name'])

            await create_alert(
                watchlist_id = wid,
                user_id      = uid,
                alert_type   = alert_type,
                title        = title,
                summary      = summary,
                severity     = severity,
                source       = source,
                source_url   = _get_source_url(source),
                signal_id    = signal['id'],
            )
            total_alerts += 1

        await update_last_checked(wid)

    logger.info(f"Weekly match complete: {total_alerts} alerts created, {skipped} duplicates skipped")
    return {
        "signals_checked":  len(new_signals),
        "watchlists_checked": len(watchlists),
        "alerts_created":   total_alerts,
        "duplicates_skipped": skipped,
        "run_at":           datetime.utcnow().isoformat(),
    }


def _is_relevant(
    signal:         dict,
    description:    str,
    user_keywords:  List[str],
    expert_keywords: List[str],
    desc_embedding: List[float] = None,
) -> Tuple[bool, str]:
    """
    Two-pass relevance check.
    Returns (is_relevant, reason_string).
    """
    signal_text = f"{signal.get('title', '')} {signal.get('description', '')}".lower()

    # Pass 1: keyword match against user keywords
    for kw in user_keywords:
        if kw in signal_text and len(kw) >= 4:
            return True, f"Keyword match: '{kw}'"

    # Pass 2: keyword match against expert domain keywords
    expert_matches = [kw for kw in expert_keywords[:15] if kw in signal_text and len(kw) > 5]
    if len(expert_matches) >= 3:
        return True, f"Domain match: {', '.join(expert_matches[:3])}"

    # Pass 3: semantic similarity (if embedding available)
    if desc_embedding and signal.get('embedding'):
        try:
            sim = _cosine_similarity(desc_embedding, signal['embedding'])
            if sim >= MIN_SIMILARITY:
                return True, f"Semantic similarity: {sim:.2f}"
        except Exception:
            pass

    return False, ""


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Fast cosine similarity between two vectors."""
    dot   = sum(x * y for x, y in zip(a, b))
    mag_a = sum(x * x for x in a) ** 0.5
    mag_b = sum(x * x for x in b) ** 0.5
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def _build_alert_title(signal: dict, alert_type: str) -> str:
    label = ALERT_TYPE_LABELS.get(alert_type, "New Signal")
    title = signal.get('title', 'New signal detected')
    return f"{label}: {title[:120]}"


def _build_alert_summary(signal: dict, match_reason: str, watchlist_name: str) -> str:
    desc = signal.get('description', '')[:300]
    loc  = signal.get('location_name') or signal.get('state_code') or 'National'
    mag  = signal.get('magnitude')
    unit = signal.get('magnitude_unit', '')
    mag_str = f" ({mag:,.0f} {unit})" if mag else ""
    return (
        f"Relevant to your watchlist '{watchlist_name}'. "
        f"{desc}{mag_str} "
        f"[{loc}] "
        f"Match: {match_reason}"
    ).strip()


SOURCE_URLS = {
    "fda_adverse_events":   "https://open.fda.gov/apis/drug/event/",
    "fda_device_events":    "https://open.fda.gov/apis/device/event/",
    "fda_recalls":          "https://open.fda.gov/apis/drug/enforcement/",
    "clinical_trials":      "https://clinicaltrials.gov/",
    "cdc_places":           "https://www.cdc.gov/places/",
    "census_sahie":         "https://www.census.gov/data/datasets/time-series/demo/sahie/",
    "cms_hospital_quality": "https://www.medicare.gov/care-compare/",
    "hrsa_shortage":        "https://data.hrsa.gov/tools/shortage-area/hpsa-find",
    "cdc_wastewater":       "https://www.cdc.gov/nwss/",
    "cdc_fluview":          "https://www.cdc.gov/flu/weekly/",
}


def _get_source_url(source: str) -> str:
    return SOURCE_URLS.get(source, "")


async def _get_recent_signals(since: datetime) -> List[dict]:
    """Fetch signals ingested since the cutoff date."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, source, signal_type, title, description,
                   magnitude, magnitude_unit, location_name, state_code,
                   geographic_scope, fetched_at
            FROM demand_signals
            WHERE fetched_at >= $1
            ORDER BY fetched_at DESC
            LIMIT 5000
            """,
            since
        )
        return [dict(r) for r in rows]
