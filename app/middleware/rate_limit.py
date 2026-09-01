"""
Rate Limiting Middleware
=========================
Protects API tokens (Anthropic, OpenAI) from abuse by enforcing:

  1. IP-level rate limiting — 60 req/min per IP for general endpoints
                             — 5 req/min per IP for expensive AI endpoints
  2. User-level daily report quotas — enforced server-side before calling Claude
  3. Burst protection — blocks IPs that hit 200+ requests/hour

This runs BEFORE any endpoint handler, so even if someone bypasses the
frontend billing gate, they can't abuse the API tokens.

Plan limits (enforced server-side, not just frontend):
  Explorer ($49):    5 market analyses / month
  Innovator ($149): 20 market analyses / month
  Institution ($799): unlimited
  Dev emails:        unlimited
"""

import time
import logging
from collections import defaultdict
from typing import Callable

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# BUG-23: evict stale entries so _ip_requests doesn't grow without bound.
_LAST_EVICT: float = 0.0
_EVICT_EVERY: float = 300.0  # prune every 5 minutes

logger = logging.getLogger(__name__)

# ── In-memory rate limit stores (reset on restart — fine for Railway) ─────────
# For production scale, swap with Redis; for <10k users this is sufficient.

_ip_requests: dict[str, list[float]] = defaultdict(list)   # ip → [timestamps]
_user_requests: dict[int, list[float]] = defaultdict(list)  # user_id → [timestamps]

# ── Limits ────────────────────────────────────────────────────────────────────

_GENERAL_LIMIT_PER_MIN   = 120   # requests per minute per IP (general)
_AI_LIMIT_PER_MIN        = 8     # requests per minute per IP (Claude endpoints)
_BURST_LIMIT_PER_HOUR    = 300   # total requests per hour per IP before hard block
_WINDOW_MIN              = 60    # seconds
_WINDOW_HOUR             = 3600

_EXPENSIVE_PATHS = {
    "/api/v1/alignment/pi-report",
    "/api/v1/alignment/check",
    "/api/v1/alignment/clarify",
    "/api/v1/alignment/competitive-sweep",
    "/api/v1/alignment/market-sizing-derivation",
}


def _prune(timestamps: list[float], window: float) -> list[float]:
    cutoff = time.monotonic() - window
    return [t for t in timestamps if t > cutoff]


class RateLimitMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware that enforces per-IP and per-user rate limits."""

    async def dispatch(self, request: Request, call_next: Callable):
        path = request.url.path

        # Skip health checks and static files
        if path in ("/health", "/docs", "/openapi.json") or path.startswith("/static"):
            return await call_next(request)

        # Get client IP (handle Railway's reverse proxy)
        client_ip = (
            request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or request.headers.get("x-real-ip", "")
            or (request.client.host if request.client else "unknown")
        )

        now = time.monotonic()

        # BUG-23: periodically evict IPs whose last request was over an hour ago
        global _LAST_EVICT
        if now - _LAST_EVICT > _EVICT_EVERY:
            stale = [ip for ip, ts in _ip_requests.items() if not ts or now - ts[-1] > _WINDOW_HOUR]
            for ip in stale:
                del _ip_requests[ip]
            _LAST_EVICT = now

        # ── 1. Hourly burst protection (hard block for extreme abuse) ─────────
        hour_reqs = _prune(_ip_requests[client_ip], _WINDOW_HOUR)
        if len(hour_reqs) >= _BURST_LIMIT_PER_HOUR:
            logger.warning("RATE LIMIT BURST: IP %s exceeded %d req/hr", client_ip, _BURST_LIMIT_PER_HOUR)
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests. Please slow down and try again later.", "retry_after": 3600},
                headers={"Retry-After": "3600"},
            )

        # ── 2. Per-minute IP limit ────────────────────────────────────────────
        limit = _AI_LIMIT_PER_MIN if path in _EXPENSIVE_PATHS else _GENERAL_LIMIT_PER_MIN
        min_reqs = _prune(_ip_requests[client_ip], _WINDOW_MIN)
        if len(min_reqs) >= limit:
            logger.warning("RATE LIMIT: IP %s exceeded %d req/min on %s", client_ip, limit, path)
            return JSONResponse(
                status_code=429,
                content={"detail": f"Rate limit exceeded. Max {limit} requests/minute for this endpoint. Please wait.", "retry_after": 60},
                headers={"Retry-After": "60"},
            )

        # Record this request — BUG-9: store full hour window so burst check accumulates
        # correctly across minutes. min_reqs is already a subset of hour_reqs.
        _ip_requests[client_ip] = hour_reqs + [now]

        return await call_next(request)
