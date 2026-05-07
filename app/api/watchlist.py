"""
Watchlist & Alerts API
======================
POST /api/v1/watchlists              — create watchlist
GET  /api/v1/watchlists              — list user's watchlists
DELETE /api/v1/watchlists/{id}       — delete watchlist

GET  /api/v1/alerts                  — get all alerts (with unread count)
GET  /api/v1/alerts/unread-count     — just the count (for notification bell)
GET  /api/v1/alerts/watchlist/{id}   — alerts for a specific watchlist
POST /api/v1/alerts/mark-seen        — mark alerts as seen
POST /api/v1/alerts/mark-all-seen    — mark all as seen

POST /api/v1/watchlists/from-report  — one-click create from PI report
POST /api/v1/admin/alerts/run-match  — manually trigger the weekly matcher
"""
import logging
from fastapi import APIRouter, HTTPException, Depends
from typing import Optional, List
from pydantic import BaseModel

from app.models.watchlist import CreateWatchlistRequest, Watchlist, Alert, AlertSummary
from app.api.auth import get_current_user
from app.db.watchlist_repository import (
    create_watchlist, get_user_watchlists, get_watchlist_by_id,
    delete_watchlist, get_user_alerts, get_watchlist_alerts,
    mark_alerts_seen, get_unread_count,
)

logger = logging.getLogger(__name__)
router       = APIRouter()
admin_router = APIRouter()


# ── Watchlists ────────────────────────────────────────────────────────────────

@router.post("", response_model=Watchlist)
async def create(
    payload:      CreateWatchlistRequest,
    current_user: dict = Depends(get_current_user),
):
    """Create a new demand surveillance watchlist."""
    return await create_watchlist(
        user_id             = current_user['id'],
        name                = payload.name,
        disease_domain      = payload.disease_domain,
        product_description = payload.product_description,
        keywords            = payload.keywords,
    )


@router.get("", response_model=List[Watchlist])
async def list_watchlists(current_user: dict = Depends(get_current_user)):
    """List all watchlists for the current user."""
    return await get_user_watchlists(current_user['id'])


@router.delete("/{watchlist_id}")
async def remove(
    watchlist_id: int,
    current_user: dict = Depends(get_current_user),
):
    deleted = await delete_watchlist(watchlist_id, current_user['id'])
    if not deleted:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    return {"deleted": True}


class FromReportRequest(BaseModel):
    report_name:         str
    disease_domain:      str
    product_description: str
    keywords:            List[str] = []


@router.post("/from-report", response_model=Watchlist)
async def create_from_report(
    payload:      FromReportRequest,
    current_user: dict = Depends(get_current_user),
):
    """One-click: create a watchlist from a PI report's expert domain and keywords."""
    return await create_watchlist(
        user_id             = current_user['id'],
        name                = f"Alert: {payload.report_name}",
        disease_domain      = payload.disease_domain,
        product_description = payload.product_description,
        keywords            = payload.keywords,
    )


# ── Alerts ────────────────────────────────────────────────────────────────────

@router.get("/alerts", response_model=List[Alert])
async def get_alerts(
    unread_only:  bool = False,
    limit:        int  = 50,
    current_user: dict = Depends(get_current_user),
):
    """Get all alerts for the current user."""
    return await get_user_alerts(
        current_user['id'], limit=limit, unread_only=unread_only)


@router.get("/alerts/unread-count")
async def unread_count(current_user: dict = Depends(get_current_user)):
    """Get unread alert count for the notification bell."""
    count = await get_unread_count(current_user['id'])
    return {"unread_count": count}


@router.get("/alerts/watchlist/{watchlist_id}", response_model=List[Alert])
async def watchlist_alerts(
    watchlist_id: int,
    current_user: dict = Depends(get_current_user),
):
    """Get alerts for a specific watchlist."""
    return await get_watchlist_alerts(watchlist_id, current_user['id'])


class MarkSeenRequest(BaseModel):
    alert_ids: Optional[List[int]] = None


@router.post("/alerts/mark-seen")
async def mark_seen(
    payload:      MarkSeenRequest,
    current_user: dict = Depends(get_current_user),
):
    """Mark specific alerts as seen."""
    await mark_alerts_seen(current_user['id'], payload.alert_ids)
    return {"updated": True}


@router.post("/alerts/mark-all-seen")
async def mark_all_seen(current_user: dict = Depends(get_current_user)):
    """Mark all alerts as seen."""
    await mark_alerts_seen(current_user['id'])
    return {"updated": True}


# ── Admin ─────────────────────────────────────────────────────────────────────

@admin_router.post("/alerts/run-match")
async def run_match_manually():
    """
    Manually trigger the weekly alert matching job.
    Useful for testing and for first-run setup.
    """
    from app.services.alert_matcher import run_weekly_match
    result = await run_weekly_match()
    return result


@admin_router.post("/alerts/send-digests")
async def send_digests_manually():
    """Manually trigger digest email sending."""
    from app.services.email_service import send_all_weekly_digests
    await send_all_weekly_digests()
    return {"status": "digests sent"}
