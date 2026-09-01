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


_IDEA_TEXT_MAX_CHARS = 8_000  # hard cap — keeps row size bounded as table grows


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
        # Time-range index — critical for admin pagination as the table grows
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS ps_created_at_idx ON prompt_submissions (created_at DESC)
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
        truncated = idea_text[:_IDEA_TEXT_MAX_CHARS]
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO prompt_submissions
                    (user_id, session_id, idea_text, product_name, sub_expert_id, report_id)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
            """, user_id, session_id, truncated, product_name, sub_expert_id, report_id)
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


async def admin_get_all_submissions(
    *,
    page: int = 1,
    per_page: int = 50,
    user_id: Optional[int] = None,
    sub_expert_id: Optional[str] = None,
    since: Optional[str] = None,   # ISO date string, e.g. "2025-01-01"
    until: Optional[str] = None,
) -> dict:
    """Admin-only: return all prompt submissions across all users, paginated.

    Joins users table to include email so you can identify who submitted what.
    Filters are all optional and stack (AND logic).
    """
    try:
        from app.db.database import get_pool
        pool = await get_pool()

        conditions = []
        params: list = []

        if user_id is not None:
            params.append(user_id)
            conditions.append(f"ps.user_id = ${len(params)}")
        if sub_expert_id is not None:
            params.append(sub_expert_id)
            conditions.append(f"ps.sub_expert_id = ${len(params)}")
        if since is not None:
            params.append(since)
            conditions.append(f"ps.created_at >= ${len(params)}::TIMESTAMPTZ")
        if until is not None:
            params.append(until)
            conditions.append(f"ps.created_at < ${len(params)}::TIMESTAMPTZ")

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        offset = (max(page, 1) - 1) * per_page
        params.extend([per_page, offset])

        async with pool.acquire() as conn:
            rows = await conn.fetch(f"""
                SELECT
                    ps.id,
                    ps.user_id,
                    u.email         AS user_email,
                    ps.session_id,
                    ps.idea_text,
                    ps.product_name,
                    ps.sub_expert_id,
                    ps.report_id,
                    ps.created_at
                FROM prompt_submissions ps
                LEFT JOIN users u ON u.id = ps.user_id
                {where}
                ORDER BY ps.created_at DESC
                LIMIT ${len(params) - 1} OFFSET ${len(params)}
            """, *params)

            total_row = await conn.fetchrow(f"""
                SELECT COUNT(*) AS total
                FROM prompt_submissions ps
                {where}
            """, *params[:-2])

        total = total_row["total"] if total_row else 0
        return {
            "total": total,
            "page": page,
            "per_page": per_page,
            "submissions": [dict(r) for r in rows],
        }
    except Exception as e:
        logger.warning("admin_get_all_submissions failed: %s", e)
        return {"total": 0, "page": page, "per_page": per_page, "submissions": []}


async def admin_get_submission_stats() -> dict:
    """Admin-only: aggregate stats — total rows, unique users, breakdown by sub_expert_id."""
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            total_row = await conn.fetchrow("SELECT COUNT(*) AS total FROM prompt_submissions")
            users_row = await conn.fetchrow(
                "SELECT COUNT(DISTINCT user_id) AS unique_users FROM prompt_submissions"
            )
            by_expert = await conn.fetch("""
                SELECT sub_expert_id, COUNT(*) AS cnt
                FROM prompt_submissions
                GROUP BY sub_expert_id
                ORDER BY cnt DESC
            """)
            by_day = await conn.fetch("""
                SELECT DATE_TRUNC('day', created_at) AS day, COUNT(*) AS cnt
                FROM prompt_submissions
                WHERE created_at >= NOW() - INTERVAL '30 days'
                GROUP BY 1
                ORDER BY 1 DESC
            """)
        return {
            "total_submissions": total_row["total"] if total_row else 0,
            "unique_users": users_row["unique_users"] if users_row else 0,
            "by_expert_type": [dict(r) for r in by_expert],
            "last_30_days_by_day": [dict(r) for r in by_day],
        }
    except Exception as e:
        logger.warning("admin_get_submission_stats failed: %s", e)
        return {}


async def get_report_interpret_history(report_id: str, *, requesting_user_id: Optional[int] = None) -> list[dict]:
    """Return all interpret sessions for a given report.

    If requesting_user_id is provided, verifies the user owns the report
    (has a prompt_submission row for it) before returning data.
    Pass requesting_user_id=None only from admin paths.
    """
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            if requesting_user_id is not None:
                owner_row = await conn.fetchrow(
                    "SELECT 1 FROM prompt_submissions WHERE report_id = $1 AND user_id = $2 LIMIT 1",
                    report_id, requesting_user_id,
                )
                if not owner_row:
                    return []  # not owner — return empty rather than 403 to avoid leaking report existence
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
