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
from fastapi import HTTPException, Header
from typing import Optional


def require_admin_key(x_admin_key: Optional[str] = Header(default=None, alias="X-Admin-Key")) -> None:
    """Reject requests that don't supply the correct ADMIN_KEY in the X-Admin-Key header.

    BUG-11: was a URL query param — leaked the key to server access logs and browser history.
    Clients: send header `X-Admin-Key: <key>` instead of `?key=<key>`.
    """
    expected = os.environ.get("ADMIN_KEY", "")
    if not expected:
        raise HTTPException(status_code=503, detail="Admin key not configured on server")
    provided = x_admin_key or ""
    if not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=403, detail="Invalid admin key")
