"""
Ingestion Scheduler
====================
Uses APScheduler to run connectors on their natural cadences:

  Weekly (Fridays 6am UTC):
    - CDCWastewater, CDCFluView       — real-time surveillance
    - ClinicalTrials                  — trial pipeline changes weekly
    - FDARecalls                      — new recalls issued frequently

  Monthly (1st of month, 2am UTC):
    - FDAAdverseEvents, FDADeviceEvents
    - CMSHospitalQuality
    - HRSAShortage

  Quarterly (1st of Jan/Apr/Jul/Oct, 1am UTC):
    - CDCPlaces                       — annual data, but check for updates
    - CensusSAHIE                     — annual data

Also exposes a manual trigger endpoint for ad-hoc runs.
"""

import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.ingestion.pipeline import run_pipeline

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="UTC")


def init_scheduler():
    """Register all ingestion jobs with their schedules."""

    # ── Weekly: real-time signals ─────────────────────────────────────────────
    scheduler.add_job(
        _run_weekly_realtime,
        CronTrigger(day_of_week="fri", hour=6, minute=0),
        id="weekly_realtime",
        name="Weekly real-time surveillance connectors",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # ── Monthly: safety and quality signals ──────────────────────────────────
    scheduler.add_job(
        _run_monthly_safety,
        CronTrigger(day=1, hour=2, minute=0),
        id="monthly_safety",
        name="Monthly FDA + CMS + clinical trials connectors",
        replace_existing=True,
        misfire_grace_time=7200,
    )

    # ── Quarterly: population baseline signals ────────────────────────────────
    scheduler.add_job(
        _run_quarterly_baseline,
        CronTrigger(month="1,4,7,10", day=1, hour=1, minute=0),
        id="quarterly_baseline",
        name="Quarterly CDC PLACES + Census SAHIE + HRSA connectors",
        replace_existing=True,
        misfire_grace_time=14400,
    )

    scheduler.start()
    logger.info("✅ Ingestion scheduler started")
    _log_next_runs()


def shutdown_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Ingestion scheduler stopped")


async def _run_weekly_realtime():
    logger.info("⏰ Running weekly real-time connectors")
    await run_pipeline(connector_names=[
        "cdc_wastewater",
        "cdc_fluview",
        "clinical_trials",
        "fda_recalls",
    ])


async def _run_monthly_safety():
    logger.info("⏰ Running monthly safety/quality connectors")
    await run_pipeline(connector_names=[
        "fda_adverse_events",
        "fda_device_events",
        "cms_hospital_quality",
        "hrsa_shortage",
    ])


async def _run_quarterly_baseline():
    logger.info("⏰ Running quarterly baseline connectors")
    await run_pipeline(connector_names=[
        "cdc_places",
        "census_sahie",
    ])


def _log_next_runs():
    """Log when each job will next fire."""
    for job in scheduler.get_jobs():
        next_run = job.next_run_time
        logger.info(f"  📅 {job.name}: next run at {next_run}")


async def trigger_connector(connector_name: str) -> dict:
    """
    Manually trigger a single connector by name.
    Called from the admin API endpoint.
    """
    logger.info(f"Manual trigger: {connector_name}")
    result = await run_pipeline(connector_names=[connector_name])
    return {
        "connector": connector_name,
        "inserted": result.total_inserted,
        "skipped": result.total_skipped,
        "errors": result.total_errors,
        "duration_seconds": result.duration_seconds,
    }


async def trigger_full_pipeline() -> dict:
    """Manually trigger the full pipeline (all connectors)."""
    logger.info("Manual full pipeline trigger")
    result = await run_pipeline()
    return {
        "connectors_run": len(result.connector_results),
        "total_inserted": result.total_inserted,
        "total_skipped": result.total_skipped,
        "total_errors": result.total_errors,
        "duration_seconds": result.duration_seconds,
        "details": [
            {
                "connector": r.connector_name,
                "inserted": r.inserted,
                "skipped": r.skipped,
                "errors": r.errors,
                "duration": r.duration_seconds,
            }
            for r in result.connector_results
        ],
    }
