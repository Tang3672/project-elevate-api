"""
User Repository
===============
All database operations for users, saved reports, and saved drafts.
"""
import json
import logging
from typing import Optional, List

from app.db.database import get_pool
from app.models.user import (
    SavedReport, SavedReportSummary, SavedDraft, UserProfile
)

logger = logging.getLogger(__name__)


# ── Table Init ────────────────────────────────────────────────────────────────

async def init_user_tables():
    """Create users, pi_reports, and draft_ideas tables if they don't exist."""
    pool = await get_pool()
    async with pool.acquire() as conn:

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id           SERIAL PRIMARY KEY,
                email        VARCHAR(200) UNIQUE NOT NULL,
                password_hash VARCHAR(500),        -- null for Google-only accounts
                google_id    VARCHAR(200) UNIQUE,  -- null for email-only accounts
                name         VARCHAR(100),
                created_at   TIMESTAMPTZ DEFAULT NOW(),
                updated_at   TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS users_email_idx ON users (email)
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS pi_reports (
                id           SERIAL PRIMARY KEY,
                user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name         VARCHAR(200) NOT NULL,
                product_type VARCHAR(50)  NOT NULL,
                idea         TEXT         NOT NULL,
                pathogen     VARCHAR(200),
                report_data  JSONB        NOT NULL,
                created_at   TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS pi_reports_user_idx ON pi_reports (user_id)
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS draft_ideas (
                id           SERIAL PRIMARY KEY,
                user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name         VARCHAR(200) NOT NULL,
                product_type VARCHAR(50)  NOT NULL DEFAULT 'antibiotic',
                idea         TEXT         NOT NULL DEFAULT '',
                pathogen     VARCHAR(200),
                created_at   TIMESTAMPTZ DEFAULT NOW(),
                updated_at   TIMESTAMPTZ DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS drafts_user_idx ON draft_ideas (user_id)
        """)

    logger.info("✅ User tables initialized")


# ── Users ─────────────────────────────────────────────────────────────────────

async def create_user(
    email: str,
    password_hash: Optional[str] = None,
    google_id:     Optional[str] = None,
    name:          Optional[str] = None,
) -> Optional[dict]:
    """Create a new user. Returns user dict or None if email already exists."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """
                INSERT INTO users (email, password_hash, google_id, name)
                VALUES ($1, $2, $3, $4)
                RETURNING id, email, name, created_at
                """,
                email.lower().strip(), password_hash, google_id, name
            )
            return dict(row)
        except Exception as e:
            if 'unique' in str(e).lower():
                return None
            raise


async def get_user_by_email(email: str) -> Optional[dict]:
    """Fetch a user by email."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, email, password_hash, google_id, name, created_at FROM users WHERE email = $1",
            email.lower().strip()
        )
        return dict(row) if row else None


async def get_user_by_id(user_id: int) -> Optional[dict]:
    """Fetch a user by ID."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, email, name, created_at FROM users WHERE id = $1",
            user_id
        )
        return dict(row) if row else None


async def get_user_by_google_id(google_id: str) -> Optional[dict]:
    """Fetch a user by Google ID."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, email, name, created_at FROM users WHERE google_id = $1",
            google_id
        )
        return dict(row) if row else None


async def update_user_google_id(user_id: int, google_id: str):
    """Link a Google account to an existing user."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET google_id = $1, updated_at = NOW() WHERE id = $2",
            google_id, user_id
        )


# ── Saved Reports ─────────────────────────────────────────────────────────────

async def save_report(
    user_id:      int,
    name:         str,
    product_type: str,
    idea:         str,
    report_data:  dict,
    pathogen:     Optional[str] = None,
) -> SavedReport:
    """Save a PI report for a user."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO pi_reports (user_id, name, product_type, idea, pathogen, report_data)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id, user_id, name, product_type, idea, pathogen, report_data, created_at
            """,
            user_id, name, product_type, idea, pathogen, json.dumps(report_data)
        )
        return SavedReport(
            report_id    = row['id'],
            user_id      = row['user_id'],
            name         = row['name'],
            product_type = row['product_type'],
            idea         = row['idea'],
            pathogen     = row['pathogen'],
            report_data  = json.loads(row['report_data']) if isinstance(row['report_data'], str) else dict(row['report_data']),
            created_at   = row['created_at'],
        )


async def get_user_reports(user_id: int) -> List[SavedReportSummary]:
    """Get all saved reports for a user (summaries only, no full report_data)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, name, product_type, idea, pathogen, created_at
            FROM pi_reports
            WHERE user_id = $1
            ORDER BY created_at DESC
            """,
            user_id
        )
        return [SavedReportSummary(
            report_id    = r['id'],
            name         = r['name'],
            product_type = r['product_type'],
            idea         = r['idea'],
            pathogen     = r['pathogen'],
            created_at   = r['created_at'],
        ) for r in rows]


async def get_report_by_id(report_id: int, user_id: int) -> Optional[SavedReport]:
    """Get a full saved report by ID (verifies ownership)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, user_id, name, product_type, idea, pathogen, report_data, created_at
            FROM pi_reports
            WHERE id = $1 AND user_id = $2
            """,
            report_id, user_id
        )
        if not row:
            return None
        return SavedReport(
            report_id    = row['id'],
            user_id      = row['user_id'],
            name         = row['name'],
            product_type = row['product_type'],
            idea         = row['idea'],
            pathogen     = row['pathogen'],
            report_data  = json.loads(row['report_data']) if isinstance(row['report_data'], str) else dict(row['report_data']),
            created_at   = row['created_at'],
        )


async def delete_report(report_id: int, user_id: int) -> bool:
    """Delete a report (verifies ownership). Returns True if deleted."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM pi_reports WHERE id = $1 AND user_id = $2",
            report_id, user_id
        )
        return result == "DELETE 1"


