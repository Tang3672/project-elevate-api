"""
Market Sizing Provenance Repository  (Brief Priority 1)
=======================================================
Persists the structured provenance bundle produced by
`market_provenance_service.build_provenance` into the four tables the brief
specifies, so every market-sizing assumption is auditable and queryable later
(portfolio benchmarking, "what did we assume last time", eval harness, etc.).

Tables:
  market_sizing_runs         one row per market-sizing computation
  market_sizing_assumptions  one row per typed, source-backed assumption
  market_sizing_scenarios    conservative / base / aggressive roll-ups
  market_sizing_sources      deduped citable sources for the run

All writes are best-effort: a persistence failure must never break report
delivery (the structured bundle is already attached to the report in-memory).
"""

import json
import logging
import uuid
from typing import Optional

logger = logging.getLogger(__name__)


async def init_market_sizing_tables():
    """Create the market-sizing provenance tables if they don't exist."""
    from app.db.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS market_sizing_runs (
                id               TEXT PRIMARY KEY,
                user_id          INTEGER,
                disease_name     TEXT,
                idea             TEXT,
                archetype        TEXT,
                formula_name     TEXT,
                geography        TEXT,
                tam_usd          DOUBLE PRECISION,
                sam_usd          DOUBLE PRECISION,
                som_usd          DOUBLE PRECISION,
                confidence_note  TEXT,
                created_at       TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS market_sizing_assumptions (
                id               SERIAL PRIMARY KEY,
                run_id           TEXT REFERENCES market_sizing_runs(id) ON DELETE CASCADE,
                assumption_type  TEXT,
                label            TEXT,
                value            DOUBLE PRECISION,
                unit             TEXT,
                source_name      TEXT,
                source_url       TEXT,
                confidence       REAL,
                used_in_formula  TEXT,
                formula          TEXT,
                retrieved_at     TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS market_sizing_scenarios (
                id               SERIAL PRIMARY KEY,
                run_id           TEXT REFERENCES market_sizing_runs(id) ON DELETE CASCADE,
                scenario         TEXT,
                tam_usd          DOUBLE PRECISION,
                sam_usd          DOUBLE PRECISION,
                som_usd          DOUBLE PRECISION,
                sam_multiplier   REAL,
                som_multiplier   REAL,
                narrative        TEXT
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS market_sizing_sources (
                id               SERIAL PRIMARY KEY,
                run_id           TEXT REFERENCES market_sizing_runs(id) ON DELETE CASCADE,
                source_name      TEXT,
                source_url       TEXT,
                citation         TEXT
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS msr_user_idx ON market_sizing_runs (user_id)")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS msr_disease_idx ON market_sizing_runs (disease_name)")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS msa_run_idx ON market_sizing_assumptions (run_id)")
    logger.info("market_sizing_* provenance tables ready")


async def save_market_sizing_run(
    provenance: dict,
    *,
    user_id: Optional[int] = None,
    disease_name: str = "",
) -> Optional[str]:
    """
    Persist a provenance bundle. Returns the generated run_id, or None on failure.
    Best-effort: never raises.
    """
    run_id = str(uuid.uuid4())
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        run = provenance.get("run", {})
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("""
                    INSERT INTO market_sizing_runs
                        (id, user_id, disease_name, idea, archetype, formula_name,
                         geography, tam_usd, sam_usd, som_usd, confidence_note)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
                """, run_id, user_id, disease_name or run.get("idea", ""),
                    run.get("idea", ""), run.get("archetype", ""),
                    run.get("formula_name", ""), run.get("geography", ""),
                    run.get("tam_usd", 0.0), run.get("sam_usd", 0.0),
                    run.get("som_usd", 0.0), run.get("confidence_note", ""))

                for a in provenance.get("assumptions", []):
                    await conn.execute("""
                        INSERT INTO market_sizing_assumptions
                            (run_id, assumption_type, label, value, unit, source_name,
                             source_url, confidence, used_in_formula, formula)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                    """, run_id, a.get("assumption_type"), a.get("label"),
                        _num(a.get("value")), a.get("unit"), a.get("source_name"),
                        a.get("source_url"), a.get("confidence"),
                        a.get("used_in_formula"), a.get("formula"))

                for s in provenance.get("scenarios", []):
                    await conn.execute("""
                        INSERT INTO market_sizing_scenarios
                            (run_id, scenario, tam_usd, sam_usd, som_usd,
                             sam_multiplier, som_multiplier, narrative)
                        VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
                    """, run_id, s.get("scenario"), s.get("tam_usd"), s.get("sam_usd"),
                        s.get("som_usd"), s.get("sam_multiplier"),
                        s.get("som_multiplier"), s.get("narrative"))

                for src in provenance.get("sources", []):
                    await conn.execute("""
                        INSERT INTO market_sizing_sources
                            (run_id, source_name, source_url, citation)
                        VALUES ($1,$2,$3,$4)
                    """, run_id, src.get("source_name"), src.get("source_url"),
                        src.get("citation"))
        logger.info("Persisted market sizing run %s (%d assumptions)",
                    run_id, len(provenance.get("assumptions", [])))
        return run_id
    except Exception as e:
        logger.warning("save_market_sizing_run failed (non-fatal): %s", e)
        return None


def _num(v) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None
