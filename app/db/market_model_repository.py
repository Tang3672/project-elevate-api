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
    await init_override_events_table()
    logger.info("market_model_version table ready")


async def init_nl_assumptions_table() -> None:
    """Create the table that persists NL-parsed market model assumption ops."""
    from app.db.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS market_nl_assumptions (
                id          TEXT PRIMARY KEY,
                report_id   TEXT    NOT NULL,
                op          TEXT    NOT NULL,
                target      TEXT,
                value       DOUBLE PRECISION,
                label       TEXT,
                quoted_span TEXT,
                confidence  DOUBLE PRECISION,
                created_at  TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS mnla_report_idx ON market_nl_assumptions (report_id, created_at)")
    logger.info("market_nl_assumptions table ready")


async def save_nl_assumption(report_id: str, assumption: dict) -> None:
    from app.db.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO market_nl_assumptions
                (id, report_id, op, target, value, label, quoted_span, confidence)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (id) DO NOTHING
        """,
            assumption["id"], report_id,
            assumption["op"],
            assumption.get("target"),
            float(assumption["value"]) if assumption.get("value") is not None else None,
            assumption.get("label"),
            assumption.get("quoted_span"),
            float(assumption["confidence"]) if assumption.get("confidence") is not None else None,
        )


async def list_nl_assumptions(report_id: str) -> list:
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, op, target, value, label, quoted_span, confidence
                FROM market_nl_assumptions
                WHERE report_id = $1
                ORDER BY created_at ASC
            """, report_id)
            return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("list_nl_assumptions failed: %s", e)
        return []


async def delete_nl_assumption(report_id: str, assumption_id: str) -> None:
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                DELETE FROM market_nl_assumptions WHERE id = $1 AND report_id = $2
            """, assumption_id, report_id)
    except Exception as e:
        logger.warning("delete_nl_assumption failed (non-fatal): %s", e)


async def init_override_events_table() -> None:
    from app.db.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS override_events (
                id                   TEXT PRIMARY KEY,
                report_id            TEXT NOT NULL,
                node_id              TEXT NOT NULL,
                original_value       DOUBLE PRECISION,
                new_value            DOUBLE PRECISION,
                ratio                DOUBLE PRECISION,
                rationale            TEXT,
                downstream_delta_pct DOUBLE PRECISION,
                user_id              TEXT,
                created_at           TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS oe_report_idx ON override_events (report_id)")


async def insert_override_event(
    report_id: str,
    node_id: str,
    original_value: float,
    new_value: float,
    rationale: str,
    user_id: str,
    downstream_delta_pct: Optional[float] = None,
) -> None:
    import uuid as _uuid
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        ratio = (new_value / original_value) if original_value and abs(original_value) > 1e-9 else None
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO override_events
                    (id, report_id, node_id, original_value, new_value, ratio,
                     rationale, downstream_delta_pct, user_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """, str(_uuid.uuid4()), report_id, node_id,
                original_value, new_value, ratio, rationale, downstream_delta_pct, user_id)
    except Exception as e:
        logger.warning("insert_override_event failed (non-fatal): %s", e)


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
