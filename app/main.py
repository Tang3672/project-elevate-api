from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import needs
from app.api.demand import admin_router, demand_router
from app.api.alignment import router as alignment_router
from app.api.auth import router as auth_router
from app.api.pdf import router as pdf_router
from app.api.watchlist import router as watchlist_router, admin_router as watchlist_admin_router
from app.api.features import trial_router, portfolio_router, grant_router
from app.api.billing import router as billing_router
from app.api.tracker import router as tracker_router
from app.api.etl import router as etl_router
from app.api.timeline import router as timeline_router
from app.db.database import init_db
from app.db.demand_repository import ensure_demand_signals_table
from app.core.config import settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle for the FastAPI application."""
    # ── Startup ────────────────────────────────────────────────────────────────
    import asyncio as _asyncio
    _asyncio.ensure_future(_init_background())
    yield
    # ── Shutdown ───────────────────────────────────────────────────────────────
    if settings.ENABLE_SCHEDULER:
        from app.scheduler.ingestion_scheduler import shutdown_scheduler
        shutdown_scheduler()
    # BUG-62: _tracker_scheduler was never shut down — process hung on container restart
    if _tracker_scheduler.running:
        _tracker_scheduler.shutdown(wait=False)
    # BUG-48A: asyncpg pool was never closed on shutdown, leaking connections on every
    # container restart.  close_db() sets _pool=None so any stray coroutine that calls
    # get_pool() after shutdown gets a fresh pool rather than a closed one.
    from app.db.database import close_db
    await close_db()


app = FastAPI(
    title="Medlevate API",
    description="Medical market intelligence for tech transfer offices, health innovators, and researchers",
    version="0.2.0",
    lifespan=lifespan,
)

# CORS — restricted to the Netlify frontends (prod + staging + preview deploys) and
# localhost for dev, instead of a wide-open "*". Extra origins (e.g. a future custom
# domain) can be added via the ALLOWED_ORIGINS setting (comma-separated).
_extra_origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]
# "null" allows file:// local HTML (Origin: null) used during dev/staging.
# allow_credentials=False: frontend uses Bearer tokens in headers, not cookies,
# so CORS credentials mode is not needed — and Chrome rejects Allow-Origin:null
# combined with Allow-Credentials:true.
_allow_origins = list({"null", "https://medlevate.com", "https://www.medlevate.com"} | set(_extra_origins))
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_origin_regex=r"https://(www\.)?medlevate\.com|https://([a-z0-9-]+\.)*netlify\.app|http://localhost(:\d+)?|http://127\.0\.0\.1(:\d+)?",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Security response headers (HSTS, nosniff, no-frame, referrer policy, …).
from app.middleware.security_headers import SecurityHeadersMiddleware
app.add_middleware(SecurityHeadersMiddleware)

# Rate limiting — protects Anthropic/OpenAI API tokens from abuse
from app.middleware.rate_limit import RateLimitMiddleware
app.add_middleware(RateLimitMiddleware)


# Global exception handler — never leak a stack trace; return a clean JSON 500.
from fastapi import Request as _Request
from fastapi.responses import JSONResponse as _JSONResponse
import logging as _logging
_log = _logging.getLogger("app.errors")


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: _Request, exc: Exception):
    _log.error("Unhandled error on %s %s: %s", request.method, request.url.path, exc, exc_info=True)
    return _JSONResponse(status_code=500, content={
        "detail": "An unexpected error occurred. Please try again.",
        "error": "internal_error",
    })

async def _init_background():
    import logging, asyncio as _asyncio
    _log = logging.getLogger(__name__)
    # BUG-64: warn loudly if JWT secret is still the well-known default from source control
    _JWT_DEFAULT = "project-elevate-dev-secret-change-in-production"
    if settings.JWT_SECRET == _JWT_DEFAULT:
        _log.warning("⚠️  JWT_SECRET is the default dev value — all tokens are forgeable. Set JWT_SECRET in production.")
    # BUG-31a: short JWT secrets (< 32 chars) are trivially brute-forced; warn loudly in any env
    elif len(settings.JWT_SECRET) < 32:
        _log.warning("⚠️  JWT_SECRET is only %d characters — use at least 32 random characters to prevent brute-force forgery.", len(settings.JWT_SECRET))
    # Warn if required API keys are missing — every report call will fail silently without these
    if not settings.ANTHROPIC_API_KEY:
        _log.warning("⚠️  ANTHROPIC_API_KEY is not set — all PI report and LLM calls will fail. Set this in Railway environment variables.")
    if not settings.STRIPE_SECRET_KEY:
        _log.warning("⚠️  STRIPE_SECRET_KEY is not set — billing and subscription endpoints will fail.")
    if not settings.STRIPE_WEBHOOK_SECRET:
        _log.warning("⚠️  STRIPE_WEBHOOK_SECRET is not set — Stripe webhook verification will fail and billing events will be silently dropped.")
    try:
        await init_db()
        await ensure_demand_signals_table()
        from app.db.user_repository import init_user_tables
        await init_user_tables()
        from app.db.watchlist_repository import init_watchlist_tables
        await init_watchlist_tables()
        from app.services.pi_memory_service import init_pi_memory_table
        await init_pi_memory_table()
        from app.services.research_world_model import init_world_model_table
        await init_world_model_table()
        from app.db.market_sizing_repository import init_market_sizing_tables
        await init_market_sizing_tables()
        from app.services.world_model_graph import init_world_model_graph
        await init_world_model_graph()
        from app.db.reports_repository import init_reports_tables
        await init_reports_tables()
        from app.db.prompt_sessions_repository import init_prompt_sessions_tables
        await init_prompt_sessions_tables()
        from app.services.report_jobs import init_report_jobs_table
        await init_report_jobs_table()
        from app.db.schema_ontology import init_ontology_tables
        await init_ontology_tables()
        from app.db.schema_priors import init_priors_tables
        await init_priors_tables()
        from app.db.disease_aggregate import ensure_aggregate_table
        await ensure_aggregate_table()
        try:
            from app.db.database import get_pool
            pool = await get_pool()
            async with pool.acquire() as conn:
                from app.services.universe_expander import prescored_universe_table
                await prescored_universe_table(conn)
        except Exception as _e:
            _log.warning("prescored_universe_table failed (non-fatal): %s", _e)
        _log.info("DB initialization complete")
    except Exception as e:
        _log.error("DB initialization failed (non-fatal): %s", e)

    # BUG-44b: On Railway multi-replica deployments every replica starts its own
    # in-process APScheduler, causing all ingestion jobs and weekly-tracker emails
    # to fire once per replica.  Guard: only run schedulers on the primary replica.
    # Railway sets RAILWAY_REPLICA_ID on each instance; when it is absent the app
    # runs on a single instance (scheduler always runs).  On multi-replica deploys
    # set SCHEDULER_PRIMARY=true on exactly one service/instance via Railway env vars.
    _replica_id  = settings.RAILWAY_REPLICA_ID
    _is_primary  = (not _replica_id) or (settings.SCHEDULER_PRIMARY.lower() == "true")

    # Start the ingestion scheduler if enabled
    if settings.ENABLE_SCHEDULER and _is_primary:
        from app.scheduler.ingestion_scheduler import init_scheduler
        init_scheduler()
    elif settings.ENABLE_SCHEDULER and not _is_primary:
        _log.info("Ingestion scheduler skipped on non-primary replica (RAILWAY_REPLICA_ID=%s)", _replica_id)

    # BUG-25: start tracker scheduler here (after DB init succeeds) instead of
    # a separate @app.on_event("startup") that fires unconditionally
    if _is_primary:
        try:
            from app.services.weekly_tracker import run_weekly_tracker
            import asyncio as _asyncio2
            _tracker_scheduler.add_job(
                lambda: _asyncio2.ensure_future(run_weekly_tracker()),
                trigger="cron", day_of_week="mon", hour=8, minute=0,
                id="weekly_tracker", replace_existing=True
            )
            _tracker_scheduler.start()
            _log.info("Weekly tracker scheduler started")
        except Exception as _sched_err:
            _log.error("Weekly tracker scheduler failed to start: %s", _sched_err)
    else:
        _log.info("Weekly tracker scheduler skipped on non-primary replica (RAILWAY_REPLICA_ID=%s)", _replica_id)


# ── Routes ────────────────────────────────────────────────────────────────────
# Step 1: hospital need submissions
app.include_router(needs.router,         prefix="/api/v1/needs",   tags=["needs"])

# Step 2: demand signal ingestion + search
app.include_router(demand_router,        prefix="/api/v1/demand",  tags=["demand"])
app.include_router(admin_router,         prefix="/api/v1/admin",   tags=["admin"])

# Step 3: inventor alignment
app.include_router(alignment_router,     prefix="/api/v1/alignment", tags=["alignment"])

# P2: PDF / HTML report export
app.include_router(pdf_router,           prefix="/api/v1",              tags=["pdf"])

# Step 4: user accounts
app.include_router(auth_router,          prefix="/api/v1/auth",        tags=["auth"])

# Step 5: watchlists & alerts
app.include_router(watchlist_router,       prefix="/api/v1/watchlists",  tags=["watchlists"])
app.include_router(watchlist_admin_router, prefix="/api/v1/admin",       tags=["admin"])

# Step 6: clinical roadmap, portfolio, grant co-pilot
app.include_router(trial_router,     prefix="/api/v1", tags=["clinical-roadmap"])
app.include_router(portfolio_router, prefix="/api/v1", tags=["portfolio"])
app.include_router(grant_router,     prefix="/api/v1", tags=["grant"])
app.include_router(billing_router,   prefix="/api/v1", tags=["billing"])
app.include_router(etl_router,       prefix="/api/v1/etl",      tags=["etl"])
app.include_router(timeline_router,  prefix="/api/v1/timeline", tags=["timeline"])
app.include_router(tracker_router,   prefix="/api/v1", tags=["tracker"])

@app.get("/health")
async def health_check():
    signal_stats: dict = {}
    try:
        from app.db.demand_repository import get_signal_counts_by_source
        rows = await get_signal_counts_by_source()
        total = sum(r["count"] for r in rows)
        last_fetched = max(
            (r["last_fetched"] for r in rows if r.get("last_fetched")),
            default=None,
        )
        signal_stats = {
            "total_signals": total,
            "last_ingested_at": last_fetched.isoformat() if last_fetched else None,
            "sources": {r["source"]: r["count"] for r in rows},
        }
    except Exception as _e:
        _log.warning("health check signal stats query failed: %s", _e)
        signal_stats = {"total_signals": None, "last_ingested_at": None}

    # Strip per-source breakdown to avoid enumerating internal connector names
    # to unauthenticated callers. Only surface aggregate counts.
    safe_signals = {
        "total_signals": signal_stats.get("total_signals"),
        "last_ingested_at": signal_stats.get("last_ingested_at"),
    }
    return {
        "status": "ok",
        "version": "0.2.0",
        "signals": safe_signals,
    }


# NOTE: /version endpoint removed — it exposed full git commit SHA and branch
# name to unauthenticated callers (information disclosure / attacker
# fingerprinting) and used a blocking subprocess.check_output call inside
# an async def (event-loop stall). Version is available via the OpenAPI
# /openapi.json spec for authenticated API consumers.





# ── Weekly Tracker Scheduler (started inside _init_background after DB is ready) ─
from apscheduler.schedulers.asyncio import AsyncIOScheduler

_tracker_scheduler = AsyncIOScheduler(timezone="UTC")
