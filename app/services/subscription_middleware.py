"""
Subscription Middleware
=======================
Checks subscription status before allowing PI report generation.
Users without an active subscription (trial or paid) are blocked
and redirected to the pricing/checkout page.

Free actions (always allowed):
- Signal index browsing
- Clinical needs browsing
- Account management
- Billing endpoints

Gated actions (require active subscription):
- POST /api/v1/alignment/pi-report
- POST /api/v1/trial-sites
- POST /api/v1/portfolio/analyze
- POST /api/v1/grant/generate
"""
import logging
from datetime import datetime, timezone
from fastapi import HTTPException
from app.db.user_repository import get_user_by_id

logger = logging.getLogger(__name__)

GATED_PATHS = {
    "/api/v1/alignment/pi-report",
    "/api/v1/trial-sites",
    "/api/v1/portfolio/analyze",
    "/api/v1/grant/generate",
}


async def check_subscription(user_id: int, path: str) -> dict:
    """
    Check if user has an active subscription for gated paths.
    Returns subscription info dict.
    Raises HTTPException 402 if not subscribed.
    """
    if path not in GATED_PATHS:
        return {"allowed": True}

    status    = user.get("subscription_status", "none")
    trial_end = user.get("trial_ends_at")
    now       = datetime.now(timezone.utc)

    # Active paid subscription
    if status == "active":
        return {"allowed": True, "status": "active"}

    # Trial period — check if still valid
    if status == "trialing" and trial_end:
        if isinstance(trial_end, datetime):
            trial_end_aware = trial_end.replace(tzinfo=timezone.utc) if trial_end.tzinfo is None else trial_end
        else:
            trial_end_aware = trial_end
        if now < trial_end_aware:
            days_left = (trial_end_aware - now).days
            return {"allowed": True, "status": "trialing", "days_left": days_left}

    # No subscription or expired trial
    raise HTTPException(
        status_code=402,
        detail={
            "error":   "subscription_required",
            "message": "Your 7-day free trial has ended. Subscribe to continue.",
            "action":  "subscribe",
        }
    )
