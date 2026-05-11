"""
Subscription Middleware v2
===========================
Access rules:
  - Not logged in:           blocked everywhere (signup required)
  - Logged in, 0 free reports used, active sub: full access
  - Logged in, 0 free reports used, no sub:  1 free PI report only, all other tools blocked
  - Logged in, 1+ free reports used, no sub: paywall on everything
  - Subscribed (active):     full access to everything
  - Developer emails:        always full access

Gated paths:
  - /api/v1/alignment/pi-report  → 1 free report allowed
  - /api/v1/trial-sites          → subscription required
  - /api/v1/portfolio/analyze    → subscription required
  - /api/v1/grant/generate       → subscription required
  - /api/v1/tracker/run          → subscription required
"""
import logging
from datetime import datetime, timezone
from fastapi import HTTPException
from app.db.user_repository import get_user_by_id

logger = logging.getLogger(__name__)

DEV_EMAILS = {
    "test@projectelevate.io",
    "ijw91021@gmail.com",
    "admin@projectelevate.io",
}

# Paths that require full subscription (no free tier)
SUBSCRIPTION_ONLY_PATHS = {
    "/api/v1/trial-sites",
    "/api/v1/portfolio/analyze",
    "/api/v1/grant/generate",
    "/api/v1/tracker/run",
}

# Paths where 1 free report is allowed
FREE_REPORT_PATH = "/api/v1/alignment/pi-report"


async def check_subscription(user_id: int, path: str) -> dict:
    """
    Check access for a given user and path.
    Returns dict with allowed status.
    Raises HTTPException 402 if not allowed.
    """
    user = await get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    email  = user.get("email", "")
    status = user.get("subscription_status", "none")
    trial_end = user.get("trial_ends_at")
    free_used = user.get("free_reports_used", 0)
    now = datetime.now(timezone.utc)

    # ── Developer bypass ──────────────────────────────────────────────────────
    if email in DEV_EMAILS:
        return {"allowed": True, "status": "developer"}

    # ── Check if subscription is active ───────────────────────────────────────
    is_subscribed = status == "active"
    if status == "trialing" and trial_end:
        trial_end_aware = trial_end.replace(tzinfo=timezone.utc) if trial_end.tzinfo is None else trial_end
        is_subscribed = now < trial_end_aware

    if is_subscribed:
        return {"allowed": True, "status": status}

    # ── Subscription-only tools (no free tier) ────────────────────────────────
    if path in SUBSCRIPTION_ONLY_PATHS:
        raise HTTPException(
            status_code=402,
            detail={
                "error":   "subscription_required",
                "message": "This tool requires an active subscription.",
                "action":  "subscribe",
                "tool_locked": True,
            }
        )

    # ── PI Report: 1 free report allowed ──────────────────────────────────────
    if path == FREE_REPORT_PATH:
        if free_used == 0:
            # Allow — will be incremented after report completes
            return {"allowed": True, "status": "free_trial", "free_reports_remaining": 1}
        else:
            raise HTTPException(
                status_code=402,
                detail={
                    "error":   "subscription_required",
                    "message": "You've used your 1 free report. Subscribe to run unlimited reports.",
                    "action":  "subscribe",
                    "free_report_used": True,
                }
            )

    return {"allowed": True}
