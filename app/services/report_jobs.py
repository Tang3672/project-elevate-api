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
                created_at  TIMESTAMPTZ DEFAULT NOW(),
                updated_at  TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS report_jobs_created_idx ON report_jobs (created_at)")
    logger.info("report_jobs table ready")


async def create_job() -> str:
    job_id = uuid.uuid4().hex[:16]
    from app.db.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO report_jobs (job_id, status) VALUES ($1, 'running')", job_id)
        # Opportunistic cleanup of jobs older than an hour.
        await conn.execute(
            "DELETE FROM report_jobs WHERE created_at < NOW() - INTERVAL '1 hour'")
    return job_id


async def set_done(job_id: str, report: dict) -> None:
    try:
        from app.db.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE report_jobs SET status='done', report=$2::jsonb, updated_at=NOW() "
                "WHERE job_id=$1", job_id, json.dumps(report))
    except Exception as e:
        logger.error("report_jobs.set_done failed for %s: %s", job_id, e)


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


async def get_job(job_id: str) -> dict | None:
    from app.db.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status, report, error FROM report_jobs WHERE job_id=$1", job_id)
    if not row:
        return None
    report = row["report"]
    if isinstance(report, str):          # asyncpg returns JSONB as text
        try:
            report = json.loads(report)
        except (ValueError, TypeError):
            report = None
    return {"status": row["status"], "report": report, "error": row["error"]}
