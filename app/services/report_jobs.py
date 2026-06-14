"""
Async Report Job Store
======================
Full report generation is a ~2-3 minute operation (rich multi-source synthesis),
which doesn't fit reliably in a single synchronous HTTP request behind a proxy.
This is a tiny in-process job registry so the API can:

  POST /pi-report/async        -> create a job, run generation in the background,
                                  return {job_id} immediately
  GET  /pi-report/status/{id}  -> poll status (running | done | error) + result

In-memory is sufficient: the backend runs a single uvicorn worker, so the
background task and the poll endpoint share this dict. Jobs expire after a TTL.
(If multi-worker/multi-instance is ever introduced, swap this for a DB/Redis
backing store — the interface stays the same.)
"""

import time
import uuid
import logging

logger = logging.getLogger(__name__)

_JOBS: dict[str, dict] = {}
_TTL_S = 1800  # jobs expire 30 min after creation


def _cleanup() -> None:
    now = time.time()
    stale = [jid for jid, v in _JOBS.items() if now - v["created_at"] > _TTL_S]
    for jid in stale:
        _JOBS.pop(jid, None)


def create_job() -> str:
    _cleanup()
    jid = uuid.uuid4().hex[:16]
    _JOBS[jid] = {"status": "running", "report": None, "error": None,
                  "created_at": time.time()}
    return jid


def set_done(job_id: str, report: dict) -> None:
    if job_id in _JOBS:
        _JOBS[job_id].update(status="done", report=report)


def set_error(job_id: str, error: str) -> None:
    if job_id in _JOBS:
        _JOBS[job_id].update(status="error", error=error)


def get_job(job_id: str) -> dict | None:
    return _JOBS.get(job_id)
