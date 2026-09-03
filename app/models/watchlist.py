"""
Watchlist and Alert Models
==========================
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Annotated
from datetime import datetime


# BUG-74: keywords was an unbounded List[str] — no per-item length cap and no list
# size cap.  An attacker could submit thousands of very long keyword strings, bloating
# DB storage and the semantic-matching query on every alert evaluation.  Cap the list
# at 50 items and each keyword at 100 characters (more than enough for any clinical term).
_Keyword = Annotated[str, Field(min_length=1, max_length=100)]


class CreateWatchlistRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200,
        description="e.g. 'CRE Antibiotic Market' or 'Alzheimer's AI Detection'")
    disease_domain: str = Field(default="auto", max_length=100,
        description="Expert domain ID or 'auto'")
    product_description: str = Field(..., min_length=10, max_length=1000,
        description="What the PI is working on — used for semantic matching")
    keywords: List[_Keyword] = Field(default_factory=list, max_length=50,
        description="Additional keywords to watch for (max 50, each max 100 chars)")


class Watchlist(BaseModel):
    watchlist_id:        int
    user_id:             int
    name:                str
    disease_domain:      str
    product_description: str
    keywords:            List[str]
    alert_count:         int = 0
    unread_count:        int = 0
    created_at:          datetime
    last_checked:        Optional[datetime] = None


class Alert(BaseModel):
    alert_id:             int
    watchlist_id:         int
    user_id:              int
    title:                str
    body:                 str    = ""
    severity:             str    = "medium"   # high | medium | low
    source:               str    = "weekly_tracker"
    recalculation_needed: bool   = False
    significance_score:   int    = 0
    source_url:           Optional[str]   = None
    seen:                 bool   = False
    created_at:           datetime


class AlertSummary(BaseModel):
    """Lightweight version for the notification bell."""
    total_unread:    int
    by_watchlist:    List[dict]   # [{watchlist_id, name, unread_count}]
    latest_alerts:   List[Alert]  # most recent 5
