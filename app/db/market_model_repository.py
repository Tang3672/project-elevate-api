"""
Market Model Version Repository — Part C
=========================================
Stores immutable snapshots of the research-tool buyer model so users can
edit individual nodes (population, spend, SAM rate, SOM rate) and see a diff
against the engine-generated baseline.

Each edit produces a new row (version). The model is forked, never mutated.
The baseline (version 1) is written once when the report is generated.
"""

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def init_market_model_table() -> None:
    from app.db.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS market_model_version (
                id             SERIAL PRIMARY KEY,
                report_id      TEXT    NOT NULL,
                version        INTEGER NOT NULL DEFAULT 1,
                parent_version INTEGER,
                user_id        INTEGER,
                nodes          JSONB   NOT NULL,
                rationale      TEXT,
                created_at     TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (report_id, version)
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS mmv_report_idx ON market_model_version (report_id)")
    logger.info("market_model_version table ready")


async def save_baseline(report_id: str, nodes: dict) -> int:
    """Write version 1 from the engine-generated derivation. Idempotent."""
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO market_model_version (report_id, version, parent_version, nodes, rationale)
                VALUES ($1, 1, NULL, $2, 'Engine-generated baseline')
                ON CONFLICT (report_id, version) DO NOTHING
                RETURNING version
            """, report_id, json.dumps(nodes))
            return 1
    except Exception as e:
        logger.warning("save_baseline failed (non-fatal): %s", e)
        return 1


async def save_edit(
    report_id: str,
    parent_version: int,
    nodes: dict,
    rationale: str,
    user_id: Optional[int],
) -> int:
    """Fork the model: increment version, persist new nodes. Returns new version."""
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            next_ver = await conn.fetchval("""
                SELECT COALESCE(MAX(version), 0) + 1 FROM market_model_version WHERE report_id = $1
            """, report_id)
            await conn.execute("""
                INSERT INTO market_model_version (report_id, version, parent_version, user_id, nodes, rationale)
                VALUES ($1, $2, $3, $4, $5, $6)
            """, report_id, next_ver, parent_version, user_id,
                json.dumps(nodes), rationale or "User edit")
            return next_ver
    except Exception as e:
        logger.warning("save_edit failed (non-fatal): %s", e)
        return parent_version + 1


async def get_version(report_id: str, version: int) -> Optional[dict]:
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM market_model_version WHERE report_id = $1 AND version = $2
            """, report_id, version)
            return _row(row)
    except Exception as e:
        logger.warning("get_version failed: %s", e)
        return None


async def get_latest(report_id: str) -> Optional[dict]:
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM market_model_version WHERE report_id = $1 ORDER BY version DESC LIMIT 1
            """, report_id)
            return _row(row)
    except Exception as e:
        logger.warning("get_latest failed: %s", e)
        return None


async def list_versions(report_id: str) -> list:
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, report_id, version, parent_version, user_id, rationale, created_at
                FROM market_model_version WHERE report_id = $1 ORDER BY version ASC
            """, report_id)
            return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("list_versions failed: %s", e)
        return []


def _row(row) -> Optional[dict]:
    if row is None:
        return None
    d = dict(row)
    if isinstance(d.get("nodes"), str):
        try:
            d["nodes"] = json.loads(d["nodes"])
        except Exception:
            pass
    return d
