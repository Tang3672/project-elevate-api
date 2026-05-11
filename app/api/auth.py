"""
Auth & User API
===============
POST /api/v1/auth/register        — email + password signup
POST /api/v1/auth/login           — email + password login
POST /api/v1/auth/google          — Google OAuth (verify ID token)
GET  /api/v1/auth/me              — get current user profile

POST /api/v1/auth/reports         — save a PI report
GET  /api/v1/auth/reports         — list saved reports
GET  /api/v1/auth/reports/{id}    — get full saved report
DELETE /api/v1/auth/reports/{id}  — delete a report
PATCH /api/v1/auth/reports/{id}   — rename a report

POST /api/v1/auth/drafts          — save a draft
GET  /api/v1/auth/drafts          — list drafts
DELETE /api/v1/auth/drafts/{id}   — delete a draft
"""
import logging
from fastapi import APIRouter, HTTPException, Request, Depends, Header
from typing import Optional, List

from app.models.user import (
    RegisterRequest, LoginRequest, GoogleAuthRequest, AuthResponse,
    UserProfile, SaveReportRequest, SavedReport, SavedReportSummary,
    SaveDraftRequest, SavedDraft,
)
from app.services.auth_service import (
    hash_password, verify_password,
    create_access_token, verify_access_token,
    verify_google_token,
)
from app.db.user_repository import (
    create_user, get_user_by_email, get_user_by_id,
    get_user_by_google_id, update_user_google_id,
    save_report, get_user_reports, get_report_by_id,
    delete_report, rename_report,
    save_draft, get_user_drafts, delete_draft,
)

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Auth helpers ──────────────────────────────────────────────────────────────

