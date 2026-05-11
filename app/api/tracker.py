"""
Tracker API endpoints
=====================
GET  /api/v1/tracker/run       — manually trigger tracker for current user (testing)
GET  /api/v1/tracker/status    — get last run status
POST /api/v1/tracker/run-all   — admin: trigger all watchlists (admin only)
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from app.api.auth import get_current_user
from app.services.weekly_tracker import run_tracker_for_user, run_weekly_tracker

logger = logging.getLogger(__name__)
router = APIRouter()

ADMIN_EMAILS = {"ijw91021@gmail.com", "admin@projectelevate.io", "test@projectelevate.io"}


@router.post("/tracker/run")
async def trigger_tracker(current_user: dict = Depends(get_current_user)):
    """Manually trigger weekly tracker for the current user's watchlists."""
    try:
        results = await run_tracker_for_user(current_user["id"])
        return {
            "status":          "complete",
            "watchlists_scanned": len(results),
            "recalculations_needed": sum(1 for r in results if r.get("recalculation_needed")),
            "results":         results,
        }
    except Exception as e:
        logger.error(f"Manual tracker run failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tracker/run-all")
async def trigger_all(current_user: dict = Depends(get_current_user)):
    """Admin: trigger tracker for all users."""
    if current_user.get("email") not in ADMIN_EMAILS:
        raise HTTPException(status_code=403, detail="Admin only")
    results = await run_weekly_tracker()
    return {"status": "complete", "processed": len(results) if results else 0}


@router.get("/tracker/grants")
async def get_grant_deadlines(
    domain: str = "all",
    current_user: dict = Depends(get_current_user)
):
    """Get upcoming grant deadlines relevant to a domain."""
    from app.services.retention_service import check_grant_deadlines
    grants = await check_grant_deadlines(domain, [])
    return {"grants": grants, "total": len(grants)}


@router.post("/tracker/check-staleness/{report_id}")
async def check_staleness(
    report_id: int,
    current_user: dict = Depends(get_current_user)
):
    """Check if a saved report is outdated."""
    from app.services.retention_service import check_report_staleness
    from app.db.user_repository import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM saved_reports WHERE id = $1 AND user_id = $2",
            report_id, current_user["id"]
        )
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    result = await check_report_staleness(dict(row))
    return result


@router.post("/tracker/test-full")
async def test_full_retention(current_user: dict = Depends(get_current_user)):
    """Full retention test — runs all 5 features and returns results."""
    from app.services.retention_service import (
        check_report_staleness, check_grant_deadlines,
        track_competitor_milestones, compute_signal_delta,
        format_retention_alert_body
    )
    from app.db.user_repository import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        wl_rows = await conn.fetch(
            "SELECT * FROM watchlists WHERE user_id = $1 ORDER BY created_at DESC LIMIT 1",
            current_user["id"]
        )
        report_rows = await conn.fetch(
            "SELECT * FROM saved_reports WHERE user_id = $1 ORDER BY created_at DESC LIMIT 1",
            current_user["id"]
        )

    # Always use mock data for testing so it works without any saved data
    watchlist = dict(wl_rows[0]) if wl_rows else {
        "id": 0, "user_id": current_user["id"],
        "name": "CRE Antibiotic Market (Demo)",
        "product_description": "A novel beta-lactam/beta-lactamase inhibitor combination targeting carbapenem-resistant Klebsiella pneumoniae and Acinetobacter baumannii in hospitalized patients with serious infections.",
        "keywords": ["CRE", "carbapenem", "QIDP", "beta-lactamase", "KPC", "NDM", "antibiotic resistance"],
        "disease_domain": "drug_amr",
    }
    # Use mock saved report if none exists
    saved_report = dict(report_rows[0]) if report_rows else {
        "id": 0,
        "user_id": current_user["id"],
        "created_at": "2026-02-01T00:00:00Z",
        "report_data": {
            "idea_submitted": "A novel beta-lactam/BLI targeting carbapenem-resistant Klebsiella pneumoniae",
            "expert_name": "AMR / Antibiotic Drug Expert",
            "expert_domain": "drug_amr",
            "disease_intelligence": {
                "condition": "Carbapenem-Resistant Enterobacterales (CRE)",
                "data_points": [
                    {"metric": "Annual U.S. CRE infections", "value": "13,100", "year": "2019", "source": "CDC AR Threats Report"},
                    {"metric": "Annual U.S. CRE deaths", "value": "1,100", "year": "2019", "source": "CDC AR Threats Report"},
                    {"metric": "CRE mortality rate in BSI", "value": "40-50%", "year": "2022", "source": "IDSA Guidelines"},
                ]
            },
            "market_sizing": {
                "total_addressable_market_usd": 285000000,
                "serviceable_market_usd": 95000000,
                "formula": "13,100 patients x $15,000/course x 45% penetration"
            },
            "regulatory_pathway": {
                "recommended_pathway": "NDA 505(b)(1) with QIDP designation",
                "designations": [
                    {"name": "QIDP", "priority": "recommended"},
                    {"name": "Fast Track", "priority": "recommended"},
                ]
            }
        }
    }
    results = {"watchlist": watchlist.get("name"), "features": {}}

    if saved_report:
        try:
            results["features"]["staleness"] = await check_report_staleness(saved_report)
        except Exception as e:
            results["features"]["staleness"] = {"error": str(e)}
    else:
        results["features"]["staleness"] = {
            "note": "No saved reports — save a report first to test staleness detection",
            "staleness_score": 0, "recalculate": False
        }

    try:
        results["features"]["grant_deadlines"] = await check_grant_deadlines(
            watchlist.get("disease_domain", "drug_amr"),
            watchlist.get("keywords", [])
        )
    except Exception as e:
        results["features"]["grant_deadlines"] = {"error": str(e)}

    try:
        desc = watchlist.get("product_description", "")[:100]
        results["features"]["competitor_milestones"] = await track_competitor_milestones(desc, desc)
    except Exception as e:
        results["features"]["competitor_milestones"] = {"error": str(e)}

    try:
        results["features"]["signal_delta"] = await compute_signal_delta(watchlist)
    except Exception as e:
        results["features"]["signal_delta"] = {"error": str(e)}

    try:
        results["formatted_alert"] = format_retention_alert_body({
            "staleness":             results["features"].get("staleness", {}),
            "grant_deadlines":       results["features"].get("grant_deadlines", []),
            "competitor_milestones": results["features"].get("competitor_milestones", []),
            "signal_delta":          results["features"].get("signal_delta", {}),
        }, watchlist.get("name", "Test"))
    except Exception as e:
        results["formatted_alert"] = f"Format error: {e}"

    return results
