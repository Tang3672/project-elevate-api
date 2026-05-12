"""
Tracker API endpoints
"""
import logging
import traceback
from fastapi import APIRouter, Depends, HTTPException
from app.api.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()

ADMIN_EMAILS = {"ijw91021@gmail.com", "admin@projectelevate.io", "test@projectelevate.io"}


@router.post("/tracker/run")
async def trigger_tracker(current_user: dict = Depends(get_current_user)):
    """Manually trigger weekly tracker for the current user's watchlists."""
    try:
        from app.services.weekly_tracker import run_tracker_for_user
        results = await run_tracker_for_user(current_user["id"])
        return {
            "status": "complete",
            "watchlists_scanned": len(results),
            "recalculations_needed": sum(1 for r in results if r.get("recalculation_needed")),
            "results": results,
        }
    except Exception as e:
        logger.error(f"Manual tracker run failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tracker/run-all")
async def trigger_all(current_user: dict = Depends(get_current_user)):
    """Admin: trigger tracker for all users."""
    if current_user.get("email") not in ADMIN_EMAILS:
        raise HTTPException(status_code=403, detail="Admin only")
    from app.services.weekly_tracker import run_weekly_tracker
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
    """Full retention test — runs all 5 features with mock data."""
    try:
        from app.services.retention_service import (
            check_report_staleness, check_grant_deadlines,
            track_competitor_milestones, compute_signal_delta,
            format_retention_alert_body
        )
        from app.db.user_repository import get_pool

        pool = await get_pool()
        try:
            async with pool.acquire() as conn:
                wl_rows = await conn.fetch(
                    "SELECT * FROM watchlists WHERE user_id = $1 ORDER BY created_at DESC LIMIT 1",
                    current_user["id"]
                )
                report_rows = await conn.fetch(
                    "SELECT * FROM saved_reports WHERE user_id = $1 ORDER BY created_at DESC LIMIT 1",
                    current_user["id"]
                )
        except Exception:
            wl_rows = []
            report_rows = []

        watchlist = dict(wl_rows[0]) if wl_rows else {
            "id": 0, "user_id": current_user["id"],
            "name": "GLP-1 Obesity Drug (Demo — high activity)",
            "product_description": "A next-generation oral GLP-1 receptor agonist for type 2 diabetes and obesity, targeting patients who cannot tolerate injectable semaglutide or tirzepatide, with improved GI tolerability profile.",
            "keywords": ["GLP-1", "semaglutide", "tirzepatide", "obesity", "diabetes", "SGLT2"],
            "disease_domain": "drug_metabolic",
        }

        saved_report = dict(report_rows[0]) if report_rows else {
            "id": 0,
            "user_id": current_user["id"],
            "created_at": "2026-02-01T00:00:00Z",
            "report_data": {
                "idea_submitted": "A next-generation oral GLP-1 receptor agonist for obesity",
                "expert_name": "Metabolic / Diabetes Drug Expert",
                "expert_domain": "drug_metabolic",
                "disease_intelligence": {
                    "condition": "Obesity and Type 2 Diabetes (GLP-1 market)",
                    "data_points": [
                        {"metric": "U.S. obesity prevalence", "value": "42%", "year": "2023", "source": "CDC"},
                        {"metric": "GLP-1 market size 2023", "value": "$35B", "year": "2023", "source": "IQVIA"},
                        {"metric": "Semaglutide (Ozempic/Wegovy) revenue", "value": "$21B", "year": "2023", "source": "Novo Nordisk annual report"},
                    ]
                },
                "market_sizing": {
                    "total_addressable_market_usd": 50000000000,
                    "serviceable_market_usd": 5000000000,
                },
                "regulatory_pathway": {
                    "recommended_pathway": "NDA 505(b)(1) with CVOT requirement",
                    "designations": [{"name": "Fast Track", "priority": "recommended"}]
                }
            }
        }

        results = {"watchlist": watchlist.get("name"), "features": {}}

        # 1. Staleness
        try:
            results["features"]["staleness"] = await check_report_staleness(saved_report)
        except Exception as e:
            results["features"]["staleness"] = {"error": str(e), "staleness_score": 0, "recalculate": False}

        # 2. Grant deadlines
        try:
            results["features"]["grant_deadlines"] = await check_grant_deadlines(
                watchlist.get("disease_domain", "drug_amr"),
                watchlist.get("keywords", [])
            )
        except Exception as e:
            results["features"]["grant_deadlines"] = []

        # 3. Competitor milestones (Claude web search)
        try:
            desc = watchlist.get("product_description", "")[:100]
            results["features"]["competitor_milestones"] = await track_competitor_milestones(desc, desc)
        except Exception as e:
            results["features"]["competitor_milestones"] = []

        # 3b. ClinicalTrials.gov + FDA live pipeline (moat wideners 2+3)
        try:
            from app.services.fda_pipeline import get_full_competitive_intelligence
            condition = watchlist.get("product_description", "obesity GLP-1 diabetes")[:80]
            keywords  = watchlist.get("keywords", ["GLP-1", "obesity"])
            ci = await get_full_competitive_intelligence(
                condition=condition,
                disease_keywords=keywords,
            )
            results["features"]["clinical_trials"] = {
                "total_trials":        ci.get("trial_pipeline", {}).get("total_trials", 0),
                "recruiting":          ci.get("trial_pipeline", {}).get("recruiting_count", 0),
                "threat_level":        ci.get("trial_pipeline", {}).get("competitive_threat_level", "unknown"),
                "top_trials":          ci.get("trial_pipeline", {}).get("active_trials", [])[:4],
                "recently_completed":  ci.get("recently_completed", [])[:2],
                "summary":             ci.get("intelligence_summary", ""),
            }
        except Exception as e:
            results["features"]["clinical_trials"] = {"error": str(e)}

        # 4. Signal delta
        try:
            results["features"]["signal_delta"] = await compute_signal_delta(watchlist)
        except Exception as e:
            results["features"]["signal_delta"] = {"new_in_30_days": 0, "error": str(e)}

        # 5. Format alert
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

    except Exception as e:
        return {"error": str(e), "traceback": traceback.format_exc()}


@router.get("/competitive-intel")
async def get_competitive_intel(
    condition: str = "carbapenem-resistant infections",
    current_user: dict = Depends(get_current_user)
):
    """Get live FDA + ClinicalTrials competitive intelligence for a condition."""
    from app.services.fda_pipeline import (
        get_full_competitive_intelligence,
        format_competitive_intelligence_for_report
    )
    keywords = condition.split()[:4]
    ci = await get_full_competitive_intelligence(
        condition=condition,
        disease_keywords=keywords,
    )
    ci["formatted"] = format_competitive_intelligence_for_report(ci)
    return ci
