"""
User and saved report models.
"""
from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List, Any
from datetime import datetime


# ── Auth ──────────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=200)
    password: str = Field(..., min_length=8, max_length=100)
    name: Optional[str] = Field(default=None, max_length=100)


class LoginRequest(BaseModel):
    email:    str = Field(..., min_length=5, max_length=200)
    # BUG-73: no max_length — unauthenticated PBKDF2 CPU-exhaustion DoS.
    # Any attacker could POST a 100MB password to /login and force 100k PBKDF2
    # iterations against it before we even checked the hash.  Cap at 100 chars
    # (matches RegisterRequest) so the input is bounded before hitting verify_password.
    password: str = Field(..., min_length=1, max_length=100)


class GoogleAuthRequest(BaseModel):
    token: str   # Google ID token from frontend


class AuthResponse(BaseModel):
    message: str = ""
    access_token: str
    token_type:   str = "bearer"
    user_id:      int
    email:        str
    name:         Optional[str] = None


class UserProfile(BaseModel):
    user_id:    int
    email:      str
    name:       Optional[str] = None
    created_at: datetime


# ── Saved Reports ─────────────────────────────────────────────────────────────

class SaveReportRequest(BaseModel):
    name:         str = Field(..., min_length=1, max_length=200,
                              description="Label for this report, e.g. 'CRE antibiotic analysis'")
    product_type: str
    idea:         str
    pathogen:     Optional[str] = None
    report_data:  dict          # the full PIReport JSON


class SavedReport(BaseModel):
    report_id:    int
    user_id:      int
    name:         str
    product_type: str
    idea:         str
    pathogen:     Optional[str] = None
    report_data:  dict
    created_at:   datetime


class SavedReportSummary(BaseModel):
    """Lightweight version for listing — no full report_data."""
    report_id:    int
    name:         str
    product_type: str
    idea:         str
    pathogen:     Optional[str] = None
    created_at:   datetime


# ── Saved Drafts ──────────────────────────────────────────────────────────────

class SaveDraftRequest(BaseModel):
    name:         str = Field(..., min_length=1, max_length=200)
    product_type: str = "antibiotic"
    idea:         str = ""
    pathogen:     Optional[str] = None


class SavedDraft(BaseModel):
    draft_id:     int
    user_id:      int
    name:         str
    product_type: str
    idea:         str
    pathogen:     Optional[str] = None
    created_at:   datetime
    updated_at:   datetime
