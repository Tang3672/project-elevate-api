"""
Admin API — ingestion pipeline monitoring and control

GET  /api/v1/admin/ingestion/status          — signal counts per source
GET  /api/v1/admin/ingestion/connectors      — list registered connectors
POST /api/v1/admin/ingestion/run/{connector} — manually trigger one connector
POST /api/v1/admin/ingestion/run-all         — manually trigger full pipeline
GET  /api/v1/demand/search                   — search demand signals (semantic)
"""

import logging
from fastapi import APIRouter, HTTPException, Query
from typing import Optional

from app.db.demand_repository import (
    get_signal_counts_by_source, search_similar_signals,
    ensure_demand_signals_table
)
from app.services.embedding_service import embed_text
from app.ingestion.pipeline import build_connector_registry
from app.scheduler.ingestion_scheduler import trigger_connector, trigger_full_pipeline

logger = logging.getLogger(__name__)

admin_router = APIRouter()
demand_router = APIRouter()


# ── Admin: ingestion monitoring ───────────────────────────────────────────────

@admin_router.get("/ingestion/status")
async def ingestion_status():
    """
    Returns how many demand signals are in the DB per source,
    with timestamps of last ingestion run.
    """
    counts = await get_signal_counts_by_source()
    total = sum(r["count"] for r in counts)
    return {
        "total_signals": total,
        "by_source": counts,
    }


@admin_router.get("/ingestion/connectors")
async def list_connectors():
    """List all registered connectors with their metadata."""
    connectors = build_connector_registry()
    return {
        "connectors": [
            {
                "name": c.source_name,
                "description": c.description,
                "update_frequency_hours": c.update_frequency_hours,
                "batch_size": c.batch_size,
            }
            for c in connectors
        ]
    }


@admin_router.post("/ingestion/run/{connector_name}")
async def run_connector_manually(connector_name: str):
    """
    Manually trigger a specific connector by name.
    This runs synchronously and may take a few minutes for large datasets.
    """
    valid_names = {c.source_name for c in build_connector_registry()}
    if connector_name not in valid_names:
        raise HTTPException(
            status_code=404,
            detail=f"Connector '{connector_name}' not found. "
                   f"Valid names: {sorted(valid_names)}"
        )

    result = await trigger_connector(connector_name)
    return result


@admin_router.post("/ingestion/run-all")
async def run_full_pipeline():
    """
    Manually trigger the full ingestion pipeline.
    Warning: this can take 10-30 minutes depending on data source response times.
    """
    result = await trigger_full_pipeline()
    return result


@admin_router.post("/ingestion/init-tables")
async def init_demand_tables():
    """Initialize (or verify) the demand_signals table and indexes."""
    await ensure_demand_signals_table()
    return {"status": "ok", "message": "demand_signals table ready"}


# ── Demand search API ─────────────────────────────────────────────────────────

@demand_router.post("/search")
async def search_demand_signals(
    query: str,
    top_k: int = Query(default=15, ge=1, le=50),
    min_similarity: float = Query(default=0.55, ge=0.0, le=1.0),
    source: Optional[str] = Query(default=None, description="Filter by source name"),
    signal_type: Optional[str] = Query(default=None),
    state: Optional[str] = Query(default=None, description="2-letter state code"),
):
    """
    Semantic search over the demand signals index.

    This is the primary endpoint used by inventor alignment (Step 3).
    Pass any free-text query — an inventor idea, a condition name, a technology
    category — and get back the most relevant demand signals from across all
    ingested public health data sources.
    """
    try:
        query_embedding = await embed_text(query)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Embedding failed: {e}")

    results = await search_similar_signals(
        query_embedding=query_embedding,
        top_k=top_k,
        min_similarity=min_similarity,
        source_filter=source,
        signal_type_filter=signal_type,
        state_filter=state,
    )

    return {
        "query": query,
        "total_matches": len(results),
        "results": results,
    }


@demand_router.get("/sources")
async def list_sources():
    """List all signal sources with record counts."""
    counts = await get_signal_counts_by_source()
    return {"sources": counts}
