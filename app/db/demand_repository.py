"""
demand_signals table — stores normalized signals from all data sources.

Sits alongside hospital_needs (Step 1) in the same Postgres DB.
Both tables feed the same pgvector index that inventor alignment searches.
"""

import json
from typing import List, Optional, Tuple
from datetime import datetime
from app.db.database import get_pool
from app.models.demand_signal import DemandSignal


async def ensure_demand_signals_table():
    """Create demand_signals table and indexes if they don't exist."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS demand_signals (
                id                      SERIAL PRIMARY KEY,

                -- Identity
                source                  VARCHAR(64) NOT NULL,
                source_record_id        VARCHAR(512),
                signal_type             VARCHAR(64) NOT NULL,
                fetched_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

                -- Core content
                title                   TEXT NOT NULL,
                description             TEXT NOT NULL,

                -- Categorization
                condition_or_topic      VARCHAR(512),
                innovation_category_hint VARCHAR(64),
                icd10_codes             TEXT[],
                keywords                TEXT[],

                -- Geography
                geographic_scope        VARCHAR(32),
                country                 VARCHAR(8) DEFAULT 'US',
                state_code              VARCHAR(4),
                county_fips             VARCHAR(8),
                census_tract            VARCHAR(16),
                location_name           VARCHAR(512),

                -- Demographics
                age_group               VARCHAR(128),
                sex                     VARCHAR(32),
                race_ethnicity          VARCHAR(256),
                income_level            VARCHAR(128),
                insurance_status        VARCHAR(128),

                -- Quantitative
                magnitude               FLOAT,
                magnitude_unit          VARCHAR(128),
                national_average        FLOAT,
                trend_direction         VARCHAR(32),
                trend_magnitude         FLOAT,

                -- Temporal
                data_year               INTEGER,
                data_period             VARCHAR(64),
                data_freshness_days     INTEGER,

                -- Provenance
                source_url              TEXT,
                confidence_score        FLOAT DEFAULT 0.8,
                raw_data                JSONB,

                -- Vector embedding (1536 dims, OpenAI text-embedding-3-small)
                embedding               vector(1536),

                -- Deduplication: prevent re-inserting the same source record
                UNIQUE (source, source_record_id)
            );
        """)

        # Vector similarity index (ivfflat, cosine distance)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS demand_signals_embedding_idx
            ON demand_signals
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100);
        """)

        # Filtering indexes for common query patterns
        for col in ["source", "signal_type", "state_code", "condition_or_topic",
                    "geographic_scope", "data_year"]:
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS demand_signals_{col}_idx
                ON demand_signals ({col});
            """)

        print("✅ demand_signals table ready")


async def upsert_signal(signal: DemandSignal, embedding: List[float]) -> Optional[int]:
    """
    Insert a demand signal with its embedding.
    Skips duplicate (source, source_record_id) pairs silently.
    Returns inserted row ID, or None if skipped.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO demand_signals (
                source, source_record_id, signal_type, fetched_at,
                title, description,
                condition_or_topic, innovation_category_hint,
                icd10_codes, keywords,
                geographic_scope, country, state_code, county_fips,
                census_tract, location_name,
                age_group, sex, race_ethnicity, income_level, insurance_status,
                magnitude, magnitude_unit, national_average,
                trend_direction, trend_magnitude,
                data_year, data_period, data_freshness_days,
                source_url, confidence_score, raw_data, embedding
            ) VALUES (
                $1,$2,$3,$4,$5,$6,$7,$8,$9,$10,
                $11,$12,$13,$14,$15,$16,$17,$18,$19,$20,
                $21,$22,$23,$24,$25,$26,$27,$28,$29,$30,$31,$32,$33::vector
            )
            ON CONFLICT (source, source_record_id) DO NOTHING
            RETURNING id
            """,
            signal.source.value,
            signal.source_record_id,
            signal.signal_type.value,
            signal.fetched_at,
            signal.title,
            signal.description,
            signal.condition_or_topic,
            signal.innovation_category_hint,
            signal.icd10_codes or [],
            signal.keywords or [],
            signal.geographic_scope.value,
            signal.country,
            signal.state_code,
            signal.county_fips,
            signal.census_tract,
            signal.location_name,
            signal.age_group,
            signal.sex,
            signal.race_ethnicity,
            signal.income_level,
            signal.insurance_status,
            signal.magnitude,
            signal.magnitude_unit,
            signal.national_average,
            signal.trend_direction,
            signal.trend_magnitude,
            signal.data_year,
            signal.data_period,
            signal.data_freshness_days,
            signal.source_url,
            signal.confidence_score,
            json.dumps(signal.raw_data) if signal.raw_data else None,
            str(embedding),
        )
    return row["id"] if row else None


async def bulk_upsert_signals(
    signals_with_embeddings: List[Tuple[DemandSignal, List[float]]]
) -> Tuple[int, int]:
    """
    Insert multiple signals efficiently. Returns (inserted_count, skipped_count).
    """
    inserted = 0
    skipped = 0
    for signal, embedding in signals_with_embeddings:
        result = await upsert_signal(signal, embedding)
        if result is not None:
            inserted += 1
        else:
            skipped += 1
    return inserted, skipped


async def search_similar_signals(
    query_embedding: List[float],
    top_k: int = 15,
    min_similarity: float = 0.55,
    source_filter: Optional[str] = None,
    signal_type_filter: Optional[str] = None,
    state_filter: Optional[str] = None,
) -> List[dict]:
    """
    Semantic search over the demand_signals index.
    Returns signals ranked by cosine similarity.
    """
    pool = await get_pool()

    filters = ["embedding IS NOT NULL"]
    params: list = [str(query_embedding), min_similarity, top_k]
    p = 4  # next param index

    if source_filter:
        filters.append(f"source = ${p}")
        params.append(source_filter)
        p += 1
    if signal_type_filter:
        filters.append(f"signal_type = ${p}")
        params.append(signal_type_filter)
        p += 1
    if state_filter:
        filters.append(f"state_code = ${p}")
        params.append(state_filter)
        p += 1

    where = " AND ".join(filters)

    async with pool.acquire() as conn:
        rows = await conn.fetch(f"""
            SELECT
                id, source, signal_type, title, description,
                condition_or_topic, geographic_scope, location_name,
                state_code, county_fips,
                age_group, race_ethnicity, insurance_status,
                magnitude, magnitude_unit, national_average,
                trend_direction, data_year, confidence_score,
                keywords, icd10_codes,
                1 - (embedding <=> $1::vector) / 2 AS similarity_score
            FROM demand_signals
            WHERE {where}
              AND 1 - (embedding <=> $1::vector) / 2 >= $2
            ORDER BY embedding <=> $1::vector
            LIMIT $3
        """, *params)

    return [dict(r) for r in rows]


async def get_signal_counts_by_source() -> List[dict]:
    """Returns row counts per source — useful for monitoring ingestion health."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT source, signal_type, COUNT(*) as count,
                   MAX(fetched_at) as last_fetched
            FROM demand_signals
            GROUP BY source, signal_type
            ORDER BY source, signal_type
        """)
    return [dict(r) for r in rows]
