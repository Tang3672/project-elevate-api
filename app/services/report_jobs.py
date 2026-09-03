"""
Async Report Job Store (DB-backed)
==================================
Full report generation is a ~2-3 minute operation, too long for a single
synchronous HTTP request behind a proxy. The API starts a background job and the
client polls:

  POST /pi-report/async        -> create a job, run generation in the background,
                                  return {job_id} immediately
  GET  /pi-report/status/{id}  -> poll status (running | done | error) + result

Jobs are persisted in Postgres (not in-process memory) so polling still works
after a deploy/restart and across instances — an in-memory store loses every
in-flight job whenever Railway cycles the container. Rows are cleaned up after
an hour. Best-effort: storage failures never crash report delivery.
"""

import json
import uuid
import logging

logger = logging.getLogger(__name__)


async def init_report_jobs_table():
    from app.db.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS report_jobs (
                job_id      TEXT PRIMARY KEY,
                status      TEXT DEFAULT 'running',
                report      JSONB,
                error       TEXT,
                owner_id    TEXT,
                created_at  TIMESTAMPTZ DEFAULT NOW(),
                updated_at  TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        # Idempotent: add owner_id column if migrating an existing table
        await conn.execute("""
            ALTER TABLE report_jobs ADD COLUMN IF NOT EXISTS owner_id TEXT
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS report_jobs_created_idx ON report_jobs (created_at)")
    logger.info("report_jobs table ready")


async def count_running_jobs(owner_id: str) -> int:
    """Return the number of jobs in 'running' state for a given owner."""
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COUNT(*) AS n FROM report_jobs "
                "WHERE owner_id = $1 AND status = 'running' "
                "AND created_at >= NOW() - INTERVAL '15 minutes'",
                str(owner_id),
            )
            return int(row["n"]) if row else 0
    except Exception as exc:
        logger.warning("count_running_jobs failed (non-fatal): %s", exc)
        return 0


async def create_job(owner_id: str | None = None) -> str:
    job_id = uuid.uuid4().hex[:16]
    from app.db.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO report_jobs (job_id, status, owner_id) VALUES ($1, 'running', $2)",
            job_id, str(owner_id) if owner_id is not None else None)
        # Opportunistic cleanup of jobs older than an hour.
        await conn.execute(
            "DELETE FROM report_jobs WHERE created_at < NOW() - INTERVAL '1 hour'")
    return job_id


async def set_done(job_id: str, report: dict) -> None:
    """Persist a completed report. Retries once after a short delay so a
    transient DB hiccup does not silently discard an expensive LLM result."""
    import asyncio as _asyncio
    serialized = json.dumps(report)
    for attempt in range(2):
        try:
            from app.db.database import get_pool
            pool = await get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE report_jobs SET status='done', report=$2::jsonb, updated_at=NOW() "
                    "WHERE job_id=$1", job_id, serialized)
            return  # success
        except Exception as e:
            logger.error("report_jobs.set_done failed for %s (attempt %d): %s",
                         job_id, attempt + 1, e)
            if attempt == 0:
                await _asyncio.sleep(2)  # brief pause before retry


async def set_error(job_id: str, error: str) -> None:
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE report_jobs SET status='error', error=$2, updated_at=NOW() "
                "WHERE job_id=$1", job_id, str(error)[:2000])
    except Exception as e:
        logger.error("report_jobs.set_error failed for %s: %s", job_id, e)


async def update_report(job_id: str, report: dict) -> None:
    """Patch a done job's report in place (e.g. after background verification)."""
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE report_jobs SET report=$2::jsonb, updated_at=NOW() "
                "WHERE job_id=$1 AND status='done'", job_id, json.dumps(report))
    except Exception as e:
        logger.error("report_jobs.update_report failed for %s: %s", job_id, e)


_JOB_TIMEOUT_MINUTES = 15  # jobs stuck in 'running' longer than this are considered crashed


async def get_job(job_id: str) -> dict | None:
    from app.db.database import get_pool
    from datetime import datetime, timezone, timedelta
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, report, error, owner_id, created_at FROM report_jobs WHERE job_id=$1",
            job_id)
    if not row:
        return None
    report = row["report"]
    if isinstance(report, str):          # asyncpg returns JSONB as text
        try:
            report = json.loads(report)
        except (ValueError, TypeError):
            report = None
    status = row["status"]
    # Guard against jobs stuck in 'running' when the worker was killed with SIGKILL
    # (asyncio.CancelledError would normally call set_error, but SIGKILL skips it).
    if status == "running":
        created_at = row["created_at"]
        if created_at is not None:
            # Make timezone-aware for comparison
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - created_at
            if age > timedelta(minutes=_JOB_TIMEOUT_MINUTES):
                status = "error"
                report = None
                error = "Report generation timed out (server restart likely). Please try again."
                return {"status": status, "report": report, "error": error,
                        "owner_id": row["owner_id"]}
    return {"status": status, "report": report, "error": row["error"],
            "owner_id": row["owner_id"]}
