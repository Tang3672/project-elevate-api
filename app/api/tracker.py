"""
Tracker API endpoints
=====================
GET  /api/v1/tracker/run       — manually trigger tracker for current user (testing)
GET  /api/v1/tracker/status    — get last run status
POST /api/v1/tracker/run-all   — admin: trigger all watchlists (admin only)
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from app.api.auth import get_current_user
from app.services.weekly_tracker import run_tracker_for_user, run_weekly_tracker

logger = logging.getLogger(__name__)
router = APIRouter()

ADMIN_EMAILS = {"ijw91021@gmail.com", "admin@projectelevate.io", "test@projectelevate.io"}


@router.post("/tracker/run")
async def trigger_tracker(current_user: dict = Depends(get_current_user)):
    """Manually trigger weekly tracker for the current user's watchlists."""
    try:
        results = await run_tracker_for_user(current_user["id"])
        return {
            "status":          "complete",
            "watchlists_scanned": len(results),
            "recalculations_needed": sum(1 for r in results if r.get("recalculation_needed")),
            "results":         results,
        }
    except Exception as e:
        logger.error(f"Manual tracker run failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tracker/run-all")
async def trigger_all(current_user: dict = Depends(get_current_user)):
    """Admin: trigger tracker for all users."""
    if current_user.get("email") not in ADMIN_EMAILS:
        raise HTTPException(status_code=403, detail="Admin only")
    results = await run_weekly_tracker()
    return {"status": "complete", "processed": len(results) if results else 0}
