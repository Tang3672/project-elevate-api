"""
Market Sizing Override Repository
=================================
Persists a PI's own market-sizing assumptions so an adjusted TAM STICKS to a
report instead of resetting on reload.

One row per (report_id, segment_id, user_id): the PI's latest edit set for that
segment on that report. Re-saving replaces it (upsert). Stores both the raw
edits (so the UI can re-render the exact funnel the PI built) and a snapshot of
the resulting TAM/SAM/SOM (so lists/dashboards don't have to recompute).

Best-effort writes: a persistence failure must never break recompute delivery —
the recomputed result is already returned to the caller in-memory.

Pattern: same asyncpg / CREATE TABLE IF NOT EXISTS convention as
market_sizing_repository.py.
"""

import json
import logging
from typing import Optional, List

logger = logging.getLogger(__name__)


async def init_market_sizing_override_tables():
    """Create the market_sizing_override table if it doesn't exist."""
    from app.db.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS market_sizing_override (
                id                SERIAL PRIMARY KEY,
                report_id         TEXT    NOT NULL,
                segment_id        INTEGER NOT NULL,
                user_id           INTEGER,
                label             TEXT,
                net_price_usd     DOUBLE PRECISION,
                overrides         JSONB   DEFAULT '{}',
                added_gates       JSONB   DEFAULT '[]',
                removed_gates     JSONB   DEFAULT '[]',
                extra_segment_ids JSONB   DEFAULT '[]',
                tam_usd           DOUBLE PRECISION,
                sam_usd           DOUBLE PRECISION,
                som_usd           DOUBLE PRECISION,
                created_at        TIMESTAMPTZ DEFAULT NOW(),
                updated_at        TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        # One saved edit set per (report, segment, user). NULL user_id (anonymous)
        # is handled with a partial-unique pair so COALESCE isn't needed at write.
        await conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS mso_report_seg_user_idx
                ON market_sizing_override (report_id, segment_id, user_id)
                WHERE user_id IS NOT NULL
        """)
        await conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS mso_report_seg_anon_idx
                ON market_sizing_override (report_id, segment_id)
                WHERE user_id IS NULL
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS mso_report_idx ON market_sizing_override (report_id)")
    logger.info("market_sizing_override table ready")


async def save_override(
    *,
    report_id: str,
    segment_id: int,
    user_id: Optional[int],
    net_price_usd: float,
    overrides: dict,
    added_gates: list,
    removed_gates: list,
    extra_segment_ids: list,
    tam_usd: Optional[float] = None,
    sam_usd: Optional[float] = None,
    som_usd: Optional[float] = None,
    label: Optional[str] = None,
) -> Optional[int]:
    """
    Upsert the PI's edit set for (report_id, segment_id, user_id).
    Returns the row id, or None on failure. Best-effort: never raises.
    """
    # Two conflict targets because user_id can be NULL; pick the matching index.
    conflict = (
        "(report_id, segment_id, user_id)" if user_id is not None
        else "(report_id, segment_id)"
    )
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(f"""
                INSERT INTO market_sizing_override
                    (report_id, segment_id, user_id, label, net_price_usd,
                     overrides, added_gates, removed_gates, extra_segment_ids,
                     tam_usd, sam_usd, som_usd)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                ON CONFLICT {conflict} DO UPDATE SET
                    label             = EXCLUDED.label,
                    net_price_usd     = EXCLUDED.net_price_usd,
                    overrides         = EXCLUDED.overrides,
                    added_gates       = EXCLUDED.added_gates,
                    removed_gates     = EXCLUDED.removed_gates,
                    extra_segment_ids = EXCLUDED.extra_segment_ids,
                    tam_usd           = EXCLUDED.tam_usd,
                    sam_usd           = EXCLUDED.sam_usd,
                    som_usd           = EXCLUDED.som_usd,
                    updated_at        = NOW()
                RETURNING id
            """,
                report_id, segment_id, user_id, label, net_price_usd,
                json.dumps(overrides or {}), json.dumps(added_gates or []),
                json.dumps(removed_gates or []), json.dumps(extra_segment_ids or []),
                tam_usd, sam_usd, som_usd,
            )
            return row["id"] if row else None
    except Exception as e:
        logger.warning("save_override failed (non-fatal): %s", e)
        return None


async def get_override(
    report_id: str, segment_id: int, user_id: Optional[int] = None,
) -> Optional[dict]:
    """
    Return the saved edit set for (report_id, segment_id, user_id), or None.
    If user_id is given but no per-user row exists, falls back to an anonymous row.
    """
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = None
            if user_id is not None:
                row = await conn.fetchrow("""
                    SELECT * FROM market_sizing_override
                    WHERE report_id = $1 AND segment_id = $2 AND user_id = $3
                """, report_id, segment_id, user_id)
            if row is None:
                row = await conn.fetchrow("""
                    SELECT * FROM market_sizing_override
                    WHERE report_id = $1 AND segment_id = $2 AND user_id IS NULL
                """, report_id, segment_id)
            return _row_to_dict(row) if row else None
    except Exception as e:
        logger.warning("get_override failed (non-fatal): %s", e)
        return None


async def list_overrides_for_report(report_id: str) -> List[dict]:
    """Return every saved edit set attached to a report (all segments/users)."""
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM market_sizing_override
                WHERE report_id = $1
                ORDER BY updated_at DESC
            """, report_id)
            return [_row_to_dict(r) for r in rows]
    except Exception as e:
        logger.warning("list_overrides_for_report failed (non-fatal): %s", e)
        return []


async def delete_override(
    report_id: str, segment_id: int, user_id: Optional[int] = None,
) -> bool:
    """Delete a saved edit set (revert to model-generated sizing). Best-effort."""
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            if user_id is not None:
                res = await conn.execute("""
                    DELETE FROM market_sizing_override
                    WHERE report_id = $1 AND segment_id = $2 AND user_id = $3
                """, report_id, segment_id, user_id)
            else:
                res = await conn.execute("""
                    DELETE FROM market_sizing_override
                    WHERE report_id = $1 AND segment_id = $2 AND user_id IS NULL
                """, report_id, segment_id)
            return res.endswith(("1", "2", "3", "4", "5", "6", "7", "8", "9"))
    except Exception as e:
        logger.warning("delete_override failed (non-fatal): %s", e)
        return False


def _row_to_dict(row) -> dict:
    if row is None:
        return {}
    d = dict(row)
    for jsonb_field in ("overrides", "added_gates", "removed_gates", "extra_segment_ids"):
        if isinstance(d.get(jsonb_field), str):
            try:
                d[jsonb_field] = json.loads(d[jsonb_field])
            except Exception:
                d[jsonb_field] = None
    return d
