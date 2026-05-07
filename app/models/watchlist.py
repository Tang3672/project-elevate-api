"""
Watchlist and Alert Models
==========================
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class CreateWatchlistRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200,
        description="e.g. 'CRE Antibiotic Market' or 'Alzheimer's AI Detection'")
    disease_domain: str = Field(default="auto",
        description="Expert domain ID or 'auto'")
    product_description: str = Field(..., min_length=10, max_length=1000,
        description="What the PI is working on — used for semantic matching")
    keywords: List[str] = Field(default_factory=list,
        description="Additional keywords to watch for")


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
    alert_id:     int
    watchlist_id: int
    user_id:      int
    signal_id:    Optional[int]   = None
    alert_type:   str             # fda_recall | clinical_trial | disease_burden | hrsa_shortage | funding | competitor
    title:        str
    summary:      str
    severity:     str             # high | medium | low
    source:       str
    source_url:   Optional[str]   = None
    seen:         bool            = False
    created_at:   datetime


class AlertSummary(BaseModel):
    """Lightweight version for the notification bell."""
    total_unread:    int
    by_watchlist:    List[dict]   # [{watchlist_id, name, unread_count}]
    latest_alerts:   List[Alert]  # most recent 5
