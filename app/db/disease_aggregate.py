"""
Disease Aggregate View
======================
Materializes per-disease metrics from all canonical sources into a single
`disease_aggregate` table that the scoring engine queries directly via SQL
instead of calling multiple live APIs per request.

Schema mirrors what the opportunity scorer needs:
  - competitor_trial_count  (from disease_burden.source='clinicaltrials')
  - approved_drug_count     (from disease_burden.source='openfda')
  - nih_grant_count         (from disease_burden.source='nih_reporter')
  - us_dalys                (from disease_burden.source='who_gho', commercial_safe=TRUE)
  - nih_total_funding_usd

Refresh cadence:
  - Rebuilt weekly (full recompute — fast because source tables are small)
  - Called by the scheduler after each ETL run

This is the "hub" in the hub-and-spoke design: downstream consumers read
ONE table, not N source tables.
"""

import logging

from app.db.database import get_pool

logger = logging.getLogger(__name__)


async def ensure_aggregate_table() -> None:
    """Create disease_aggregate table if not exists."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS disease_aggregate (
                disease_label           TEXT PRIMARY KEY,
                mondo_id                VARCHAR(20),
                therapeutic_area        VARCHAR(50),
                -- Pipeline competition (live CT.gov, refreshed weekly)
                competitor_trial_count  INTEGER  DEFAULT 0,
                trial_data_source       TEXT     DEFAULT 'clinicaltrials_gov',
                -- Approvals (openFDA, refreshed weekly)
                approved_drug_count     INTEGER  DEFAULT 0,
                -- Funding (NIH RePORTER, refreshed weekly)
                nih_grant_count         INTEGER  DEFAULT 0,
                nih_total_funding_usd   BIGINT   DEFAULT 0,
                -- Burden (WHO GHO — commercial-safe only)
                us_dalys                FLOAT,
                daly_source             TEXT     DEFAULT 'who_gho',
                -- Prevalence
                us_patient_population   BIGINT,
                -- Composite freshness
                last_refreshed          TIMESTAMPTZ DEFAULT NOW(),
                -- Raw computed_at for cache invalidation
                etl_version             INTEGER  DEFAULT 1
            );
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS da_mondo_idx ON disease_aggregate (mondo_id);"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS da_ta_idx ON disease_aggregate (therapeutic_area);"
        )


async def refresh_disease_aggregate() -> int:
    """
    Recompute disease_aggregate from all source tables.
    Uses UPSERT so it's safe to run repeatedly.
    Returns number of rows refreshed.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        await ensure_aggregate_table()

        # Pull all diseases that have ANY burden signal
        diseases = await conn.fetch("""
            SELECT DISTINCT disease_label FROM disease_burden
            UNION
            SELECT DISTINCT disease_label FROM nih_grants
        """)

        refreshed = 0
        for row in diseases:
            disease = row["disease_label"]

            # Resolve MONDO and TA from disease table
            meta = await conn.fetchrow("""
                SELECT d.mondo_id, d.therapeutic_area
                FROM disease d
                WHERE lower(d.label) = lower($1)
                LIMIT 1
            """, disease)
            mondo_id = meta["mondo_id"] if meta else None
            ta       = meta["therapeutic_area"] if meta else None

            # Aggregate burden metrics (commercial-safe sources only)
            metrics = await conn.fetch("""
                SELECT source_name, metric, value
                FROM disease_burden
                WHERE disease_label = $1
                  AND commercial_safe = TRUE
                ORDER BY fetched_at DESC
            """, disease)

            agg: dict = {
                "competitor_trial_count": 0,
                "approved_drug_count":    0,
                "nih_grant_count":        0,
                "nih_total_funding_usd":  0,
                "us_dalys":               None,
                "us_patient_population":  None,
                "daly_source":            "none",
            }

            for m in metrics:
                src, metric, val = m["source_name"], m["metric"], m["value"]
                if metric == "trial_count":
                    agg["competitor_trial_count"] = max(agg["competitor_trial_count"], int(val))
                elif metric == "approved_drug_count":
                    agg["approved_drug_count"] = max(agg["approved_drug_count"], int(val))
                elif metric == "nih_active_grant_count":
                    agg["nih_grant_count"] = max(agg["nih_grant_count"], int(val))
                elif metric == "nih_total_funding_usd":
                    agg["nih_total_funding_usd"] = max(agg["nih_total_funding_usd"], int(val))
                elif metric == "dalys_absolute" and src == "who_gho":
                    agg["us_dalys"]     = float(val)
                    agg["daly_source"]  = "who_gho"
                elif metric == "prevalence" and agg["us_patient_population"] is None:
                    agg["us_patient_population"] = int(val)

            await conn.execute("""
                INSERT INTO disease_aggregate (
                    disease_label, mondo_id, therapeutic_area,
                    competitor_trial_count, approved_drug_count,
                    nih_grant_count, nih_total_funding_usd,
                    us_dalys, daly_source, us_patient_population,
                    last_refreshed
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,NOW())
                ON CONFLICT (disease_label) DO UPDATE SET
                    mondo_id               = COALESCE(EXCLUDED.mondo_id, disease_aggregate.mondo_id),
                    therapeutic_area       = COALESCE(EXCLUDED.therapeutic_area, disease_aggregate.therapeutic_area),
                    competitor_trial_count = EXCLUDED.competitor_trial_count,
                    approved_drug_count    = EXCLUDED.approved_drug_count,
                    nih_grant_count        = EXCLUDED.nih_grant_count,
                    nih_total_funding_usd  = EXCLUDED.nih_total_funding_usd,
                    us_dalys               = COALESCE(EXCLUDED.us_dalys, disease_aggregate.us_dalys),
                    daly_source            = EXCLUDED.daly_source,
                    us_patient_population  = COALESCE(EXCLUDED.us_patient_population, disease_aggregate.us_patient_population),
                    last_refreshed         = NOW()
            """,
                disease, mondo_id, ta,
                agg["competitor_trial_count"],
                agg["approved_drug_count"],
                agg["nih_grant_count"],
                agg["nih_total_funding_usd"],
                agg["us_dalys"],
                agg["daly_source"],
                agg["us_patient_population"],
            )
            refreshed += 1

    logger.info("disease_aggregate refreshed: %d rows", refreshed)
    return refreshed


async def get_disease_aggregate(disease_label: str) -> dict | None:
    """
    Fast read: return the aggregate row for a disease (single SQL query).
    Returns None if disease not yet in the aggregate table.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM disease_aggregate WHERE lower(disease_label)=lower($1)",
            disease_label,
        )
        return dict(row) if row else None
