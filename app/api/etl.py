"""
ETL Admin API
=============
POST /api/v1/etl/run/weekly       — trigger weekly canonical ETL
POST /api/v1/etl/run/full         — trigger full bootstrap ETL
POST /api/v1/etl/run/ontology     — trigger MONDO + RxNorm refresh
POST /api/v1/etl/embed            — embed unembedded publications
GET  /api/v1/etl/status           — last N ETL run records
GET  /api/v1/etl/aggregate        — disease aggregate table snapshot
"""

import asyncio
import logging
from fastapi import APIRouter, HTTPException, BackgroundTasks

from app.db.database import get_pool

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/run/weekly")
async def trigger_weekly_etl(background_tasks: BackgroundTasks):
    """Trigger weekly canonical ETL in the background."""
    async def _run():
        from app.ingestion.etl_orchestrator import run_weekly_etl
        from app.core.config import settings
        await run_weekly_etl(api_key_fda=getattr(settings, "FDA_API_KEY", ""))

    background_tasks.add_task(_run)
    return {"status": "started", "job": "weekly_etl"}


@router.post("/run/full")
async def trigger_full_etl(background_tasks: BackgroundTasks):
    """Trigger full bootstrap ETL (slow — runs in background)."""
    async def _run():
        from app.ingestion.etl_orchestrator import run_full_etl
        from app.core.config import settings
        await run_full_etl(api_key_fda=getattr(settings, "FDA_API_KEY", ""))

    background_tasks.add_task(_run)
    return {"status": "started", "job": "full_etl",
            "note": "This takes 20-30 minutes. Check /etl/status for progress."}


@router.post("/run/ontology")
async def trigger_ontology_etl(background_tasks: BackgroundTasks):
    """Trigger MONDO + RxNorm ontology refresh."""
    async def _run():
        from app.ingestion.etl_orchestrator import run_ontology_etl
        await run_ontology_etl(bulk=False)

    background_tasks.add_task(_run)
    return {"status": "started", "job": "ontology_etl"}


@router.post("/embed")
async def trigger_embedding(background_tasks: BackgroundTasks, limit: int = 200):
    """Embed unembedded publication abstracts into pgvector."""
    async def _run():
        from app.services.rag_service import embed_publications
        n = await embed_publications(limit=limit)
        logger.info("Embedding job complete: %d publications", n)

    background_tasks.add_task(_run)
    return {"status": "started", "job": "embed_publications", "limit": limit}


@router.get("/status")
async def etl_status(limit: int = 20):
    """Return last N ETL run records."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            rows = await conn.fetch("""
                SELECT source_name, job_name, status, rows_fetched, rows_upserted,
                       error_message, started_at, completed_at
                FROM etl_run
                ORDER BY started_at DESC
                LIMIT $1
            """, limit)
            return {"runs": [dict(r) for r in rows]}
        except Exception:
            return {"runs": [], "note": "etl_run table not yet initialized"}


@router.get("/aggregate")
async def disease_aggregate_snapshot(disease: str = None):
    """Return disease_aggregate table contents."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            if disease:
                rows = await conn.fetch(
                    "SELECT * FROM disease_aggregate WHERE lower(disease_label)=lower($1)", disease
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM disease_aggregate ORDER BY disease_label LIMIT 50"
                )
            return {"diseases": [dict(r) for r in rows], "count": len(rows)}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


@router.post("/expand-universe/mondo")
async def trigger_mondo_expansion(background_tasks: BackgroundTasks,
                                   max_pages: int = 40):
    """
    Expand disease universe using MONDO ontology (20,000 diseases).
    More reliable than CT.gov on Railway. Takes 20-40 minutes.
    """
    async def _run():
        from app.services.universe_expander import run_mondo_expansion
        result = await run_mondo_expansion(max_pages=max_pages)
        logger.info("MONDO expansion complete: %s", result)
    background_tasks.add_task(_run)
    return {"status": "started", "source": "mondo",
            "note": f"Loading up to {max_pages * 500:,} MONDO diseases. Check /etl/universe-stats."}


@router.post("/expand-universe")
async def trigger_universe_expansion(background_tasks: BackgroundTasks,
                                      max_pages: int = 30):
    """
    Harvest ALL conditions from CT.gov and pre-score them into disease_scored table.
    Expands from 309 curated diseases to 5,000-15,000 diseases.
    Takes 30-60 minutes. Run once then weekly.
    """
    async def _run():
        from app.services.universe_expander import run_universe_expansion
        result = await run_universe_expansion(max_pages=max_pages)
        logger.info("Universe expansion complete: %s", result)
    background_tasks.add_task(_run)
    return {"status": "started", "max_pages": max_pages,
            "note": f"Harvesting ~{max_pages * 1000:,} CT.gov studies. Check /etl/universe-stats when done."}


