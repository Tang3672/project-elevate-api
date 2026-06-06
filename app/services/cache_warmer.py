"""
Discovery Cache Warmer
======================
Pre-fetches CT.gov trial counts and FDA approval counts for all 309 diseases
in the universe so the discovery engine returns in <2s instead of ~56s.

Two-level persistence:
  L1 — in-process dicts: _TRIAL_COUNT_CACHE, _APPROVAL_COUNT_CACHE
       (imported from opportunity_scorer_v2; lost on restart)
  L2 — DB: disease_aggregate.competitor_trial_count, approved_drug_count
       (persists across restarts; read back into L1 at startup)

Startup flow (non-blocking):
  1. startup() calls asyncio.create_task(warm_discovery_cache())
  2. warm_discovery_cache() loads L2 → L1 first (instant if DB populated)
  3. Then fetches any missing diseases from live APIs with semaphore(8)
  4. Writes results back to L2

Subsequent restarts skip the 56s API phase entirely (DB hit → L1 loaded).
"""

import asyncio
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

_SEMAPHORE_LIMIT = 8      # max concurrent CT.gov requests
_CACHE_TTL_DB    = 86_400 * 7   # 7-day DB staleness threshold (seconds)


async def _load_from_db() -> tuple[dict[str, int], dict[str, int]]:
    """
    Load trial counts and approval counts from disease_aggregate into memory.
    Returns ({disease: trial_count}, {disease: approval_count}).
    """
    trial_counts:    dict[str, int] = {}
    approval_counts: dict[str, int] = {}
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT disease_label, competitor_trial_count, approved_drug_count,
                       last_refreshed
                FROM disease_aggregate
                WHERE competitor_trial_count IS NOT NULL
                   OR approved_drug_count IS NOT NULL
            """)
            now = time.time()
            for row in rows:
                label    = row["disease_label"]
                age_secs = (now - row["last_refreshed"].timestamp()
                            if row["last_refreshed"] else _CACHE_TTL_DB + 1)
                if age_secs < _CACHE_TTL_DB:
                    if row["competitor_trial_count"] is not None:
                        trial_counts[label] = int(row["competitor_trial_count"])
                    if row["approved_drug_count"] is not None:
                        approval_counts[label] = int(row["approved_drug_count"])
    except Exception as e:
        logger.warning("cache_warmer: DB load failed: %s", e)
    return trial_counts, approval_counts


async def _save_to_db(trial_counts: dict[str, int],
                      approval_counts: dict[str, int]) -> None:
    """Upsert fetched counts into disease_aggregate for persistence."""
    try:
        from app.db.database import get_pool
        from app.db.disease_aggregate import ensure_aggregate_table
        pool = await get_pool()
        async with pool.acquire() as conn:
            await ensure_aggregate_table()
            for disease, count in trial_counts.items():
                await conn.execute("""
                    INSERT INTO disease_aggregate (disease_label, competitor_trial_count, last_refreshed)
                    VALUES ($1, $2, NOW())
                    ON CONFLICT (disease_label) DO UPDATE SET
                        competitor_trial_count = EXCLUDED.competitor_trial_count,
                        last_refreshed = NOW()
                """, disease, count)
            for disease, count in approval_counts.items():
                await conn.execute("""
                    INSERT INTO disease_aggregate (disease_label, approved_drug_count, last_refreshed)
                    VALUES ($1, $2, NOW())
                    ON CONFLICT (disease_label) DO UPDATE SET
                        approved_drug_count = EXCLUDED.approved_drug_count,
                        last_refreshed = NOW()
                """, disease, count)
    except Exception as e:
        logger.warning("cache_warmer: DB save failed: %s", e)


def _populate_l1_caches(trial_counts: dict[str, int],
                         approval_counts: dict[str, int]) -> None:
    """Push loaded counts into the in-process scorer caches (L1)."""
    try:
        from app.services.opportunity_scorer_v2 import (
            _TRIAL_COUNT_CACHE, _APPROVAL_COUNT_CACHE, _CACHE_TTL
        )
        now = time.monotonic()
        for disease, count in trial_counts.items():
            _TRIAL_COUNT_CACHE[disease] = (count, now)
        for disease, count in approval_counts.items():
            _APPROVAL_COUNT_CACHE[disease] = (count, now)
        logger.info("cache_warmer: L1 populated — %d trial, %d approval counts",
                    len(trial_counts), len(approval_counts))
    except Exception as e:
        logger.warning("cache_warmer: L1 populate failed: %s", e)


async def _fetch_trial_count_throttled(
    semaphore: asyncio.Semaphore,
    disease: str,
    ta: str,
) -> tuple[str, Optional[int]]:
    """Fetch one disease's trial count under the shared semaphore."""
    async with semaphore:
        try:
            from app.services.opportunity_scorer_v2 import _fetch_live_trial_count
            count = await _fetch_live_trial_count(disease, ta)
            return disease, count
        except Exception as e:
            logger.debug("cache_warmer: trial fetch failed for '%s': %s", disease, e)
            return disease, None


