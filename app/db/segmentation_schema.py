"""
Segmentation Schema
===================
Sparse segment fact table for multi-dimensional market segmentation.

Tables:
  dimensions        — each segmentation axis (line_of_therapy, biomarker, ...)
  dimension_values  — allowed values per axis (1L, 2L, positive, ...)
  segments          — each unique combination of dimension values (+ aggregate stubs)
  segment_dimensions — M2M: which values a segment constrains
  segment_estimates — point/interval estimate per (segment, metric) with provenance
  seg_sources       — bibliographic / data sources
  seg_summing_matrix — S matrix rows for MinT reconciliation (Stage 2)
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def ensure_tables() -> None:
    """Create all segmentation tables if they do not already exist."""
    from app.db.database import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS seg_dimensions (
                dim_id      SERIAL PRIMARY KEY,
                product_id  INTEGER,           -- NULL = global/shared dimension
                name        TEXT NOT NULL,      -- "line_of_therapy"
                label       TEXT NOT NULL,      -- "Line of Therapy"
                UNIQUE (name, COALESCE(product_id, 0))
            );
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS seg_dimension_values (
                value_id  SERIAL PRIMARY KEY,
                dim_id    INTEGER NOT NULL REFERENCES seg_dimensions(dim_id) ON DELETE CASCADE,
                code      TEXT NOT NULL,   -- "1L"
                label     TEXT NOT NULL,   -- "First Line"
                sort_order INTEGER DEFAULT 0,
                UNIQUE (dim_id, code)
            );
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS seg_segments (
                segment_id      TEXT PRIMARY KEY,    -- canonical ID from segmentation_engine
                product_id      INTEGER,
                is_bottom_level BOOLEAN NOT NULL DEFAULT TRUE,
                level           INTEGER NOT NULL DEFAULT 0,
                label           TEXT,
                created_at      TIMESTAMPTZ DEFAULT NOW()
            );
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS seg_segments_product_idx
            ON seg_segments (product_id, is_bottom_level);
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS seg_segment_dimensions (
                segment_id  TEXT NOT NULL REFERENCES seg_segments(segment_id) ON DELETE CASCADE,
                dim_id      INTEGER NOT NULL REFERENCES seg_dimensions(dim_id) ON DELETE CASCADE,
                value_id    INTEGER NOT NULL REFERENCES seg_dimension_values(value_id) ON DELETE CASCADE,
                PRIMARY KEY (segment_id, dim_id)
            );
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS seg_sources (
                source_id   SERIAL PRIMARY KEY,
                name        TEXT NOT NULL,
                url         TEXT,
                citation    TEXT,
                table_ref   TEXT,   -- e.g. "Table 3, Supplement A"
                quote       TEXT,   -- verbatim supporting sentence
                retrieved_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS seg_estimates (
                id            SERIAL PRIMARY KEY,
                segment_id    TEXT NOT NULL REFERENCES seg_segments(segment_id) ON DELETE CASCADE,
                metric        TEXT NOT NULL,       -- "population", "market_size_usd", "penetration_rate"
                point         FLOAT NOT NULL,
                low           FLOAT,
                high          FLOAT,
                dist_type     TEXT,                -- "pert", "normal", "lognormal", "point"
                dist_params   JSONB,               -- {low, mode, high} or {mean, sd} etc.
                source_id     INTEGER REFERENCES seg_sources(source_id),
                is_assumption BOOLEAN NOT NULL DEFAULT TRUE,
                pooled_from   TEXT,                -- segment_id this was shrunk toward
                evidence_strength TEXT DEFAULT 'none',
                created_at    TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE (segment_id, metric)
            );
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS seg_estimates_metric_idx
            ON seg_estimates (metric, is_assumption);
        """)

        # Stores the non-zero entries of the S matrix for Stage 2 MinT reconciliation.
        # coef = 1.0 for standard sum aggregation; fractional for weighted aggregation.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS seg_summing_matrix (
                parent_segment_id TEXT NOT NULL REFERENCES seg_segments(segment_id) ON DELETE CASCADE,
                child_segment_id  TEXT NOT NULL REFERENCES seg_segments(segment_id) ON DELETE CASCADE,
                coef              FLOAT NOT NULL DEFAULT 1.0,
                PRIMARY KEY (parent_segment_id, child_segment_id)
            );
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS seg_summing_matrix_child_idx
            ON seg_summing_matrix (child_segment_id);
        """)

    logger.info("Segmentation schema tables verified / created.")


async def persist_segment_tree(tree: "SegmentTree", product_id: int) -> None:
    """
    Write a SegmentTree's structure (segments + summing matrix) to the DB.
    Idempotent — upserts on segment_id PK.
    """
    from app.db.database import get_pool
    from app.services.segmentation_engine import SegmentTree  # noqa: F401

    await ensure_tables()
    pool = await get_pool()

    async with pool.acquire() as conn:
        async with conn.transaction():
            # Upsert segments
            for seg in tree.all_segments:
                await conn.execute("""
                    INSERT INTO seg_segments (segment_id, product_id, is_bottom_level, level, label)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (segment_id) DO UPDATE SET
                        product_id      = EXCLUDED.product_id,
                        is_bottom_level = EXCLUDED.is_bottom_level,
                        level           = EXCLUDED.level,
                        label           = EXCLUDED.label
                """, seg.segment_id, product_id, seg.is_bottom_level, seg.level, seg.label)

            # Upsert S matrix (non-zero entries only)
            n_all, n_bot = tree.S.shape
            for i in range(n_all):
                for j in range(n_bot):
                    if tree.S[i, j] != 0.0:
                        parent_id = tree.all_segments[i].segment_id
                        child_id = tree.bottom_segments[j].segment_id
                        coef = float(tree.S[i, j])
                        await conn.execute("""
                            INSERT INTO seg_summing_matrix (parent_segment_id, child_segment_id, coef)
                            VALUES ($1, $2, $3)
                            ON CONFLICT (parent_segment_id, child_segment_id) DO UPDATE SET coef = EXCLUDED.coef
                        """, parent_id, child_id, coef)

    logger.info(
        "Persisted segment tree: product_id=%s, %d segments, %d S-matrix entries.",
        product_id, len(tree.all_segments),
        int(tree.S.sum()),
    )