@router.get("/universe-stats")
async def universe_stats():
    """Return stats on the pre-scored disease universe."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            total = await conn.fetchval("SELECT COUNT(*) FROM disease_scored")
            by_tier = await conn.fetch("""
                SELECT tier, COUNT(*) as cnt FROM disease_scored
                GROUP BY tier ORDER BY cnt DESC
            """)
            by_ta = await conn.fetch("""
                SELECT therapeutic_area, COUNT(*) as cnt FROM disease_scored
                GROUP BY therapeutic_area ORDER BY cnt DESC LIMIT 10
            """)
            top5 = await conn.fetch("""
                SELECT disease_label, score, tier FROM disease_scored
                ORDER BY score DESC NULLS LAST LIMIT 5
            """)
            return {
                "total_diseases": total,
                "by_tier": {r["tier"]: r["cnt"] for r in by_tier},
                "by_ta":   {r["therapeutic_area"]: r["cnt"] for r in by_ta},
                "top5":    [{"disease": r["disease_label"], "score": r["score"], "tier": r["tier"]} for r in top5],
            }
        except Exception as e:
            return {"total_diseases": 0, "note": "disease_scored table empty or not yet created", "error": str(e)}


@router.post("/warm-cache")
async def trigger_cache_warm(background_tasks: BackgroundTasks, force: bool = False):
    """Force-refresh the discovery cache (trial counts + approval counts)."""
    async def _run():
        from app.services.cache_warmer import warm_discovery_cache
        result = await warm_discovery_cache(force_refresh=force)
        logger.info("Manual cache warm: %s", result)
    background_tasks.add_task(_run)
    return {"status": "started", "force_refresh": force,
            "note": "Check /etl/cache-status for progress"}


@router.get("/cache-status")
async def cache_status():
    """Return current in-process discovery cache hit counts."""
    try:
        from app.services.opportunity_scorer_v2 import _TRIAL_COUNT_CACHE, _APPROVAL_COUNT_CACHE
        from app.services.universe_builder import get_universe
        universe_size = len(get_universe())
        return {
            "universe_size":        universe_size,
            "trial_counts_cached":  len(_TRIAL_COUNT_CACHE),
            "approval_counts_cached": len(_APPROVAL_COUNT_CACHE),
            "trial_coverage_pct":   round(len(_TRIAL_COUNT_CACHE) / universe_size * 100, 1),
            "ready":                len(_TRIAL_COUNT_CACHE) >= universe_size * 0.9,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/signals")
async def signal_ingestion_status():
    """
    Return demand_signals row counts and last-fetch timestamps per source.
    Useful for monitoring whether the ingestion scheduler is running.
    """
    from app.db.demand_repository import get_signal_counts_by_source
    try:
        rows = await get_signal_counts_by_source()
        total = sum(r["count"] for r in rows)
        last_fetched = max(
            (r["last_fetched"] for r in rows if r.get("last_fetched")),
            default=None,
        )
        return {
            "total_signals": total,
            "last_ingested_at": last_fetched.isoformat() if last_fetched else None,
            "by_source": [
                {
                    "source": r["source"],
                    "signal_type": r["signal_type"],
                    "count": r["count"],
                    "last_fetched": r["last_fetched"].isoformat() if r.get("last_fetched") else None,
                }
                for r in rows
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/signals/run")
async def trigger_signal_pipeline(
    background_tasks: BackgroundTasks,
    connectors: str = None,
):
    """
    Manually trigger the demand-signal ingestion pipeline.
    ?connectors=cdc_wastewater,clinical_trials  — runs only those connectors.
    Omit to run all connectors.
    """
    connector_list = [c.strip() for c in connectors.split(",")] if connectors else None

    async def _run():
        from app.ingestion.pipeline import run_pipeline
        result = await run_pipeline(connector_names=connector_list)
        logger.info("Manual signal pipeline: %s", result.summary())

    background_tasks.add_task(_run)
    return {
        "status": "started",
        "connectors": connector_list or "all",
        "note": "Check /etl/signals for updated counts when complete.",
    }


@router.get("/licenses")
async def license_registry():
    """Return the source license register."""
    import json, pathlib
    try:
        data = json.loads(
            (pathlib.Path(__file__).parent.parent / "data" / "source_licenses.json").read_text()
        )
        safe     = {k: v for k, v in data["sources"].items() if v["commercial_safe"]}
        restricted = {k: v for k, v in data["sources"].items() if not v["commercial_safe"]}
        return {
            "commercial_safe_count": len(safe),
            "restricted_count": len(restricted),
            "restricted_sources": list(restricted.keys()),
            "last_reviewed": data["_meta"]["last_reviewed"],
            "disclaimer": data["_meta"]["reminder"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