async def rename_report(report_id: int, user_id: int, name: str) -> bool:
    """Rename a saved report."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE pi_reports SET name = $1 WHERE id = $2 AND user_id = $3",
            name, report_id, user_id
        )
        return result == "UPDATE 1"


# ── Drafts ────────────────────────────────────────────────────────────────────

async def save_draft(
    user_id:      int,
    name:         str,
    product_type: str = "antibiotic",
    idea:         str = "",
    pathogen:     Optional[str] = None,
) -> SavedDraft:
    """Save or update a draft idea."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO draft_ideas (user_id, name, product_type, idea, pathogen)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id, user_id, name, product_type, idea, pathogen, created_at, updated_at
            """,
            user_id, name, product_type, idea, pathogen
        )
        return SavedDraft(
            draft_id     = row['id'],
            user_id      = row['user_id'],
            name         = row['name'],
            product_type = row['product_type'],
            idea         = row['idea'],
            pathogen     = row['pathogen'],
            created_at   = row['created_at'],
            updated_at   = row['updated_at'],
        )


async def get_user_drafts(user_id: int) -> List[SavedDraft]:
    """Get all drafts for a user."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, user_id, name, product_type, idea, pathogen, created_at, updated_at
            FROM draft_ideas
            WHERE user_id = $1
            ORDER BY updated_at DESC
            """,
            user_id
        )
        return [SavedDraft(
            draft_id     = r['id'],
            user_id      = r['user_id'],
            name         = r['name'],
            product_type = r['product_type'],
            idea         = r['idea'],
            pathogen     = r['pathogen'],
            created_at   = r['created_at'],
            updated_at   = r['updated_at'],
        ) for r in rows]


async def delete_draft(draft_id: int, user_id: int) -> bool:
    """Delete a draft."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM draft_ideas WHERE id = $1 AND user_id = $2",
            draft_id, user_id
        )
        return result == "DELETE 1"


async def get_all_users() -> list:
    """Get all users for weekly digest sending."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, email, name FROM users ORDER BY id"
        )
        return [dict(r) for r in rows]


async def update_user_subscription(
    user_id:             int,
    subscription_status: str = None,
    trial_ends_at=None,
    stripe_customer_id:  str = None,
):
    """Update user subscription fields."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if stripe_customer_id:
            await conn.execute(
                "UPDATE users SET stripe_customer_id = $1 WHERE id = $2",
                stripe_customer_id, user_id
            )
        if subscription_status:
            await conn.execute(
                "UPDATE users SET subscription_status = $1 WHERE id = $2",
                subscription_status, user_id
            )
        if trial_ends_at:
            await conn.execute(
                "UPDATE users SET trial_ends_at = $1 WHERE id = $2",
                trial_ends_at, user_id
            )


async def get_user_by_stripe_customer_id(stripe_customer_id: str):
    """Find user by Stripe customer ID."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM users WHERE stripe_customer_id = $1",
            stripe_customer_id
        )
        return dict(row) if row else None


async def get_user_by_id(user_id: int):
    """Get user by ID."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
        return dict(row) if row else None


async def increment_free_report_count(user_id: int):
    """Increment the free report counter for a user."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET free_reports_used = free_reports_used + 1 WHERE id = $1",
            user_id
        )

async def get_free_reports_used(user_id: int) -> int:
    """Get how many free reports a user has used."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT free_reports_used FROM users WHERE id = $1", user_id
        )
        return row['free_reports_used'] if row else 0
