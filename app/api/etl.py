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
