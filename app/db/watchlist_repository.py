"""
Watchlist Repository
====================
All database operations for watchlists and alerts.
"""
import logging
from typing import List, Optional
from datetime import datetime, timedelta

from app.db.database import get_pool
from app.models.watchlist import Watchlist, Alert

logger = logging.getLogger(__name__)


async def init_watchlist_tables():
    """Create watchlists and alerts tables if they don't exist."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_watchlists (
                id                  SERIAL PRIMARY KEY,
                user_id             INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name                VARCHAR(200) NOT NULL,
                disease_domain      VARCHAR(50)  NOT NULL DEFAULT 'auto',
                product_description TEXT         NOT NULL,
                keywords            TEXT[]       DEFAULT '{}',
                last_checked        TIMESTAMPTZ,
                created_at          TIMESTAMPTZ  DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS watchlists_user_idx ON user_watchlists (user_id)
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_alerts (
                id           SERIAL PRIMARY KEY,
                watchlist_id INTEGER NOT NULL REFERENCES user_watchlists(id) ON DELETE CASCADE,
                user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                signal_id    INTEGER,
                alert_type   VARCHAR(50)  NOT NULL,
                title        TEXT         NOT NULL,
                summary      TEXT         NOT NULL,
                severity     VARCHAR(20)  NOT NULL DEFAULT 'medium',
                source       VARCHAR(100) NOT NULL,
                source_url   TEXT,
                seen         BOOLEAN      DEFAULT FALSE,
                created_at   TIMESTAMPTZ  DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS alerts_user_idx      ON user_alerts (user_id)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS alerts_watchlist_idx ON user_alerts (watchlist_id)
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS alerts_seen_idx      ON user_alerts (user_id, seen)
        """)
    logger.info("✅ Watchlist tables initialized")


# ── Watchlists ────────────────────────────────────────────────────────────────

async def create_watchlist(
    user_id:             int,
    name:                str,
    disease_domain:      str,
    product_description: str,
    keywords:            List[str] = None,
) -> Watchlist:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO user_watchlists (user_id, name, disease_domain, product_description, keywords)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id, user_id, name, disease_domain, product_description, keywords, created_at, last_checked
            """,
            user_id, name, disease_domain, product_description, keywords or []
        )
        return _row_to_watchlist(row, alert_count=0, unread_count=0)


async def get_user_watchlists(user_id: int) -> List[Watchlist]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT w.*,
                COUNT(a.id)                                    AS alert_count,
                COUNT(a.id) FILTER (WHERE a.seen = FALSE)      AS unread_count
            FROM user_watchlists w
            LEFT JOIN user_alerts a ON a.watchlist_id = w.id
            WHERE w.user_id = $1
            GROUP BY w.id
            ORDER BY w.created_at DESC
            """,
            user_id
        )
        return [_row_to_watchlist(r, r['alert_count'], r['unread_count']) for r in rows]


async def get_watchlist_by_id(watchlist_id: int, user_id: int) -> Optional[Watchlist]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM user_watchlists WHERE id = $1 AND user_id = $2",
            watchlist_id, user_id
        )
        return _row_to_watchlist(row) if row else None


async def delete_watchlist(watchlist_id: int, user_id: int) -> bool:
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM user_watchlists WHERE id = $1 AND user_id = $2",
            watchlist_id, user_id
        )
        return result == "DELETE 1"


async def get_all_watchlists_for_matching() -> List[dict]:
    """Get all watchlists across all users for the weekly matcher."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, user_id, name, disease_domain, product_description, keywords
            FROM user_watchlists
            ORDER BY id
        """)
        return [dict(r) for r in rows]


async def update_last_checked(watchlist_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE user_watchlists SET last_checked = NOW() WHERE id = $1",
            watchlist_id
        )


def _row_to_watchlist(row, alert_count=0, unread_count=0) -> Watchlist:
    return Watchlist(
        watchlist_id        = row['id'],
        user_id             = row['user_id'],
        name                = row['name'],
        disease_domain      = row['disease_domain'],
        product_description = row['product_description'],
        keywords            = list(row['keywords']) if row['keywords'] else [],
        alert_count         = int(alert_count),
        unread_count        = int(unread_count),
        created_at          = row['created_at'],
        last_checked        = row.get('last_checked'),
    )


