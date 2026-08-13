"""
Override Ledger Repository  (v3 Part F)
========================================
Aggregated, cross-report store of expert corrections to model-generated market
sizing assumptions.  Unlike market_sizing_override (which persists per-report
edits so they reload), this table is the training-data accumulation layer:

  - Every time a user saves a step correction via the waterfall UI, we append
    one row per corrected step to override_ledger.
  - Rows are never updated after insert (append-only audit log).
  - The report_id is stored as a SHA-256 hash prefix so rows can be deduped
    across refreshes without exposing raw report identifiers.
  - Aggregates (median ratio, count) are the output surface: they tell you
    which model steps are systematically over- or under-estimated and by how much.

Schema note: uses PERCENTILE_CONT which requires asyncpg with PostgreSQL 9.4+.
All writes are best-effort (non-fatal); failures are logged and ignored.

Usage:
    from app.db import override_ledger_repository as _ledger
    await _ledger.init_override_ledger_table()
    await _ledger.append_corrections(step_overrides, rationale, report_id)
    stats = await _ledger.get_stats()
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def init_override_ledger_table() -> None:
    """Create the override_ledger table if it doesn't exist."""
    from app.db.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS override_ledger (
                id           SERIAL PRIMARY KEY,
                step_label   TEXT              NOT NULL,
                step_role    TEXT,                         -- TAM / SAM / SOM
                orig_value   DOUBLE PRECISION  NOT NULL,
                new_value    DOUBLE PRECISION  NOT NULL,
                ratio        DOUBLE PRECISION  NOT NULL,   -- new_value / orig_value
                rationale    TEXT,
                report_hash  TEXT,                         -- SHA-256[:8] of report_id for audit
                captured_at  TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS ovl_step_label_idx ON override_ledger (step_label)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS ovl_captured_at_idx ON override_ledger (captured_at DESC)"
        )
    logger.info("override_ledger table ready")


async def append_corrections(
    step_overrides: dict,
    rationale: Optional[str] = None,
    report_id: Optional[str] = None,
) -> int:
    """
    Append one row per corrected step to override_ledger.

    step_overrides: {step_label: {"orig": float, "override": float, "role": str}}
    Returns the number of rows inserted (0 on failure).
    Best-effort: never raises.

    Only inserts rows where:
    - orig_value > 0 (avoid division by zero in ratio)
    - new_value > 0 (user set a real value, not zeroed out)
    - new_value != orig_value (an actual change, not a no-op save)
    """
    if not step_overrides:
        return 0

    report_hash = hashlib.sha256((report_id or "").encode()).hexdigest()[:8] if report_id else None
    rat = (rationale or "")[:500] or None

    rows: list[tuple] = []
    for label, vals in step_overrides.items():
        if not isinstance(vals, dict):
            continue
        orig = vals.get("orig")
        new = vals.get("override")
        role = vals.get("role") or None
        if orig is None or new is None:
            continue
        try:
            orig_f = float(orig)
            new_f  = float(new)
        except (TypeError, ValueError):
            continue
        if orig_f <= 0 or new_f <= 0 or abs(new_f - orig_f) < 1e-9:
            continue
        ratio = new_f / orig_f
        rows.append((str(label)[:300], role, orig_f, new_f, ratio, rat, report_hash))

    if not rows:
        return 0

    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.executemany(
                """
                INSERT INTO override_ledger
                    (step_label, step_role, orig_value, new_value, ratio, rationale, report_hash)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                rows,
            )
        logger.info("override_ledger: appended %d corrections (report_hash=%s)", len(rows), report_hash)
        return len(rows)
    except Exception as exc:
        logger.warning("override_ledger: append failed (non-fatal): %s", exc)
        return 0


async def get_stats(
    step_label: Optional[str] = None,
    min_corrections: int = 3,
    limit: int = 50,
) -> list[dict]:
    """
    Return aggregated correction statistics, optionally filtered to one step.

    Each row: {step_label, step_role, correction_count, median_ratio,
               p25_ratio, p75_ratio, last_correction_at}

    Only returns steps with at least `min_corrections` corrections.
    Sorted by correction_count DESC.

    Returns [] on any DB error.
    """
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            where = "WHERE orig_value > 0 AND new_value > 0"
            params: list = []
            if step_label:
                where += " AND step_label = $1"
                params.append(step_label)

            rows = await conn.fetch(f"""
                SELECT
                    step_label,
                    step_role,
                    COUNT(*)                                                 AS correction_count,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ratio)      AS median_ratio,
                    PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY ratio)     AS p25_ratio,
                    PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY ratio)     AS p75_ratio,
                    MAX(captured_at)                                         AS last_correction_at
                FROM override_ledger
                {where}
                GROUP BY step_label, step_role
                HAVING COUNT(*) >= {min_corrections}
                ORDER BY correction_count DESC
                LIMIT {limit}
            """, *params)
            return [dict(r) for r in rows]
    except Exception as exc:
        logger.warning("override_ledger: get_stats failed (non-fatal): %s", exc)
        return []


async def get_recent_rationales(step_label: str, limit: int = 5) -> list[str]:
    """
    Return the most recent non-empty rationale strings for a step.
    Used to surface expert reasoning alongside the aggregated stats.
    """
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT rationale FROM override_ledger
                WHERE step_label = $1
                  AND rationale IS NOT NULL
                  AND rationale != ''
                ORDER BY captured_at DESC
                LIMIT $2
            """, step_label, limit)
            return [r["rationale"] for r in rows]
    except Exception as exc:
        logger.warning("override_ledger: get_recent_rationales failed (non-fatal): %s", exc)
        return []


async def count_total_corrections() -> int:
    """Return total correction count across all steps. Used for health checks."""
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS n FROM override_ledger WHERE orig_value > 0 AND new_value > 0"
            )
            return int(row["n"]) if row else 0
    except Exception as exc:
        logger.warning("override_ledger: count_total_corrections failed: %s", exc)
        return 0
