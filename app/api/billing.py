"""
Billing API
===========
POST /api/v1/billing/create-checkout  — create Stripe checkout session
POST /api/v1/billing/webhook          — Stripe webhook handler
GET  /api/v1/billing/status           — get current subscription status
POST /api/v1/billing/cancel           — cancel subscription
"""
import logging
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import JSONResponse

from app.api.auth import get_current_user
from app.services.stripe_service import (
    create_checkout_session, get_subscription_status,
    construct_webhook_event, cancel_subscription
)
from app.db.user_repository import (
    get_user_by_id, update_user_subscription
)
from app.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/billing/create-checkout")
async def create_checkout(
    request:      Request,
    current_user: dict = Depends(get_current_user),
):
    """Create a Stripe Checkout session and return the URL."""
    origin = request.headers.get("origin", "https://preeminent-zuccutto-bd1f9d.netlify.app")
    success_url = f"{origin}/billing/success?session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url  = f"{origin}/billing/cancel"

    try:
        checkout_url = await create_checkout_session(
            user_id     = current_user["id"],
            user_email  = current_user["email"],
            success_url = success_url,
            cancel_url  = cancel_url,
        )
        return {"checkout_url": checkout_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/billing/status")
async def billing_status(current_user: dict = Depends(get_current_user)):
    """Get current subscription status for the logged-in user."""
    user = await get_user_by_id(current_user["id"])
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    sub_status = user.get("subscription_status", "none")
    trial_ends = user.get("trial_ends_at")
    stripe_id  = user.get("stripe_customer_id")

    # Check if trial is still active
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    is_active = sub_status in ("active", "trialing")
    if trial_ends and sub_status == "trialing":
        if hasattr(trial_ends, 'replace'):
            trial_ends_aware = trial_ends.replace(tzinfo=timezone.utc) if trial_ends.tzinfo is None else trial_ends
            is_active = now < trial_ends_aware

    return {
        "subscription_status": sub_status,
        "is_active":           is_active,
        "trial_ends_at":       trial_ends.isoformat() if trial_ends else None,
        "stripe_customer_id":  stripe_id,
        "plan":                "starter" if is_active else "none",
    }


@router.post("/billing/cancel")
async def cancel_sub(current_user: dict = Depends(get_current_user)):
    """Cancel subscription at end of current period."""
    user = await get_user_by_id(current_user["id"])
    stripe_id = user.get("stripe_customer_id") if user else None
    if not stripe_id:
        raise HTTPException(status_code=400, detail="No active subscription")
    success = await cancel_subscription(stripe_id)
    if success:
        await update_user_subscription(
            user_id=current_user["id"],
            subscription_status="cancel_pending",
        )
    return {"cancelled": success}


@router.post("/billing/webhook")
async def stripe_webhook(request: Request):
    """
    Stripe webhook handler.
    Verifies signature, processes subscription lifecycle events,
    updates user subscription status in database.
    """
    payload    = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = construct_webhook_event(payload, sig_header)
    except Exception as e:
        logger.error(f"Webhook signature verification failed: {e}")
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    event_type = event["type"]
    data       = event["data"]["object"]
    logger.info(f"Stripe webhook: {event_type}")

    try:
        if event_type == "checkout.session.completed":
            await _handle_checkout_completed(data)

        elif event_type == "customer.subscription.created":
            await _handle_subscription_created(data)

        elif event_type == "customer.subscription.updated":
            await _handle_subscription_updated(data)

        elif event_type == "customer.subscription.deleted":
            await _handle_subscription_deleted(data)

    except Exception as e:
        logger.error(f"Webhook processing error for {event_type}: {e}")
        # Return 200 so Stripe doesn't retry — log and investigate separately
        return JSONResponse({"status": "error_logged"})

    return JSONResponse({"status": "ok"})


# ── Webhook handlers ──────────────────────────────────────────────────────────

async def _handle_checkout_completed(session: dict):
    """User completed checkout — link Stripe customer to our user."""
    user_id     = session.get("metadata", {}).get("user_id")
    customer_id = session.get("customer")
    if not user_id or not customer_id:
        logger.warning("checkout.session.completed missing user_id or customer")
        return

    await update_user_subscription(
        user_id             = int(user_id),
        stripe_customer_id  = customer_id,
        subscription_status = "trialing",
    )
    logger.info(f"User {user_id} linked to Stripe customer {customer_id}")


async def _handle_subscription_created(sub: dict):
    """Subscription created — set status and trial end date."""
    user_id  = sub.get("metadata", {}).get("user_id")
    status   = sub.get("status", "trialing")
    trial_end = sub.get("trial_end")
    customer_id = sub.get("customer")

    if not user_id:
        # Try to find user by customer ID
        user_id = await _get_user_id_by_customer(customer_id)
    if not user_id:
        logger.warning(f"subscription.created — no user_id found for customer {customer_id}")
        return

    from datetime import datetime, timezone
    trial_ends_at = datetime.fromtimestamp(trial_end, tz=timezone.utc) if trial_end else None

    await update_user_subscription(
        user_id             = int(user_id),
        stripe_customer_id  = customer_id,
        subscription_status = status,
        trial_ends_at       = trial_ends_at,
    )
    logger.info(f"User {user_id} subscription created: {status}")


async def _handle_subscription_updated(sub: dict):
    """Subscription updated — sync status."""
    customer_id = sub.get("customer")
    status      = sub.get("status")
    trial_end   = sub.get("trial_end")

    user_id = await _get_user_id_by_customer(customer_id)
    if not user_id:
        return

    from datetime import datetime, timezone
    trial_ends_at = datetime.fromtimestamp(trial_end, tz=timezone.utc) if trial_end else None

    await update_user_subscription(
        user_id             = user_id,
        subscription_status = status,
        trial_ends_at       = trial_ends_at,
    )
    logger.info(f"User {user_id} subscription updated: {status}")


async def _handle_subscription_deleted(sub: dict):
    """Subscription cancelled/expired — mark as inactive."""
    customer_id = sub.get("customer")
    user_id = await _get_user_id_by_customer(customer_id)
    if not user_id:
        return
    await update_user_subscription(
        user_id             = user_id,
        subscription_status = "canceled",
    )
    logger.info(f"User {user_id} subscription canceled")


async def _get_user_id_by_customer(customer_id: str) -> int | None:
    """Look up user by Stripe customer ID."""
    from app.db.user_repository import get_user_by_stripe_customer_id
    user = await get_user_by_stripe_customer_id(customer_id)
    return user["id"] if user else None
