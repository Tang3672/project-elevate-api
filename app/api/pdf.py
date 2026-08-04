"""
PDF report endpoint  (P2)
=========================
GET /pi-report/{job_id}/pdf   — returns PDF bytes (or HTML if playwright absent)
GET /pi-report/{job_id}/html  — returns HTML for preview / debugging
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, Response

from app.services.report_jobs import get_job
from app.services.pdf_renderer import (
    derive_filename,
    derive_product_name,
    render_report_html,
    generate_pdf,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/pi-report", tags=["pdf"])


async def _load_report(job_id: str) -> dict:
    row = await get_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} not found")
    if row.get("status") != "done":
        raise HTTPException(status_code=409, detail=f"Job {job_id!r} status={row.get('status')}")
    report = row.get("report")
    if not report:
        raise HTTPException(status_code=404, detail=f"Job {job_id!r} has no report data")
    return report


@router.get("/{job_id}/html", response_class=HTMLResponse)
async def get_report_html(job_id: str):
    """Return the report as a print-ready HTML document (for preview and debugging)."""
    report = await _load_report(job_id)
    html = render_report_html(
        report=report,
        product_name=report.get("product_name", ""),
        institution=report.get("institution", ""),
    )
    return HTMLResponse(content=html, status_code=200)


@router.get("/{job_id}/pdf")
async def get_report_pdf(job_id: str):
    """
    Return the report as a PDF (via headless Chromium) or HTML fallback.
    Content-Disposition sets the F-01 filename: {product}-commercial-intelligence-{date}.pdf
    Blocked when validation.export_blocked is True (arithmetic errors make the
    market model factually wrong — the artifact must not be shared).
    """
    report = await _load_report(job_id)

    val = report.get("validation") or {}
    if val.get("export_blocked"):
        raise HTTPException(
            status_code=422,
            detail={
                "error": "export_blocked",
                "message": (
                    "PDF export is blocked because the Math Verifier found an arithmetic "
                    "inconsistency in the market model. Correct the flagged errors before "
                    "exporting."
                ),
                "validation_summary": val.get("summary", ""),
            },
        )
    pname = report.get("product_name") or derive_product_name(report)
    date_str = (report.get("generated_at") or "")[:10]  # ISO date portion

    pdf_bytes = await generate_pdf(
        report=report,
        product_name=pname,
        institution=report.get("institution", ""),
    )
    filename = derive_filename(pname, date_str)

    # Detect whether playwright returned PDF or HTML fallback
    is_pdf = pdf_bytes[:4] == b"%PDF"
    media_type = "application/pdf" if is_pdf else "text/html; charset=utf-8"

    return Response(
        content=pdf_bytes,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
