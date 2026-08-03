"""
Fraction Review Queue
=====================
DB interface for the human-review gate on auto-extracted funnel fractions.

Table: funnel_fraction_review
  status: 'pending'  — awaiting human review
          'approved' — PI or data steward confirmed; used automatically on next run
          'rejected' — bad extraction; extraction re-runs and will surface a new candidate

check_approved_fraction()  — fast path: < 2ms on indexed (disease, gate) lookup
queue_fraction_for_review() — writes pending row; UPSERT on (disease_name, gate_name, pmid)
  so re-runs with the same source don't create duplicate rows.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.services.funnel_fraction_extractor import LiteratureFractionResult


async def ensure_tables() -> None:
    """Create funnel_fraction_review table if it doesn't exist yet."""
    from app.db.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS funnel_fraction_review (
                id                SERIAL PRIMARY KEY,
                disease_name      TEXT NOT NULL,
                gate_name         TEXT NOT NULL,
                fraction          FLOAT NOT NULL,
                pmid              TEXT,
                verbatim_quote    TEXT,
                citation          TEXT,
                confidence        FLOAT NOT NULL,
                extraction_method TEXT,
                raw_abstract      TEXT,
                status            TEXT NOT NULL DEFAULT 'pending',
                created_at        TIMESTAMPTZ DEFAULT NOW(),
                reviewed_at       TIMESTAMPTZ,
                reviewer_note     TEXT,
                UNIQUE (disease_name, gate_name, COALESCE(pmid, ''))
            );
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS ffr_lookup_idx
            ON funnel_fraction_review (LOWER(disease_name), LOWER(gate_name), status);
        """)


async def check_approved_fraction(disease_name: str, gate_name: str) -> Optional[float]:
    """
    Return the approved fraction for this (disease, gate) pair, or None if not found.
    Only returns rows with status='approved'; ignores pending/rejected rows.
    """
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT fraction FROM funnel_fraction_review
                WHERE LOWER(disease_name) = LOWER($1)
                  AND LOWER(gate_name)    = LOWER($2)
                  AND status = 'approved'
                ORDER BY reviewed_at DESC NULLS LAST, id DESC
                LIMIT 1
            """, disease_name, gate_name)
            if row:
                return float(row["fraction"])
    except Exception as e:
        logger.warning("check_approved_fraction DB error: %s", e)
    return None


async def queue_fraction_for_review(result: "LiteratureFractionResult") -> None:
    """
    Insert (or update) a pending fraction-review row.

    UPSERT logic: if a row with the same (disease_name, gate_name, pmid) already
    exists with status='pending', update its fraction and confidence so repeated
    extraction runs don't pile up duplicates. Already-approved rows are left alone.
    """
    if result.fraction is None:
        return

    try:
        await ensure_tables()
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO funnel_fraction_review
                    (disease_name, gate_name, fraction, pmid, verbatim_quote,
                     citation, confidence, extraction_method, raw_abstract, status)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'pending')
                ON CONFLICT (disease_name, gate_name, COALESCE(pmid, ''))
                DO UPDATE SET
                    fraction          = EXCLUDED.fraction,
                    confidence        = EXCLUDED.confidence,
                    verbatim_quote    = EXCLUDED.verbatim_quote,
                    citation          = EXCLUDED.citation,
                    extraction_method = EXCLUDED.extraction_method,
                    raw_abstract      = EXCLUDED.raw_abstract,
                    created_at        = NOW()
                WHERE funnel_fraction_review.status = 'pending'
            """,
                result.disease_name,
                result.gate_name,
                result.fraction,
                result.pmid,
                result.verbatim_quote,
                result.citation,
                result.confidence,
                result.extraction_method,
                result.raw_abstract,
            )
    except Exception as e:
        logger.warning("queue_fraction_for_review DB error (non-fatal): %s", e)
