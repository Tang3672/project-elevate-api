"""
Auth Service
============
Handles JWT creation/verification, password hashing, and Google OAuth token verification.
"""
import hashlib
import hmac
import json
import base64
import time
import logging
from typing import Optional
from datetime import datetime, timedelta

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
JWT_SECRET      = getattr(settings, 'JWT_SECRET', 'project-elevate-secret-key-change-in-production')
JWT_ALGORITHM   = "HS256"
JWT_EXPIRE_DAYS = 30

GOOGLE_TOKEN_INFO_URL = "https://oauth2.googleapis.com/tokeninfo"


# ── Password hashing (using hashlib — no bcrypt dependency needed) ─────────────

def hash_password(password: str) -> str:
    """Hash a password using PBKDF2-HMAC-SHA256."""
    import os
    salt = os.urandom(32)
    key  = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100_000)
    return base64.b64encode(salt + key).decode()


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against its hash."""
    try:
        raw    = base64.b64decode(hashed.encode())
        salt   = raw[:32]
        stored = raw[32:]
        key    = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100_000)
        return hmac.compare_digest(key, stored)
    except Exception:
        return False


# ── JWT (pure Python, no python-jose needed) ──────────────────────────────────

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode()


def _b64url_decode(data: str) -> bytes:
    padding = 4 - len(data) % 4
    if padding != 4:
        data += '=' * padding
    return base64.urlsafe_b64decode(data)


def create_access_token(user_id: int, email: str) -> str:
    """Create a signed JWT token."""
    header  = _b64url_encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64url_encode(json.dumps({
        "sub":   str(user_id),
        "email": email,
        "exp":   int(time.time()) + JWT_EXPIRE_DAYS * 86400,
        "iat":   int(time.time()),
    }).encode())
    msg       = f"{header}.{payload}"
    signature = _b64url_encode(
        hmac.new(JWT_SECRET.encode(), msg.encode(), hashlib.sha256).digest()
    )
    return f"{msg}.{signature}"


def verify_access_token(token: str) -> Optional[dict]:
    """Verify a JWT token and return the payload, or None if invalid."""
    try:
        parts = token.split('.')
        if len(parts) != 3:
            return None
        header, payload, signature = parts
        msg      = f"{header}.{payload}"
        expected = _b64url_encode(
            hmac.new(JWT_SECRET.encode(), msg.encode(), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(signature, expected):
            return None
        data = json.loads(_b64url_decode(payload))
        if data.get('exp', 0) < time.time():
            return None
        return data
    except Exception:
        return None


# ── Google OAuth ──────────────────────────────────────────────────────────────

async def verify_google_token(id_token: str) -> Optional[dict]:
    """
    Verify a Google ID token and return the user info.
    Returns dict with 'email', 'name', 'sub' (Google user ID), or None if invalid.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                GOOGLE_TOKEN_INFO_URL,
                params={"id_token": id_token}
            )
            if r.status_code != 200:
                logger.warning(f"Google token verification failed: {r.status_code}")
                return None
            data = r.json()
            # Validate it's for our app (optional — add your Google client ID to .env)
            google_client_id = getattr(settings, 'GOOGLE_CLIENT_ID', None)
            if google_client_id and data.get('aud') != google_client_id:
                logger.warning("Google token audience mismatch")
                return None
            return {
                'email': data.get('email'),
                'name':  data.get('name'),
                'sub':   data.get('sub'),   # Google's unique user ID
            }
    except Exception as e:
        logger.error(f"Google token verification error: {e}")
        return None
