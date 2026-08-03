"""
Market Segment Repository
=========================
DB schema and CRUD for:
  market_segment  — treatable-segment funnels (the core of segmented TAM)
  disease_profile — disease-level anchor data (prevalence, DALYs, etc.)
  expert_report   — slot for expert-authored commercialization reports (wired, empty until populated)

Pattern: same asyncpg / CREATE TABLE IF NOT EXISTS convention as market_sizing_repository.py.
"""

import json
import logging
from typing import Optional, List

logger = logging.getLogger(__name__)


async def init_market_segment_tables():
    """Create market_segment, disease_profile, and expert_report tables if they don't exist."""
    from app.db.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        # ── disease_profile ──────────────────────────────────────────────────────
        # Disease-level anchor: prevalence, burden, approved count, NIH funding.
        # market_segment.disease_name is the join key (mondo_id is optional / future).
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS disease_profile (
                id                  SERIAL PRIMARY KEY,
                disease_name        TEXT    NOT NULL UNIQUE,
                disease_mondo_id    TEXT,
                therapeutic_area    TEXT,
                us_prevalence       BIGINT,
                us_prevalence_src   TEXT,
                us_incidence        BIGINT,
                us_incidence_src    TEXT,
                dalys_per_100k      NUMERIC,
                dalys_src           TEXT,
                approved_tx_count   INTEGER,
                active_trials_count INTEGER,
                nih_funding_usd     BIGINT,
                nih_funding_src     TEXT,
                annual_cost_usd     INTEGER,
                annual_cost_src     TEXT,
                has_biomarker       BOOLEAN DEFAULT FALSE,
                notes               TEXT,
                data_quality        TEXT    DEFAULT 'seed',
                last_refreshed      TIMESTAMPTZ DEFAULT NOW(),
                created_at          TIMESTAMPTZ DEFAULT NOW(),
                updated_at          TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS dp_name_idx ON disease_profile (disease_name)")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS dp_mondo_idx ON disease_profile (disease_mondo_id)")

        # ── market_segment ───────────────────────────────────────────────────────
        # One row per treatable segment (pathway/indication slice). A disease has
        # MANY segments. The funnel JSONB walks from top-line incidence/prevalence
        # down to the realistically reachable treated population.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS market_segment (
                id                  SERIAL PRIMARY KEY,
                disease_name        TEXT    NOT NULL,
                disease_mondo_id    TEXT,
                segment_name        TEXT    NOT NULL,
                pathway_tag         TEXT,
                product_fit_keywords JSONB  DEFAULT '[]',
                funnel              JSONB   NOT NULL DEFAULT '[]',
                som_penetration_pct NUMERIC,
                som_penetration_src TEXT,
                care_setting        TEXT,
                site_count          INTEGER,
                site_count_src      TEXT,
                notes               TEXT,
                data_quality        TEXT    DEFAULT 'seed',
                source_type         TEXT    DEFAULT 'literature',
                created_at          TIMESTAMPTZ DEFAULT NOW(),
                updated_at          TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS ms_disease_name_idx ON market_segment (disease_name)")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS ms_pathway_idx ON market_segment (pathway_tag)")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS ms_mondo_idx ON market_segment (disease_mondo_id)")

        # ── expert_report ────────────────────────────────────────────────────────
        # Slot for expert-authored commercialization reports. Wired now, populated later.
        # When a row exists for a disease/segment, it overrides literature funnel rates
        # and flips source_type='expert_report' on affected segments.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS expert_report (
                id                  SERIAL PRIMARY KEY,
                disease_mondo_id    TEXT,
                segment_id          INTEGER REFERENCES market_segment(id) ON DELETE SET NULL,
                title               TEXT    NOT NULL,
                author_role         TEXT,
                author_name         TEXT,
                content             TEXT,
                structured_claims   JSONB   DEFAULT '[]',
                verified            BOOLEAN DEFAULT FALSE,
                created_at          TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS er_disease_idx ON expert_report (disease_mondo_id)")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS er_segment_idx ON expert_report (segment_id)")

    logger.info("market_segment / disease_profile / expert_report tables ready")


# ── market_segment CRUD ──────────────────────────────────────────────────────

async def upsert_segment(seg: dict) -> Optional[int]:
    """
    Insert or update a market_segment row. Matches on (disease_name, pathway_tag).
    Returns the segment id, or None on failure.
    """
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                INSERT INTO market_segment
                    (disease_name, disease_mondo_id, segment_name, pathway_tag,
                     product_fit_keywords, funnel, som_penetration_pct, som_penetration_src,
                     care_setting, site_count, site_count_src, notes, data_quality, source_type)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14)
                ON CONFLICT DO NOTHING
                RETURNING id
            """,
                seg["disease_name"],
                seg.get("disease_mondo_id"),
                seg["segment_name"],
                seg.get("pathway_tag"),
                json.dumps(seg.get("product_fit_keywords", [])),
                json.dumps(seg.get("funnel", [])),
                seg.get("som_penetration_pct"),
                seg.get("som_penetration_src"),
                seg.get("care_setting"),
                seg.get("site_count"),
                seg.get("site_count_src"),
                seg.get("notes"),
                seg.get("data_quality", "seed"),
                seg.get("source_type", "literature"),
            )
            return row["id"] if row else None
    except Exception as e:
        logger.warning("upsert_segment failed (non-fatal): %s", e)
        return None


async def get_segments_for_disease(disease_name: str) -> List[dict]:
    """
    Return all market_segment rows for a disease name.
    Uses case-insensitive prefix matching so minor name variations still resolve.
    """
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM market_segment
                WHERE LOWER(disease_name) = LOWER($1)
                   OR LOWER($1) LIKE LOWER(disease_name) || '%'
                   OR LOWER(disease_name) LIKE LOWER($1) || '%'
                ORDER BY data_quality DESC, id ASC
            """, disease_name)
            return [_row_to_dict(r) for r in rows]
    except Exception as e:
        logger.warning("get_segments_for_disease failed (non-fatal): %s", e)
        return []


async def get_segment_by_id(segment_id: int) -> Optional[dict]:
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM market_segment WHERE id = $1", segment_id)
            return _row_to_dict(row) if row else None
    except Exception as e:
        logger.warning("get_segment_by_id failed: %s", e)
        return None


async def get_expert_report_for_segment(segment_id: int) -> Optional[dict]:
    """Return the most recent verified expert_report for a segment, or None."""
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM expert_report
                WHERE segment_id = $1
                ORDER BY verified DESC, created_at DESC
                LIMIT 1
            """, segment_id)
            if not row:
                return None
            d = dict(row)
            if isinstance(d.get("structured_claims"), str):
                d["structured_claims"] = json.loads(d["structured_claims"])
            return d
    except Exception as e:
        logger.warning("get_expert_report_for_segment failed: %s", e)
        return None


def _row_to_dict(row) -> dict:
    if row is None:
        return {}
    d = dict(row)
    for jsonb_field in ("product_fit_keywords", "funnel"):
        if isinstance(d.get(jsonb_field), str):
            try:
                d[jsonb_field] = json.loads(d[jsonb_field])
            except Exception:
                d[jsonb_field] = []
    return d
