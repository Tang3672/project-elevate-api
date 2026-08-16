"""
Prompt Sessions Repository
==========================
Two tables that record what PIs submit and how they refine results.

prompt_submissions — one row per idea submitted for report generation.
interpret_sessions — one row per assumptions-refinement interaction.

Both are best-effort: writes never raise into the main report path.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def init_prompt_sessions_tables():
    from app.db.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS prompt_submissions (
                id              SERIAL PRIMARY KEY,
                user_id         INTEGER REFERENCES users(id) ON DELETE SET NULL,
                session_id      TEXT,
                idea_text       TEXT NOT NULL,
                product_name    TEXT,
                sub_expert_id   TEXT,
                report_id       TEXT,
                created_at      TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS ps_user_idx ON prompt_submissions (user_id)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS ps_report_idx ON prompt_submissions (report_id)
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS interpret_sessions (
                id                  SERIAL PRIMARY KEY,
                report_id           TEXT NOT NULL,
                user_id             INTEGER REFERENCES users(id) ON DELETE SET NULL,
                assumption_key      TEXT,
                original_value      JSONB,
                modified_value      JSONB,
                interpretation_text TEXT,
                created_at          TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS is_report_idx ON interpret_sessions (report_id)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS is_user_idx ON interpret_sessions (user_id)
        """)
    logger.info("prompt_sessions tables ready")


async def record_prompt_submission(
    *,
    idea_text: str,
    user_id: Optional[int] = None,
    session_id: Optional[str] = None,
    product_name: Optional[str] = None,
    sub_expert_id: Optional[str] = None,
    report_id: Optional[str] = None,
) -> Optional[int]:
    """Insert a prompt submission row. Returns the new row id, or None on error."""
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO prompt_submissions
                    (user_id, session_id, idea_text, product_name, sub_expert_id, report_id)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
            """, user_id, session_id, idea_text, product_name, sub_expert_id, report_id)
        return row["id"] if row else None
    except Exception as e:
        logger.warning("record_prompt_submission failed (non-fatal): %s", e)
        return None


async def link_submission_to_report(submission_id: int, report_id: str) -> None:
    """Back-fill report_id once report generation completes."""
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE prompt_submissions SET report_id = $1 WHERE id = $2",
                report_id, submission_id,
            )
    except Exception as e:
        logger.warning("link_submission_to_report failed (non-fatal): %s", e)


async def record_interpret_session(
    *,
    report_id: str,
    user_id: Optional[int] = None,
    assumption_key: Optional[str] = None,
    original_value=None,
    modified_value=None,
    interpretation_text: Optional[str] = None,
) -> Optional[int]:
    """Insert an interpret/assumption-refinement row. Returns the new row id, or None on error."""
    import json
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO interpret_sessions
                    (report_id, user_id, assumption_key, original_value, modified_value, interpretation_text)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
            """,
                report_id,
                user_id,
                assumption_key,
                json.dumps(original_value) if original_value is not None else None,
                json.dumps(modified_value) if modified_value is not None else None,
                interpretation_text,
            )
        return row["id"] if row else None
    except Exception as e:
        logger.warning("record_interpret_session failed (non-fatal): %s", e)
        return None


async def get_user_prompt_history(
    user_id: int,
    *,
    limit: int = 50,
) -> list[dict]:
    """Return recent prompt submissions for a user (newest first)."""
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, session_id, idea_text, product_name, sub_expert_id,
                       report_id, created_at
                FROM prompt_submissions
                WHERE user_id = $1
                ORDER BY created_at DESC
                LIMIT $2
            """, user_id, limit)
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("get_user_prompt_history failed (non-fatal): %s", e)
        return []


async def get_report_interpret_history(report_id: str) -> list[dict]:
    """Return all interpret sessions for a given report."""
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, user_id, assumption_key, original_value, modified_value,
                       interpretation_text, created_at
                FROM interpret_sessions
                WHERE report_id = $1
                ORDER BY created_at ASC
            """, report_id)
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("get_report_interpret_history failed (non-fatal): %s", e)
        return []
