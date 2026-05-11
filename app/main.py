from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import needs
from app.api.demand import admin_router, demand_router
from app.api.alignment import router as alignment_router
from app.api.auth import router as auth_router
from app.api.watchlist import router as watchlist_router, admin_router as watchlist_admin_router
from app.api.features import trial_router, portfolio_router, grant_router
from app.api.billing import router as billing_router
from app.api.tracker import router as tracker_router
from app.db.database import init_db
from app.db.demand_repository import ensure_demand_signals_table
from app.core.config import settings

app = FastAPI(
    title="Project Elevate API",
    description="Healthcare innovation demand intelligence platform",
    version="0.2.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup():
    # Initialize DB tables (hospital_needs from Step 1, demand_signals new)
    await init_db()
    await ensure_demand_signals_table()
    from app.db.user_repository import init_user_tables
    await init_user_tables()
    from app.db.watchlist_repository import init_watchlist_tables
    await init_watchlist_tables()

    # Start the ingestion scheduler if enabled
    if settings.ENABLE_SCHEDULER:
        from app.scheduler.ingestion_scheduler import init_scheduler
        init_scheduler()

@app.on_event("shutdown")
async def shutdown():
    if settings.ENABLE_SCHEDULER:
        from app.scheduler.ingestion_scheduler import shutdown_scheduler
        shutdown_scheduler()

# ── Routes ────────────────────────────────────────────────────────────────────
# Step 1: hospital need submissions
app.include_router(needs.router,         prefix="/api/v1/needs",   tags=["needs"])

# Step 2: demand signal ingestion + search
app.include_router(demand_router,        prefix="/api/v1/demand",  tags=["demand"])
app.include_router(admin_router,         prefix="/api/v1/admin",   tags=["admin"])

# Step 3: inventor alignment
app.include_router(alignment_router,     prefix="/api/v1/alignment", tags=["alignment"])

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
app.include_router(tracker_router,   prefix="/api/v1", tags=["tracker"])

@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "service": "project-elevate",
        "version": "0.2.0",
        "scheduler_enabled": settings.ENABLE_SCHEDULER,
    }



@app.get("/debug/env-full")
def debug_env_full():
    import os
    # Find anything anthropic-related
    anthropic_vars = {k: v[:10]+"..." for k,v in os.environ.items() if "anthrop" in k.lower()}
    all_keys = [k for k in os.environ.keys()]
    return {
        "anthropic_related": anthropic_vars,
        "all_var_names": sorted(all_keys),
        "total_vars": len(all_keys)
    }

@app.get("/debug/env-check")
def debug_env_check():
    import os
    # Scan all env vars stripping whitespace from key names
    key = ""
    for k, v in os.environ.items():
        if k.strip() == "ANTHROPIC_API_KEY" and v.strip():
            key = v.strip()
            break
    # Also check settings object
    from app.core.config import settings
    settings_key = settings.ANTHROPIC_API_KEY
    return {
        "anthropic_key_present": bool(key),
        "anthropic_key_prefix": key[:14] + "..." if key else None,
        "anthropic_key_length": len(key) if key else 0,
        "settings_key_present": bool(settings_key),
        "settings_key_length": len(settings_key),
        "has_openai_key": bool(os.getenv("OPENAI_API_KEY")),
        "has_database_url": bool(os.getenv("DATABASE_URL")),
    }


# ── Weekly Tracker Scheduler ──────────────────────────────────────────────────
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import asyncio

_tracker_scheduler = AsyncIOScheduler(timezone="UTC")

@app.on_event("startup")
async def start_tracker_scheduler():
    from app.services.weekly_tracker import run_weekly_tracker
    _tracker_scheduler.add_job(
        lambda: asyncio.create_task(run_weekly_tracker()),
        trigger="cron", day_of_week="mon", hour=8, minute=0,
        id="weekly_tracker", replace_existing=True
    )
    _tracker_scheduler.start()
    import logging; logging.getLogger(__name__).info("Weekly tracker scheduler started")
