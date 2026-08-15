"""
Shared admin authentication dependency.

All admin_router endpoints must depend on require_admin_key.
The key is read from the ADMIN_KEY environment variable — set it in Railway
(or .env for local dev). Never hardcode it in source.

Usage:
    from app.api.admin_auth import require_admin_key
    admin_router = APIRouter(dependencies=[Depends(require_admin_key)])
"""
import os
import hmac
from fastapi import HTTPException, Query


def require_admin_key(key: str = Query(default="", alias="key")) -> None:
    """Reject requests that don't supply the correct ADMIN_KEY query param."""
    expected = os.environ.get("ADMIN_KEY", "")
    if not expected:
        raise HTTPException(status_code=503, detail="Admin key not configured on server")
    if not hmac.compare_digest(key, expected):
        raise HTTPException(status_code=403, detail="Invalid admin key")
