"""
ETL Orchestrator
================
Coordinates all ingestion jobs in the correct dependency order:

  Phase 0: Ontology (MONDO + RxNorm) — monthly
  Phase 1: FDA approvals + NIH grants + CT.gov burden — weekly
  Phase 2: Publications (OpenAlex) — weekly
  Phase 3: Mechanisms (Open Targets + ChEMBL) — weekly
  Final:   Refresh disease_aggregate materialized table

Each job is logged to etl_run for auditability and incremental updates.
The scheduler calls run_weekly_etl() every Sunday at 2am UTC.
run_full_etl() bootstraps from scratch (run once to seed).
"""

import asyncio
import logging
from datetime import datetime, timezone

from app.db.database import get_pool

logger = logging.getLogger(__name__)


async def _log_run(conn, source: str, job: str, status: str,
                   fetched: int = 0, upserted: int = 0,
                   error: str = None, started_at: datetime = None) -> None:
    try:
        await conn.execute("""
            INSERT INTO etl_run (source_name, job_name, status, rows_fetched,
                                  rows_upserted, error_message, started_at, completed_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,NOW())
        """, source, job, status, fetched, upserted, error, started_at or datetime.now(timezone.utc))
    except Exception as e:
        logger.warning("etl_run log failed: %s", e)


async def _run_job(name: str, coro) -> tuple[bool, str]:
    """Run an ETL coroutine, log result, return (success, error_msg)."""
    started = datetime.now(timezone.utc)
    pool = await get_pool()
    try:
        result = await coro
        rows = sum(result.values()) if isinstance(result, dict) else (result or 0)
        async with pool.acquire() as conn:
            await _log_run(conn, name, name, "completed",
                           fetched=rows, upserted=rows, started_at=started)
        logger.info("ETL ✓ %s: %s rows", name, rows)
        return True, ""
    except Exception as e:
        msg = str(e)[:500]
        async with pool.acquire() as conn:
            await _log_run(conn, name, name, "failed", error=msg, started_at=started)
        logger.error("ETL ✗ %s: %s", name, msg)
        return False, msg


async def run_weekly_etl(api_key_fda: str = "") -> dict:
    """
    Run all weekly refresh jobs. Safe to call repeatedly (idempotent upserts).
    Returns summary of {job_name: success_bool}.
    """
    logger.info("=== Weekly ETL started ===")
    summary = {}

    # 1. FDA approvals (openFDA)
    from app.ingestion.connectors.fda_approvals import load_fda_approvals
    ok, _ = await _run_job("fda_approvals", load_fda_approvals(api_key_fda))
    summary["fda_approvals"] = ok

    # 2. NIH RePORTER grants
    from app.ingestion.connectors.nih_reporter import load_nih_funding
    ok, _ = await _run_job("nih_reporter", load_nih_funding())
    summary["nih_reporter"] = ok

    # 3. WHO GHO burden (commercial-safe DALYs)
    from app.ingestion.connectors.who_gho import load_burden_for_diseases
    ok, _ = await _run_job("who_gho", load_burden_for_diseases())
    summary["who_gho"] = ok

    # 4. OpenAlex publications
    from app.ingestion.connectors.openalex import load_publications
    ok, _ = await _run_job("openalex", load_publications(limit_per_disease=50))
    summary["openalex"] = ok

    # 5. Open Targets disease-target associations
    from app.ingestion.connectors.open_targets import load_disease_targets, load_chembl_indications
    ok, _ = await _run_job("open_targets", load_disease_targets())
    summary["open_targets"] = ok

    # 6. ChEMBL drug-indication pairs
    ok, _ = await _run_job("chembl_indications", load_chembl_indications())
    summary["chembl_indications"] = ok

    # 7. Refresh aggregate table (must run last)
    from app.db.disease_aggregate import refresh_disease_aggregate
    ok, _ = await _run_job("disease_aggregate", refresh_disease_aggregate())
    summary["disease_aggregate"] = ok

    # 8. Embed new publications (async — don't block weekly ETL)
    asyncio.create_task(_embed_new_publications())

    logger.info("=== Weekly ETL done: %s ===", summary)
    return summary


async def run_ontology_etl(bulk: bool = False) -> dict:
    """
    Run monthly ontology refresh: MONDO + RxNorm for our disease universe.
    bulk=True: crawl full MONDO (~10k terms, takes several minutes).
    """
    from app.services.opportunity_scorer import OPPORTUNITY_UNIVERSE
    disease_names = [d for d, *_ in OPPORTUNITY_UNIVERSE]

    summary = {}

    # MONDO
    from app.ingestion.connectors.mondo import load_mondo_for_diseases, bulk_load_mondo
    if bulk:
        ok, _ = await _run_job("mondo_bulk", bulk_load_mondo(max_pages=20))
    else:
        ok, _ = await _run_job("mondo_targeted", load_mondo_for_diseases(disease_names))
    summary["mondo"] = ok

    # RxNorm for approved drugs
    from app.ingestion.connectors.rxnorm import load_drugs_for_names
    # We load drug names from drug_disease_indication table
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT DISTINCT drug_label FROM drug_disease_indication LIMIT 200")
        drug_names = [r["drug_label"] for r in rows]
    if drug_names:
        ok, _ = await _run_job("rxnorm", load_drugs_for_names(drug_names))
        summary["rxnorm"] = ok

    return summary


async def run_full_etl(api_key_fda: str = "") -> dict:
    """
    Full bootstrap: ontology → weekly data → publications.
    Run once to seed the database from scratch (~20-30 minutes).
    """
    logger.info("=== Full ETL bootstrap started ===")
    summary = {}
    summary.update(await run_ontology_etl(bulk=False))
    summary.update(await run_weekly_etl(api_key_fda))
    logger.info("=== Full ETL bootstrap complete: %s ===", summary)
    return summary


async def _embed_new_publications() -> None:
    """Background task: embed any unembedded publication abstracts."""
    try:
        from app.services.rag_service import embed_publications
        n = await embed_publications(limit=200)
        logger.info("Background embedding: %d publications embedded", n)
    except Exception as e:
        logger.warning("Background embedding failed: %s", e)
