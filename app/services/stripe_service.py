"""
Stripe Billing Service
======================
Handles subscription lifecycle:
- Create checkout session (with 7-day free trial)
- Handle webhooks (subscription created/updated/deleted, checkout completed)
- Query subscription status
"""
import logging
import stripe
from typing import Optional
from datetime import datetime, timezone

from app.core.config import settings

logger = logging.getLogger(__name__)


def get_stripe():
    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe


async def create_checkout_session(
    user_id:    int,
    user_email: str,
    success_url: str,
    cancel_url:  str,
) -> str:
    """
    Create a Stripe Checkout session with 7-day free trial.
    Returns the checkout URL to redirect the user to.
    """
    s = get_stripe()
    try:
        session = s.checkout.Session.create(
            mode               = "subscription",
            payment_method_types = ["card"],
            customer_email     = user_email,
            line_items         = [{
                "price":    settings.STRIPE_PRICE_ID,
                "quantity": 1,
            }],
            subscription_data  = {
                "trial_period_days": 7,
                "metadata": {"user_id": str(user_id)},
            },
            metadata           = {"user_id": str(user_id)},
            success_url        = success_url,
            cancel_url         = cancel_url,
            allow_promotion_codes = True,
        )
        logger.info(f"Checkout session created for user {user_id}: {session.id}")
        return session.url
    except Exception as e:
        logger.error(f"Stripe checkout session failed: {e}")
        raise


async def get_subscription_status(stripe_customer_id: str) -> dict:
    """Get current subscription status for a customer."""
    s = get_stripe()
    try:
        subscriptions = s.Subscription.list(
            customer=stripe_customer_id,
            status="all",
            limit=1,
        )
        if not subscriptions.data:
            return {"status": "none", "trial_end": None, "current_period_end": None}

        sub = subscriptions.data[0]
        return {
            "status":               sub.status,
            "trial_end":            sub.trial_end,
            "current_period_end":   sub.current_period_end,
            "cancel_at_period_end": sub.cancel_at_period_end,
        }
    except Exception as e:
        logger.error(f"Failed to get subscription status: {e}")
        return {"status": "unknown"}


def construct_webhook_event(payload: bytes, sig_header: str):
    """Verify and construct a Stripe webhook event."""
    s = get_stripe()
    return s.Webhook.construct_event(
        payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
    )


async def cancel_subscription(stripe_customer_id: str) -> bool:
    """Cancel subscription at period end."""
    s = get_stripe()
    try:
        subscriptions = s.Subscription.list(customer=stripe_customer_id, limit=1)
        if subscriptions.data:
            s.Subscription.modify(
                subscriptions.data[0].id,
                cancel_at_period_end=True,
            )
            return True
        return False
    except Exception as e:
        logger.error(f"Cancel subscription failed: {e}")
        return False
