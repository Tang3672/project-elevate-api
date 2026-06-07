"""
Subscription Middleware v3
===========================
Plan-based quota enforcement:
  free        → 1 report total (lifetime), all other tools blocked
  explorer    → 5 reports/month, no validation/timeline/tracker
  innovator   → 20 reports/month, full access
  institution → unlimited, full access

Enforcement is server-side only. try_consume_report() uses an atomic DB
UPDATE ... WHERE ... RETURNING that blocks over-spending even under concurrent
requests — the client cannot hack quotas by replaying requests.

Developer bypass: DEV_EMAILS always get through with unlimited access.
"""
import logging
from datetime import datetime, timezone
from fastapi import HTTPException
from app.db.user_repository import get_user_by_id, try_consume_report, get_usage

logger = logging.getLogger(__name__)

DEV_EMAILS = {
    "test@medlevate.io",
    "ijw91021@gmail.com",
    "admin@medlevate.io",
    "oneonesie100@gmail.com",
}

# Paths that consume a report quota slot
REPORT_PATHS = {"/api/v1/alignment/pi-report"}

# Paths that require Innovator+ (not available on Explorer)
INNOVATOR_PATHS = {
    "/api/v1/trial-sites",
    "/api/v1/tracker/run",
}

# Paths that require any active subscription (Explorer+)
SUBSCRIPTION_PATHS = {
    "/api/v1/portfolio/analyze",
    "/api/v1/grant/generate",
}


def _is_active(user: dict) -> bool:
    status    = user.get("subscription_status", "none")
    trial_end = user.get("trial_ends_at")
    if status == "active":
        return True
    if status == "trialing" and trial_end:
        now = datetime.now(timezone.utc)
        t   = trial_end.replace(tzinfo=timezone.utc) if trial_end.tzinfo is None else trial_end
        return now < t
    return False


async def check_subscription(user_id: int, path: str) -> dict:
    """
    Check access for a user + path. Raises HTTP 402 if blocked.
    For report paths, atomically consumes one quota slot.
    Returns dict with allowed=True and current usage on success.
    """
    user = await get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    email       = user.get("email", "")
    plan        = user.get("plan_name") or "free"
    is_active   = _is_active(user)

    # Developer bypass — unlimited everything
    if email in DEV_EMAILS:
        return {"allowed": True, "status": "developer"}

    # ── Innovator-only tools ──────────────────────────────────────────────────
    if path in INNOVATOR_PATHS:
        if not is_active or plan not in ("innovator", "institution", "professional"):
            raise HTTPException(
                status_code=402,
                detail={
                    "error":   "plan_upgrade_required",
                    "message": "This feature requires the Innovator plan or higher.",
                    "action":  "upgrade",
                    "required_plan": "innovator",
                }
            )
        return {"allowed": True, "status": plan}

    # ── Subscription-required tools (Explorer+) ───────────────────────────────
    if path in SUBSCRIPTION_PATHS:
        if not is_active:
            raise HTTPException(
                status_code=402,
                detail={
                    "error":   "subscription_required",
                    "message": "This tool requires an active subscription.",
                    "action":  "subscribe",
                }
            )
        return {"allowed": True, "status": plan}

    # ── Report path: consume one quota slot ───────────────────────────────────
    if path in REPORT_PATHS:
        result = await try_consume_report(user_id)
        if not result["allowed"]:
            usage = result.get("usage", {})
            raise HTTPException(
                status_code=402,
                detail={
                    "error":           "quota_exceeded",
                    "message":         result["reason"],
                    "action":          "upgrade",
                    "plan":            plan,
                    "reports_used":    usage.get("used", 0),
                    "reports_quota":   usage.get("quota"),
                    "reports_remaining": 0,
                    "reset_at":        usage.get("reset_at"),
                }
            )
        usage = result.get("usage", {})
        return {
            "allowed":           True,
            "status":            plan,
            "reports_used":      usage.get("used", 0),
            "reports_quota":     usage.get("quota"),
            "reports_remaining": usage.get("remaining"),
        }

    return {"allowed": True}
