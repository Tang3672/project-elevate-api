from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api import needs
from app.api.demand import admin_router, demand_router
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
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
async def startup():
    # Initialize DB tables (hospital_needs from Step 1, demand_signals new)
    await init_db()
    await ensure_demand_signals_table()

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

@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "service": "project-elevate",
        "version": "0.2.0",
        "scheduler_enabled": settings.ENABLE_SCHEDULER,
    }
