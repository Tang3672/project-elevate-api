"""
Ingestion Pipeline
==================
Orchestrates the full flow: connectors → normalize → embed → store

Handles:
- Running one or all connectors
- Batch embedding (efficient API usage)
- Upsert to DB with deduplication
- Progress logging and error isolation (one connector failure doesn't stop others)
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Type

from app.ingestion.connectors.base import BaseConnector
from app.models.demand_signal import DemandSignal
from app.services.embedding_service import embed_batch
from app.db.demand_repository import bulk_upsert_signals, ensure_demand_signals_table
from app.db.database import init_db

# Import all connectors
from app.ingestion.connectors.cdc_places import CDCPlacesConnector
from app.ingestion.connectors.openfda import (
    FDAAdverseEventsConnector, FDADeviceEventsConnector, FDARecallsConnector
)
from app.ingestion.connectors.cms_quality import CMSHospitalQualityConnector
from app.ingestion.connectors.census_sahie import CensusSAHIEConnector
from app.ingestion.connectors.clinical_trials import ClinicalTrialsConnector
from app.ingestion.connectors.cdc_surveillance import (
    CDCWastewaterConnector, CDCFluViewConnector
)
from app.ingestion.connectors.hrsa_shortage import HRSAShortageConnector
from app.core.config import settings

logger = logging.getLogger(__name__)

# ── Connector registry ────────────────────────────────────────────────────────
# Ordered by priority: real-time first, then burden, then baseline

def build_connector_registry() -> List[BaseConnector]:
    """Instantiate all connectors with credentials from settings."""
    return [
        # Tier 4 — Real-time / weekly
        CDCWastewaterConnector(),
        CDCFluViewConnector(),

        # Tier 2 — Disease burden & utilization
        CDCPlacesConnector(app_token=settings.CDC_APP_TOKEN, level="county"),
        FDAAdverseEventsConnector(api_key=settings.FDA_API_KEY),
        FDADeviceEventsConnector(api_key=settings.FDA_API_KEY),
        FDARecallsConnector(api_key=settings.FDA_API_KEY),
        CMSHospitalQualityConnector(),
        ClinicalTrialsConnector(),

        # Tier 1 — Population baseline
        CensusSAHIEConnector(api_key=settings.CENSUS_API_KEY),
        HRSAShortageConnector(),
    ]


# ── Run result ────────────────────────────────────────────────────────────────

@dataclass
class ConnectorResult:
    connector_name: str
    inserted: int = 0
    skipped: int = 0
    errors: int = 0
    duration_seconds: float = 0.0
    error_message: str = ""


@dataclass
class PipelineResult:
    started_at: datetime = field(default_factory=datetime.utcnow)
    finished_at: datetime = None
    connector_results: List[ConnectorResult] = field(default_factory=list)

    @property
    def total_inserted(self) -> int:
        return sum(r.inserted for r in self.connector_results)

    @property
    def total_skipped(self) -> int:
        return sum(r.skipped for r in self.connector_results)

    @property
    def total_errors(self) -> int:
        return sum(r.errors for r in self.connector_results)

    @property
    def duration_seconds(self) -> float:
        if self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return 0.0

    def summary(self) -> str:
        lines = [
            f"Pipeline run: {self.started_at.strftime('%Y-%m-%d %H:%M')} → {self.duration_seconds:.1f}s",
            f"Total: {self.total_inserted} inserted, {self.total_skipped} skipped, {self.total_errors} errors",
            "",
        ]
        for r in self.connector_results:
            status = "✅" if r.errors == 0 else "⚠️"
            lines.append(
                f"  {status} {r.connector_name}: "
                f"+{r.inserted} inserted, {r.skipped} skipped "
                f"({r.duration_seconds:.1f}s)"
            )
            if r.error_message:
                lines.append(f"      Error: {r.error_message}")
        return "\n".join(lines)


# ── Pipeline ──────────────────────────────────────────────────────────────────

async def run_connector(connector: BaseConnector) -> ConnectorResult:
    """
    Run a single connector end-to-end: fetch → embed → store.
    Errors are caught per-batch so partial runs succeed.
    """
    result = ConnectorResult(connector_name=connector.source_name)
    start = datetime.utcnow()

    try:
        async with connector:
            batch_num = 0
            async for signal_batch in connector.fetch():
                batch_num += 1
                if not signal_batch:
                    continue

                # Build text for embedding — combine title + description
                texts = [
                    f"{s.title}\n\n{s.description}"
                    for s in signal_batch
                ]

                # Embed the batch
                try:
                    embeddings = await embed_batch(texts)
                except Exception as e:
                    logger.error(
                        f"{connector.source_name} batch {batch_num} embedding failed: {e}"
                    )
                    result.errors += len(signal_batch)
                    continue

                # Store with embeddings
                try:
                    pairs = list(zip(signal_batch, embeddings))
                    inserted, skipped = await bulk_upsert_signals(pairs)
                    result.inserted += inserted
                    result.skipped += skipped

                    logger.info(
                        f"{connector.source_name} batch {batch_num}: "
                        f"+{inserted} inserted, {skipped} skipped"
                    )
                except Exception as e:
                    logger.error(
                        f"{connector.source_name} batch {batch_num} DB write failed: {e}"
                    )
                    result.errors += len(signal_batch)

    except Exception as e:
        logger.error(f"{connector.source_name} connector failed: {e}", exc_info=True)
        result.error_message = str(e)

    result.duration_seconds = (datetime.utcnow() - start).total_seconds()
    return result


async def run_pipeline(
    connector_names: List[str] = None,
    concurrency: int = 3
) -> PipelineResult:
    """
    Run the full ingestion pipeline (or a subset of connectors).

    Args:
        connector_names: Optional list of connector source_names to run.
                         If None, runs all registered connectors.
        concurrency:     Max connectors running in parallel.
                         Keep low (3) to avoid rate limit issues.
    """
    result = PipelineResult()

    # Ensure schema exists
    await init_db()
    await ensure_demand_signals_table()

    # Build connector list
    all_connectors = build_connector_registry()
    if connector_names:
        connectors = [c for c in all_connectors if c.source_name in connector_names]
        if not connectors:
            logger.warning(f"No connectors matched: {connector_names}")
            return result
    else:
        connectors = all_connectors

    logger.info(
        f"Starting ingestion pipeline: {len(connectors)} connectors, "
        f"concurrency={concurrency}"
    )

    # Run with bounded concurrency using a semaphore
    sem = asyncio.Semaphore(concurrency)

    async def _run_with_sem(connector: BaseConnector) -> ConnectorResult:
        async with sem:
            return await run_connector(connector)

    tasks = [_run_with_sem(c) for c in connectors]
    connector_results = await asyncio.gather(*tasks, return_exceptions=False)
    result.connector_results = list(connector_results)
    result.finished_at = datetime.utcnow()

    logger.info("\n" + result.summary())
    return result


# ── CLI entry point ───────────────────────────────────────────────────────────

async def run_pipeline_cli(connector_filter: str = None):
    """Entry point for running from command line or scripts."""
    names = [connector_filter] if connector_filter else None
    result = await run_pipeline(connector_names=names)
    print(result.summary())
    return result


if __name__ == "__main__":
    import sys
    connector_filter = sys.argv[1] if len(sys.argv) > 1 else None
    asyncio.run(run_pipeline_cli(connector_filter))
