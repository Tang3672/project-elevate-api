"""
Timeline API
============
POST /api/v1/timeline/generate   — generate timeline from idea + product_type
POST /api/v1/timeline/export/ical — export timeline as .ics calendar file
"""

import logging
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import Response as FastAPIResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter()


class TimelineRequest(BaseModel):
    idea:         str = Field(..., min_length=20, max_length=2000)
    product_type: str = Field(default="other")
    disease_name: Optional[str] = None
    start_date:   Optional[str] = None   # ISO date "2026-06-01"; defaults to today


class ICalRequest(BaseModel):
    timeline: dict   # serialised DevelopmentTimeline dict


@router.post("/generate")
async def generate_timeline(payload: TimelineRequest):
    try:
        from app.services.timeline_service import generate_timeline as _gen
        start = (date.fromisoformat(payload.start_date)
                 if payload.start_date else date.today())
        tl = _gen(
            idea=payload.idea,
            product_type=payload.product_type,
            disease_name=payload.disease_name,
            start_date=start,
        )
        return tl
    except Exception as e:
        logger.error("Timeline generation failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/export/ical")
async def export_ical(payload: ICalRequest):
    """Export a timeline as an .ics file downloadable by any calendar app."""
    try:
        ical_bytes = _build_ical(payload.timeline)
        return FastAPIResponse(
            content=ical_bytes,
            media_type="text/calendar",
            headers={
                "Content-Disposition": 'attachment; filename="development_timeline.ics"'
            },
        )
    except Exception as e:
        logger.error("iCal export failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def _build_ical(tl: dict) -> bytes:
    """Build an RFC 5545-compliant iCal file from a timeline dict."""
    from icalendar import Calendar, Event, vText, vDatetime, vDate
    import uuid

    cal = Calendar()
    cal.add("prodid", "-//Project Elevate//Development Timeline//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("x-wr-calname", f"Dev Timeline: {tl.get('disease', 'Innovation')}")
    cal.add("x-wr-timezone", "UTC")

    product = tl.get("product_type", "")
    disease = tl.get("disease", "")

    def _add_event(title: str, start_iso: str, end_iso: Optional[str],
                   description: str, category: str, all_day: bool = True):
        ev = Event()
        ev.add("uid", str(uuid.uuid4()))
        ev.add("summary", title)
        ev.add("description", description[:2000])
        ev.add("categories", [category])

        try:
            d_start = date.fromisoformat(start_iso[:10])
        except Exception:
            return

        if all_day:
            ev.add("dtstart", vDate(d_start))
            if end_iso:
                d_end = date.fromisoformat(end_iso[:10])
                ev.add("dtend", vDate(d_end))
            else:
                ev.add("dtend", vDate(d_start))
        else:
            ev.add("dtstart", vDatetime(datetime.fromisoformat(start_iso + "T09:00:00")))
            ev.add("dtend",   vDatetime(datetime.fromisoformat(start_iso + "T10:00:00")))

        cal.add_component(ev)

    # Phases as multi-day events
    for ph in tl.get("phases", []):
        activities = "\n".join(f"• {a}" for a in ph.get("key_activities", []))
        _add_event(
            title=f"[{product.upper()}] {ph['name']}",
            start_iso=ph.get("start_iso", ""),
            end_iso=ph.get("end_iso", ""),
            description=f"Duration: {ph['duration_months']} months\nCost: {ph['cost_fmt']}\n\n{activities}",
            category="Clinical Phase",
            all_day=True,
        )

    # Regulatory milestones as single-day events
    for ms in tl.get("regulatory_milestones", []):
        _add_event(
            title=f"🏛 {ms['event']}",
            start_iso=ms.get("iso_date", ""),
            end_iso=None,
            description=ms.get("description", ""),
            category="Regulatory",
            all_day=True,
        )

    # Funding windows
    for fw in tl.get("funding_windows", []):
        _add_event(
            title=f"💰 {fw['name']} ({fw['amount']})",
            start_iso=fw.get("iso_date", ""),
            end_iso=None,
            description=fw.get("description", ""),
            category="Funding",
            all_day=True,
        )

    # Strategic calendar
    for ev_data in tl.get("strategic_calendar", []):
        _add_event(
            title=f"⭐ {ev_data['event']}",
            start_iso=ev_data.get("iso_date", ""),
            end_iso=None,
            description=ev_data.get("description", ""),
            category="Strategic",
            all_day=True,
        )

    return cal.to_ical()