async def _fetch_approval_count_throttled(
    semaphore: asyncio.Semaphore,
    disease: str,
    static_fallback: int,
) -> tuple[str, Optional[int]]:
    """Fetch one disease's FDA approval count under the shared semaphore."""
    async with semaphore:
        try:
            from app.services.opportunity_scorer_v2 import _fetch_live_approval_count
            count = await _fetch_live_approval_count(disease, static_fallback)
            return disease, count
        except Exception as e:
            logger.debug("cache_warmer: approval fetch failed for '%s': %s", disease, e)
            return disease, None


async def warm_discovery_cache(force_refresh: bool = False) -> dict:
    """
    Main entry point. Call with asyncio.create_task() at startup.

    1. Load from DB → L1  (fast path; skips live API if DB is fresh)
    2. Identify missing/stale diseases
    3. Fetch missing from live APIs (semaphore-throttled, non-blocking)
    4. Save back to DB + L1

    Returns summary dict.
    """
    t_start = time.monotonic()
    logger.info("cache_warmer: starting discovery cache warm-up (force=%s)", force_refresh)

    # Step 1: Load from DB
    db_trials, db_approvals = await _load_from_db()

    if not force_refresh:
        _populate_l1_caches(db_trials, db_approvals)

    # Step 2: Identify diseases needing live fetch
    from app.services.universe_builder import get_universe
    universe = get_universe()   # 309 diseases

    missing_trial    = [(d, ta, approved) for d, ta, _, approved, *_ in universe
                        if force_refresh or d not in db_trials]
    missing_approval = [(d, approved) for d, _, _, approved, *_ in universe
                        if force_refresh or d not in db_approvals]

    logger.info("cache_warmer: %d/%d diseases need live trial fetch, "
                "%d/%d need approval fetch",
                len(missing_trial), len(universe),
                len(missing_approval), len(universe))

    if not missing_trial and not missing_approval:
        logger.info("cache_warmer: all %d diseases already cached (%.1fs)",
                    len(universe), time.monotonic() - t_start)
        return {"status": "cached", "diseases": len(universe), "fetched": 0}

    # Step 3: Throttled live fetches
    sem = asyncio.Semaphore(_SEMAPHORE_LIMIT)

    trial_tasks    = [_fetch_trial_count_throttled(sem, d, ta)
                      for d, ta, _ in missing_trial]
    approval_tasks = [_fetch_approval_count_throttled(sem, d, fb)
                      for d, fb in missing_approval]

    trial_results    = await asyncio.gather(*trial_tasks,    return_exceptions=True)
    approval_results = await asyncio.gather(*approval_tasks, return_exceptions=True)

    new_trials    = {d: c for d, c in trial_results
                     if not isinstance((d,c), Exception) and c is not None}
    new_approvals = {d: c for d, c in approval_results
                     if not isinstance((d,c), Exception) and c is not None}

    # Step 4: Merge and persist
    merged_trials    = {**db_trials,    **new_trials}
    merged_approvals = {**db_approvals, **new_approvals}

    _populate_l1_caches(merged_trials, merged_approvals)
    await _save_to_db(new_trials, new_approvals)

    elapsed = time.monotonic() - t_start
    logger.info(
        "cache_warmer: complete — %d trial + %d approval counts cached in %.1fs",
        len(merged_trials), len(merged_approvals), elapsed,
    )
    return {
        "status":            "warmed",
        "diseases_in_universe": len(universe),
        "trial_from_db":     len(db_trials),
        "trial_fetched":     len(new_trials),
        "approval_from_db":  len(db_approvals),
        "approval_fetched":  len(new_approvals),
        "elapsed_seconds":   round(elapsed, 1),
    }