# ── Alerts ────────────────────────────────────────────────────────────────────

async def create_alert(
    watchlist_id: int,
    user_id:      int,
    alert_type:   str,
    title:        str,
    summary:      str,
    severity:     str = "medium",
    source:       str = "",
    source_url:   Optional[str] = None,
    signal_id:    Optional[int] = None,
) -> Alert:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO user_alerts
                (watchlist_id, user_id, signal_id, alert_type, title, summary, severity, source, source_url)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING *
            """,
            watchlist_id, user_id, signal_id, alert_type, title, summary, severity, source, source_url
        )
        return _row_to_alert(row)


async def get_user_alerts(
    user_id:  int,
    limit:    int = 50,
    unread_only: bool = False,
) -> List[Alert]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        where = "WHERE user_id = $1" + (" AND seen = FALSE" if unread_only else "")
        rows = await conn.fetch(
            f"SELECT * FROM user_alerts {where} ORDER BY created_at DESC LIMIT $2",
            user_id, limit
        )
        return [_row_to_alert(r) for r in rows]


async def get_watchlist_alerts(watchlist_id: int, user_id: int, limit: int = 20) -> List[Alert]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM user_alerts WHERE watchlist_id = $1 AND user_id = $2 ORDER BY created_at DESC LIMIT $3",
            watchlist_id, user_id, limit
        )
        return [_row_to_alert(r) for r in rows]


async def mark_alerts_seen(user_id: int, alert_ids: List[int] = None):
    """Mark specific alerts (or all) as seen."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if alert_ids:
            await conn.execute(
                "UPDATE user_alerts SET seen = TRUE WHERE user_id = $1 AND id = ANY($2)",
                user_id, alert_ids
            )
        else:
            await conn.execute(
                "UPDATE user_alerts SET seen = TRUE WHERE user_id = $1",
                user_id
            )


async def get_unread_count(user_id: int) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COUNT(*) AS cnt FROM user_alerts WHERE user_id = $1 AND seen = FALSE",
            user_id
        )
        return int(row['cnt'])


async def alert_already_exists(watchlist_id: int, signal_id: int) -> bool:
    """Prevent duplicate alerts for the same signal."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM user_alerts WHERE watchlist_id = $1 AND signal_id = $2",
            watchlist_id, signal_id
        )
        return row is not None


async def get_recent_alerts_for_digest(user_id: int, days: int = 7) -> List[Alert]:
    """Get all alerts from the past N days for the weekly digest email."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT * FROM user_alerts
            WHERE user_id = $1
              AND created_at >= NOW() - INTERVAL '%s days'
            ORDER BY severity DESC, created_at DESC
            """ % days,
            user_id
        )
        return [_row_to_alert(r) for r in rows]


def _row_to_alert(row) -> Alert:
    return Alert(
        alert_id     = row['id'],
        watchlist_id = row['watchlist_id'],
        user_id      = row['user_id'],
        signal_id    = row.get('signal_id'),
        alert_type   = row['alert_type'],
        title        = row['title'],
        summary      = row['summary'],
        severity     = row['severity'],
        source       = row['source'],
        source_url   = row.get('source_url'),
        seen         = row['seen'],
        created_at   = row['created_at'],
    )


async def get_all_active_watchlists() -> list:
    """Get all watchlists for weekly tracker."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM watchlists ORDER BY created_at DESC"
        )
        return [dict(r) for r in rows]


async def get_watchlists_for_user(user_id: int) -> list:
    """Get watchlists for a specific user."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM watchlists WHERE user_id = $1 ORDER BY created_at DESC",
            user_id
        )
        return [dict(r) for r in rows]


async def create_alert(
    watchlist_id: int,
    user_id: int,
    title: str,
    body: str,
    severity: str = "medium",
    source: str = "weekly_tracker",
    recalculation_needed: bool = False,
    significance_score: int = 0,
) -> dict:
    """Create an alert for a watchlist."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO alerts
               (watchlist_id, user_id, title, body, severity, source,
                recalculation_needed, significance_score)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
               RETURNING *""",
            watchlist_id, user_id, title, body, severity, source,
            recalculation_needed, significance_score
        )
        return dict(row) if row else {}