async def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    """Dependency: extract and verify JWT from Authorization header."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token   = authorization.split(" ", 1)[1]
    payload = verify_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = await get_user_by_id(int(payload['sub']))
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


async def get_optional_user(authorization: Optional[str] = Header(None)) -> Optional[dict]:
    """Dependency: return user if authenticated, None if not."""
    try:
        return await get_current_user(authorization)
    except HTTPException:
        return None


# ── Register ──────────────────────────────────────────────────────────────────

@router.post("/register", response_model=AuthResponse)
async def register(payload: RegisterRequest, request: Request):
    """Create a new account with email + password."""
    # Password strength validation
    pw = payload.password
    if len(pw) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if not any(c.isdigit() for c in pw):
        raise HTTPException(status_code=400, detail="Password must contain at least one number")
    if not any(c.isalpha() for c in pw):
        raise HTTPException(status_code=400, detail="Password must contain at least one letter")

    existing = await get_user_by_email(payload.email)
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    hashed = hash_password(payload.password)
    user   = await create_user(
        email         = payload.email,
        password_hash = hashed,
        name          = payload.name,
    )
    if not user:
        raise HTTPException(status_code=409, detail="Email already registered")

    # Send verification email
    try:
        from app.services.email_verification import create_verification_token, send_verification_email
        base_url = str(request.base_url).rstrip('/')
        ver_token = await create_verification_token(user['id'])
        await send_verification_email(user['email'], user.get('name',''), ver_token, base_url)
    except Exception as e:
        logger.warning(f"Verification email failed: {e}")

    token = create_access_token(user['id'], user['email'])
    return AuthResponse(
        access_token = token,
        user_id      = user['id'],
        email        = user['email'],
        name         = user.get('name'),
    )


# ── Login ─────────────────────────────────────────────────────────────────────

@router.post("/login", response_model=AuthResponse)
async def login(payload: LoginRequest):
    """Log in with email + password."""
    user = await get_user_by_email(payload.email)
    if not user or not user.get('password_hash'):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not verify_password(payload.password, user['password_hash']):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    # Check email verification — skip for dev accounts
    DEV_EMAILS = {"test@projectelevate.io", "ijw91021@gmail.com", "admin@projectelevate.io"}
    if not user.get('email_verified', False) and user['email'] not in DEV_EMAILS:
        raise HTTPException(
            status_code=403,
            detail="Please verify your email before logging in. Check your inbox."
        )
    # Block unverified accounts (skip for dev emails)
    DEV_EMAILS = {"test@projectelevate.io", "ijw91021@gmail.com", "admin@projectelevate.io"}
    if not user.get('email_verified', False) and user.get('email') not in DEV_EMAILS:
        raise HTTPException(
            status_code=403,
            detail="Please verify your email before logging in. Check your inbox for a verification link."
        )

    token = create_access_token(user['id'], user['email'])
    return AuthResponse(
        access_token = token,
        user_id      = user['id'],
        email        = user['email'],
        name         = user.get('name'),
    )


# ── Google OAuth ──────────────────────────────────────────────────────────────



@router.get("/verify-email")
async def verify_email(token: str):
    """Verify email via token link."""
    from app.services.email_verification import verify_token
    user_id = await verify_token(token)
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid or expired verification link. Please register again.")
    return {"message": "Email verified! You can now log in to Project Elevate."}

@router.post("/google", response_model=AuthResponse)
async def google_auth(payload: GoogleAuthRequest):
    """
    Verify a Google ID token (from Google Sign-In on the frontend).
    Creates account if first time, logs in if returning user.
    """
    google_info = await verify_google_token(payload.token)
    if not google_info or not google_info.get('email'):
        raise HTTPException(status_code=401, detail="Invalid Google token")

    email     = google_info['email']
    google_id = google_info['sub']
    name      = google_info.get('name')

    # Check if user exists by Google ID
    user = await get_user_by_google_id(google_id)

    if not user:
        # Check if email already registered (link accounts)
        user = await get_user_by_email(email)
        if user:
            # Link Google ID to existing account
            await update_user_google_id(user['id'], google_id)
        else:
            # Create new account
            user = await create_user(
                email     = email,
                google_id = google_id,
                name      = name,
            )
            if not user:
                raise HTTPException(status_code=500, detail="Failed to create account")

    token = create_access_token(user['id'], user['email'])
    return AuthResponse(
        access_token = token,
        user_id      = user['id'],
        email        = user['email'],
        name         = user.get('name'),
    )


# ── Profile ───────────────────────────────────────────────────────────────────

@router.get("/me", response_model=UserProfile)
async def get_me(current_user: dict = Depends(get_current_user)):
    """Get current user profile."""
    return UserProfile(
        user_id    = current_user['id'],
        email      = current_user['email'],
        name       = current_user.get('name'),
        created_at = current_user['created_at'],
    )


# ── Saved Reports ─────────────────────────────────────────────────────────────

@router.post("/reports", response_model=SavedReport)
async def create_report(
    payload:      SaveReportRequest,
    current_user: dict = Depends(get_current_user),
):
    """Save a PI report."""
    return await save_report(
        user_id      = current_user['id'],
        name         = payload.name,
        product_type = payload.product_type,
        idea         = payload.idea,
        report_data  = payload.report_data,
        pathogen     = payload.pathogen,
    )


@router.get("/reports", response_model=List[SavedReportSummary])
async def list_reports(current_user: dict = Depends(get_current_user)):
    """List all saved reports for the current user."""
    return await get_user_reports(current_user['id'])


@router.get("/reports/{report_id}", response_model=SavedReport)
async def get_report(
    report_id:    int,
    current_user: dict = Depends(get_current_user),
):
    """Get a full saved report by ID."""
    report = await get_report_by_id(report_id, current_user['id'])
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@router.delete("/reports/{report_id}")
async def remove_report(
    report_id:    int,
    current_user: dict = Depends(get_current_user),
):
    """Delete a saved report."""
    deleted = await delete_report(report_id, current_user['id'])
    if not deleted:
        raise HTTPException(status_code=404, detail="Report not found")
    return {"deleted": True}


@router.patch("/reports/{report_id}")
async def update_report_name(
    report_id:    int,
    name:         str,
    current_user: dict = Depends(get_current_user),
):
    """Rename a saved report."""
    updated = await rename_report(report_id, current_user['id'], name)
    if not updated:
        raise HTTPException(status_code=404, detail="Report not found")
    return {"updated": True}


# ── Drafts ────────────────────────────────────────────────────────────────────

@router.post("/drafts", response_model=SavedDraft)
async def create_draft(
    payload:      SaveDraftRequest,
    current_user: dict = Depends(get_current_user),
):
    """Save a draft idea."""
    return await save_draft(
        user_id      = current_user['id'],
        name         = payload.name,
        product_type = payload.product_type,
        idea         = payload.idea,
        pathogen     = payload.pathogen,
    )


@router.get("/drafts", response_model=List[SavedDraft])
async def list_drafts(current_user: dict = Depends(get_current_user)):
    """List all drafts for the current user."""
    return await get_user_drafts(current_user['id'])


@router.delete("/drafts/{draft_id}")
async def remove_draft(
    draft_id:     int,
    current_user: dict = Depends(get_current_user),
):
    """Delete a draft."""
    deleted = await delete_draft(draft_id, current_user['id'])
    if not deleted:
        raise HTTPException(status_code=404, detail="Draft not found")
    return {"deleted": True}
